"""슬라이드를 HyperFrames(HTML → 영상)로 움직이는 모션 그래픽 카드로 만든다.

카드 내용(글자, 색, 크기, 카드 종류)은 motion.read_cards()가 pptx에서 읽은 것을 쓴다.
같은 움직임이 반복되면 단조로워서 카드마다 등장 방식을 바꾼다 (바로 앞 카드와 같은 방식은 쓰지 않는다).

문장 카드
- blurword: 단어마다 흐림이 걷히며 나타난다
- maskrise: 줄마다 가려진 틀 안에서 밀려 올라온다
- greyink: 회색 글자가 단어 순서대로 제 색으로 칠해지고 마지막 줄 밑에 선이 그어진다
- wipe: 줄마다 왼쪽에서 오른쪽으로 닦아내듯 드러나고 빨간 줄에는 형광펜이 칠해진다
- center: 가운데 정렬, 줄 전체가 살짝 크게 흐린 상태에서 또렷해진다
- slam: 짧은 강조 문장. 첫 줄이 크게 찍히듯 들어오고 나머지가 따라온다
숫자 카드: 숫자가 자릿수마다 돌아가는 다이얼(오도미터)로 맞춰지고 밑줄이 그어진다
비교 카드: 숫자 다이얼 + 막대 두 개가 차례로 차오른다
파트 표지: 초록 패널이 화면을 쓸고 지나가며 열리고, 번호 다이얼과 제목이 나타난다
논문 카드: 어두운 카드가 오른쪽에서 미끄러져 들어오고 인용문이 단어마다 칠해진다

모든 카드를 영상 하나로 이어서 한 번에 렌더링한 뒤(크롬을 한 번만 띄운다) 카드별로 잘라 쓴다.
HyperFrames CLI(npx hyperframes)와 크롬이 없으면 None을 돌려주고 편집기는 예전 방식으로 대신한다.
"""
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from . import motion_templates as tpl
from .motion import Card, Run, read_cards

ROOT = Path(__file__).resolve().parent.parent
FONTS_DIR = ROOT / "assets" / "fonts"
VENDOR = ROOT / "assets" / "vendor"
HF_VERSION = "0.8.191"
FPS = 30
LEAD = 0.1           # 모든 등장을 이만큼 앞당긴다: 카드 첫 프레임이 빈 배경이면 화면이 깜빡이는 것처럼 보인다
PREROLL = 3          # 카드 영상을 이만큼(프레임) 진행된 시점부터 쓴다 (카드끼리 컷으로 넘어갈 때 빈 화면 깜빡임 방지)
AMBIENT_MIN = 6.5   # 카드 영상 최소 길이: 애니메이션이 끝나도 배경 빛·카메라가 천천히 움직여 멈춘 화면이 안 되게 (2026-11-09)
HOLD = 0.35          # 애니메이션이 끝난 뒤 카드별로 남겨 두는 시간 (나머지는 편집기가 마지막 장면을 늘린다)
TEXT_STYLES = ["maskrise", "blurword", "wipe", "greyink", "center"]

GREEN, RED, WHITE = "#52B788", "#E63946", "#FFFFFF"


def _env() -> dict:
    env = dict(os.environ)
    env.setdefault("DO_NOT_TRACK", "1")
    env.setdefault("HYPERFRAMES_NO_TELEMETRY", "1")
    return env


def _hf(args: list[str], cwd: Path, timeout: int = 3600) -> subprocess.CompletedProcess:
    return subprocess.run(["npx", "-y", f"hyperframes@{HF_VERSION}", *args], cwd=cwd, env=_env(),
                          capture_output=True, text=True, timeout=timeout)


def available(work: Path) -> bool:
    if not (shutil.which("npx") and shutil.which("ffmpeg")):
        return False
    try:
        r = _hf(["browser", "ensure"], work, timeout=900)
    except (subprocess.TimeoutExpired, OSError):
        return False
    return r.returncode == 0


def _gsap() -> Path | None:
    """GSAP을 npm에서 받아 assets/vendor에 둔다 (CDN이 막힌 환경이 있다)."""
    js = VENDOR / "gsap.min.js"
    if js.exists():
        return js
    VENDOR.mkdir(parents=True, exist_ok=True)
    tmp = VENDOR / "_pack"
    tmp.mkdir(exist_ok=True)
    r = subprocess.run(["npm", "pack", "gsap@3.14.2", "--silent"], cwd=tmp, capture_output=True, text=True)
    tgz = tmp / (r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "")
    if r.returncode != 0 or not tgz.is_file():
        return None
    subprocess.run(["tar", "xzf", str(tgz), "package/dist/gsap.min.js"], cwd=tmp, check=True)
    shutil.copy(tmp / "package/dist/gsap.min.js", js)
    shutil.rmtree(tmp, ignore_errors=True)
    return js


# ---------- 카드 HTML ----------

def _esc(s: str) -> str:
    return html.escape(s)


def _li(runs: list[Run], scale: float = 1.0) -> str:
    """줄 틀. 단어 사이 공백도 글자 크기에 맞게 벌어지도록 줄의 글자 크기를 가장 큰 단어에 맞춘다."""
    size = max(r.size for r in runs) * 2 * scale
    return f'<div class="li" style="font-size:{size:.0f}px">{_words(runs, scale)}</div>'


def _words(runs: list[Run], scale: float = 1.0, base_cls: str = "w") -> str:
    """런(색/크기)을 지키면서 단어마다 span으로 나눈다."""
    out = []
    for r in runs:
        style = f"color:{r.color};font-size:{r.size * 2 * scale:.0f}px;"
        if r.italic:
            style += "font-style:italic;font-weight:600;"
        elif r.size < 30:
            style += "font-weight:700;"
        for tok in re.split(r"(\s+)", r.text):
            if not tok:
                continue
            if tok.isspace():
                out.append(" ")
            else:
                out.append(f'<span class="{base_cls}" style="{style}">{_esc(tok)}</span>')
    return "".join(out)


_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _odometer(text: str, cid: str) -> tuple[str, list[tuple[str, int]]]:
    """숫자의 각 자릿수를 0~9가 적힌 세로 띠로 만든다. (띠 id, 몇 칸 내려갈지) 목록도 돌려준다."""
    out, strips, last, k = [], [], 0, 0
    for m in _NUM.finditer(text):
        out.append(_esc(text[last:m.start()]))
        digits = [ch for ch in m.group() if ch.isdigit()]
        di = 0
        for ch in m.group():
            if not ch.isdigit():
                out.append(f'<span class="dsep">{_esc(ch)}</span>')
                continue
            # 앞자리는 한 바퀴, 뒷자리일수록 더 많이 돈다 (실제 다이얼처럼)
            turns = 1 + (len(digits) - 1 - di)
            seq = [str(n % 10) for n in range(turns * 10)] + [ch]
            sid = f"{cid}d{k}"
            out.append(f'<span class="dcol"><span class="dstrip" id="{sid}">' +
                       "".join(f"<span>{d}</span>" for d in seq) + "</span></span>")
            strips.append((sid, len(seq) - 1))
            k += 1
            di += 1
        last = m.end()
    out.append(_esc(text[last:]))
    return "".join(out), strips


class _TL:
    """GSAP 타임라인 코드 조각을 모은다. 시간은 카드 시작 기준."""

    def __init__(self, t0: float):
        self.t0, self.lines, self.end = t0, [], 0.0

    def add(self, sel: str, frm: dict, to: dict, at: float, dur: float):
        n = to.get("_n", 1)  # stagger가 걸리는 대상 수 (끝나는 시각 계산용)
        to = {k: v for k, v in to.items() if not k.startswith("_")}
        to["duration"] = round(dur, 3)
        at = max(0.0, at - LEAD)
        self.lines.append(f"tl.fromTo({json.dumps(sel)},{json.dumps(frm)},{json.dumps(to)},{self.t0 + at:.3f});")
        stagger = to.get("stagger", 0)
        self.end = max(self.end, at + dur + (stagger * (n - 1) if isinstance(stagger, (int, float)) else 0))

    def raw(self, js: str, end: float = 0.0):
        self.lines.append(js)
        self.end = max(self.end, end)


def _text_card(c: Card, cid: str, style: str, tl: _TL) -> str:
    lines, header = [], ""
    centered = style == "center"
    for i, p in enumerate(c.paras):
        mark = '<div class="marker"></div>' if style == "wipe" and any(r.color.upper() == RED for r in p) else ""
        lines.append(f'<div class="ln" id="{cid}l{i}">{mark}{_li(p)}</div>')
    body = "".join(lines)
    n = len(c.paras)
    S = f"#{cid}"
    if style == "maskrise":
        tl.add(f"{S} .li", {"opacity": 0, "y": 22, "filter": "blur(6px)"}, ({"opacity": 1, "y": 0, "filter": "blur(0px)", "ease": "power3.out", "stagger": 0.12, "_n": n}), 0.12, 0.75)
    elif style == "blurword":
        nw = sum(len(r.text.split()) for p in c.paras for r in p)
        tl.add(f"{S} .w", {"opacity": 0, "filter": "blur(10px)"},
               ({"opacity": 1, "filter": "blur(0px)", "ease": "power2.out", "stagger": 0.06, "_n": nw}), 0.1, 0.22)
        tl.end = max(tl.end, 0.1 + 0.22 + 0.06 * nw)
    elif style == "greyink":
        nw = sum(len(r.text.split()) for p in c.paras for r in p)
        tl.raw(f'gsap.set("{S} .w",{{opacity:1}});')
        tl.add(f"{S} .li", {"opacity": 0}, {"opacity": 1, "duration": 0.2}, 0.05, 0.2)
        tl.raw(f'document.querySelectorAll("{S} .w").forEach((el,i)=>{{const c=getComputedStyle(el).color;'
               f'tl.fromTo(el,{{color:"#3a3a3a"}},{{color:c,duration:0.18,ease:"none"}},{tl.t0 + 0.25:.3f}+i*0.07);}});',
               end=0.25 + 0.07 * nw + 0.18)
        body += f'<div class="uline" id="{cid}u"></div>'
        tl.add(f"#{cid}u", {"scaleX": 0}, {"scaleX": 1, "ease": "power3.inOut"}, 0.25 + 0.07 * nw, 0.5)
    elif style == "wipe":
        tl.add(f"{S} .li", {"clipPath": "inset(0% 100% 0% 0%)"},
               ({"clipPath": "inset(0% 0% 0% 0%)", "ease": "power3.inOut", "stagger": 0.16, "_n": n}), 0.08, 0.6)
        # 빨간 강조 줄에는 형광펜
        for i, p in enumerate(c.paras):
            if any(r.color.upper() == RED for r in p):
                tl.add(f"#{cid}l{i} .marker", {"scaleX": 0}, {"scaleX": 1, "ease": "power2.out"}, 0.5 + 0.16 * i, 0.45)
    elif style == "center":
        tl.add(f"{S} .ln", {"opacity": 0, "scale": 1.06, "filter": "blur(8px)"},
               ({"opacity": 1, "scale": 1, "filter": "blur(0px)", "ease": "expo.out", "stagger": 0.14, "_n": n}), 0.1, 0.6)
        body = f'<div class="rule" id="{cid}r"></div>' + body
        tl.add(f"#{cid}r", {"scaleX": 0}, {"scaleX": 1, "ease": "power3.out"}, 0.05, 0.5)
    elif style == "slam":
        tl.add(f"#{cid}l0", {"opacity": 0, "scale": 1.35, "filter": "blur(6px)"},
               {"opacity": 1, "scale": 1, "filter": "blur(0px)", "ease": "expo.out"}, 0.08, 0.45)
        if n > 1:
            tl.add(f"{S} .ln:not(#{cid}l0) .li", {"opacity": 0, "y": 22, "filter": "blur(6px)"},
                   ({"opacity": 1, "y": 0, "filter": "blur(0px)", "ease": "power3.out", "stagger": 0.1, "_n": n - 1}), 0.32, 0.6)
    cls = "card text center" if centered else "card text"
    return cls, body


def _stat_card(c: Card, cid: str, variant: int, tl: _TL, compare: bool) -> tuple[str, str]:
    parts, all_strips = [], []
    k = 0
    for i, p in enumerate(c.paras):
        big = max(r.size for r in p)
        if big >= 60:
            spans = []
            for r in p:
                inner, strips = _odometer(r.text, f"{cid}n{k}")
                k += 1
                all_strips += strips
                spans.append(f'<span style="color:{r.color};font-size:{r.size * 2:.0f}px">{inner}</span>')
            parts.append(f'<div class="ln hero" id="{cid}l{i}"><div class="li">{"".join(spans)}</div></div>')
        else:
            parts.append(f'<div class="ln" id="{cid}l{i}">{_li(p)}</div>')
    body = "".join(parts)
    tl.add(f"#{cid} .hero", {"opacity": 0, "y": 30}, {"opacity": 1, "y": 0, "ease": "expo.out"}, 0.05, 0.5)
    for j, (sid, steps) in enumerate(all_strips):
        frac = steps / (steps + 1) * 100
        tl.add(f"#{sid}", {"yPercent": 0}, {"yPercent": -frac, "ease": "expo.out"}, 0.1 + 0.05 * j, 1.1)
    tl.add(f"#{cid} .ln:not(.hero) .li", {"opacity": 0, "y": 22, "filter": "blur(6px)"},
           ({"opacity": 1, "y": 0, "filter": "blur(0px)", "ease": "power3.out", "stagger": 0.1, "_n": max(1, len(c.paras) - 1)}), 0.7, 0.6)
    if compare:
        vals = [float(v) for v in re.findall(r"(\d+(?:\.\d+)?)\s*%", " ".join(r.text for p in c.paras for r in p))][:2]
        bars = "".join(f'<div class="brow"><div class="bfill" id="{cid}b{j}" style="width:{v}%;'
                       f'background:{GREEN if j == 0 else "#6b6b6b"}"></div><span class="bval">{v:g}%</span></div>'
                       for j, v in enumerate(vals))
        body += f'<div class="bars">{bars}</div>'
        for j in range(len(vals)):
            tl.add(f"#{cid}b{j}", {"scaleX": 0}, {"scaleX": 1, "ease": "power3.out"}, 1.05 + 0.18 * j, 0.8)
        tl.add(f"#{cid} .bval", {"opacity": 0}, ({"opacity": 1, "stagger": 0.18, "_n": len(vals)}), 1.5, 0.3)
    else:
        body += f'<div class="uline" id="{cid}u"></div>'
        tl.add(f"#{cid}u", {"scaleX": 0}, {"scaleX": 1, "ease": "power3.inOut"}, 0.9, 0.55)
    return "card stat", body


def _part_card(c: Card, cid: str, tl: _TL) -> tuple[str, str]:
    num, rest = None, []
    for p in c.paras:
        t = "".join(r.text for r in p).strip()
        if num is None and re.fullmatch(r"\d+", t):
            num = t
        else:
            rest.append(p)
    inner, strips = _odometer(num or "", f"{cid}n")
    body = (f'<div class="pnum">{inner}</div>' +
            "".join(f'<div class="ln" id="{cid}l{i}">{_li(p)}</div>' for i, p in enumerate(rest)) +
            f'<div class="uline wide" id="{cid}u"></div>')
    tl.add(f"#{cid}sw", {"xPercent": -101}, {"xPercent": 101, "ease": "power3.inOut"}, 0.0, 0.7)
    tl.add(f"#{cid} .pnum", {"opacity": 0}, {"opacity": 1, "ease": "none"}, 0.3, 0.15)
    for j, (sid, steps) in enumerate(strips):
        tl.add(f"#{sid}", {"yPercent": 0}, {"yPercent": -steps / (steps + 1) * 100, "ease": "expo.out"}, 0.3 + 0.08 * j, 1.0)
    nw = sum(len(r.text.split()) for p in rest for r in p)
    tl.add(f"#{cid} .ln .w", {"opacity": 0, "filter": "blur(10px)"},
           ({"opacity": 1, "filter": "blur(0px)", "ease": "power2.out", "stagger": 0.07, "_n": nw}), 0.55, 0.25)
    tl.add(f"#{cid}u", {"scaleX": 0}, {"scaleX": 1, "ease": "power3.inOut"}, 0.8 + 0.07 * nw, 0.6)
    return "card part", body


def _paper_card(c: Card, cid: str, tl: _TL) -> tuple[str, str]:
    rows = []
    for i, p in enumerate(c.paras):
        big = max(r.size for r in p)
        scale = 1.9 if big < 20 else 1.3  # 논문 정보는 작게 적혀 있어서 영상에서 읽히게 키운다
        cls = "ln title" if i == 0 else ("ln quote" if any(r.italic for r in p) else "ln")
        rows.append(f'<div class="{cls}" id="{cid}l{i}">{_li(p, scale)}</div>')
    body = f'<div class="paper" id="{cid}p"><div class="pbar" id="{cid}pb"></div>{"".join(rows)}</div>'
    n = len(c.paras)
    tl.add(f"#{cid}p", {"x": 140, "opacity": 0, "filter": "blur(8px)"},
           {"x": 0, "opacity": 1, "filter": "blur(0px)", "ease": "expo.out"}, 0.05, 0.7)
    tl.add(f"#{cid}pb", {"scaleY": 0}, {"scaleY": 1, "ease": "power3.inOut"}, 0.3, 0.6)
    tl.add(f"#{cid} .ln:not(.quote) .li", {"opacity": 0, "y": 22, "filter": "blur(6px)"},
           ({"opacity": 1, "y": 0, "filter": "blur(0px)", "ease": "power3.out", "stagger": 0.09, "_n": n}), 0.35, 0.55)
    nq = sum(len(r.text.split()) for p in c.paras if any(r.italic for r in p) for r in p)
    if nq:
        tl.raw(f'gsap.set("#{cid} .quote .li",{{yPercent:0}});'
               f'document.querySelectorAll("#{cid} .quote .w").forEach((el,i)=>{{const c=getComputedStyle(el).color;'
               f'tl.fromTo(el,{{color:"#333",opacity:0.6}},{{color:c,opacity:1,duration:0.12,ease:"none"}},'
               f'{tl.t0 + 0.8:.3f}+i*0.035);}});', end=0.8 + 0.035 * nq + 0.12)
    return "card paper-card", body


_HANGUL = re.compile(r"[\uac00-\ud7a3]")


def _paper_ko_card(c: Card, cid: str, tl: _TL, spec: dict) -> tuple[str, str]:
    """한국어 요약을 크게, 출처(저자·제목·영어 원문·링크)는 아래 작은 상자에 (2026-11-14: 영어 원문이 먼저 눈에 들어와 못 읽고 넘긴다).
    spec: {"ko": ["한국어 요약 줄", ...]} (**강조어** 가능)."""
    texts = ["".join(r.text for r in p).strip() for p in c.paras]
    cite = texts[0] if texts else ""
    title = texts[1] if len(texts) > 1 and not texts[1].startswith("http") else ""
    quotes = [t for i, t in enumerate(texts[2:], 2) if t and not t.startswith("http") and not _HANGUL.search(t)]
    if "drop_quotes" in spec:  # 출처 상자에서 뺄 원문 인용 (번호, 0부터)
        quotes = [q for i, q in enumerate(quotes) if i not in spec["drop_quotes"]]
    link = next((t for t in texts if t.startswith("http")), "")
    ko = "".join(f'<div class="ln kp-l" id="{cid}k{i}"><div class="li">{tpl._hl(t)}</div></div>' for i, t in enumerate(spec["ko"]))
    src = (f'<div class="kp-src" id="{cid}s"><div class="kp-cite">{_esc(cite)}</div>'
           + (f'<div class="kp-title">{_esc(title)}</div>' if title else "")
           + "".join(f'<div class="kp-q">{_esc(q)}</div>' for q in quotes)
           + (f'<div class="kp-link">{_esc(link)}</div>' if link else "") + "</div>")
    if spec.get("note"):  # 한계(증례 1건, 설문이라 인과 불명확 등)는 작게 함께 적는다
        ko += f'<div class="ln kp-l kp-note" id="{cid}n"><div class="li">{_esc(spec["note"])}</div></div>'
    body = (f'<div class="kp" id="{cid}p"><div class="kp-tag" id="{cid}t">논문 근거</div>{ko}{src}</div>')
    tl.add(f"#{cid}t", {"opacity": 0, "x": -30}, {"opacity": 1, "x": 0, "ease": "power3.out"}, 0.1, 0.5)
    tl.add(f"#{cid} .kp-l .li", {"opacity": 0, "y": 22, "filter": "blur(8px)"},
           {"opacity": 1, "y": 0, "filter": "blur(0px)", "ease": "power3.out", "stagger": 0.18, "_n": len(spec["ko"]) + bool(spec.get("note"))}, 0.3, 0.6)
    t_hl = 0.3 + 0.18 * len(spec["ko"]) + 0.5
    tl.add(f"#{cid} .hl .hlm", {"scaleX": 0}, {"scaleX": 1, "ease": "power2.inOut"}, t_hl, 0.6)
    tl.add(f"#{cid}s", {"opacity": 0, "y": 30}, {"opacity": 1, "y": 0, "ease": "power3.out"}, t_hl + 0.3, 0.7)
    return "card paper-card", body


def auto_spec(c: Card) -> dict | None:
    """설정 파일이 없어도 알아볼 수 있는 카드: 파트 표지('PART 1/3'), 경고('오해 금지', '한계', '주의')."""
    texts = ["".join(r.text for r in p).strip() for p in c.paras]
    head = f"{c.header} {texts[0] if texts else ''}"
    m = re.search(r"PART\s*(\d+)\s*/\s*(\d+)", head, re.I)
    if m:
        rest = [t for t in texts if not re.search(r"PART\s*\d", t, re.I)]
        return {"kind": "part", "num": int(m.group(1)), "total": int(m.group(2)),
                "title": rest[0] if rest else "", "sub": " · ".join(rest[1:])}
    if c.header.strip() in ("오해 금지", "한계", "주의", "경고"):
        return {"kind": "warning", "tag": c.header.strip(), "text": texts}
    return None


def card_kinds(pptx: Path, specs: dict | None = None) -> dict[int, str]:
    """슬라이드 번호 → 카드 종류 (템플릿 이름 또는 text/stat/compare/part/paper)."""
    specs = {int(k): v for k, v in (specs or {}).items()}
    out = {}
    for c in read_cards(pptx):
        sp = specs.get(c.no) or auto_spec(c)
        out[c.no] = sp["kind"] if sp and sp.get("kind") in tpl.KINDS else c.kind
    return out


def _bg_html(spec, cid: str) -> str:
    """카드 뒤에 깔 장면 사진 (설정의 "bg": 이미지 경로). 흐리고 어둡게 해서 글자가 잘 읽히게 (2026-11-09)."""
    if not spec or not spec.get("bg"):
        return ""
    import base64
    from PIL import Image, ImageFilter, ImageEnhance
    import io
    im = Image.open(spec["bg"]).convert("RGB")
    im = im.resize((2000, int(im.height * 2000 / im.width)))
    im = ImageEnhance.Brightness(im.filter(ImageFilter.GaussianBlur(spec.get("bg_blur", 3)))).enhance(spec.get("bg_bright", 0.7))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=82)
    return f'<div class="cbg" style="background-image:url(data:image/jpeg;base64,{base64.b64encode(buf.getvalue()).decode()})"></div>'


def build_project(cards: list[Card], folder: Path, specs: dict | None = None) -> list[tuple[int, float, float]]:
    """카드들을 이어 붙인 HyperFrames 프로젝트를 쓴다. [(슬라이드 번호, 시작 초, 길이)]를 돌려준다.
    specs: {슬라이드 번호: 템플릿 설정} (motion_templates 참고). 없는 카드는 글자 카드로 만든다."""
    specs = {int(k): v for k, v in (specs or {}).items()}
    (folder / "assets" / "fonts").mkdir(parents=True, exist_ok=True)
    for f in FONTS_DIR.glob("Pretendard-*.otf"):
        shutil.copy(f, folder / "assets" / "fonts" / f.name)
    js = _gsap()
    if js is None:
        raise RuntimeError("GSAP을 받지 못했습니다")
    shutil.copy(js, folder / "assets" / "gsap.min.js")

    sections, scripts, spans = [], [], []
    t, prev_style, k = 0.0, None, 0
    prev_variant, ic_k = None, 0
    for c in cards:
        cid = f"c{c.no:02d}"
        tl = _TL(t)
        spec = specs.get(c.no) or auto_spec(c)
        if spec and spec.get("kind") == "icontext" and "variant" not in spec:
            # 아이콘+문장 카드가 이어지면 단조롭다: 모양을 돌려 쓰고 바로 앞 카드와 같은 모양은 피한다
            vs = tpl.ICONTEXT_VARIANTS
            if vs[ic_k % len(vs)] == prev_variant:
                ic_k += 1
            spec = dict(spec, variant=vs[ic_k % len(vs)])
            ic_k += 1
        if spec and spec.get("kind") in tpl.KINDS:
            texts = ["".join(r.text for r in p).strip() for p in c.paras]
            cls, body = tpl.build(spec, texts, cid, tl)
            style = spec["kind"]
            if style == "warning":  # 경고 머리표가 머리말을 대신한다
                c = Card(c.no, "", c.paras, c.kind)
        elif c.kind in ("stat", "compare"):
            cls, body = _stat_card(c, cid, c.no, tl, c.kind == "compare")
            style = c.kind
        elif c.kind == "part":
            cls, body = _part_card(c, cid, tl)
            style = "part"
        elif c.kind == "paper" and spec and spec.get("ko"):
            cls, body = _paper_ko_card(c, cid, tl, spec)
            style = "paper"
        elif c.kind == "paper":
            cls, body = _paper_card(c, cid, tl)
            style = "paper"
        else:
            texts = ["".join(r.text for r in p).strip() for p in c.paras]
            all_red = all(any(r.color.upper() == RED for r in p) for p in c.paras)
            if all_red and len(texts) <= 3 and max(len(x) for x in texts) <= 10 and prev_style != "slam":
                style = "slam"
            else:
                choices = [s for s in TEXT_STYLES if s != prev_style]
                style = choices[k % len(choices)]
                k += 1
            cls, body = _text_card(c, cid, style, tl)
        prev_style = style
        prev_variant = spec.get("variant") if spec and spec.get("kind") == "icontext" else None
        dur = round(max(1.0, tl.end) + HOLD, 3)
        dur = max(dur, AMBIENT_MIN)
        dur = round(round(dur * FPS) / FPS, 4)
        # 계속 움직이는 바탕: 빛 두 개가 천천히 흐르고, 화면이 아주 조금씩 다가온다 (끝난 카드가 정지 화면처럼 보이지 않게)
        if spec and spec.get("bg"):
            tl.raw(f'tl.fromTo("#{cid} .cbg",{{x:-40}},{{x:40,duration:{dur},ease:"none"}},{t:.3f});')
        tl.raw(f'tl.fromTo("#{cid} .amb .g1",{{x:-90,y:-30,opacity:.85}},{{x:110,y:40,opacity:1,duration:{dur},ease:"sine.inOut"}},{t:.3f});')
        tl.raw(f'tl.fromTo("#{cid} .amb .g2",{{x:80,y:30}},{{x:-100,y:-30,duration:{dur},ease:"sine.inOut"}},{t:.3f});')
        header = f'<div class="hdr" id="{cid}h">{_esc(c.header)}</div>' if c.header else ""
        if c.kind == "part" or style == "part":  # 초록 패널이 화면 전체를 쓸고 지나간다
            header += f'<div class="sweep" id="{cid}sw"></div>'
        # 머리말(섹션 이름)은 첫 프레임부터 떠 있게 둔다 (카드가 바뀌어도 화면이 비지 않게)
        sections.append(f'<section id="{cid}" class="clip {cls}" data-start="{t:.4f}" data-duration="{dur}" '
                        f'data-track-index="0">{_bg_html(spec, cid)}<div class="amb"><i class="g1"></i><i class="g2"></i></div>{header}<div class="stage"><div class="fit">{body}</div></div></section>')
        scripts.extend(tl.lines)
        spans.append((c.no, t, dur))
        t = round(t + dur, 4)

    page = PAGE.replace("{TPL_CSS}", tpl.CSS).replace("{SECTIONS}", "\n".join(sections)).replace("{SCRIPT}", "\n".join(scripts)) \
        .replace("{DURATION}", f"{t:.4f}")
    (folder / "index.html").write_text(page, encoding="utf-8")
    (folder / "hyperframes.json").write_text(json.dumps({"name": "dermahub-cards"}), encoding="utf-8")
    return spans


PAGE = """<!doctype html>
<html lang="ko"><head><meta charset="UTF-8"><meta name="viewport" content="width=1920, height=1080">
<script src="assets/gsap.min.js"></script>
<style>
@font-face{font-family:"Pretendard";src:url("assets/fonts/Pretendard-ExtraBold.otf");font-weight:800}
@font-face{font-family:"Pretendard";src:url("assets/fonts/Pretendard-Bold.otf");font-weight:600 700}
*{margin:0;padding:0;box-sizing:border-box}
html,body{width:1920px;height:1080px;overflow:hidden;background:#0A0A0A}
#root{position:relative;width:1920px;height:1080px;overflow:hidden;font-family:"Pretendard",sans-serif;font-weight:800;color:#fff}
/* 한글은 띄어쓰기에서만 줄을 바꾸고, 여러 줄이면 길이를 고르게 (2026-11-14: '치/료', '왔다갔/다'처럼 한두 글자만 넘어가 지저분) */
.card,.card *{word-break:keep-all;overflow-wrap:normal;text-wrap:balance}
.card{position:absolute;inset:0;overflow:hidden;
 background:radial-gradient(1100px 760px at 6% 0%,rgba(82,183,136,.11),transparent 62%),
            radial-gradient(900px 700px at 100% 100%,rgba(230,57,70,.07),transparent 60%),#0A0A0A}

.cbg{position:absolute;left:-60px;right:-60px;top:0;bottom:0;background-size:cover;background-position:center;z-index:0}
.cbg::after{content:"";position:absolute;inset:0;background:linear-gradient(90deg,rgba(10,10,10,.62),rgba(10,10,10,.12) 70%)}
.amb{position:absolute;inset:0;pointer-events:none;z-index:0}
.amb i{position:absolute;border-radius:50%;filter:blur(40px)}
.amb .g1{width:1100px;height:800px;left:-260px;top:-300px;background:radial-gradient(closest-side,rgba(82,183,136,.20),transparent)}
.amb .g2{width:1000px;height:760px;right:-280px;bottom:-320px;background:radial-gradient(closest-side,rgba(230,57,70,.13),transparent)}
.card::after{content:"";position:absolute;inset:0;pointer-events:none;z-index:6;
 background:radial-gradient(ellipse at center,transparent 55%,rgba(0,0,0,.55) 100%),
 url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='220' height='220'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='.9' numOctaves='2' stitchTiles='stitch'/><feColorMatrix values='0 0 0 0 1  0 0 0 0 1  0 0 0 0 1  0 0 0 .07 0'/></filter><rect width='100%' height='100%' filter='url(%23n)'/></svg>")}
.stage{z-index:2;transform-origin:center center}
.hdr{z-index:3}
.hdr{position:absolute;left:130px;top:62px;font-size:34px;font-weight:700;color:#52B788;letter-spacing:.02em}
.stage{position:absolute;left:130px;right:130px;top:150px;height:700px;display:flex;align-items:center}
.fit{position:relative;width:100%;transform-origin:left center}
.center .stage{justify-content:center}.center .fit{transform-origin:center center;text-align:center}
.ln{overflow:visible;line-height:1.28;padding-bottom:.06em;word-break:keep-all;position:relative;width:fit-content;max-width:100%}
.center .ln{margin-left:auto;margin-right:auto}
.li{display:block;will-change:transform}
.w{display:inline-block}
.hero{line-height:1.02;margin-bottom:22px}
.dcol{display:inline-block;height:1em;line-height:1em;overflow:hidden;vertical-align:-0.08em}
.dstrip{display:flex;flex-direction:column}.dstrip span{height:1em;line-height:1em}
.dsep{display:inline-block}
.uline{height:8px;width:360px;background:#52B788;border-radius:4px;margin-top:34px;transform-origin:left center}
.uline.wide{width:520px}
.center .uline{margin-left:auto;margin-right:auto;transform-origin:center}
.rule{height:6px;width:120px;background:#52B788;border-radius:3px;margin:0 auto 34px;transform-origin:center}
.marker{position:absolute;left:-8px;right:-8px;top:52%;height:40%;background:rgba(230,57,70,.22);border-radius:6px;transform-origin:left center;z-index:-1}
.bars{margin-top:44px;display:flex;flex-direction:column;gap:22px;width:1150px}
.brow{position:relative;height:40px;background:#1A1A1A;border-radius:20px;overflow:visible}
.bfill{height:100%;border-radius:20px;transform-origin:left center}
.bval{position:absolute;right:-150px;top:-4px;font-size:42px;color:#ddd;font-weight:800}
.sweep{position:absolute;inset:0;background:#52B788;z-index:5}
.pnum{font-size:300px;color:#262626;line-height:1;margin-bottom:10px}
.paper{position:relative;background:#141414;border:1px solid #262626;border-radius:28px;padding:44px 56px 44px 74px;
 box-shadow:0 40px 90px rgba(0,0,0,.55)}
.pbar{position:absolute;left:36px;top:44px;bottom:44px;width:6px;background:#52B788;border-radius:3px;transform-origin:top}
.paper .title{margin-bottom:14px}
.quote{margin:12px 0}
.kp{width:1640px}
.kp-tag{display:inline-block;font-size:34px;font-weight:800;color:#0B0B0B;background:#52B788;border-radius:12px;padding:6px 20px;margin-bottom:26px}
.kp-l{font-size:76px;font-weight:800;line-height:1.28;color:#fff}
.kp-note{font-size:36px;font-weight:600;color:#a8a8a8;margin-top:10px}
.kp-src{margin-top:40px;border-left:5px solid #52B788;padding:6px 0 6px 28px;max-width:1400px}
.kp-cite{font-size:28px;font-weight:700;color:#52B788}
.kp-title{font-size:24px;color:#9a9a9a;margin-top:4px}
.kp-q{font-size:24px;font-style:italic;color:#8a8a8a;margin-top:6px;line-height:1.35}
.kp-link{font-size:20px;color:#6a6a6a;margin-top:8px}
{TPL_CSS}
</style></head>
<body>
<div id="root" data-composition-id="main" data-start="0" data-duration="{DURATION}" data-width="1920" data-height="1080" data-fps="30">
{SECTIONS}
</div>
<script>
// 자막 자리(아래 20%)를 넘지 않게 카드 내용 크기를 맞춘다 (타임라인을 만들기 전에 한 번만 잰다)
document.querySelectorAll('.stage').forEach(st=>{const f=st.querySelector('.fit');
 const s=Math.min(1,st.clientHeight/f.scrollHeight);f.style.transform=`scale(${s})`;});
const tl=gsap.timeline({paused:true});
{SCRIPT}
window.__timelines=window.__timelines||{};
window.__timelines["main"]=tl;
tl.seek(0);
</script>
</body></html>"""


def render(pptx: Path, work: Path, specs: dict | None = None, skip: set | None = None) -> dict[int, tuple[Path, float]] | None:
    """슬라이드 번호 → (카드 mp4, 길이). HyperFrames를 쓸 수 없으면 None. skip: 쓰지 않을 슬라이드 번호 (렌더하지 않는다)"""
    folder = work / "hf_cards"
    folder.mkdir(parents=True, exist_ok=True)
    cards = [c for c in read_cards(pptx) if not skip or c.no not in skip]
    try:
        spans = build_project(cards, folder, specs)
    except RuntimeError as e:
        print(f"  HyperFrames 카드 준비 실패 ({e})")
        return None
    key = hashlib.sha1((folder / "index.html").read_bytes()).hexdigest()[:10]
    allmp4 = folder / f"all_{key}.mp4"
    out_dir = folder / f"cards_{key}"
    if not allmp4.exists():
        if not available(work):
            print("  HyperFrames(npx/크롬)를 쓸 수 없어 기본 모션 카드로 대신합니다.")
            return None
        total = spans[-1][1] + spans[-1][2] if spans else 0
        print(f"  HyperFrames로 모션 그래픽 카드 {len(cards)}장 렌더링 중 ({total:.0f}초 분량)...")
        r = _hf(["render", "--quality", "delivery", "--output", str(allmp4)], folder)
        if r.returncode != 0 or not allmp4.exists():
            print(f"  HyperFrames 렌더 실패, 기본 모션 카드로 대신합니다:\n{(r.stdout + r.stderr)[-1500:]}")
            return None
    out_dir.mkdir(exist_ok=True)
    result = {}
    for no, start, dur in spans:
        mp4 = out_dir / f"card{no:02d}_p{PREROLL}.mp4"
        if not mp4.exists():
            # 프레임 번호로 정확히 자른다. 초로 자르면 다음 카드의 첫 프레임(글자가 아직 안 나온 상태)이 한 장 딸려 와서,
            # 편집기가 마지막 프레임을 늘릴 때 그 빈 화면이 슬라이드 내내 보인다
            # 첫 몇 프레임은 글자가 아직 투명해서 빈 화면처럼 보인다: 애니메이션이 조금 진행된 시점부터 쓴다
            f0, f1 = round(start * FPS) + PREROLL, round((start + dur) * FPS) - 1
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(allmp4),
                            "-vf", f"trim=start_frame={f0}:end_frame={f1},setpts=PTS-STARTPTS",
                            "-c:v", "libx264", "-preset", "veryfast", "-crf", "14", "-pix_fmt", "yuv420p", "-an",
                            str(mp4)], check=True)
        result[no] = (mp4, dur)
    return result
