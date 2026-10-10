"""타임라인과 단어 타임스탬프로 ASS 자막(자막, 챕터 라벨, 로고, 큰 글씨)을 만들고 효과음 위치를 정한다."""
from dataclasses import dataclass

from .cuts import _ends_sentence, is_filler
from .timeline import Timeline

MAX_CHARS = 14      # 한 줄 최대 글자 수 (공백 제외)
MAX_WORDS = 6       # 한 줄 최대 어절 수
LINE_GAP = 0.5      # 출력 시간 기준으로 이만큼 비면 줄을 끊는다
POP_MIN_GAP = 20.0  # 강조 효과음 최소 간격 (자주 나면 거슬린다)
CTA_SEC = 6.0       # 마지막 구독 안내 표시 시간

YELLOW = "&H0000D2FF&"  # #FFD200 (ASS는 BGR 순서)

HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{cap},86,&H00FFFFFF,&H00FFFFFF,&H00000000,&H90000000,0,0,0,0,100,100,0,0,1,6,2,2,80,80,70,1
Style: Label,{big},44,&H00FFFFFF,&H00FFFFFF,&H38141414,&H38141414,0,0,0,0,100,100,0,0,3,14,0,7,56,56,52,1
Style: Logo,Pretendard Bold,34,&H10FFFFFF,&H10FFFFFF,&H50000000,&H00000000,0,0,0,0,100,100,0,0,1,3,1,9,56,56,56,1
Style: Big,{big},110,&H00FFFFFF,&H00FFFFFF,&H00000000,&H90000000,0,0,0,0,100,100,0,0,1,7,3,5,120,120,0,1
Style: Sub,{big},48,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,4,0,5,120,120,0,1
Style: Cta,{big},58,&H00FFFFFF,&H00FFFFFF,&H202020E0,&H202020E0,0,0,0,0,100,100,0,0,3,18,0,8,80,80,70,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


@dataclass
class OutWord:
    text: str
    s: float
    e: float
    section: str


def ts(t: float) -> str:
    t = max(0.0, t)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def esc(text: str) -> str:
    return text.replace("\\", "").replace("{", "(").replace("}", ")")


def fix_text(text: str, fixes: dict[str, str]) -> str:
    for wrong, right in fixes.items():
        text = text.replace(wrong, right)
    return text


def map_words(words: list[dict], tl: Timeline, fixes: dict[str, str]) -> list[OutWord]:
    """원본 단어들을 출력 타임라인 시간으로 옮기고 잘못 인식된 용어를 고친다 (잘려나간 단어는 빠진다)."""
    out: list[OutWord] = []
    for c in tl.clips:
        if c.kind == "bumper":
            continue
        for w in words:
            if w["s"] >= c.src_start - 0.03 and w["e"] <= c.src_end + 0.08 and not is_filler(w["w"]):
                s = c.out_start + max(0.0, w["s"] - c.src_start)
                e = min(c.out_start + c.dur, c.out_start + (w["e"] - c.src_start))
                out.append(OutWord(fix_text(w["w"], fixes), s, max(e, s + 0.05), c.kind))
    out.sort(key=lambda w: w.s)
    return out


def group_lines(ws: list[OutWord]) -> list[list[OutWord]]:
    lines: list[list[OutWord]] = []
    cur: list[OutWord] = []
    for w in ws:
        if cur:
            chars = sum(len(x.text) for x in cur) + len(w.text)
            if (chars > MAX_CHARS or len(cur) >= MAX_WORDS or w.s - cur[-1].e > LINE_GAP
                    or w.section != cur[-1].section or _ends_sentence(cur[-1].text)):
                lines.append(cur)
                cur = []
        cur.append(w)
    if cur:
        lines.append(cur)
    return lines


def _clean(text: str) -> str:
    return text.rstrip(".,…")


def build_ass(words: list[dict], tl: Timeline, plan: dict, channel: str,
              fonts: tuple[str, str] = ("Pretendard ExtraBold", "Pretendard ExtraBold")
              ) -> tuple[str, list[tuple[float, str]]]:
    """ASS 자막 문자열과 효과음 이벤트 [(시간, 종류)] 를 돌려준다."""
    events: list[str] = []
    sfx: list[tuple[float, str]] = []
    keywords = [k for k in plan.get("keywords", []) if k.strip()]
    total = tl.duration

    def add(layer: int, start: float, end: float, style: str, text: str):
        events.append(f"Dialogue: {layer},{ts(start)},{ts(end)},{style},,0,0,0,,{text}")

    # 자막
    lines = group_lines(map_words(words, tl, plan.get("fix", {})))
    last_pop = -POP_MIN_GAP
    for i, line in enumerate(lines):
        start = line[0].s
        end = line[-1].e + 0.3
        if i + 1 < len(lines):
            end = min(end, lines[i + 1][0].s)
        parts, hit = [], False
        for w in line:
            t = esc(_clean(w.text) if w is line[-1] else w.text)
            if any(k in w.text for k in keywords):
                parts.append(f"{{\\c{YELLOW}}}{t}{{\\c&H00FFFFFF&}}")
                hit = True
            else:
                parts.append(t)
        add(1, start, end, "Cap", " ".join(parts))
        if hit and start - last_pop >= POP_MIN_GAP:
            sfx.append((start, "pop"))
            last_pop = start

    # 로고
    if channel:
        add(0, 0, total, "Logo", esc(channel))

    hooks = [c for c in tl.clips if c.kind == "hook"]
    bumper = next((c for c in tl.clips if c.kind == "bumper"), None)
    if hooks:
        sfx.append((0.0, "whoosh"))
    if bumper:
        b0, b1 = bumper.out_start, bumper.out_start + bumper.dur
        title = esc(plan.get("title") or "")
        pop_in = "{\\fad(60,120)\\fscx70\\fscy70\\t(0,160,\\fscx100\\fscy100)}"
        if title:
            add(3, b0, b1, "Big", pop_in + title)
        if channel:
            add(3, b0, b1, "Sub", "{\\fad(60,120)\\pos(960,640)}" + esc(channel))
        sfx.append((b0, "whoosh"))

    # 챕터: 시작할 때 화면 중앙에 크게, 그 뒤로는 좌상단에 계속
    chapters = plan.get("chapters", [])
    starts = sorted((c.out_start, c.chapter) for c in tl.clips if c.chapter is not None)
    for n, (t0, ch) in enumerate(starts):
        t1 = starts[n + 1][0] if n + 1 < len(starts) else total
        label = esc(chapters[ch]["label"])
        if t0 > 1.0:  # 본편 첫 챕터는 범퍼 직후라 큰 글씨 생략
            add(3, t0, t0 + 1.6, "Big",
                "{\\fad(80,160)\\pos(960,230)\\fscx80\\fscy80\\t(0,140,\\fscx100\\fscy100)}"
                f"{{\\c{YELLOW}}}Q.{{\\c&H00FFFFFF&}} {label}")
            sfx.append((t0, "whoosh"))
        add(2, t0 + (1.6 if t0 > 1.0 else 0), t1, "Label", f"{{\\c{YELLOW}}}Q.{{\\c&H00FFFFFF&}} {label}")

    # 마지막 구독 안내
    if total > 30:
        add(3, total - CTA_SEC, total, "Cta",
            "{\\fad(150,200)\\fscx80\\fscy80\\t(0,180,\\fscx100\\fscy100)}구독 · 좋아요 · 알림설정")
        sfx.append((total - CTA_SEC, "ding"))

    header = HEADER.replace("{cap}", fonts[0]).replace("{big}", fonts[1])
    return header + "\n".join(events) + "\n", sorted(sfx)
