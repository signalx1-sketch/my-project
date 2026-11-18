"""두 사람 썸네일 (2026-11-18): 왼쪽 인물(얼굴 모자이크 가능), 오른쪽 원장님을 같은 크기로, 아래 빨간 띠 전체에 큰 글자 2줄.
사람은 scripts/person_mask.py로 정확하게 오려 낸다.

사용법: python scripts/make_thumbnail_duo.py 설정.json 결과.jpg
설정: {"bg": 배경, "left": {"src", "mask", "mosaic": true, "badge": "?"}, "right": {"src", "mask", "beauty": true},
       "person_h": 540, "band_h": 250, "band": "#E8202A",
       "lines": [[["고3 아들을 둔", "white"]], [["수능 0.1% ", "#FFE600"], ["원장 생각", "white"]]], "size": 120}
"""
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_thumbnail import AGGRO, beautify  # noqa: E402

W, H = 1280, 720


def cut(spec, target_h):
    im = Image.open(spec["src"]).convert("RGB")
    m = Image.open(spec["mask"]).convert("L")
    bb = m.point(lambda v: 255 if v > 40 else 0).getbbox()
    im, m = im.crop(bb), m.crop(bb)
    if spec.get("beauty"):
        im = beautify(im, spec.get("beauty_strength", 1.0))
    if spec.get("mosaic"):  # 얼굴·머리를 뉴스처럼 큰 모자이크로 (알아볼 수 없게) + 전체 흐림
        w, h = im.size
        hb = (int(w * spec.get("head_x0", 0.25)), 0, int(w * spec.get("head_x1", 0.75)), int(h * spec.get("head_h", 0.45)))
        hd = im.crop(hb)
        bw, bh = hd.size
        blk = spec.get("block", 34)
        hd = hd.resize((max(1, bw // blk), max(1, bh // blk)), Image.BILINEAR).resize((bw, bh), Image.NEAREST)
        im.paste(hd, hb[:2])
        im = im.filter(ImageFilter.GaussianBlur(spec.get("blur", 7)))
    s = target_h / im.height
    size = (int(im.width * s), target_h)
    return im.resize(size, Image.LANCZOS), m.resize(size, Image.LANCZOS)


def main():
    cfg = json.load(open(sys.argv[1]))
    out = sys.argv[2]
    canvas = Image.open(cfg["bg"]).convert("RGB").resize((W, H))
    ph = cfg.get("person_h", 540)
    band_h = cfg.get("band_h", 250)
    top = H - band_h + cfg.get("overlap", 40) - ph  # 사람 아랫부분은 띠 뒤로 조금 들어간다
    L, R = cfg["left"], cfg["right"]
    # 사람마다 높이를 따로 줄 수 있다 (사진에 몸이 더 많이 나온 쪽은 키워야 머리 크기가 비슷해진다, 2026-11-18)
    li, lm = cut(L, L.get("h", ph))
    ri, rm = cut(R, R.get("h", ph))
    lx = L.get("x", W // 4 - li.width // 2)
    rx = R.get("x", 3 * W // 4 - ri.width // 2)
    # 사람 둘레 얇은 흰 테두리 (배경과 떨어져 보이게)
    for img, m, x, sp in ((li, lm, lx, L), (ri, rm, rx, R)):
        y = sp.get("y", top)
        edge = m.filter(ImageFilter.MaxFilter(cfg.get("outline", 7)))
        canvas.paste(Image.new("RGB", img.size, "white"), (x, y), edge)
        canvas.paste(img, (x, y), m)
    d = ImageDraw.Draw(canvas)
    if L.get("badge"):
        f = ImageFont.truetype(AGGRO, 64)
        cx, cy = lx + int(li.width * L.get("badge_x", 0.7)), L.get("y", top) + L.get("badge_y", 70)
        d.ellipse([cx - 44, cy - 44, cx + 44, cy + 44], fill="#E8202A", outline="white", width=6)
        d.text((cx, cy + 2), L["badge"], font=f, fill="white", anchor="mm")
    # 아래 빨간 띠 전체 + 큰 글자 2줄 (줄마다 [글자, 색] 조각을 이어 쓴다)
    by = H - band_h
    d.rectangle([0, by, W, H], fill=cfg.get("band", "#E8202A"))
    d.line([(0, by), (W, by)], fill="black", width=6)
    lines = cfg["lines"]
    size = cfg.get("size", 120)
    maxw = W - 2 * cfg.get("margin", 30)

    def width(f, parts):
        return sum(d.textlength(t, font=f) for t, _ in parts)
    f = ImageFont.truetype(AGGRO, size)
    while max(width(f, p) for p in lines) > maxw and size > 50:
        size -= 2
        f = ImageFont.truetype(AGGRO, size)
    gap = int(size * cfg.get("gap", 1.0))
    y = by + (band_h - gap * len(lines)) // 2 + int(size * 0.86)
    sw = cfg.get("stroke", 12)
    for parts in lines:
        x = (W - width(f, parts)) / 2
        for t, col in parts:
            d.text((x, y), t, font=f, fill=col, stroke_width=sw, stroke_fill="black", anchor="ls")
            x += d.textlength(t, font=f)
        y += gap
    canvas.save(out, quality=95)
    print("ok", out)


if __name__ == "__main__":
    main()
