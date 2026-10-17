"""컷 구성(parts) 계산 + ASS 자막(후킹 문구, 단어 강조 자막) 생성."""
from dataclasses import dataclass

from .config import OUT_H, OUT_W
from .planner import ShortPlan


@dataclass
class Part:
    start: float   # 원본 기준 시각
    end: float
    zoom: float = 1.0
    teaser: bool = False

    @property
    def dur(self) -> float:
        return self.end - self.start


# ---------------------------------------------------------------- 컷 구성

def speech_islands(words: list[dict], start: float, end: float,
                   max_gap: float = 0.5, pad: float = 0.12) -> list[tuple[float, float]]:
    """단어 타임스탬프로 '말하는 구간'만 남김 (사이 공백이 max_gap보다 길면 잘라냄)."""
    ws = [w for w in words if w["end"] > start and w["start"] < end]
    if not ws:
        return [(start, end)]
    islands: list[list[float]] = []
    for w in ws:
        s, e = max(start, w["start"] - pad), min(end, w["end"] + pad)
        if islands and s - islands[-1][1] <= max_gap:
            islands[-1][1] = max(islands[-1][1], e)
        else:
            islands.append([s, e])
    # 첫/마지막 섬은 클립 경계까지 붙여서 문장이 잘리지 않게
    islands[0][0] = max(start, min(islands[0][0], start + 0.3))
    return [(round(s, 3), round(e, 3)) for s, e in islands]


def subtract_silences(start: float, end: float, silences: list, keep_pad: float = 0.12):
    parts, cur = [], start
    for s, e in silences:
        s, e = s + keep_pad, e - keep_pad
        if e <= cur or s >= end or e - s < 0.3:
            continue
        if s > cur:
            parts.append((cur, s))
        cur = max(cur, e)
    if cur < end:
        parts.append((cur, end))
    return parts or [(start, end)]


def build_parts(plan: ShortPlan, words: list[dict], silences: list, *, cut_silence: bool,
                zoom_punch: bool) -> list[Part]:
    if cut_silence:
        ranges = speech_islands(words, plan.start, plan.end) if words else \
            subtract_silences(plan.start, plan.end, silences)
    else:
        ranges = [(plan.start, plan.end)]
    ranges = [r for r in ranges if r[1] - r[0] >= 0.25] or [(plan.start, plan.end)]

    parts: list[Part] = []
    if plan.teaser_end > plan.teaser_start:
        parts.append(Part(plan.teaser_start, plan.teaser_end, zoom=1.18 if zoom_punch else 1.0, teaser=True))
    zoom = 1.0
    for i, (s, e) in enumerate(ranges):
        # 1초 이상인 컷에서만 줌을 번갈아 바꿔 '점프컷' 느낌
        if zoom_punch and i > 0 and e - s >= 1.0:
            zoom = 1.1 if zoom == 1.0 else 1.0
        parts.append(Part(s, e, zoom=zoom))
    return parts


def output_timeline(parts: list[Part]) -> list[tuple[Part, float]]:
    """각 part가 결과 영상에서 시작하는 시각."""
    out, t = [], 0.0
    for p in parts:
        out.append((p, t))
        t += p.dur
    return out


# ---------------------------------------------------------------- 자막 묶기

def chunk_words(words: list[dict], max_chars: int = 12, max_words: int = 3, max_gap: float = 0.35):
    """화면에 한 번에 보여줄 짧은 자막 덩어리 (1~3단어)."""
    chunks, cur = [], []
    for w in words:
        if cur:
            text_len = sum(len(x["text"]) for x in cur) + len(cur) + len(w["text"])
            if (len(cur) >= max_words or text_len > max_chars or w["start"] - cur[-1]["end"] > max_gap
                    or cur[-1]["text"].endswith((".", "?", "!", ","))):
                chunks.append(cur)
                cur = []
        cur.append(w)
    if cur:
        chunks.append(cur)
    return chunks


# ---------------------------------------------------------------- ASS

def _ts(t: float) -> str:
    t = max(0.0, t)
    cs = int(round(t * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _esc(text: str) -> str:
    return text.replace("\\", "＼").replace("{", "(").replace("}", ")").replace("\n", " ")


YELLOW = "&H0000F0FF&"   # ASS 색상은 BGR
WHITE = "&H00FFFFFF&"


def _clean(word: str) -> str:
    return "".join(ch for ch in word if ch.isalnum())


def _is_highlight(word: str, highlights: list[str]) -> bool:
    w = _clean(word)
    return bool(w) and any(h and (_clean(h) in w or (len(w) >= 2 and w in _clean(h))) for h in highlights)


def build_ass(plan: ShortPlan, parts: list[Part], words: list[dict], *, layout: str,
              total: float, font: str, src_w: int, src_h: int) -> str:
    # 레이아웃별 위치: blur는 영상이 가운데, crop은 화면 전체
    if layout == "blur":
        video_h = OUT_W * src_h / src_w
        top_space = (OUT_H - video_h) / 2
        hook_y = max(260, top_space * 0.55)
        cap_y = min(OUT_H - 260, OUT_H - top_space * 0.55) if top_space > 300 else OUT_H * 0.72
    else:
        hook_y, cap_y = 330, OUT_H * 0.70

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {OUT_W}
PlayResY: {OUT_H}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Hook,{font},96,{WHITE},{WHITE},&H00000000&,&H99000000&,0,0,0,0,100,100,0,0,1,7,4,5,60,60,0,1
Style: Caption,{font},84,{WHITE},{WHITE},&H00000000&,&H80000000&,0,0,0,0,100,100,0,0,1,8,3,5,70,70,0,1
Style: Teaser,{font},54,{WHITE},{WHITE},&H00000000&,&H802020E0&,0,0,0,0,100,100,0,0,3,14,0,5,40,40,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []

    # 상단 후킹 문구: 처음부터 끝까지, 첫 줄 흰색 / 둘째 줄 노란색, 등장 시 팝
    lines = [l for l in plan.hook_text.split("\n") if l.strip()][:2]
    if lines:
        styled = [_esc(lines[0])] + [f"{{\\c{YELLOW}}}{_esc(l)}" for l in lines[1:]]
        pop = "{\\fscx70\\fscy70\\t(0,180,\\fscx105\\fscy105)\\t(180,260,\\fscx100\\fscy100)}"
        events.append(f"Dialogue: 2,{_ts(0)},{_ts(total)},Hook,,0,0,0,,"
                      f"{{\\pos({OUT_W // 2},{int(hook_y)})}}{pop}" + "\\N".join(styled))

    timeline = output_timeline(parts)
    for p, offset in timeline:
        if p.teaser:
            events.append(f"Dialogue: 3,{_ts(offset)},{_ts(offset + p.dur)},Teaser,,0,0,0,,"
                          f"{{\\pos({OUT_W // 2},{int(max(110, hook_y - 190))})}}잠시 후 공개")
        part_words = [w for w in words if w["start"] >= p.start - 0.05 and w["end"] <= p.end + 0.05]
        for chunk in chunk_words(part_words):
            s = offset + max(0.0, chunk[0]["start"] - p.start)
            e = offset + min(p.dur, chunk[-1]["end"] - p.start)
            if e - s < 0.05:
                continue
            pieces = []
            for w in chunk:
                t = _esc(w["text"])
                pieces.append(f"{{\\c{YELLOW}}}{t}{{\\c{WHITE}}}" if _is_highlight(w["text"], plan.highlight_words) else t)
            pop = "{\\fscx80\\fscy80\\t(0,90,\\fscx100\\fscy100)}"
            events.append(f"Dialogue: 1,{_ts(s)},{_ts(e)},Caption,,0,0,0,,"
                          f"{{\\pos({OUT_W // 2},{int(cap_y)})}}{pop}" + " ".join(pieces))
    return header + "\n".join(events) + "\n"
