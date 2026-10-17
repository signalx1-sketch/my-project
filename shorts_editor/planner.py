"""어떤 구간을 쇼츠로 자를지, 어떤 문구를 넣을지 결정.

1순위: Claude가 대본을 읽고 구간·후킹 문구·제목을 고름.
대체: 음량·말 밀도·장면 전환 기반 자동 점수로 고름.
"""
import json
import logging
import os
from dataclasses import asdict, dataclass, field

import numpy as np

from .config import Options

log = logging.getLogger(__name__)

HOP = 0.5  # audio_envelope 간격과 같아야 함
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-opus-5-5")


@dataclass
class ShortPlan:
    start: float
    end: float
    title: str                       # 업로드용 제목
    hook_text: str                   # 화면 상단 문구 (줄바꿈은 \n)
    teaser_start: float = 0.0        # 맨 앞 미리보기 구간 (없으면 0, 0)
    teaser_end: float = 0.0
    highlight_words: list[str] = field(default_factory=list)
    reason: str = ""
    score: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ShortPlan":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ---------------------------------------------------------------- 공통

def _zscore(x: np.ndarray) -> np.ndarray:
    sd = x.std()
    return (x - x.mean()) / sd if sd > 1e-6 else np.zeros_like(x)


def hop_scores(analysis: dict) -> np.ndarray:
    """0.5초 단위 '재미 점수': 음량 + 음량 급등 + 말 밀도 + 장면 전환."""
    dur = analysis["probe"]["duration"]
    n = max(1, int(np.ceil(dur / HOP)))
    loud = np.full(n, -60.0)
    env = np.array(analysis.get("envelope") or [], dtype=float)
    loud[: min(n, len(env))] = env[:n]
    loud = np.maximum(loud, -60.0)
    rise = np.maximum(np.diff(loud, prepend=loud[0]), 0)

    density = np.zeros(n)
    for seg in analysis.get("transcript", []):
        for w in seg["words"]:
            i = int(w["start"] / HOP)
            if i < n:
                density[i] += 1
    scenes = np.zeros(n)
    for t in analysis.get("scenes", []):
        i = int(t / HOP)
        if i < n:
            scenes[i] += 1
    # 주변 2초로 부드럽게
    k = np.ones(4) / 4
    density = np.convolve(density, k, mode="same")
    scenes = np.convolve(scenes, k, mode="same")
    return 0.45 * _zscore(loud) + 0.2 * _zscore(rise) + 0.25 * _zscore(density) + 0.1 * _zscore(scenes)


def _window_mean(scores: np.ndarray, s: float, e: float) -> float:
    a, b = int(s / HOP), max(int(s / HOP) + 1, int(e / HOP))
    return float(scores[a:b].mean()) if b <= len(scores) and a < b else float(scores[a:].mean() if a < len(scores) else 0)


def _sentences(analysis: dict) -> list[dict]:
    return [s for s in analysis.get("transcript", []) if s["text"]]


def _overlaps(a: tuple, b: tuple) -> bool:
    return a[0] < b[1] and b[0] < a[1]


def best_teaser(scores: np.ndarray, start: float, end: float, length: float = 2.5) -> tuple[float, float]:
    """클립 뒷부분에서 가장 강한 2.5초. 클립 평균보다 확실히 강할 때만."""
    if end - start < 15:
        return 0.0, 0.0
    lo = start + (end - start) * 0.4
    best, best_t = -1e9, None
    t = lo
    while t + length <= end:
        v = _window_mean(scores, t, t + length)
        if v > best:
            best, best_t = v, t
        t += HOP
    if best_t is None or best - _window_mean(scores, start, end) < 0.6:
        return 0.0, 0.0
    return round(best_t, 2), round(best_t + length, 2)


# ---------------------------------------------------------------- 자동(휴리스틱) 선정

FALLBACK_HOOKS = [
    "이 장면 놓치면\n후회합니다",
    "끝까지 보면\n소름 돋는 이유",
    "아무도 예상 못한\n결말",
    "이거 실화임?\n직접 보세요",
    "여기서부터\n분위기 반전",
]


def _hook_from_text(text: str) -> str:
    text = text.strip().rstrip(".")
    if len(text) <= 12:
        return text
    words, lines, cur = text.split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > 12 and cur:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
        if len(lines) == 2:
            break
    if len(lines) < 2 and cur:
        lines.append(cur)
    return "\n".join(lines[:2])


def heuristic_plan(analysis: dict, opts: Options) -> list[ShortPlan]:
    dur = analysis["probe"]["duration"]
    scores = hop_scores(analysis)
    sents = _sentences(analysis)

    if dur <= opts.min_len:
        windows = [(0.0, dur)]
    else:
        if sents:  # 문장 시작/끝에 맞춰 자르기
            starts = [s["start"] for s in sents]
            ends = [s["end"] for s in sents]
        else:
            starts = list(np.arange(0, dur - opts.min_len + 1e-6, 1.0))
            ends = list(np.arange(opts.min_len, dur + 1e-6, 1.0)) + [dur]
        words = [w for x in sents for w in x["words"]]

        def length(s, e):  # 무음 컷 이후 실제 길이 기준
            if not (opts.cut_silence and words):
                return e - s
            from .captions import speech_islands
            return sum(b - a for a, b in speech_islands(words, s, e))

        windows = []
        for s in starts:
            cands = [e for e in ends if opts.min_len <= e - s <= opts.max_len * 2
                     and opts.min_len <= length(s, e) <= opts.max_len]
            if not cands:
                continue
            # 시작 3초(후킹 구간) 가중치를 크게
            def value(e):
                return 0.55 * _window_mean(scores, s, e) + 0.45 * _window_mean(scores, s, s + 3)
            e = max(cands, key=value)
            windows.append((float(s), float(e)))

    ranked = sorted(windows, key=lambda w: 0.55 * _window_mean(scores, *w) + 0.45 * _window_mean(scores, w[0], w[0] + 3),
                    reverse=True)
    chosen: list[tuple[float, float]] = []
    for w in ranked:
        if all(not _overlaps(w, c) for c in chosen):
            chosen.append(w)
        if len(chosen) >= opts.count:
            break

    plans = []
    for i, (s, e) in enumerate(chosen):
        ts, te = best_teaser(scores, s, e) if opts.teaser else (0.0, 0.0)
        inside = [x for x in sents if x["start"] >= s and x["end"] <= e]
        if inside:
            # 가장 강한 문장(음량 기준)을 후킹 문구로
            key = max(inside, key=lambda x: _window_mean(scores, x["start"], x["end"]))
            hook = _hook_from_text(key["text"])
            title = key["text"][:40]
        else:
            hook = FALLBACK_HOOKS[i % len(FALLBACK_HOOKS)]
            title = hook.replace("\n", " ")
        plans.append(ShortPlan(start=round(s, 2), end=round(e, 2), title=f"{title} #shorts",
                               hook_text=hook, teaser_start=ts, teaser_end=te,
                               reason="자동 분석: 음량·말 밀도·장면 전환 점수 상위 구간",
                               score=round(_window_mean(scores, s, e), 3)))
    return plans


# ---------------------------------------------------------------- Claude 선정

SYSTEM_PROMPT = """당신은 조회수 상위 1% 유튜브 쇼츠 편집자입니다. 긴 원본 영상의 대본을 보고, 시청 지속률이 높고 클릭률(CTR)이 잘 나오는 쇼츠 구간을 고르고 문구를 씁니다.

구간 선정 원칙
- 처음 1~3초 안에 시청자를 붙잡는 말(질문, 반전, 충격적인 사실, 갈등, 숫자)로 시작하는 구간을 고르세요. 인사·자기소개·"자 그럼"처럼 늘어지는 말로 시작하면 안 됩니다.
- 앞뒤 맥락 없이도 이해되는 완결된 이야기여야 하고, 끝은 결론·펀치라인·여운이 있는 문장에서 끝나야 합니다 (반복 시청 유도).
- 시작과 끝은 반드시 대본에 주어진 문장 경계 시각에 맞추세요.
- 구간끼리 겹치면 안 됩니다.

미리보기(teaser)
- 클립 안에서 가장 강렬한 1.5~3초(웃음, 반전, 핵심 한마디)를 골라 맨 앞에 미리 보여줍니다. 클립 앞쪽 40% 이후에서 고르세요. 마땅한 순간이 없으면 teaser_start, teaser_end 모두 0으로 두세요.

hook_text (화면 상단에 계속 떠 있는 문구)
- 2줄, 줄바꿈은 \\n, 한 줄에 12자 이내.
- 호기심 격차를 만드세요: 결과를 암시하되 답은 영상 안에 있게. 숫자·대비·구체적 단어를 쓰세요.
- 영상 내용과 다른 낚시는 금지 (이탈률이 올라가 오히려 노출이 줄어듭니다).

title (업로드 제목)
- 40자 이내, 핵심 키워드를 앞쪽에, 끝에 #shorts.

highlight_words
- 자막에서 노란색으로 강조할 핵심 단어 3~8개. 대본에 실제로 나오는 단어 그대로 쓰세요.

score: 예상 성과 0~100."""

PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "shorts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "start": {"type": "number"},
                    "end": {"type": "number"},
                    "teaser_start": {"type": "number"},
                    "teaser_end": {"type": "number"},
                    "hook_text": {"type": "string"},
                    "title": {"type": "string"},
                    "highlight_words": {"type": "array", "items": {"type": "string"}},
                    "reason": {"type": "string"},
                    "score": {"type": "number"},
                },
                "required": ["start", "end", "teaser_start", "teaser_end", "hook_text", "title",
                             "highlight_words", "reason", "score"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["shorts"],
    "additionalProperties": False,
}


def _transcript_lines(analysis: dict) -> str:
    scores = hop_scores(analysis)
    lines = []
    for s in _sentences(analysis):
        energy = _window_mean(scores, s["start"], s["end"])
        lines.append(f"[{s['start']:.2f}-{s['end']:.2f}] (에너지 {energy:+.1f}) {s['text']}")
    return "\n".join(lines)


def ai_plan(analysis: dict, opts: Options) -> list[ShortPlan]:
    import anthropic

    dur = analysis["probe"]["duration"]
    user = (
        f"원본 길이: {dur:.1f}초\n"
        f"만들 쇼츠 개수: {opts.count}개\n"
        f"쇼츠 길이: {opts.min_len:.0f}~{opts.max_len:.0f}초 (말 없는 부분은 자동으로 잘려 실제로는 조금 짧아집니다)\n"
        f"미리보기(teaser) 사용: {'예' if opts.teaser else '아니오 (teaser_start, teaser_end는 0)'}\n\n"
        "대본 (문장별 [시작-끝 초], 에너지는 음량·말 빠르기 기반 상대 점수):\n"
        f"{_transcript_lines(analysis)}"
    )
    client = anthropic.Anthropic()
    with client.beta.messages.stream(
        model=CLAUDE_MODEL,
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        output_config={"effort": "high",
                       "format": {"type": "json_schema", "schema": PLAN_SCHEMA}},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        messages=[{"role": "user", "content": user}],
    ) as stream:
        msg = stream.get_final_message()
    if msg.stop_reason == "refusal":
        raise RuntimeError("Claude가 요청을 거절했습니다.")
    text = "".join(b.text for b in msg.content if b.type == "text")
    data = json.loads(text)
    return [ShortPlan.from_dict(d) for d in data["shorts"]]


def _snap(t: float, points: list[float]) -> float:
    return min(points, key=lambda p: abs(p - t)) if points else t


def sanitize(plans: list[ShortPlan], analysis: dict, opts: Options) -> list[ShortPlan]:
    """AI 결과를 문장 경계·길이·겹침 규칙에 맞게 보정."""
    dur = analysis["probe"]["duration"]
    sents = _sentences(analysis)
    starts = [s["start"] for s in sents]
    ends = [s["end"] for s in sents]
    out: list[ShortPlan] = []
    for p in plans:
        s = max(0.0, _snap(p.start, starts))
        e = min(dur, _snap(p.end, ends))
        if e - s > opts.max_len + 5:  # 너무 길면 최대 길이 안쪽 문장 끝까지
            inner = [x for x in ends if s + opts.min_len <= x <= s + opts.max_len]
            e = max(inner) if inner else s + opts.max_len
        if e - s < min(opts.min_len * 0.5, dur):
            continue
        if any(_overlaps((s, e), (o.start, o.end)) for o in out):
            continue
        p.start, p.end = round(s, 2), round(e, 2)
        if not (p.start <= p.teaser_start < p.teaser_end <= p.end) or p.teaser_end - p.teaser_start > 4:
            p.teaser_start = p.teaser_end = 0.0
        if not opts.teaser:
            p.teaser_start = p.teaser_end = 0.0
        p.hook_text = p.hook_text.replace("\\n", "\n").strip()
        out.append(p)
    return out[: opts.count]


def plan_shorts(analysis: dict, opts: Options) -> tuple[list[ShortPlan], str]:
    """(계획 목록, 사용한 방법) 반환."""
    if opts.use_ai and _sentences(analysis):
        try:
            plans = sanitize(ai_plan(analysis, opts), analysis, opts)
            if plans:
                return plans, "claude"
        except Exception as e:  # API 키 없음·네트워크 오류 등 → 자동 분석으로 대체
            log.warning("Claude 구간 선정 실패, 자동 분석으로 대체: %s", e)
    return heuristic_plan(analysis, opts), "heuristic"
