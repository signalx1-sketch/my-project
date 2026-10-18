"""컷 구성(parts) 계산 + ASS 자막(후킹 문구, 단어 강조 자막) 생성."""
from dataclasses import dataclass

from .config import OUT_H, OUT_W
from .planner import ShortPlan
from .styles import TextStyle, ass_color, ass_size, text_width


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


def split_long_shots(ranges, words: list[dict], max_shot: float = 3.2, min_shot: float = 1.2):
    """말이 쉬지 않고 이어져도 ~3초마다 단어 사이에서 컷을 나눠 줌 변화를 줌 (내용은 그대로)."""
    out = []
    for a, b in ranges:
        gaps = [(w1["end"] + w2["start"]) / 2 for w1, w2 in zip(words, words[1:])
                if a + min_shot < w1["end"] and w2["start"] < b - min_shot]
        cur = a
        for g in gaps:
            if g - cur >= max_shot:
                out.append((cur, round(g, 3)))
                cur = round(g, 3)
        out.append((cur, b))
    return out


def build_parts(plan: ShortPlan, words: list[dict], silences: list, *, cut_silence: bool,
                zoom_punch: bool) -> list[Part]:
    spans = [tuple(x) for x in plan.segments] or [(plan.start, plan.end)]
    ranges = []
    for a, b in spans:
        if cut_silence:
            ranges += speech_islands(words, a, b) if words else subtract_silences(a, b, silences)
        else:
            ranges.append((a, b))
    ranges = [r for r in ranges if r[1] - r[0] >= 0.25] or spans

    if zoom_punch and words:
        ranges = split_long_shots(ranges, words)

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


def to_output_time(parts: list[Part], t: float) -> float | None:
    """원본 시각 t가 결과 영상에서 나오는 시각 (잘려 나간 곳이면 다음 컷 시작)."""
    nxt = None
    for p, off in output_timeline(parts):
        if p.teaser:
            continue
        if p.start <= t < p.end:
            return off + t - p.start
        if p.start >= t and nxt is None:
            nxt = off
    return nxt


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


def _hook_line(line: str, default_yellow: bool) -> str:
    """[대괄호] 안은 노란색 강조. 대괄호가 없으면 줄 전체 색을 기본값으로."""
    if "[" not in line:
        t = _esc(line)
        return f"{{\\c{YELLOW}}}{t}" if default_yellow else t
    out, cur, yellow = [], "", False
    for ch in line:
        if ch in "[]":
            if cur:
                out.append(f"{{\\c{YELLOW if yellow else WHITE}}}{_esc(cur)}")
            cur, yellow = "", ch == "["
        else:
            cur += ch
    if cur:
        out.append(f"{{\\c{YELLOW if yellow else WHITE}}}{_esc(cur)}")
    return "".join(out)


def build_ass(plan: ShortPlan, parts: list[Part], words: list[dict], *, layout: str,
              total: float, font: str, src_w: int, src_h: int,
              header_style: str = "bar", cta_text: str = "", related_text: str = "",
              style: TextStyle | None = None) -> str:
    if style is None:  # 예전 방식 (Black Han Sans, 흰/노랑 2톤)
        style = TextStyle(header_font=font, caption_font=font, header_pt=96 / 0.3, caption_pt=84 / 0.3,
                          header_color="", header_bar=header_style == "bar", caption_italic=False,
                          caption_highlight=True)
    st = style.resolved()
    hdr_lines = [l.replace("[", "").replace("]", "") for l in plan.hook_text.split("\n") if l.strip()][:2]
    hdr_px = st.header_pt * st.pt_scale
    widest = max((text_width(st.header_font, hdr_px, l) for l in hdr_lines), default=0)
    if widest > OUT_W - 100:  # 화면 폭에 맞게 축소 (좌우 여백 50px)
        hdr_px *= (OUT_W - 100) / widest
    cap_px = st.caption_pt * st.pt_scale
    hdr_col, cap_col, hl_col = ass_color(st.header_color or "#FFFFFF"), ass_color(st.caption_color), \
        ass_color(st.highlight_color)
    slant = "\\fax-0.18" if st.caption_italic else ""
    # 레이아웃별 위치: blur는 영상이 가운데, crop은 화면 전체
    if layout == "black":  # 레퍼런스(1080×1920 기준 실측): 문구 중심 386, 자막 중심 1449
        hook_y, cap_y = 386, 1449
    elif layout == "blur":
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
Style: Hook,{st.header_font},{ass_size(st.header_font, hdr_px):.0f},{hdr_col},{hdr_col},&H00000000&,&H99000000&,-1,0,0,0,100,100,0,0,1,7,4,5,40,40,0,1
Style: Caption,{st.caption_font},{ass_size(st.caption_font, cap_px):.0f},{cap_col},{cap_col},&H00000000&,&H80000000&,-1,0,0,0,100,100,0,0,1,7,3,5,60,60,0,1
Style: Teaser,{st.caption_font},54,{WHITE},{WHITE},&H00000000&,&H802020E0&,-1,0,0,0,100,100,0,0,3,14,0,5,40,40,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []

    # 상단 후킹 문구: 처음부터 끝까지. [대괄호]는 노란색 강조 (없으면 둘째 줄이 노란색)
    lines = [l for l in plan.hook_text.split("\n") if l.strip()][:2]
    if lines:
        if st.header_color:  # 문구 전체를 한 색으로
            styled = [_esc(l) for l in hdr_lines]
        else:
            styled = [_hook_line(l, default_yellow=i > 0) for i, l in enumerate(lines)]
        if layout == "black":
            # 검은 배경 위에 줄마다 따로 배치 (줄 간격 = 글자 크기 × 1.22, 레퍼런스 실측)
            pitch = hdr_px * 1.22
            y0 = hook_y - pitch * (len(styled) - 1) / 2
            for i, line in enumerate(styled):
                events.append(f"Dialogue: 2,{_ts(0)},{_ts(total)},Hook,,0,0,0,,"
                              f"{{\\q2\\pos({OUT_W // 2},{int(y0 + i * pitch)})\\bord0\\shad0}}{line}")
        elif st.header_bar:
            # 레퍼런스 채널처럼 화면 폭 전체 검은 바 위에 문구
            bar_h = int(hdr_px * 1.3 * len(lines) + 70)
            y0 = int(hook_y - bar_h / 2)
            events.append(f"Dialogue: 1,{_ts(0)},{_ts(total)},Hook,,0,0,0,,"
                          f"{{\\an7\\pos(0,{y0})\\bord0\\shad0\\1c&H000000&\\1a&H10&\\p1}}"
                          f"m 0 0 l {OUT_W} 0 {OUT_W} {bar_h} 0 {bar_h}{{\\p0}}")
            events.append(f"Dialogue: 2,{_ts(0)},{_ts(total)},Hook,,0,0,0,,"
                          f"{{\\pos({OUT_W // 2},{int(hook_y)})\\bord3\\shad0}}" + "\\N".join(styled))
        else:
            pop = "{\\fscx70\\fscy70\\t(0,180,\\fscx105\\fscy105)\\t(180,260,\\fscx100\\fscy100)}"
            events.append(f"Dialogue: 2,{_ts(0)},{_ts(total)},Hook,,0,0,0,,"
                          f"{{\\pos({OUT_W // 2},{int(hook_y)})}}{pop}" + "\\N".join(styled))
    if related_text:
        # 연관 동영상 유도 문구: 처음부터 끝까지 고정. 레퍼런스 실측 — 왼쪽 5%에서 시작,
        # 중심 높이 89.5%, 글자 높이 화면의 2.2% (유튜브 '관련 동영상' 링크 바로 위를 가리킴)
        rel_px = OUT_H * 0.022 / 0.86
        events.append(f"Dialogue: 3,{_ts(0)},{_ts(total)},Hook,,0,0,0,,"
                      f"{{\\an4\\q2\\pos({int(OUT_W * 0.05)},{int(OUT_H * 0.895)})"
                      f"\\fs{ass_size(st.header_font, rel_px):.0f}\\bord0\\shad0}}{_esc(related_text)}")
    if cta_text:  # 마지막 3초 하단 안내 (예: 풀영상은 고정 댓글에서)
        events.append(f"Dialogue: 3,{_ts(max(0, total - 3))},{_ts(total)},Caption,,0,0,0,,"
                      f"{{\\pos({OUT_W // 2},{OUT_H - 120})\\fs52\\c{YELLOW}\\fad(200,0)}}{_esc(cta_text)}")

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
                hl = st.caption_highlight and _is_highlight(w["text"], plan.highlight_words)
                pieces.append(f"{{\\c{hl_col}}}{t}{{\\c{cap_col}}}" if hl else t)
            pop = f"{{{slant}\\fscx80\\fscy80\\t(0,90,\\fscx100\\fscy100)}}"
            events.append(f"Dialogue: 1,{_ts(s)},{_ts(e)},Caption,,0,0,0,,"
                          f"{{\\pos({OUT_W // 2},{int(cap_y)})}}{pop}" + " ".join(pieces))
    return header + "\n".join(events) + "\n"
