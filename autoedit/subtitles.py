"""타임라인과 단어 타임스탬프로 ASS 자막(자막, 챕터 라벨, 로고, 큰 글씨)을 만들고 효과음 위치를 정한다."""
from dataclasses import dataclass
import re

from .cuts import _ends_sentence, is_filler
from .timeline import Timeline

# 자막 스타일. 기본은 더마허브 레퍼런스 영상(youtu.be/dybUda36l7A)의 자막:
# Pretendard Bold, 화면 높이 3~3.5% 크기, 흰 글자 + 테두리 없이 반투명 검정 박스, 하단 중앙 한 줄(10~25자),
# 강조색/애니메이션 없음, 화자·슬라이드·자료 화면 위 어디서나 같은 모양.
CAPTION_STYLES = {
    "reference": {
        "font": "Pretendard",  # 굵기는 Bold 칸(-1)으로 고른다 (libass는 'Pretendard Bold'라는 이름으로 못 찾는다)
        "line": "52,&H00FFFFFF,&H00FFFFFF,&H80000000,&H80000000,-1,0,0,0,100,100,0,0,3,12,0,2,80,80,54,1",
        "max_chars": 22, "max_words": 9, "highlight": False,
    },
    # 예전 스타일: 어그로체 M 큰 글씨 + 검은 테두리, 핵심 단어 노란색
    "aggro": {
        "font": None,  # fonts.caption_fonts()가 고른 글꼴
        "line": "86,&H00FFFFFF,&H00FFFFFF,&H00000000,&H90000000,0,0,0,0,100,100,0,0,1,6,2,2,80,80,70,1",
        "max_chars": 14, "max_words": 6, "highlight": True,
    },
}
DEFAULT_CAPTION_STYLE = "reference"
MAX_CHARS = 14      # 한 줄 최대 글자 수 (공백 제외) - 스타일마다 바뀐다
MAX_WORDS = 6       # 한 줄 최대 어절 수
LINE_COST = 160     # 자막 줄 하나를 더 쓰는 비용 (나쁜 자리에서 끊는 비용과 견준다)
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
Style: Cap,{cap},{capline}
Style: Label,{big},44,&H00FFFFFF,&H00FFFFFF,&H38141414,&H38141414,0,0,0,0,100,100,0,0,3,14,0,7,56,56,52,1
Style: Logo,Pretendard,34,&H10FFFFFF,&H10FFFFFF,&H50000000,&H00000000,-1,0,0,0,100,100,0,0,1,3,1,9,56,56,56,1
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
    """원본 단어들을 출력 타임라인 시간으로 옮기고 잘못 인식된 용어를 고친다 (잘려나간 단어는 빠진다).

    음성 인식의 단어 시간에는 앞뒤 쉼이 붙어 있어서 무음을 자른 경계에 걸치는 경우가 많다.
    그래서 단어가 가장 많이 겹치는 클립에 붙이고, 그 클립 안으로 시간을 잘라 넣는다.
    """
    out: list[OutWord] = []
    clips = [c for c in tl.clips if c.kind != "bumper"]
    for w in words:
        if is_filler(w["w"]) or w.get("drop"):
            continue
        for kind in ("hook", "body"):  # 콜드 오픈에 쓰인 문장은 본편에도 한 번 더 나온다
            best, ov = None, 0.05
            for c in clips:
                if c.kind != kind:
                    continue
                o = min(w["e"], c.src_end) - max(w["s"], c.src_start)
                if o > ov:
                    best, ov = c, o
            if best is None:
                continue
            c = best
            s = c.to_out(max(w["s"], c.src_start))
            e = min(c.out_start + c.dur, c.to_out(w["e"]))
            out.append(OutWord(fix_text(w["w"], fixes), s, max(e, s + 0.05), c.kind))
    out.sort(key=lambda w: w.s)
    return _fix_phrases(out, {k: v for k, v in fixes.items() if " " in k.strip()})


def _fix_phrases(out: list[OutWord], fixes: dict[str, str]) -> list[OutWord]:
    """여러 어절에 걸친 교정('간별 진단' → '감별 진단'). 단어 하나씩 고치면 띄어쓰기가 있는 표현은 안 맞는다."""
    for wrong, right in fixes.items():
        k = len(wrong.split())
        i = 0
        while i + k <= len(out):
            win = out[i:i + k]
            joined = " ".join(w.text for w in win)
            if wrong in joined:
                toks = joined.replace(wrong, right).split()
                if len(toks) == k:
                    for w, t in zip(win, toks):
                        w.text = t
                else:  # 어절 수가 달라지면 첫 단어에 몰아 넣고 나머지는 지운다 (시간은 끝 단어까지)
                    win[0].text, win[0].e = " ".join(toks), win[-1].e
                    del out[i + 1:i + k]
            i += 1
    return out


# 이 글자로 끝나는 어절 뒤에서 끊으면 의미 단위로 자연스럽다 (연결어미, 조사, 쉼표)
# 뒤 말을 꾸미는 어절: 이 뒤에서 줄을 바꾸면 의미가 끊긴다 (2026-10-30)
NO_BREAK_AFTER = {"이", "그", "저", "이런", "그런", "저런", "웬만한", "어떤", "모든", "몇", "한", "두", "세", "네", "더", "가장",
                  "제일", "너무", "아주", "좀", "다른", "같은", "약", "총", "첫", "첫째", "둘째", "셋째", "다", "또", "안", "못", "잘",
                  "딱", "이거", "그거", "저거", "짧은", "큰", "작은", "새", "엉뚱한", "강력한", "충분한"}
# 앞말에 기대는 말: 이 말 앞에서 줄을 바꾸지 않는다 ('있는 / 거랑', '없다는 / 게', '바르다 / 보니')
NO_BREAK_BEFORE = ("거", "것", "게", "데", "때", "수", "줄", "적", "분이", "분들", "순간", "같은", "같이", "때문", "싶", "보니", "입니다",
                   "라는", "라고", "보다", "정도", "있는", "있다", "있어", "있죠", "있고", "있을", "있으면", "한다면", "하는")


def _leans(word: str) -> bool:
    """앞말에 기대는 말인가 (한 글자 의존명사는 짧은 어절일 때만: '수란트라'는 아님)."""
    return any(word.startswith(x) and (len(x) > 1 or len(word) <= 3) for x in NO_BREAK_BEFORE)
GOOD_BREAK = (",", "다", "라", "까", "고", "서", "면", "며", "데", "는", "은", "도", "를", "을", "에", "게", "지만", "니까", "요", "죠")


# 형태소 분석(Kiwi)으로 줄을 끊어도 되는 자리를 정한다 (2026-10-30). 없으면 위 낱말 목록 규칙만 쓴다
_KIWI = None


def _kiwi():
    global _KIWI
    if _KIWI is None:
        try:
            import os
            from kiwipiepy import Kiwi
            path = os.environ.get("KIWI_MODEL") or os.path.expanduser("~/tools/kiwi_model")
            _KIWI = Kiwi(model_path=path) if os.path.isdir(path) else Kiwi()
        except Exception:
            _KIWI = False
    return _KIWI


def _pos_gaps(texts: list[str]) -> list[int] | None:
    """어절 사이마다 끊기 비용 (len(texts)-1개). 꾸미는 어미·관형사 뒤, 의존명사·보조용언 앞, 명사+명사 사이는 비싸다."""
    k = _kiwi()
    if not k or len(texts) < 2:
        return None
    line = " ".join(texts)
    starts, pos = [], 0
    for t in texts:
        starts.append(pos)
        pos += len(t) + 1
    try:
        toks = k.tokenize(line)
    except Exception:
        return None
    per = [[] for _ in texts]
    for tk in toks:
        i = max(j for j, st in enumerate(starts) if st <= tk.start)
        per[i].append(tk.tag)
    gaps = []
    for i in range(len(texts) - 1):
        a, b = per[i], per[i + 1]
        if not a or not b:
            gaps.append(60)
            continue
        last, first = a[-1], b[0]
        if last in ("ETM", "MM") or first in ("NNB", "VX") or last == "XPN":
            gaps.append(700)
        elif last.startswith("NN") and first in ("VV", "VA"):
            gaps.append(150)  # 조사 없는 명사 + 동사 ('돈 / 날리는')
        elif last.startswith("NN") and first.startswith("NN"):
            gaps.append(300)  # 명사 + 명사 ('혈관 / 확장과')
        elif last in ("EF", "SF"):
            gaps.append(-30)  # 말이 끝나는 곳 ('가라 / 홍조와')
        elif last in ("EC", "SP"):
            gaps.append(-10)  # 연결어미·쉼표 뒤가 가장 자연스럽다
        elif last in ("JKO", "JC"):
            gaps.append(120)  # 목적어 뒤('돈 / 날리는'), 이음 조사 뒤('주사와 / 홍조')
        elif last in ("JKS", "JKC"):
            gaps.append(50)   # 주어 뒤('효과가 / 없거나')
        elif last.startswith("J"):
            gaps.append(20)
        elif last == "MAG":
            gaps.append(120)  # 부사 뒤 ('크게 / 신경 쓰지')
        else:
            gaps.append(60)
    return gaps


def _chars(ws: list[OutWord]) -> int:
    return sum(len(x.text.replace(" ", "")) for x in ws)


def _balanced(seg: list[OutWord], max_chars: int, max_words: int) -> list[list[OutWord]]:
    """한 덩어리를 줄 수가 가장 적고 길이가 고르게, 되도록 의미 단위에서 끊는다.

    "…좋아하지 / 않아요"처럼 두세 글자만 다음 줄로 밀리는 것을 막는다.
    """
    n = len(seg)
    total = _chars(seg)
    k = max(-(-total // max_chars), -(-n // max_words))
    target = total / k
    INF = float("inf")
    gaps = _pos_gaps([w.text for w in seg])
    # best[j]: 앞에서 j어절까지 줄로 나눴을 때 (줄 수, 비용)
    best: list[tuple[float, float]] = [(0, 0.0)] + [(INF, INF)] * n
    back = [0] * (n + 1)
    for j in range(1, n + 1):
        for i in range(j - 1, -1, -1):
            line = seg[i:j]
            c = _chars(line)
            if c > max_chars and j - i > 1 or j - i > max_words:
                break
            cost = 0.5 * (c - target) ** 2
            if c < 4 and n > 1:
                cost += 200  # 너무 짧은 줄
            elif c < 6 and n > 1:
                cost += 40
            if j < n and gaps is not None:
                cost += gaps[j - 1]
            elif j < n and not seg[j - 1].text.rstrip().endswith(GOOD_BREAK):
                cost += 60   # 의미 단위가 아닌 곳에서 끊음
            if j < n and _leans(seg[j].text):
                cost += 700
            if j < n and (seg[j - 1].text.rstrip(",") in NO_BREAK_AFTER or re.fullmatch(r"\d+,", seg[j - 1].text)):
                cost += 700  # 꾸미는 말 뒤('웬만한 / 중고차', '이 / 세 줄')에서 끊지 않는다
            cand = (best[i][0] + 1, best[i][1] + cost)
            # 줄 수가 하나 늘더라도 나쁜 자리에서 끊는 것보다 나으면 그쪽을 고른다 (줄 하나 = LINE_COST)
            if cand[1] + LINE_COST * cand[0] < best[j][1] + LINE_COST * best[j][0]:
                best[j], back[j] = cand, i
    out, j = [], n
    while j > 0:
        out.append(seg[back[j]:j])
        j = back[j]
    return out[::-1]


def group_lines(ws: list[OutWord], max_chars: int = MAX_CHARS, max_words: int = MAX_WORDS) -> list[list[OutWord]]:
    """자막 줄 나누기. 문장 끝, 긴 쉼, 구간(콜드 오픈/본편)이 바뀌는 곳에서 먼저 끊고,
    그 안에서 길면 고르게 나눈다."""
    segs: list[list[OutWord]] = []
    cur: list[OutWord] = []
    for w in ws:
        glued = cur and (cur[-1].text.rstrip(",") in NO_BREAK_AFTER or _leans(w.text))
        if cur and (w.section != cur[-1].section or not glued and (w.s - cur[-1].e > LINE_GAP or _ends_sentence(cur[-1].text))):
            segs.append(cur)
            cur = []
        cur.append(w)
    if cur:
        segs.append(cur)
    lines: list[list[OutWord]] = []
    for seg in segs:
        if _chars(seg) <= max_chars and len(seg) <= max_words:
            lines.append(seg)
        else:
            lines.extend(_balanced(seg, max_chars, max_words))
    return lines


def _clean(text: str) -> str:
    return text.rstrip(".,…")


def _visible(start: float, end: float, hide: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """[start, end]에서 hide 구간을 뺀 나머지 중 0.4초 이상인 조각."""
    out, cur = [], start
    for s, e in sorted(hide):
        if e <= cur or s >= end:
            continue
        if s > cur:
            out.append((cur, s))
        cur = max(cur, e)
    if cur < end:
        out.append((cur, end))
    return [(a, b) for a, b in out if b - a >= 0.4]


def build_ass(words: list[dict], tl: Timeline, plan: dict, channel: str,
              fonts: tuple[str, str] = ("Pretendard ExtraBold", "Pretendard ExtraBold"),
              hide: list[tuple[float, float]] = (), style: str = DEFAULT_CAPTION_STYLE
              ) -> tuple[str, list[tuple[float, str]]]:
    """ASS 자막 문자열과 효과음 이벤트 [(시간, 종류)] 를 돌려준다.

    hide: 슬라이드가 화면을 덮는 구간. 슬라이드에 섹션 이름이 있어서 이 동안은 좌상단 챕터 라벨과
    큰 챕터 제목을 숨긴다 (아래 자막은 그대로 둔다).
    """
    hide = list(hide)
    cs = CAPTION_STYLES[style]
    events: list[str] = []
    sfx: list[tuple[float, str]] = []
    # 강조색을 쓰지 않는 스타일이면 키워드 강조(와 그 팝 효과음)도 끈다
    keywords = [k for k in plan.get("keywords", []) if k.strip()] if cs["highlight"] else []
    total = tl.duration

    def add(layer: int, start: float, end: float, style: str, text: str):
        events.append(f"Dialogue: {layer},{ts(start)},{ts(end)},{style},,0,0,0,,{text}")

    # 자막
    lines = group_lines(map_words(words, tl, plan.get("fix", {})), cs["max_chars"], cs["max_words"])
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
    # 위쪽 진행 탭이 있는 파트는 좌상단 라벨을 띄우지 않는다 (같은 내용이 두 번 보인다)
    tab_chs = set((plan.get("progress") or {}).get("chapters") or [])
    starts = sorted((c.out_start, c.chapter) for c in tl.clips if c.chapter is not None)
    for n, (t0, ch) in enumerate(starts):
        t1 = starts[n + 1][0] if n + 1 < len(starts) else total
        label = esc(chapters[ch]["label"])
        covered = any(s <= t0 + 0.05 < e for s, e in hide)
        if t0 > 1.0 and not covered:  # 본편 첫 챕터는 범퍼 직후라 큰 글씨 생략. 표지 슬라이드가 덮으면 생략
            add(3, t0, t0 + 1.6, "Big",
                "{\\fad(80,160)\\pos(960,230)\\fscx80\\fscy80\\t(0,140,\\fscx100\\fscy100)}"
                f"{{\\c{YELLOW}}}Q.{{\\c&H00FFFFFF&}} {label}")
            sfx.append((t0, "whoosh"))
        for a, b in ([] if ch in tab_chs else _visible(t0 + (1.6 if t0 > 1.0 and not covered else 0), t1, hide)):
            add(2, a, b, "Label", f"{{\\c{YELLOW}}}Q.{{\\c&H00FFFFFF&}} {label}")

    # 마지막 구독 안내
    if total > 30:
        add(3, total - CTA_SEC, total, "Cta",
            "{\\fad(150,200)\\fscx80\\fscy80\\t(0,180,\\fscx100\\fscy100)}구독 · 좋아요 · 알림설정")
        sfx.append((total - CTA_SEC, "ding"))

    header = (HEADER.replace("{capline}", cs["line"]).replace("{cap}", cs["font"] or fonts[0])
              .replace("{big}", fonts[1]))
    return header + "\n".join(events) + "\n", sorted(sfx)
