"""모션 카드 템플릿: 글자만 있는 카드 말고, 내용 모양에 맞춘 그림 카드.

카드마다 쓸 템플릿과 내용은 슬라이드 옆의 카드 설정 JSON(--cards)에 적는다. {"17": {"kind": "icons", ...}}
설정이 없어도 머리말이 '오해 금지/한계/주의'면 경고 카드, 'PART n/m'으로 시작하면 파트 표지로 자동으로 바꾼다.

- icons: 아이콘 원이 차례로 튀어나오고 그 사이를 선이 잇는다 (샴푸 → 세안제 → 화장품 → 먹는 약 → 시술)
- phone: 휴대폰 메모장이 올라오고 줄마다 글자가 타이핑된다
- checklist: 빈 체크 상자에 체크 표시가 차례로 그려진다
- compare2: 두 칸이 좌우에서 들어오고 막대 길이로 차이를 보여준다 (2주 ≠ 2년)
- dots: 같은 횟수가 한 달에 몰렸는지 1년에 퍼졌는지 점으로 보여준다
- fork: 시간 축 가운데 '사용 시작' 핀을 꽂고 앞/뒤 구간을 칠한다 (쓰기 전부터? 쓰고 나서부터?)
- timeline: 선이 그어지며 시점 노드가 하나씩 나타난다
- bubble: 말풍선이 뜨고 ✕/✓ 도장이 찍힌다
- warning: 경고 표시 머리표와 빨간 세로선, 줄마다 올라오는 글자
- graph: 약을 끊은 뒤 증상 곡선 두 개(원래대로 / 더 심해짐)가 그려진다
- part: 초록 패널이 쓸고 지나간 뒤 파트 번호, 제목, 3단계 진행 막대
"""
import html
import re
from pathlib import Path

ICONS = Path(__file__).resolve().parent.parent / "assets" / "vendor" / "icons"
GREEN, RED, GREY = "#52B788", "#E63946", "#8A8A8A"
KINDS = {"icons", "phone", "checklist", "compare2", "dots", "fork", "timeline", "bubble", "warning", "graph", "part",
         "icontext", "diverge", "tags", "prompt", "timer", "segments", "merge", "iconlist"}


def _e(s) -> str:
    return html.escape(str(s))


def svg(name: str, cls: str = "ic") -> str:
    """Lucide 아이콘 SVG. 선마다 pathLength=1을 넣어 '그려지는' 애니메이션을 걸 수 있게 한다."""
    p = ICONS / f"{name}.svg"
    if not p.exists():
        p = ICONS / "sparkles.svg"
    s = re.sub(r"<!--.*?-->", "", p.read_text(encoding="utf-8"), flags=re.S).strip()
    s = re.sub(r'\s(width|height|class)="[^"]*"', "", s)
    s = s.replace("<svg", f'<svg class="{cls}"', 1)
    return re.sub(r"<(path|line|circle|polyline|rect|polygon|ellipse)\b", r'<\1 pathLength="1"', s)


def _lines(texts, cls: str, cid: str, tag: str) -> str:
    return "".join(f'<div class="ln {cls}" id="{cid}{tag}{i}"><div class="li">{_e(t)}</div></div>'
                   for i, t in enumerate(texts))


def _draw(tl, sel: str, at: float, dur: float = 0.5, stagger: float = 0.0, n: int = 1):
    to = {"strokeDashoffset": 0, "ease": "power2.inOut"}
    if stagger:
        to.update(stagger=stagger, _n=n)
    tl.add(sel, {"strokeDashoffset": 1}, to, at, dur)


def _rise(tl, sel: str, at: float, n: int = 1, stagger: float = 0.12, dur: float = 0.6):
    tl.add(sel, {"yPercent": 70}, {"yPercent": 0, "ease": "expo.out", "stagger": stagger, "_n": n}, at, dur)


def build(spec: dict, paras: list[str], cid: str, tl) -> tuple[str, str]:
    """(카드 class, 본문 HTML). tl은 motion_hf._TL."""
    k = spec["kind"]
    return globals()[f"_{k}"](spec, paras, cid, tl)


def _title(spec, cid, tl, at=0.0, cls="ttl") -> str:
    t = spec.get("title")
    if not t:
        return ""
    t = [t] if isinstance(t, str) else t
    _rise(tl, f"#{cid} .{cls} .li", at, len(t))
    return _lines(t, cls, cid, "t")


def _icons(spec, paras, cid, tl):
    items = spec["items"]
    tiles = "".join(f'<div class="itile" id="{cid}i{j}"><div class="icirc">{svg(ic)}</div>'
                    f'<div class="ilab">{_e(lab)}</div></div>' for j, (lab, ic) in enumerate(items))
    body = _title(spec, cid, tl) + f'<div class="irow"><div class="iline" id="{cid}il"></div>{tiles}</div>'
    n = len(items)
    tl.add(f"#{cid} .itile", {"scale": 0.55, "opacity": 0.25},
           {"scale": 1, "opacity": 1, "ease": "back.out(1.8)", "stagger": 0.16, "_n": n}, 0.1, 0.5)
    _draw(tl, f"#{cid} .icirc .ic *", 0.25, 0.55, 0.03, n * 3)
    tl.add(f"#{cid}il", {"scaleX": 0}, {"scaleX": 1, "ease": "power3.inOut"}, 0.25 + 0.16 * n, 0.7)
    if spec.get("caption"):
        body += _lines([spec["caption"]], "icap", cid, "c")
        _rise(tl, f"#{cid} .icap .li", 0.5 + 0.16 * n)
    return "card tpl", body


def _phone(spec, paras, cid, tl):
    left = spec.get("title") or paras
    rows = []
    for j, ln in enumerate(spec["lines"]):
        txt, tone = (ln, "") if isinstance(ln, str) else (ln[0], ln[1])
        rows.append(f'<div class="mrow {tone}"><span class="mdot"></span><span class="mt" id="{cid}m{j}">{_e(txt)}</span></div>')
    phone = (f'<div class="phone" id="{cid}ph"><div class="notch"></div><div class="scr">'
             f'<div class="mhead"><span>‹ 메모</span><span>완료</span></div>'
             f'<div class="mtitle">{_e(spec.get("memo_title", "진료 전 메모"))}</div>{"".join(rows)}</div></div>')
    body = f'<div class="split"><div class="lcol">{_lines(left, "big", cid, "t")}</div>{phone}</div>'
    _rise(tl, f"#{cid} .lcol .li", 0.05, len(left))
    tl.add(f"#{cid}ph", {"y": 140, "rotation": -6, "opacity": 0.35},
           {"y": 0, "rotation": -2, "opacity": 1, "ease": "expo.out"}, 0.05, 0.75)
    t = 0.6
    for j, ln in enumerate(spec["lines"]):
        n = len(ln if isinstance(ln, str) else ln[0])
        d = min(0.9, 0.045 * n + 0.1)
        tl.add(f"#{cid}m{j}", {"clipPath": "inset(0% 100% 0% 0%)"},
               {"clipPath": "inset(0% 0% 0% 0%)", "ease": f"steps({max(1, n)})"}, t, d)
        tl.add(f"#{cid} .mrow:nth-of-type({j + 1}) .mdot", {"scale": 0}, {"scale": 1, "ease": "back.out(3)"}, t, 0.25)
        t += d + 0.12
    return "card tpl", body


def _checklist(spec, paras, cid, tl):
    rows = "".join(f'<div class="crow" id="{cid}r{j}"><div class="cbox">{svg("check", "ck")}</div>'
                   f'<div class="ln"><div class="li">{_e(it)}</div></div></div>' for j, it in enumerate(spec["items"]))
    body = _title(spec, cid, tl) + f'<div class="clist">{rows}</div>'
    t = 0.15
    acc = spec.get("accent")
    for j in range(len(spec["items"])):
        tl.add(f"#{cid}r{j} .li", {"yPercent": 80}, {"yPercent": 0, "ease": "expo.out"}, t, 0.55)
        tl.add(f"#{cid}r{j} .cbox", {"borderColor": "#444"}, {"borderColor": GREEN, "ease": "none"}, t + 0.25, 0.15)
        _draw(tl, f"#{cid}r{j} .ck *", t + 0.25, 0.3)
        t += 0.38
    if acc is not None:  # 강조할 줄: 빨갛게 바뀌며 커지고 옆에 꼬리표가 붙는다
        body = body.replace(f'id="{cid}r{acc}">', f'id="{cid}r{acc}"><div class="ctag" id="{cid}tag">{_e(spec.get("accent_label", "제일 중요"))}</div>', 1)
        tl.add(f"#{cid}r{acc}", {"scale": 1, "color": "#ffffff"}, {"scale": 1.12, "color": RED, "ease": "back.out(2)", "transformOrigin": "left center"}, t + 0.1, 0.45)
        tl.add(f"#{cid}r{acc} .cbox", {"borderColor": GREEN}, {"borderColor": RED, "ease": "none"}, t + 0.1, 0.2)
        tl.add(f"#{cid}tag", {"scale": 0, "opacity": 0}, {"scale": 1, "opacity": 1, "ease": "back.out(3)"}, t + 0.3, 0.35)
        t += 0.6
    if spec.get("caption"):
        body += _lines([spec["caption"]], "icap", cid, "c")
        _rise(tl, f"#{cid} .icap .li", t + 0.1)
    return "card tpl", body


def _compare2(spec, paras, cid, tl):
    def panel(side, d):
        return (f'<div class="cpanel {side}" id="{cid}{side}"><div class="cbig{" long" if len(d["title"]) > 3 else ""}" style="color:{d.get("color", "#fff")}">'
                f'{_e(d["title"])}</div><div class="csub">{_e(d.get("sub", ""))}</div>'
                f'<div class="ctrack"><div class="cfill" id="{cid}{side}f" style="width:{100 * d.get("bar", 0.5):.1f}%;'
                f'background:{d.get("color", GREEN)}"></div></div></div>')
    L, R = spec["left"], spec["right"]
    body = (_title(spec, cid, tl) + f'<div class="cmp">{panel("L", L)}<div class="cmid" id="{cid}x">{_e(spec.get("mid", "≠"))}</div>'
            f'{panel("R", R)}</div>')
    tl.add(f"#{cid}L", {"x": -80, "opacity": 0.3}, {"x": 0, "opacity": 1, "ease": "expo.out"}, 0.05, 0.6)
    tl.add(f"#{cid}R", {"x": 80, "opacity": 0.3}, {"x": 0, "opacity": 1, "ease": "expo.out"}, 0.15, 0.6)
    tl.add(f"#{cid}x", {"scale": 2.2, "opacity": 0}, {"scale": 1, "opacity": 1, "ease": "back.out(2)"}, 0.45, 0.45)
    tl.add(f"#{cid}Lf", {"scaleX": 0}, {"scaleX": 1, "ease": "power2.out"}, 0.6, 0.4)
    tl.add(f"#{cid}Rf", {"scaleX": 0}, {"scaleX": 1, "ease": "power2.inOut"}, 0.75, 1.1)
    if spec.get("caption"):
        body += _lines([spec["caption"]], "icap", cid, "c")
        _rise(tl, f"#{cid} .icap .li", 1.3)
    return "card tpl", body


def _dots(spec, paras, cid, tl):
    rows, t = [], 0.5
    for j, r in enumerate(spec["rows"]):
        n, span = r.get("n", 5), r["span"]
        pos = [span * (k + 0.5) / n for k in range(n)]
        dots = "".join(f'<span class="dot" style="left:{100 * p:.2f}%;background:{r.get("color", GREEN)}"></span>' for p in pos)
        rows.append(f'<div class="drow" id="{cid}d{j}"><div class="dlab">{_e(r["label"])}</div>'
                    f'<div class="dtrack"><div class="dline"></div>{dots}<span class="dend">{_e(spec.get("axis", "1년"))}</span></div></div>')
    body = _title(spec, cid, tl) + f'<div class="dots">{"".join(rows)}</div>'
    tl.add(f"#{cid} .dline", {"scaleX": 0}, {"scaleX": 1, "ease": "power3.inOut", "stagger": 0.15, "_n": 2}, 0.2, 0.6)
    tl.add(f"#{cid} .dlab", {"x": -40, "opacity": 0.3}, {"x": 0, "opacity": 1, "ease": "expo.out", "stagger": 0.15, "_n": 2}, 0.1, 0.5)
    for j, r in enumerate(spec["rows"]):
        st = 0.08 if r["span"] < 0.3 else 0.22
        tl.add(f"#{cid}d{j} .dot", {"scale": 0}, {"scale": 1, "ease": "back.out(3)", "stagger": st, "_n": r.get("n", 5)}, t, 0.3)
        t += st * r.get("n", 5) + 0.25
    return "card tpl", body


def _fork(spec, paras, cid, tl):
    body = (_title(spec, cid, tl) +
            f'<div class="fork"><div class="fzone fl" id="{cid}zl"><span>{_e(spec["left"])}</span></div>'
            f'<div class="fzone fr" id="{cid}zr"><span>{_e(spec["right"])}</span></div>'
            f'<div class="faxis" id="{cid}ax"></div><div class="fpin" id="{cid}pin"><div class="fpl">{svg(spec.get("icon", "pill"))}'
            f'<b>{_e(spec.get("pin", "사용 시작"))}</b></div><div class="fstem"></div></div></div>')
    tl.add(f"#{cid}ax", {"scaleX": 0}, {"scaleX": 1, "ease": "power3.inOut"}, 0.1, 0.6)
    tl.add(f"#{cid}pin", {"y": -90, "opacity": 0}, {"y": 0, "opacity": 1, "ease": "bounce.out"}, 0.45, 0.6)
    tl.add(f"#{cid}zl", {"scaleX": 0, "opacity": 0.4}, {"scaleX": 1, "opacity": 1, "ease": "expo.out"}, 0.9, 0.6)
    tl.add(f"#{cid}zr", {"scaleX": 0, "opacity": 0.4}, {"scaleX": 1, "opacity": 1, "ease": "expo.out"}, 1.25, 0.6)
    return "card tpl", body


def _timeline(spec, paras, cid, tl):
    nodes = spec["nodes"]
    acc = spec.get("accent", len(nodes) - 1)
    n = len(nodes)
    items = []
    for j, nd in enumerate(nodes):
        lab, sub = (nd, "") if isinstance(nd, str) else (nd[0], nd[1] if len(nd) > 1 else "")
        x = 100 * (j + 0.5) / n
        items.append(f'<div class="tnode{" acc" if j == acc else ""}" id="{cid}n{j}" style="left:{x:.2f}%">'
                     f'<div class="tlab">{_e(lab)}</div><div class="tdot"></div><div class="tsub">{_e(sub)}</div></div>')
    body = _title(spec, cid, tl) + f'<div class="tline"><div class="tbar" id="{cid}b"></div>{"".join(items)}</div>'
    total = 0.4 + 0.45 * n
    tl.add(f"#{cid}b", {"scaleX": 0}, {"scaleX": 1, "ease": "none"}, 0.1, total)
    for j in range(n):
        at = 0.1 + total * (j + 0.5) / n - 0.1
        tl.add(f"#{cid}n{j} .tdot", {"scale": 0}, {"scale": 1, "ease": "back.out(3)"}, at, 0.3)
        tl.add(f"#{cid}n{j} .tlab, #{cid}n{j} .tsub", {"y": 24, "opacity": 0}, {"y": 0, "opacity": 1, "ease": "expo.out"}, at + 0.05, 0.45)
    return "card tpl", body


def _bubble(spec, paras, cid, tl):
    good = spec.get("tone", "bad") == "good"
    col = GREEN if good else RED
    text = spec["text"] if isinstance(spec["text"], list) else [spec["text"]]
    words = "".join(f'<div class="bl">{"".join(f"<span class=w>{_e(w)}</span> " for w in t.split())}</div>' for t in text)
    stamp = svg("check" if good else "x", "st")
    body = (f'<div class="bwrap"><div class="bub" id="{cid}bb">{words}<div class="btail"></div></div>'
            f'<div class="stamp" id="{cid}st" style="border-color:{col};color:{col}">{stamp}</div></div>'
            + _lines([spec["note"]], "bnote", cid, "c").replace('class="ln', f'style="color:{col}" class="ln'))
    nw = sum(len(t.split()) for t in text)
    tl.add(f"#{cid}bb", {"scale": 0.7, "opacity": 0.3, "transformOrigin": "10% 100%"},
           {"scale": 1, "opacity": 1, "ease": "back.out(1.6)"}, 0.05, 0.5)
    tl.add(f"#{cid} .bub .w", {"opacity": 0.15}, {"opacity": 1, "ease": "none", "stagger": 0.09, "_n": nw}, 0.3, 0.12)
    at = 0.35 + 0.09 * nw + 0.15
    tl.add(f"#{cid}st", {"scale": 2.4, "opacity": 0, "rotation": -25}, {"scale": 1, "opacity": 1, "rotation": -8, "ease": "expo.out"}, at, 0.4)
    _draw(tl, f"#{cid}st .st *", at + 0.1, 0.35)
    _rise(tl, f"#{cid} .bnote .li", at + 0.3)
    return "card tpl", body


def _warning(spec, paras, cid, tl):
    tag = spec.get("tag", "주의")
    body = (f'<div class="wtag" id="{cid}wt">{svg("triangle-alert", "wi")}<span>{_e(tag)}</span></div>'
            f'<div class="wbody"><div class="wbar" id="{cid}wb"></div>{_lines(spec.get("text") or paras, "big", cid, "t")}</div>')
    tl.add(f"#{cid}wt", {"x": -30, "opacity": 0.35}, {"x": 0, "opacity": 1, "ease": "expo.out"}, 0.0, 0.45)
    _draw(tl, f"#{cid}wt .wi *", 0.1, 0.4)
    tl.add(f"#{cid}wb", {"scaleY": 0}, {"scaleY": 1, "ease": "power3.inOut"}, 0.15, 0.55)
    n = len(spec.get("text") or paras)
    _rise(tl, f"#{cid} .wbody .li", 0.3, n, 0.13)
    return "card tpl hasred", body


def _graph(spec, paras, cid, tl):
    # 1400x520 좌표. 끊은 시점 x=520, 원래 상태 y=230, 약 쓰는 동안 y=380
    a, b = spec["lines"]
    pre = "M60 230 C 160 230, 200 380, 300 380 L 520 380"
    ret = "M520 380 C 640 380, 700 230, 860 230 L 1300 230"
    reb = "M520 380 C 640 380, 680 70, 860 70 C 1000 70, 1100 110, 1300 110"
    body = (_title(spec, cid, tl) +
            f'<svg class="graph" viewBox="0 0 1400 520" id="{cid}g">'
            f'<line x1="60" y1="470" x2="1340" y2="470" class="gax" pathLength="1"/>'
            f'<line x1="60" y1="230" x2="1340" y2="230" class="gbase" pathLength="1"/>'
            f'<line x1="520" y1="20" x2="520" y2="470" class="gstop" pathLength="1"/>'
            f'<path d="{pre}" class="gl gpre" pathLength="1"/>'
            f'<path d="{ret}" class="gl" stroke="{GREY}" pathLength="1"/>'
            f'<path d="{reb}" class="gl" stroke="{RED}" pathLength="1"/>'
            f'<text x="70" y="215" class="gtx gsm">{_e(spec.get("base", "원래 상태"))}</text>'
            f'<text x="535" y="50" class="gtx gsm" id="{cid}gs">{_e(spec.get("stop", "끊음"))}</text>'
            f'<text x="1300" y="300" class="gtx" text-anchor="end" fill="#bbb" id="{cid}ga">{_e(a)}</text>'
            f'<text x="1300" y="185" class="gtx" text-anchor="end" fill="{RED}" id="{cid}gb">{_e(b)}</text></svg>')
    tl.add(f"#{cid} .gax, #{cid} .gbase", {"strokeDashoffset": 1}, {"strokeDashoffset": 0, "ease": "power2.out"}, 0.05, 0.5)
    _draw(tl, f"#{cid} .gpre", 0.3, 0.6)
    tl.add(f"#{cid} .gstop, #{cid}gs", {"opacity": 0}, {"opacity": 1, "ease": "none"}, 0.8, 0.25)
    _draw(tl, f"#{cid} .gl:nth-of-type(2)", 1.0, 0.7)
    tl.add(f"#{cid}ga", {"opacity": 0, "x": 20}, {"opacity": 1, "x": 0, "ease": "expo.out"}, 1.55, 0.4)
    _draw(tl, f"#{cid} .gl:nth-of-type(3)", 1.75, 0.8)
    tl.add(f"#{cid}gb", {"opacity": 0, "x": 20}, {"opacity": 1, "x": 0, "ease": "expo.out"}, 2.4, 0.4)
    return "card tpl", body


def _part(spec, paras, cid, tl):
    num, total = int(spec["num"]), int(spec.get("total", 3))
    steps = "".join(f'<div class="pstep{" on" if j + 1 == num else (" done" if j + 1 < num else "")}" id="{cid}s{j}"></div>'
                    for j in range(total))
    body = (f'<div class="pbig">{num:02d}</div><div class="pmeta" id="{cid}pm">PART {num}/{total}</div>'
            f'{_lines([spec["title"]], "ptitle", cid, "t")}'
            + (_lines([spec["sub"]], "psub", cid, "u") if spec.get("sub") else "") +
            f'<div class="psteps">{steps}</div>')
    tl.add(f"#{cid}sw", {"xPercent": -101}, {"xPercent": 101, "ease": "power3.inOut"}, 0.0, 0.7)
    tl.add(f"#{cid} .pbig", {"opacity": 0, "x": -60}, {"opacity": 1, "x": 0, "ease": "expo.out"}, 0.3, 0.7)
    tl.add(f"#{cid}pm", {"opacity": 0, "y": 20}, {"opacity": 1, "y": 0, "ease": "expo.out"}, 0.35, 0.4)
    _rise(tl, f"#{cid} .ptitle .li", 0.45)
    _rise(tl, f"#{cid} .psub .li", 0.6)
    tl.add(f"#{cid} .pstep", {"scaleX": 0}, {"scaleX": 1, "ease": "power3.out", "stagger": 0.1, "_n": total}, 0.7, 0.5)
    return "card tpl part", body


ICONTEXT_VARIANTS = ["badge", "top", "mark"]


def _icontext(spec, paras, cid, tl):
    """아이콘(또는 큰 숫자) + 문장. 연달아 나와도 단조롭지 않게 모양이 세 가지다 (motion_hf가 돌려 쓴다).
    - badge: 왼쪽(또는 오른쪽) 큰 원 안에 아이콘, 원이 한 번 퍼지고 글자는 줄마다 올라온다
    - top: 위에 작은 원이 튀어 내려오고 아래에 가운데 정렬 문장이 흐림에서 또렷해진다
    - mark: 화면 오른쪽에 아주 큰 반투명 아이콘이 그려지고, 왼쪽 큰 문장 아래로 초록 막대가 그어진다"""
    tone = spec.get("tone", "green")
    var = spec.get("variant", "badge")
    if spec.get("strike") and var == "mark":
        var = "badge"
    inner = (f'<div class="ibig">{_e(spec["big"])}</div>' if spec.get("big") else svg(spec.get("icon", "sparkles")))
    strike = '<div class="istrike" id="%sx"></div>' % cid if spec.get("strike") else ""
    lines = spec.get("text") or paras
    n = len(lines)
    if var == "mark":
        mark = (f'<div class="imark {tone}" id="{cid}b"><div class="ibig">{_e(spec["big"])}</div></div>' if spec.get("big")
                else f'<div class="imark {tone}" id="{cid}b">{svg(spec.get("icon", "sparkles"))}</div>')
        body = f'<div class="itx mark">{mark}<div class="itext">{_lines(lines, "big", cid, "t")}<div class="ibar" id="{cid}u"></div></div></div>'
        tl.add(f"#{cid}b", {"scale": 1.15, "opacity": 0}, {"scale": 1, "opacity": 0.85, "ease": "power2.out"}, 0.0, 1.0)
        _draw(tl, f"#{cid}b .ic *", 0.0, 1.1, 0.06, 4)
        _rise(tl, f"#{cid} .itext .li", 0.1, n, 0.12)
        tl.add(f"#{cid}u", {"scaleX": 0}, {"scaleX": 1, "ease": "power3.inOut"}, 0.35 + 0.12 * n, 0.55)
    elif var == "top":
        body = (f'<div class="itx top"><div class="ibadge {tone}" id="{cid}b"><div class="ipulse" id="{cid}p"></div>{inner}{strike}</div>'
                f'<div class="itext">{_lines(lines, "big", cid, "t")}</div></div>')
        tl.add(f"#{cid}b", {"y": -70, "opacity": 0.3}, {"y": 0, "opacity": 1, "ease": "bounce.out"}, 0.0, 0.7)
        _draw(tl, f"#{cid}b .ic *", 0.2, 0.5, 0.04, 4)
        tl.add(f"#{cid} .ibig", {"scale": 1.6, "opacity": 0}, {"scale": 1, "opacity": 1, "ease": "expo.out"}, 0.1, 0.5)
        tl.add(f"#{cid}p", {"scale": 1, "opacity": 0.7}, {"scale": 1.5, "opacity": 0, "ease": "power2.out"}, 0.55, 0.7)
        if strike:
            tl.add(f"#{cid}x", {"scaleX": 0, "rotation": -35}, {"scaleX": 1, "rotation": -35, "ease": "power3.out"}, 0.7, 0.35)
        tl.add(f"#{cid} .itext .ln", {"opacity": 0, "filter": "blur(10px)", "scale": 1.05},
               {"opacity": 1, "filter": "blur(0px)", "scale": 1, "ease": "expo.out", "stagger": 0.14, "_n": n}, 0.25, 0.6)
    else:
        body = (f'<div class="itx {spec.get("side", "left")}"><div class="ibadge {tone}" id="{cid}b"><div class="ipulse" id="{cid}p"></div>'
                f'{inner}{strike}</div><div class="itext">{_lines(lines, "big", cid, "t")}</div></div>')
        tl.add(f"#{cid}b", {"scale": 0.6, "opacity": 0.3}, {"scale": 1, "opacity": 1, "ease": "back.out(1.7)"}, 0.0, 0.55)
        _draw(tl, f"#{cid}b .ic *", 0.15, 0.6, 0.04, 4)
        tl.add(f"#{cid} .ibig", {"scale": 1.6, "opacity": 0}, {"scale": 1, "opacity": 1, "ease": "expo.out"}, 0.1, 0.5)
        tl.add(f"#{cid}p", {"scale": 1, "opacity": 0.7}, {"scale": 1.45, "opacity": 0, "ease": "power2.out"}, 0.45, 0.7)
        if strike:
            tl.add(f"#{cid}x", {"scaleX": 0, "rotation": -35}, {"scaleX": 1, "rotation": -35, "ease": "power3.out"}, 0.75, 0.35)
        _rise(tl, f"#{cid} .itext .li", 0.25, n, 0.13)
    if spec.get("caption"):
        body += _lines([spec["caption"]], "icap", cid, "c")
        _rise(tl, f"#{cid} .icap .li", 0.4 + 0.13 * n)
    return "card tpl", body


def _diverge(spec, paras, cid, tl):
    """한 점(같은 얼굴)에서 갈래가 여러 개로 갈라져 각각 다른 결과로 이어진다."""
    fr, br = spec["from"], spec["branches"]
    n = len(br)
    H = 600
    ys = [H * (k + 0.5) / n for k in range(n)]
    paths = "".join(f'<path d="M330 {H / 2:.0f} C 640 {H / 2:.0f}, 700 {y:.0f}, 980 {y:.0f}" class="dvl" pathLength="1"/>' for y in ys)
    nodes = "".join(
        f'<div class="dvn" id="{cid}n{k}" style="top:{y - 70:.0f}px"><div class="dvc">{svg(b.get("icon", "hospital"))}</div>'
        f'<div class="dvt"><div class="dvlab">{_e(b["label"])}</div>'
        + (f'<div class="dvtag" style="background:{b.get("color", RED)}">{_e(b["tag"])}</div>' if b.get("tag") else "")
        + "</div></div>" for k, (b, y) in enumerate(zip(br, ys)))
    body = (_title(spec, cid, tl) + f'<div class="dv"><svg class="dvs" viewBox="0 0 1660 {H}">{paths}</svg>'
            f'<div class="dvf" id="{cid}f" style="top:{H / 2 - 150:.0f}px"><div class="dvc big">{svg(fr.get("icon", "scan-face"))}</div>'
            f'<div class="dvlab">{_e(fr["label"])}</div></div>{nodes}</div>')
    tl.add(f"#{cid}f", {"scale": 0.6, "opacity": 0.3}, {"scale": 1, "opacity": 1, "ease": "back.out(1.7)"}, 0.0, 0.5)
    _draw(tl, f"#{cid}f .ic *", 0.1, 0.5, 0.04, 4)
    _draw(tl, f"#{cid} .dvl", 0.45, 0.6, 0.12, n)
    for k in range(n):
        at = 0.8 + 0.18 * k
        tl.add(f"#{cid}n{k}", {"x": -40, "opacity": 0}, {"x": 0, "opacity": 1, "ease": "expo.out"}, at, 0.45)
        _draw(tl, f"#{cid}n{k} .ic *", at, 0.45)
        tl.add(f"#{cid}n{k} .dvtag", {"scale": 2, "opacity": 0}, {"scale": 1, "opacity": 1, "ease": "back.out(2)"}, at + 0.35 + 0.1 * n, 0.35)
    return "card tpl", body


def _tags(spec, paras, cid, tl):
    """큰 카드 여러 장이 뒤집히듯 차례로 나타난다 (병원마다 다른 진단 등)."""
    cards = "".join(f'<div class="tgc" id="{cid}c{k}" style="border-color:{c.get("color", "#333")}"><div class="tgh">{svg(c.get("icon", "hospital"))}'
                    f'<span>{_e(c.get("head", ""))}</span></div><div class="tgb">{_e(c["text"])}</div></div>'
                    for k, c in enumerate(spec["cards"]))
    body = _title(spec, cid, tl) + f'<div class="tgs">{cards}</div>'
    if spec.get("caption"):
        body += _lines([spec["caption"]], "icap", cid, "c")
    n = len(spec["cards"])
    tl.add(f"#{cid} .tgc", {"rotationY": -80, "opacity": 0.2, "transformPerspective": 900},
           {"rotationY": 0, "opacity": 1, "ease": "back.out(1.4)", "stagger": 0.2, "_n": n}, 0.05, 0.6)
    _draw(tl, f"#{cid} .tgh .ic *", 0.3, 0.5, 0.05, n * 3)
    if spec.get("caption"):
        _rise(tl, f"#{cid} .icap .li", 0.4 + 0.2 * n)
    return "card tpl", body


def _prompt(spec, paras, cid, tl):
    """채팅 입력창에 글자가 타이핑되고 보내기 버튼이 눌린다 ('의사에게 넣는 프롬프트')."""
    txt = spec["text"]
    body = (_title(spec, cid, tl) + f'<div class="pr"><div class="prl">{_e(spec.get("label", "프롬프트"))}</div>'
            f'<div class="prb" id="{cid}box"><span class="prt" id="{cid}t">{_e(txt)}</span><span class="prc" id="{cid}cur"></span>'
            f'<div class="prs" id="{cid}s">{svg("send", "ic")}</div></div></div>')
    if spec.get("caption"):
        body += _lines([spec["caption"]], "icap", cid, "c")
    tl.add(f"#{cid}box", {"y": 60, "opacity": 0.3}, {"y": 0, "opacity": 1, "ease": "expo.out"}, 0.05, 0.5)
    d = min(1.4, 0.06 * len(txt) + 0.2)
    tl.add(f"#{cid}t", {"clipPath": "inset(0% 100% 0% 0%)"}, {"clipPath": "inset(0% 0% 0% 0%)", "ease": f"steps({len(txt)})"}, 0.45, d)
    tl.add(f"#{cid}s", {"scale": 1, "backgroundColor": "#2a2a2a"}, {"scale": 1.18, "backgroundColor": GREEN, "ease": "back.out(3)"}, 0.5 + d, 0.3)
    _draw(tl, f"#{cid}s .ic *", 0.5 + d, 0.3)
    if spec.get("caption"):
        _rise(tl, f"#{cid} .icap .li", 0.7 + d)
    return "card tpl", body


def _timer(spec, paras, cid, tl):
    """원형 타이머가 줄어들며 시간(1~2분)이 짧다는 걸 보여준다."""
    lines = spec.get("text") or paras
    body = (f'<div class="itx"><div class="tmr"><svg viewBox="0 0 300 300"><circle cx="150" cy="150" r="130" class="tmb"/>'
            f'<circle cx="150" cy="150" r="130" class="tmf" id="{cid}r"/></svg><div class="tmt">{_e(spec["big"])}</div></div>'
            f'<div class="itext">{_lines(lines, "big", cid, "t")}</div></div>')
    tl.add(f"#{cid}r", {"strokeDashoffset": 0}, {"strokeDashoffset": 570, "ease": "power1.inOut"}, 0.1, 1.4)
    tl.add(f"#{cid} .tmt", {"scale": 1.5, "opacity": 0}, {"scale": 1, "opacity": 1, "ease": "expo.out"}, 0.05, 0.5)
    _rise(tl, f"#{cid} .itext .li", 0.3, len(lines), 0.13)
    return "card tpl", body


def _segments(spec, paras, cid, tl):
    """막대 하나를 구간으로 나눠 그린다 (썼다 → 쉬었다 → 다시 썼다, 질환 | 의인성)."""
    segs = spec["segs"]
    parts = "".join(f'<div class="sg" id="{cid}s{k}" style="flex:{s["w"]}"><div class="sgf{" gap" if s.get("gap") else ""}" '
                    f'style="background:{"transparent" if s.get("gap") else s.get("color", GREEN)}"></div><span>{_e(s["label"])}</span></div>'
                    for k, s in enumerate(segs))
    pin = ""
    if spec.get("pin"):
        pin = (f'<div class="sgp" id="{cid}p" style="left:{100 * spec["pin"]["at"]:.1f}%"><div class="sgq">{_e(spec["pin"]["label"])}</div>'
               f'<div class="sgl"></div></div>')
    body = _title(spec, cid, tl) + f'<div class="sgw"><div class="sgr">{parts}</div>{pin}</div>'
    if spec.get("caption"):
        body += _lines([spec["caption"]], "icap", cid, "c")
    t = 0.3
    for k, s in enumerate(segs):
        d = 0.25 + 0.6 * s["w"]
        tl.add(f"#{cid}s{k} .sgf", {"scaleX": 0}, {"scaleX": 1, "ease": "none"}, t, d)
        tl.add(f"#{cid}s{k} span", {"y": 30, "opacity": 0}, {"y": 0, "opacity": 1, "ease": "expo.out"}, t + d * 0.5, 0.4)
        t += d
    if pin:
        tl.add(f"#{cid}p", {"y": -80, "opacity": 0}, {"y": 0, "opacity": 1, "ease": "bounce.out"}, t, 0.6)
        t += 0.4
    if spec.get("caption"):
        _rise(tl, f"#{cid} .icap .li", t)
    return "card tpl", body


def _merge(spec, paras, cid, tl):
    """조각 여러 개가 가운데로 모여 한 문장(한 줄)이 된다."""
    chips = spec["chips"]
    n = len(chips)
    row = "".join(f'<div class="mgc" id="{cid}c{k}">{_e(c)}</div>' for k, c in enumerate(chips))
    body = (_title(spec, cid, tl) + f'<div class="mg"><div class="mgr">{row}</div><div class="mga" id="{cid}a">{svg("arrow-right", "ic")}</div>'
            f'<div class="mgres" id="{cid}res">{_e(spec["result"])}</div></div>')
    tl.add(f"#{cid} .mgc", {"y": 50, "opacity": 0}, {"y": 0, "opacity": 1, "ease": "back.out(2)", "stagger": 0.15, "_n": n}, 0.05, 0.45)
    tl.add(f"#{cid} .mgc", {"backgroundColor": "#1b2a22"}, {"backgroundColor": "#2f6f52", "ease": "none", "stagger": 0.12, "_n": n}, 0.75, 0.2)
    tl.add(f"#{cid}a", {"scale": 0, "rotation": 90}, {"scale": 1, "rotation": 90, "ease": "back.out(2)"}, 1.15, 0.35)
    tl.add(f"#{cid}res", {"scale": 0.7, "opacity": 0}, {"scale": 1, "opacity": 1, "ease": "back.out(1.8)"}, 1.35, 0.5)
    return "card tpl", body


def _iconlist(spec, paras, cid, tl):
    """아이콘 + 한 줄씩 (채널 소개, 안내 사항)."""
    rows = "".join(f'<div class="ilr" id="{cid}r{k}"><div class="ilc">{svg(ic)}</div><div class="ln"><div class="li">{_e(t)}</div></div></div>'
                   for k, (ic, t) in enumerate(spec["rows"]))
    body = _title(spec, cid, tl) + f'<div class="il">{rows}</div>'
    if spec.get("foot"):
        body += _lines([spec["foot"]], "icap", cid, "c")
    for k in range(len(spec["rows"])):
        at = 0.1 + 0.3 * k
        tl.add(f"#{cid}r{k} .ilc", {"scale": 0.5, "opacity": 0}, {"scale": 1, "opacity": 1, "ease": "back.out(2)"}, at, 0.4)
        _draw(tl, f"#{cid}r{k} .ic *", at + 0.05, 0.45)
        tl.add(f"#{cid}r{k} .li", {"yPercent": 80}, {"yPercent": 0, "ease": "expo.out"}, at + 0.1, 0.5)
    if spec.get("foot"):
        _rise(tl, f"#{cid} .icap .li", 0.3 + 0.3 * len(spec["rows"]))
    return "card tpl", body


CSS = """
.tpl .fit{display:flex;flex-direction:column;align-items:flex-start}
.ttl{font-size:92px;line-height:1.2}
.big{font-size:104px;line-height:1.22}
.icap{font-size:64px;color:#cfcfcf;margin-top:30px}
.ic{width:84px;height:84px;color:#fff;stroke-width:1.7}
.ic *,.ck *,.st *,.wi *{stroke-dasharray:1;stroke-dashoffset:0}
.irow{position:relative;display:flex;justify-content:space-between;width:1560px;margin:56px 0 10px}
.iline{position:absolute;left:95px;right:95px;top:95px;height:6px;background:#52B788;transform-origin:left center}
.itile{position:relative;z-index:1;display:flex;flex-direction:column;align-items:center;width:250px}
.icirc{width:190px;height:190px;border-radius:50%;background:#141414;border:5px solid #52B788;display:flex;align-items:center;justify-content:center;box-shadow:0 18px 50px rgba(0,0,0,.5)}
.ilab{margin-top:26px;font-size:58px;white-space:nowrap}
.split{display:flex;align-items:center;justify-content:space-between;width:1660px;gap:60px}
.lcol{flex:1}
.phone{width:580px;height:760px;border-radius:64px;background:#1b1b1b;border:10px solid #2c2c2c;position:relative;box-shadow:0 40px 90px rgba(0,0,0,.6);flex:none}
.notch{position:absolute;top:14px;left:50%;width:130px;height:30px;margin-left:-65px;border-radius:15px;background:#000}
.scr{position:absolute;inset:60px 24px 30px;background:#f6f3ea;border-radius:26px;padding:26px 24px;color:#222;overflow:hidden}
.mhead{display:flex;justify-content:space-between;font-size:30px;color:#c9a227;font-weight:700;margin-bottom:18px}
.mtitle{font-size:46px;font-weight:800;margin-bottom:22px;color:#111}
.mrow{display:flex;align-items:flex-start;gap:12px;font-size:38px;font-weight:700;line-height:1.3;margin-bottom:22px;color:#222}
.mrow.red{color:#c62f3b}.mrow.green{color:#2d8a5f}
.mdot{flex:none;width:16px;height:16px;border-radius:50%;background:#c9a227;margin-top:18px}
.mt{display:block;white-space:nowrap}
.clist{display:flex;flex-direction:column;gap:30px;margin-top:20px}
.crow{display:flex;align-items:center;gap:40px}
.cbox{width:104px;height:104px;border-radius:22px;border:7px solid #444;display:flex;align-items:center;justify-content:center;flex:none}
.ck{width:76px;height:76px;color:#52B788;stroke-width:3.2}
.crow .ln{font-size:104px}
.cmp{display:flex;align-items:center;gap:50px;width:1660px;margin-top:10px}
.cpanel{flex:1;background:#141414;border:1px solid #262626;border-radius:36px;padding:44px 50px}
.cbig{font-size:170px;line-height:1;white-space:nowrap}
.cbig.long{font-size:112px}
.csub{font-size:48px;color:#9a9a9a;margin:18px 0 34px;font-weight:700;min-height:1em}
.ctrack{height:30px;border-radius:15px;background:#232323;overflow:hidden}
.cfill{height:100%;border-radius:15px;transform-origin:left center}
.cmid{font-size:150px;color:#fff;flex:none}
.dots{display:flex;flex-direction:column;gap:80px;margin-top:50px;width:1660px}
.drow{display:flex;align-items:center;gap:40px}
.dlab{width:420px;font-size:62px;flex:none}
.dtrack{position:relative;flex:1;height:60px}
.dline{position:absolute;left:0;right:0;top:27px;height:6px;background:#333;transform-origin:left}
.dot{position:absolute;top:8px;width:44px;height:44px;margin-left:-22px;border-radius:50%}
.dend{position:absolute;right:0;top:70px;font-size:34px;color:#777}
.fork{position:relative;width:1660px;height:470px;margin-top:20px}
.faxis{position:absolute;left:0;right:0;top:300px;height:8px;background:#555;border-radius:4px;transform-origin:left}
.faxis:after{content:"";position:absolute;right:-6px;top:-13px;border-left:30px solid #555;border-top:17px solid transparent;border-bottom:17px solid transparent}
.fzone{position:absolute;top:220px;height:170px;width:calc(50% - 30px);border-radius:24px;display:flex;align-items:center;justify-content:center}
.fzone span{position:absolute;top:190px;font-size:66px;white-space:nowrap}
.fl{left:0;background:rgba(138,138,138,.16);transform-origin:right center}
.fr{right:0;background:rgba(230,57,70,.2);transform-origin:left center}
.fr span{color:#ff6b75}
.fpin{position:absolute;left:50%;top:40px;transform:translateX(-50%);display:flex;flex-direction:column;align-items:center}
.fpl{display:flex;align-items:center;gap:14px;background:#52B788;color:#0A0A0A;border-radius:40px;padding:14px 30px;font-size:44px}
.fpl .ic{width:48px;height:48px;color:#0A0A0A;stroke-width:2.4}
.fstem{width:6px;height:200px;background:#52B788}
.tline{position:relative;width:1660px;height:420px;margin-top:30px}
.tbar{position:absolute;left:3%;right:3%;top:196px;height:8px;background:#52B788;border-radius:4px;transform-origin:left}
.tnode{position:absolute;top:0;width:400px;margin-left:-200px;display:flex;flex-direction:column;align-items:center;text-align:center}
.tlab{height:170px;display:flex;align-items:flex-end;font-size:58px;line-height:1.15;padding-bottom:12px}
.tdot{width:46px;height:46px;border-radius:50%;background:#0A0A0A;border:8px solid #52B788;margin-top:7px}
.tsub{font-size:42px;color:#9a9a9a;margin-top:22px;font-weight:700;line-height:1.25}
.tnode.acc .tdot{border-color:#E63946;background:#E63946;width:60px;height:60px;margin-top:0}
.tnode.acc .tlab,.tnode.acc .tsub{color:#ff6b75}
.bwrap{position:relative;display:inline-block;margin-top:20px}
.bub{position:relative;background:#1d1d1d;border:2px solid #2e2e2e;border-radius:56px;padding:56px 80px;font-size:96px;line-height:1.25;max-width:1500px}
.btail{position:absolute;left:90px;bottom:-40px;width:0;height:0;border-left:30px solid transparent;border-right:30px solid transparent;border-top:44px solid #1d1d1d}
.stamp{position:absolute;right:-90px;top:-80px;width:190px;height:190px;border-radius:50%;border:12px solid;background:#0A0A0A;display:flex;align-items:center;justify-content:center}
.st{width:120px;height:120px;stroke-width:3.4}
.bnote{font-size:84px;margin-top:70px}
.wtag{display:flex;align-items:center;gap:18px;background:rgba(230,57,70,.16);border:3px solid #E63946;color:#ff6b75;border-radius:50px;padding:14px 36px;font-size:46px;margin-bottom:36px}
.wi{width:52px;height:52px;color:#E63946;stroke-width:2.3}
.wbody{position:relative;padding-left:56px}
.wbar{position:absolute;left:0;top:10px;bottom:10px;width:12px;background:#E63946;border-radius:6px;transform-origin:top}
.graph{width:1500px;height:557px;margin-top:10px;overflow:visible}
.gax{stroke:#555;stroke-width:5;fill:none;stroke-dasharray:1}
.gbase{stroke:#777;stroke-width:4;fill:none;stroke-dasharray:1}
.gstop{stroke:#52B788;stroke-width:4;stroke-dasharray:14 12}
.gl{fill:none;stroke-width:12;stroke-linecap:round;stroke-dasharray:1}
.gpre{stroke:#52B788}
.gtx{font-family:Pretendard;font-weight:800;font-size:52px;fill:#fff}
.gsm{font-size:36px;fill:#9a9a9a}
.part .stage{top:120px}
.pbig{position:absolute;right:0;top:-40px;font-size:420px;line-height:1;color:#1d1d1d}
.pmeta{font-size:50px;color:#52B788;letter-spacing:.08em;margin-bottom:10px}
.ptitle{font-size:200px;line-height:1.1}
.psub{font-size:66px;color:#bdbdbd;margin-top:16px}
.psteps{display:flex;gap:18px;margin-top:56px}
.pstep{width:200px;height:16px;border-radius:8px;background:#2a2a2a;transform-origin:left}
.pstep.on{background:#52B788}.pstep.done{background:#2f6f52}
.itx{display:flex;align-items:center;gap:90px;width:1660px}
.itx.right{flex-direction:row-reverse;justify-content:flex-end}
.ibadge{position:relative;width:330px;height:330px;border-radius:50%;background:#141414;border:8px solid #52B788;color:#52B788;
 display:flex;align-items:center;justify-content:center;flex:none;box-shadow:0 30px 70px rgba(0,0,0,.5)}
.ibadge.red{border-color:#E63946;color:#E63946}
.ibadge .ic{width:160px;height:160px;stroke-width:1.6;color:#fff}
.ibig{font-size:220px;line-height:1;color:#52B788}
.ibadge.red .ibig{color:#E63946}
.ipulse{position:absolute;inset:-10px;border-radius:50%;border:6px solid currentColor}
.istrike{position:absolute;left:-10px;right:-10px;top:calc(50% - 9px);height:18px;background:#E63946;border-radius:9px}
.itext .ln{font-size:104px}
.ctag{position:absolute;right:-230px;top:50%;margin-top:-34px;background:#E63946;color:#fff;font-size:40px;padding:10px 26px;border-radius:34px}
.crow{position:relative}
.dv{position:relative;width:1660px;height:600px}
.dvs{position:absolute;inset:0;width:1660px;height:600px;overflow:visible}
.dvl{fill:none;stroke:#3a3a3a;stroke-width:6;stroke-dasharray:1}
.dvf{position:absolute;left:30px;display:flex;flex-direction:column;align-items:center;gap:16px}
.dvc{width:140px;height:140px;border-radius:50%;background:#141414;border:5px solid #52B788;display:flex;align-items:center;justify-content:center;flex:none}
.dvc.big{width:260px;height:260px}.dvc.big .ic{width:130px;height:130px}
.dvn{position:absolute;left:980px;display:flex;align-items:center;gap:30px}
.dvt{display:flex;align-items:center;gap:24px}
.dvlab{font-size:56px}
.dvtag{font-size:46px;padding:8px 28px;border-radius:30px;color:#fff}
.tgs{display:flex;gap:44px;width:1660px;margin-top:30px}
.tgc{flex:1;background:#141414;border:4px solid #333;border-radius:36px;padding:40px 44px;min-height:380px;display:flex;flex-direction:column;justify-content:space-between}
.tgh{display:flex;align-items:center;gap:18px;font-size:40px;color:#9a9a9a}.tgh .ic{width:60px;height:60px}
.tgb{font-size:104px;line-height:1.1}
.pr{width:1500px;margin-top:40px}
.prl{font-size:42px;color:#52B788;margin-bottom:22px}
.prb{position:relative;display:flex;align-items:center;background:#161616;border:3px solid #333;border-radius:60px;padding:36px 150px 36px 56px;font-size:76px;min-height:160px}
.prt{white-space:nowrap}
.prc{display:inline-block;width:6px;height:80px;background:#52B788;margin-left:8px}
.prs{position:absolute;right:26px;top:50%;margin-top:-54px;width:108px;height:108px;border-radius:50%;background:#2a2a2a;display:flex;align-items:center;justify-content:center}
.prs .ic{width:56px;height:56px;color:#0A0A0A}
.tmr{position:relative;width:360px;height:360px;flex:none}
.tmr svg{width:360px;height:360px;transform:rotate(-90deg)}
.tmb{fill:none;stroke:#222;stroke-width:22}
.tmf{fill:none;stroke:#E63946;stroke-width:22;stroke-dasharray:817;stroke-linecap:round}
.tmt{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;font-size:96px;color:#fff}
.sgw{position:relative;width:1660px;margin-top:150px}
.sgr{display:flex;height:120px;gap:10px}
.sg{position:relative}
.sgf{position:absolute;inset:0;border-radius:22px;transform-origin:left center}
.sgf.gap{border:4px dashed #555}
.sg span{position:absolute;left:0;right:0;top:140px;text-align:center;font-size:52px;white-space:nowrap}
.sgp{position:absolute;top:-130px;transform:translateX(-50%);display:flex;flex-direction:column;align-items:center}
.sgq{background:#E63946;color:#fff;font-size:56px;padding:6px 30px;border-radius:30px}
.sgl{width:6px;height:150px;background:#E63946}
.mg{display:flex;flex-direction:column;align-items:center;width:1660px;gap:30px;margin-top:20px}
.mgr{display:flex;gap:30px}
.mgc{background:#1b2a22;border:3px solid #52B788;color:#bff0d6;font-size:70px;padding:18px 48px;border-radius:60px}
.mga .ic{width:90px;height:90px;color:#52B788}
.mgres{background:#52B788;color:#0A0A0A;font-size:92px;padding:26px 70px;border-radius:70px}
.il{display:flex;flex-direction:column;gap:34px;margin-top:20px}
.ilr{display:flex;align-items:center;gap:36px}
.ilc{width:120px;height:120px;border-radius:30px;background:#1b2a22;display:flex;align-items:center;justify-content:center;flex:none}
.ilc .ic{width:68px;height:68px;color:#52B788}
.ilr .ln{font-size:76px}
.itx.top{flex-direction:column;align-items:center;gap:40px;text-align:center}
.itx.top .ibadge{width:220px;height:220px}.itx.top .ibadge .ic{width:110px;height:110px}.itx.top .ibig{font-size:140px}
.itx.top .ln{margin:0 auto}
.tpl .fit:has(.itx.top){align-items:center}
.itx.mark{position:relative;min-height:560px}
.imark{position:absolute;right:-60px;top:50%;width:620px;height:620px;margin-top:-310px;color:#52B788;opacity:.85;
 display:flex;align-items:center;justify-content:center}
.imark.red{color:#E63946}
.imark .ic{width:520px;height:520px;stroke-width:1.3;color:inherit}
.imark .ibig{font-size:560px;color:inherit}
.itx.mark .itext .ln{font-size:118px}
.ibar{height:14px;width:420px;background:#52B788;border-radius:7px;margin-top:34px;transform-origin:left center}
"""
