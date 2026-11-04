"""좌우 비교 썸네일 (2026-11-04, 골프 '백돌이 vs 프로 / 진작 이렇게 할걸...' 레퍼런스 구도).
왼쪽 잘못한 예(빨간 표시), 오른쪽 잘한 예(초록 표시), 가운데 초록 세로줄, 위에 짧은 라벨,
아래 아주 큰 초록 문구(검은 테두리), 원장님은 오려서 오른쪽 아래.

사용법: python scripts/make_thumbnail_split.py 설정.json 결과.jpg
설정: {"left": {"src", "center": [x, y], "zoom", "label", "label_color"}, "right": {...},
       "doc": 원장님프레임.png, "doc_mask": 마스크.png, "doc_box": [x0, y0, x1, y1], "doc_h": 460,
       "title": "보습, 진작 이렇게 할걸...", "title_color": "#2BF24A", "split": 640}
"""
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_thumbnail import AGGRO, W, H, beautify  # noqa: E402


def panel(src: str, w: int, center, zoom: float, bright: float = 1.0) -> Image.Image:
    """src를 (가로 w, 세로 H) 칸에 채운다. center는 원본에서 칸 가운데에 올 점, zoom은 원본 높이 대비 배율."""
    im = Image.open(src).convert("RGB")
    sc = H / im.height * zoom
    im = im.resize((round(im.width * sc), round(im.height * sc)), Image.LANCZOS)
    cx, cy = center[0] * sc, center[1] * sc
    x0 = int(min(max(cx - w / 2, 0), im.width - w))
    y0 = int(min(max(cy - H / 2, 0), im.height - H))
    out = im.crop((x0, y0, x0 + w, y0 + H))
    out = out.filter(ImageFilter.UnsharpMask(radius=1.6, percent=40, threshold=2))
    return ImageEnhance.Brightness(out).enhance(bright)


def stroke_text(d, xy, s, font, fill, stroke, sw, anchor="la"):
    d.text(xy, s, font=font, fill=fill, stroke_width=sw, stroke_fill=stroke, anchor=anchor)


def main():
    cfg = json.load(open(sys.argv[1]))
    out = sys.argv[2]
    sx = cfg.get("split", 640)
    canvas = Image.new("RGB", (W, H), "black")
    L, R = cfg["left"], cfg["right"]
    canvas.paste(panel(L["src"], sx, L["center"], L.get("zoom", 1.0), L.get("bright", 1.0)), (0, 0))
    canvas.paste(panel(R["src"], W - sx, R["center"], R.get("zoom", 1.0), R.get("bright", 1.0)), (sx, 0))

    # 원장님 (오려서 오른쪽 아래). 설정에 doc이 없으면 넣지 않는다
    if cfg.get("doc"):
        doc = Image.open(cfg["doc"]).convert("RGB")
        if cfg.get("beauty", True):
            doc = beautify(doc, cfg.get("beauty_strength", 1.0))
        m = Image.open(cfg["doc_mask"]).convert("L")
        box = tuple(cfg["doc_box"])
        doc, m = doc.crop(box), m.crop(box)
        dh = cfg.get("doc_h", 460)
        sc = dh / doc.height
        doc = doc.resize((int(doc.width * sc), dh), Image.LANCZOS)
        m = m.resize(doc.size, Image.LANCZOS)
        # 원장님 둘레에 얇은 흰 테두리 (배경과 떨어져 보이게)
        if cfg.get("doc_outline", 6):
            edge = m.filter(ImageFilter.MaxFilter(cfg.get("doc_outline", 6) * 2 + 1))
            canvas.paste(Image.new("RGB", doc.size, "white"), (W - doc.width + cfg.get("doc_dx", 60), H - dh), edge)
        canvas.paste(doc, (W - doc.width + cfg.get("doc_dx", 60), H - dh), m)

    # 아래쪽 어둡게 (큰 글자 받침)
    shade = Image.new("L", (W, H), 0)
    sd = ImageDraw.Draw(shade)
    sh = cfg.get("shade_h", 250)
    for y in range(H - sh, H):
        sd.line([(0, y), (W, y)], fill=int(cfg.get("shade", 200) * (y - (H - sh)) / sh))
    canvas = Image.composite(Image.new("RGB", (W, H), "black"), canvas, shade)

    d = ImageDraw.Draw(canvas)
    # 가운데 초록 세로줄
    lw = cfg.get("split_w", 6)
    d.rectangle([sx - lw // 2, 0, sx + lw // 2, H - cfg.get("split_stop", 170)], fill=cfg.get("split_color", "#2BF24A"))

    # 위 라벨 + 밑줄 (왼쪽 빨강, 오른쪽 초록)
    lf = ImageFont.truetype(AGGRO, cfg.get("label_size", 64))
    for side, x0, col in ((L, 0, "#E8202A"), (R, sx, cfg.get("split_color", "#2BF24A"))):
        lx, ly = side.get("label_xy", [x0 + 40, 34])
        stroke_text(d, (lx, ly), side["label"], lf, side.get("label_color", "white"), "black", 7)
        tw = d.textlength(side["label"], font=lf)
        d.rounded_rectangle([lx, ly + cfg.get("label_size", 64) + 16, lx + tw, ly + cfg.get("label_size", 64) + 28],
                            radius=6, fill=side.get("bar", col), outline="black", width=3)

    # 아래 큰 문구 (줄바꿈 \n이 있으면 여러 줄, 가장 긴 줄이 폭에 맞게)
    lines = cfg["title"].split("\n")
    size = cfg.get("title_size", 120)
    maxw = W - 2 * cfg.get("title_margin", 30)
    f = ImageFont.truetype(AGGRO, size)
    while max(d.textlength(t, font=f) for t in lines) > maxw and size > 50:
        size -= 2
        f = ImageFont.truetype(AGGRO, size)
    gap = int(size * cfg.get("title_gap", 1.02))
    y = H - cfg.get("title_bottom", 34) - gap * (len(lines) - 1)
    sw = cfg.get("title_stroke", 14)
    # 투톤: title_parts [[글자, 색], ...]를 한 줄로 이어 쓴다 (합친 글자는 title과 같아야 한다)
    parts = cfg.get("title_parts")
    # 글자 뒤 띠 (예: 빨강). 위아래 검은 테두리
    if cfg.get("banner"):
        bb = d.textbbox((W // 2, y), lines[-1], font=f, anchor="ms")
        pad = cfg.get("banner_pad", 18)
        top = y - gap * (len(lines) - 1) + (bb[1] - y) - pad
        d.rectangle([0, top, W, bb[3] + pad], fill=cfg["banner"], outline="black", width=6)
    for t in lines:
        if parts and len(lines) == 1:
            x = W // 2 - d.textlength(t, font=f) / 2
            for s, col in parts:
                stroke_text(d, (x, y), s, f, col, "black", sw, anchor="ls")
                x += d.textlength(s, font=f)
        else:
            stroke_text(d, (W // 2, y), t, f, cfg.get("title_color", "#2BF24A"), "black", sw, anchor="ms")
        y += gap
    canvas.save(out, quality=95)


if __name__ == "__main__":
    main()
