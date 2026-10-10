"""편집 계획을 실제 클립 순서(타임라인)로 바꾼다.

결과 순서: 콜드 오픈(hooks) → 인트로 범퍼 → 본편
모든 경계는 프레임 단위로 맞춰서 영상과 오디오 길이가 어긋나지 않게 한다.
"""
from dataclasses import dataclass, field

from .cuts import Sentence, keep_ranges

FPS = 30
BUMPER_SEC = 1.4

# 줌은 꼭 필요한 곳에만: 콜드 오픈은 문장마다 한 번 바꾸고, 본편은 계획의 punch 문장에서만 당긴다.
# 화면 전환은 슬라이드와 자료 화면이 맡는다.
ZOOM_WIDE = 1.0
ZOOM_TIGHT = 1.10
HOOK_ZOOMS = (1.0, 1.12)
SHOT_MIN = 8.0        # 긴 구간은 문장 경계에서 클립을 나눈다 (줌 지정 단위)
SHOT_MAX = 14.0


def snap(t: float) -> float:
    return round(round(t * FPS) / FPS, 4)


@dataclass
class Clip:
    kind: str            # "hook" | "bumper" | "body"
    src_start: float
    src_end: float
    zoom: float = 1.0
    out_start: float = 0.0
    joined: bool = False  # 원본에서 앞 클립과 바로 이어지면 True (오디오 페이드를 넣지 않는다)
    chapter: int | None = None  # 이 클립에서 챕터가 시작되면 챕터 번호

    @property
    def dur(self) -> float:
        return round(self.src_end - self.src_start, 4)


@dataclass
class Timeline:
    clips: list[Clip] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return self.clips[-1].out_start + self.clips[-1].dur if self.clips else 0.0


def _sentence_span(sentences: list[Sentence], a: int, b: int) -> tuple[float, float]:
    a, b = max(0, a), min(len(sentences) - 1, b)
    return sentences[a].start, sentences[b].end


def _shots(a: float, b: float, sentence_starts: list[float], word_starts: list[float],
           shot_min: float = SHOT_MIN, shot_max: float = SHOT_MAX) -> list[tuple[float, float]]:
    """하나로 이어진 구간 [a, b]를 줌을 바꿀 샷들로 나눈다. 문장 경계를 우선으로 쓴다."""
    cands = sorted({(t, True) for t in sentence_starts if a + 1.0 < t < b - 1.0}
                   | {(t, False) for t in word_starts if a + 1.0 < t < b - 1.0})
    shots, cur = [], a
    for t, at_sentence in cands:
        held = t - cur
        if held >= shot_min and (at_sentence or held >= shot_max):
            shots.append((cur, t))
            cur = t
    shots.append((cur, b))
    return shots


def build(words: list[dict], sentences: list[Sentence], plan: dict,
          silences: list[tuple[float, float]] = ()) -> Timeline:
    tl = Timeline()
    sentence_starts = [s.start for s in sentences]
    word_starts = [w["s"] for w in words]

    # 1. 콜드 오픈
    for k, h in enumerate(plan["hooks"]):
        s, e = _sentence_span(sentences, h["from"], h["to"])
        for a, b in keep_ranges(words, s, e, silences):
            tl.clips.append(Clip("hook", a, b, zoom=HOOK_ZOOMS[k % 2]))

    # 2. 인트로 범퍼 (콜드 오픈이 있을 때만)
    if tl.clips:
        first = sentences[0].start if sentences else 0.0
        tl.clips.append(Clip("bumper", first, first + BUMPER_SEC))

    # 3. 본편: skip 구간을 빼고, 챕터 시작 문장을 표시한다
    skipped = set()
    for sk in plan["skip"]:
        skipped.update(range(sk["from"], sk["to"] + 1))
    chapter_at = {c["from"]: n for n, c in enumerate(plan["chapters"])}

    body: list[list] = []  # [시작, 끝, 챕터번호]
    for s in sentences:
        if s.idx in skipped:
            continue
        for i, (a, b) in enumerate(keep_ranges(words, s.start, s.end, silences)):
            chapter = chapter_at.get(s.idx) if i == 0 else None
            if body and a <= body[-1][1] + 0.05:
                # 원본에서 바로 이어지는 구간: 챕터 경계가 아니면 합치고, 경계면 겹침만 없앤다
                if chapter is None:
                    body[-1][1] = max(body[-1][1], b)
                    continue
                body[-1][1] = min(body[-1][1], a)
            body.append([a, b, chapter])

    punch = [(sentences[i].start, sentences[i].end) for i in plan.get("punch", []) if 0 <= i < len(sentences)]
    for a, b, chapter in body:
        for j, (sa, sb) in enumerate(_shots(a, b, sentence_starts, word_starts)):
            mid = (sa + sb) / 2
            zoom = ZOOM_TIGHT if any(ps <= mid < pe for ps, pe in punch) else ZOOM_WIDE
            tl.clips.append(Clip("body", sa, sb, zoom=zoom, chapter=chapter if j == 0 else None, joined=j > 0))

    # 문장 단위로 따로 잘라서 생긴 겹침을 정리하고 프레임에 맞춘다
    t = 0.0
    for c in tl.clips:
        c.src_start, c.src_end = snap(c.src_start), snap(c.src_end)
        if c.src_end - c.src_start < 1 / FPS:
            c.src_end = c.src_start + 1 / FPS
        c.out_start = snap(t)
        t += c.dur
    return tl
