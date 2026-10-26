"""화면 위쪽 진행 표시: '1 순서 · 2 기간 · 3 끊었을 때' 탭을 띄우고 지금 파트를 초록으로 칠한다.

계획 JSON에 {"progress": {"labels": ["순서", "기간", "끊었을 때"], "chapters": [2, 3, 4]}}가 있으면 켠다.
chapters는 plan["chapters"]의 번호 (각 파트가 시작하는 챕터). 마지막 파트는 다음 챕터가 시작할 때까지 보인다.
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .timeline import Timeline

FONT = Path(__file__).resolve().parent.parent / "assets" / "fonts" / "Pretendard-Bold.otf"
GREEN = (82, 183, 136, 255)
TOP, H, PADX, GAP, SIZE = 34, 58, 26, 12, 32


def make_tabs(labels: list[str], folder: Path) -> list[Path]:
    """파트마다 하나씩, 그 파트가 켜진 탭 그림(투명 PNG, 화면 위쪽 띠)."""
    folder.mkdir(parents=True, exist_ok=True)
    font = ImageFont.truetype(str(FONT), SIZE)
    texts = [f"{i + 1}  {t}" for i, t in enumerate(labels)]
    widths = [int(font.getlength(t)) + 2 * PADX for t in texts]
    total = sum(widths) + GAP * (len(texts) - 1)
    out = []
    for k in range(len(labels)):
        im = Image.new("RGBA", (1920, TOP + H + 20), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        x = (1920 - total) // 2
        for j, (t, w) in enumerate(zip(texts, widths)):
            on = j == k
            fill = GREEN if on else ((20, 20, 20, 170) if j > k else (30, 60, 46, 200))
            d.rounded_rectangle((x, TOP, x + w, TOP + H), radius=H // 2, fill=fill)
            col = (10, 10, 10, 255) if on else ((190, 190, 190, 255) if j > k else (140, 200, 170, 255))
            d.text((x + w / 2, TOP + H / 2 + 1), t, font=font, fill=col, anchor="mm")
            x += w + GAP
        p = folder / f"tab{k}.png"
        im.save(p)
        out.append(p)
    return out


def windows(tl: Timeline, plan: dict, end: float) -> list[tuple[int, float, float]]:
    """[(파트 번호, 출력 시작, 출력 끝)]."""
    cfg = plan.get("progress") or {}
    chs = cfg.get("chapters") or []
    starts: dict[int, float] = {}
    for c in tl.clips:
        if c.chapter is not None and c.chapter not in starts:
            starts[c.chapter] = c.out_start
    res = []
    for k, ch in enumerate(chs):
        if ch not in starts:
            continue
        nxt = [t for c2, t in starts.items() if c2 > ch]
        res.append((k, starts[ch], min(nxt) if nxt else end))
    return res


def overlay_filters(tabs: list[Path], wins: list[tuple[int, float, float]], first_input: int,
                    base: str) -> tuple[list[str], str, str]:
    """(입력 인자, 필터 조각, 결과 라벨)."""
    args, parts, cur = [], [], base
    for n, (k, a, b) in enumerate(wins):
        args += ["-loop", "1", "-framerate", "30", "-i", str(tabs[k])]
        parts.append(f"[{first_input + n}:v]format=rgba,fade=t=in:st={a:.3f}:d=0.25:alpha=1[tb{n}]")
        parts.append(f"[{cur}][tb{n}]overlay=0:0:enable='between(t,{a:.3f},{b:.3f})':shortest=0:eof_action=pass[pg{n}]")
        cur = f"pg{n}"
    return args, ";".join(parts), cur
