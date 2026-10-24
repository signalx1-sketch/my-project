"""발표 슬라이드를 움직이는 모션 그래픽 카드로 다시 만든다.

pptx에서 글자와 색, 크기를 읽어 HTML 카드로 짜고, 헤드리스 크롬(Playwright)으로 프레임마다 찍어 mp4로 만든다.
카드 종류는 슬라이드 내용으로 고른다.
- 숫자 카드: 큰 숫자가 0부터 올라간다 (5,885명, 962명 · 16주). "83% vs 73.7%"는 막대 비교까지 그린다
- 파트 표지: 큰 번호가 커지며 들어오고 밑줄이 그어진다
- 논문 카드: 왼쪽 세로선이 그어지고 제목, 저자, 원문 인용이 차례로 나타난다
- 문장 카드: 줄마다 아래에서 올라오며 나타난다
애니메이션은 앞 1~2초에만 있고, 나머지는 마지막 장면을 그대로 이어 붙인다 (렌더 시간 절약).
노드나 Playwright가 없으면 None을 돌려주고, 편집기는 정지 이미지 슬라이드를 쓴다.
"""
import hashlib
import html
import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

FONTS_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"
RENDERER = Path(__file__).resolve().parent / "motion_render.mjs"
NODE_PATHS = ["/opt/node-tools/node_modules"]  # 클라우드 컨테이너의 Playwright 위치 (없으면 전역 설치본)
FPS = 30
STAGGER = 0.12   # 줄과 줄 사이 등장 간격
ENTER = 0.45     # 한 줄이 나타나는 데 걸리는 시간

GREEN, RED, WHITE, GRAY = "#52B788", "#E63946", "#FFFFFF", "#8A8A8A"


@dataclass
class Run:
    text: str
    size: float     # pt
    color: str
    italic: bool = False


@dataclass
class Card:
    no: int
    header: str = ""
    paras: list[list[Run]] = field(default_factory=list)
    kind: str = "text"   # text | stat | compare | part | paper


def _color(run, default=WHITE) -> str:
    try:
        rgb = run.font.color.rgb
        return f"#{rgb}" if rgb is not None else default
    except (AttributeError, TypeError):
        return default


def read_cards(pptx: Path) -> list[Card]:
    from pptx import Presentation

    prs = Presentation(str(pptx))
    H = prs.slide_height
    cards = []
    for no, slide in enumerate(prs.slides, 1):
        shapes = sorted((sh for sh in slide.shapes if sh.has_text_frame and sh.text_frame.text.strip()
                         and sh.top is not None and sh.top < H * 0.92), key=lambda sh: sh.top)
        card = Card(no)
        for k, sh in enumerate(shapes):
            paras = []
            for p in sh.text_frame.paragraphs:
                runs = [Run(r.text, r.font.size.pt if r.font.size else 18, _color(r), bool(r.font.italic))
                        for r in p.runs if r.text]
                if runs:
                    paras.append(runs)
            if k == 0 and len(shapes) > 1 and max(r.size for p in paras for r in p) <= 24 and sh.top < H * 0.15:
                card.header = " ".join(r.text for p in paras for r in p)
                continue
            card.paras.extend(paras)
        text = " ".join(r.text for p in card.paras for r in p)
        big = max((r.size for p in card.paras for r in p), default=0)
        if card.header.upper().startswith("PART"):
            card.kind = "part"
        elif any(r.italic for p in card.paras for r in p) or "doi.org" in text:
            card.kind = "paper"
        elif re.search(r"\d+(\.\d+)?\s*%\s*vs\s*\d+(\.\d+)?\s*%", text):
            card.kind = "compare"
        elif big >= 80 and re.search(r"\d", text):
            card.kind = "stat"
        cards.append(card)
    return cards


_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _count_spans(text: str) -> str:
    """글자 속 숫자를 카운트업 span으로 감싼다."""
    out, last = [], 0
    for m in _NUM.finditer(text):
        out.append(html.escape(text[last:m.start()]))
        raw = m.group()
        dec = len(raw.split(".")[1]) if "." in raw else 0
        val = float(raw.replace(",", ""))
        out.append(f'<span class="num" data-k="count" data-v="{val}" data-dec="{dec}" '
                   f'data-comma="{int("," in raw)}">{html.escape(raw)}</span>')
        last = m.end()
    out.append(html.escape(text[last:]))
    return "".join(out)


def _para_html(runs: list[Run], count: bool, scale: float) -> str:
    parts = []
    for r in runs:
        inner = _count_spans(r.text) if count else html.escape(r.text)
        style = f"font-size:{r.size * 2 * scale:.0f}px;color:{r.color};"
        if r.italic:
            style += "font-style:italic;font-weight:600;"
        elif r.size < 30:
            style += "font-weight:700;"
        parts.append(f'<span style="{style}">{inner}</span>')
    return "".join(parts)


def card_html(c: Card) -> tuple[str, float]:
    """카드 HTML과 애니메이션 길이(초)."""
    t, body, extra = 0.25, [], ""
    is_count = c.kind in ("stat", "compare")
    for i, p in enumerate(c.paras):
        big = max(r.size for r in p)
        kind = "up"
        if c.kind == "part" and i == 0 and big >= 100:
            kind = "scale"
        # 논문 카드의 작은 글씨(출처, 원문 인용)는 영상에서 안 읽혀서 키운다
        line = _para_html(p, is_count and big >= 60, 1.6 if c.kind == "paper" and big < 20 else 1.0)
        cls = "line hero" if big >= 60 else "line"
        if c.kind == "paper" and i > 0:
            cls += " cite"
        body.append(f'<div class="{cls}" data-k="{kind}" data-s="{t:.2f}" data-d="{ENTER}">{line}</div>')
        t += STAGGER if big < 60 else STAGGER * 2
    end = t + ENTER
    if c.kind in ("stat", "compare"):
        end = max(end, 1.4)
    if c.kind == "compare":
        vals = [float(v) for v in re.findall(r"(\d+(?:\.\d+)?)\s*%", " ".join(r.text for p in c.paras for r in p))][:2]
        bars = "".join(
            f'<div class="barrow"><div class="bar" data-k="barx" data-w="{v}" data-s="{1.0 + k * 0.15:.2f}" '
            f'data-d="0.7" style="background:{GREEN if k == 0 else GRAY}"></div></div>' for k, v in enumerate(vals))
        extra = f'<div class="bars">{bars}</div>'
        end = max(end, 1.0 + 0.15 * len(vals) + 0.8)
    rule = ""
    if c.kind == "part":
        rule = f'<div class="rule" data-k="barx" data-w="22" data-s="{t:.2f}" data-d="0.6"></div>'
        end = max(end, t + 0.7)
    accent = ""
    if c.kind == "paper":
        accent = '<div class="accent" data-k="bary" data-s="0.2" data-d="0.6"></div>'
    header = (f'<div class="header" data-k="left" data-s="0" data-d="0.4">{html.escape(c.header)}</div>'
              if c.header else "")
    page = TEMPLATE.replace("{FONTS}", FONTS_DIR.as_uri()).replace("{HEADER}", header) \
        .replace("{BODY}", accent + '<div class="stack">' + "".join(body) + "</div>" + rule + extra) \
        .replace("{KIND}", c.kind)
    return page, min(end + 0.15, 3.0)


TEMPLATE = """<!doctype html><html><head><meta charset="utf-8"><style>
@font-face{font-family:P;src:url({FONTS}/Pretendard-ExtraBold.otf);font-weight:800}
@font-face{font-family:P;src:url({FONTS}/Pretendard-Bold.otf);font-weight:600 700}
html,body{margin:0;width:1920px;height:1080px;overflow:hidden;background:#0A0A0A}
body{font-family:P,sans-serif;font-weight:800;color:#fff;
 background:radial-gradient(1200px 800px at 8% 0%,rgba(82,183,136,.10),transparent 60%),
            radial-gradient(900px 700px at 100% 100%,rgba(230,57,70,.06),transparent 60%),#0A0A0A}
.header{position:absolute;left:130px;top:62px;font-size:34px;color:#52B788;font-weight:700;letter-spacing:.02em}
.body{position:absolute;left:130px;right:130px;top:150px;height:700px;display:flex;align-items:center}
.wrap{position:relative;width:100%;transform-origin:left center}
.stack{display:flex;flex-direction:column;gap:14px}
.line{line-height:1.25;white-space:pre-wrap;word-break:keep-all}
.hero{line-height:1.05;margin-bottom:18px}
.num{font-variant-numeric:tabular-nums}
.part .line:first-child span{color:#2A2A2A!important}
.cite{padding-left:40px}
.accent{position:absolute;left:0;top:90px;bottom:0;width:6px;background:#52B788;border-radius:3px;transform-origin:top}
.rule{height:8px;background:#52B788;border-radius:4px;margin-top:34px;width:0}
.bars{margin-top:40px;display:flex;flex-direction:column;gap:22px;width:1100px}
.barrow{height:34px;background:#1C1C1C;border-radius:17px;overflow:hidden}
.bar{height:100%;width:0;border-radius:17px}
</style></head><body class="{KIND}">{HEADER}<div class="body"><div class="wrap">{BODY}</div></div>
<script>
// 내용이 자막 자리(아래 20%)를 넘지 않게 전체 크기를 줄인다
const wrap=document.querySelector('.wrap'),box=document.querySelector('.body');
const fit=()=>{const s=Math.min(1,box.clientHeight/wrap.scrollHeight,box.clientWidth/wrap.scrollWidth);wrap.style.transform=`scale(${s})`};
const ease=x=>1-Math.pow(1-x,3);
const prog=(t,s,d)=>Math.min(1,Math.max(0,(t-s)/d));
const fmt=(v,dec,comma)=>{let s=v.toFixed(dec);if(comma){const [a,b]=s.split('.');s=a.replace(/\\B(?=(\\d{3})+(?!\\d))/g,',')+(b?'.'+b:'')}return s};
window.seek=t=>{
 fit();
 for(const el of document.querySelectorAll('[data-k]')){
  const k=el.dataset.k;
  if(k==='count'){const host=el.closest('[data-s]');const s=+(host?host.dataset.s:0)+0.05;
    const p=1-Math.pow(1-prog(t,s,0.9),4);el.textContent=fmt(+el.dataset.v*p,+el.dataset.dec,el.dataset.comma==='1');continue}
  const p=ease(prog(t,+el.dataset.s,+el.dataset.d||0.45));
  if(k==='up'){el.style.opacity=p;el.style.transform=`translateY(${(1-p)*36}px)`}
  else if(k==='left'){el.style.opacity=p;el.style.transform=`translateX(${-(1-p)*30}px)`}
  else if(k==='scale'){el.style.opacity=p;el.style.transform=`scale(${1.18-0.18*p})`;el.style.transformOrigin='left bottom'}
  else if(k==='barx'){el.style.width=(+el.dataset.w*p)+'%'}
  else if(k==='bary'){el.style.transform=`scaleY(${p})`}
 }
};
window.seek(0);
</script></body></html>"""


def available() -> bool:
    if not (shutil.which("node") and RENDERER.exists()):
        return False
    r = subprocess.run(["node", "-e", "require('playwright')"], capture_output=True, env=_env())
    return r.returncode == 0


def _env() -> dict:
    import os

    env = dict(os.environ)
    root = subprocess.run(["npm", "root", "-g"], capture_output=True, text=True).stdout.strip() if shutil.which("npm") else ""
    env["NODE_PATH"] = ":".join(p for p in [env.get("NODE_PATH", ""), root, *NODE_PATHS] if p)
    if Path("/opt/pw-browsers/chromium").exists() and "CHROMIUM_PATH" not in env:
        env["CHROMIUM_PATH"] = "/opt/pw-browsers/chromium"
    return env


def render(pptx: Path, work: Path) -> dict[int, tuple[Path, float]] | None:
    """슬라이드 번호 → (카드 mp4, 애니메이션 길이). 쓸 수 없으면 None."""
    if not available():
        print("  모션 그래픽: Node/Playwright가 없어 정지 슬라이드로 대신합니다.")
        return None
    folder = work / "motion"
    folder.mkdir(parents=True, exist_ok=True)
    jobs, out = [], {}
    for c in read_cards(pptx):
        page, secs = card_html(c)
        key = hashlib.sha1(page.encode()).hexdigest()[:10]
        h, mp4 = folder / f"card{c.no:02d}_{key}.html", folder / f"card{c.no:02d}_{key}.mp4"
        h.write_text(page, encoding="utf-8")
        out[c.no] = (mp4, secs)
        if not mp4.exists():
            jobs.append({"html": str(h), "out": str(mp4), "seconds": secs, "fps": FPS})
    if jobs:
        print(f"  모션 그래픽 카드 {len(jobs)}장 렌더링 중...")
        jf = folder / "jobs.json"
        jf.write_text(json.dumps(jobs, ensure_ascii=False), encoding="utf-8")
        r = subprocess.run(["node", str(RENDERER), str(jf)], env=_env(), capture_output=True, text=True)
        if r.returncode != 0:
            print(f"  모션 그래픽 실패, 정지 슬라이드로 대신합니다: {r.stderr[-500:]}")
            return None
    return out
