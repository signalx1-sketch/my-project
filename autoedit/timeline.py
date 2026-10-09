"""편집 계획을 실제 클립 순서(타임라인)로 바꾼다.

결과 순서: 콜드 오픈(hooks) → 인트로 범퍼 → 본편
모든 경계는 프레임 단위로 맞춰서 영상과 오디오 길이가 어긋나지 않게 한다.
"""
from dataclasses import dataclass, field

from .cuts import Sentence, keep_ranges

FPS = 30
BUMPER_SEC = 1.4

ZOOM_WIDE = 1.0
ZOOM_TIGHT = 1.15
HOOK_ZOOMS = (1.12, 1.26)
MIN_ZOOM_HOLD = 2.5  # 줌을 바꾼 뒤 최소 유지 시간 (너무 자주 바뀌면 어지럽다)


def snap(t: float) -> float:
    return round(round(t * FPS) / FPS, 4)


@dataclass
class Clip:
    kind: str            # "hook" | "bumper" | "body"
    src_start: float
    src_end: float
    zoom: float = 1.0
    out_start: float = 0.0
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


def build(words: list[dict], sentences: list[Sentence], plan: dict) -> Timeline:
    tl = Timeline()

    # 1. 콜드 오픈
    for n, h in enumerate(plan["hooks"]):
        s, e = _sentence_span(sentences, h["from"], h["to"])
        for i, (a, b) in enumerate(keep_ranges(words, s, e)):
            tl.clips.append(Clip("hook", a, b, zoom=HOOK_ZOOMS[(n + i) % 2]))

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
        for i, (a, b) in enumerate(keep_ranges(words, s.start, s.end)):
            chapter = chapter_at.get(s.idx) if i == 0 else None
            if body and a <= body[-1][1] + 0.05:
                # 원본에서 바로 이어지는 구간: 챕터 경계가 아니면 합치고, 경계면 겹침만 없앤다
                if chapter is None:
                    body[-1][1] = max(body[-1][1], b)
                    continue
                body[-1][1] = min(body[-1][1], a)
            body.append([a, b, chapter])

    zoom, held = ZOOM_WIDE, 0.0
    for a, b, chapter in body:
        if chapter is not None:
            zoom, held = ZOOM_WIDE, 0.0
        elif held >= MIN_ZOOM_HOLD:
            zoom, held = (ZOOM_TIGHT if zoom == ZOOM_WIDE else ZOOM_WIDE), 0.0
        tl.clips.append(Clip("body", a, b, zoom=zoom, chapter=chapter))
        held += b - a

    # 문장 단위로 따로 잘라서 생긴 겹침을 정리하고 프레임에 맞춘다
    t = 0.0
    for c in tl.clips:
        c.src_start, c.src_end = snap(c.src_start), snap(c.src_end)
        if c.src_end - c.src_start < 1 / FPS:
            c.src_end = c.src_start + 1 / FPS
        c.out_start = snap(t)
        t += c.dur
    return tl
