"""사진 한 장을 화면 가득 까는 썸네일 (2026-11-20, 입주위염: 띠 없는 썸네일).

증상 사진(생성 인물)을 화면 전체에 깔고, 원장님 누끼를 한쪽에, 큰 글자는 어두운 그라데이션 위에 얹는다.
빨간 띠 없이도 글자가 읽히도록 글자 쪽만 어둡게 한다. 증상 부위에는 빨간 원을 칠 수 있다.

사용법: python scripts/make_thumbnail_photo.py 설정.json 결과.jpg
설정: {"photo": {"src", "scale", "anchor": [사진 x, 사진 y], "at": [화면 x, 화면 y]},
       "shade": [{"dir": "bottom"|"right"|"left"|"top", "start": 0~1, "alpha": 0~255}],
       "circle": {"box": [x0, y0, x1, y1], "color", "width"},
       "doc": {"src", "mask", "h", "x", "y", "beauty", "outline"},
       "texts": [{"parts": [[글자, 색], ...], "x", "y", "size", "align": "left"|"center"|"right", "stroke"}]}
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_thumbnail import AGGRO, beautify  # noqa: E402

W, H = 1280, 720


def place_photo(spec):
    im = Image.open(spec["src"]).convert("RGB")
    s = spec.get("scale", H / im.height)
    im = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
    ax, ay = spec.get("anchor", [im.width / s / 2, im.height / s / 2])
    tx, ty = spec.get("at", [W / 2, H / 2])
    ox, oy = round(tx - ax * s), round(ty - ay * s)
    # 사진이 화면을 다 못 덮으면 같은 사진을 크게 흐려 뒤에 깐다
    fill = im.resize((W, round(W * im.height / im.width)) if im.width / im.height < W / H else (round(H * im.width / im.height), H))
    canvas = fill.crop((0, 0, W, H)).filter(ImageFilter.GaussianBlur(30))
    canvas.paste(im, (ox, oy))
    return canvas


def shade(canvas, sh):
    """한쪽 가장자리로 갈수록 어두워지는 그라데이션 (글자 자리만 어둡게)."""
    a = np.zeros((H, W), np.float32)
    d = sh.get("dir", "bottom")
    n = H if d in ("bottom", "top") else W
    t = np.clip((np.arange(n) / n - sh.get("start", 0.5)) / max(1e-3, 1 - sh.get("start", 0.5)), 0, 1)
    t = t ** sh.get("gamma", 0.8) * sh.get("alpha", 220)
    if d in ("top", "left"):
        t = t[::-1]
    if d in ("bottom", "top"):
        a[:] = t[:, None]
    else:
        a[:] = t[None, :]
    layer = Image.new("RGB", (W, H), tuple(sh.get("color", [8, 8, 10])))
    return Image.composite(layer, canvas, Image.fromarray(a.astype(np.uint8)))


def main():
    cfg = json.load(open(sys.argv[1]))
    out = sys.argv[2]
    canvas = place_photo(cfg["photo"])
    for sh in cfg.get("shade", []):
        canvas = shade(canvas, sh)
    d = ImageDraw.Draw(canvas)
    c = cfg.get("circle")
    if c:  # 증상 부위 빨간 원 (흰 테두리를 밑에 깔아 어디서나 보이게)
        w = c.get("width", 9)
        d.ellipse(c["box"], outline="white", width=w + 6)
        d.ellipse(c["box"], outline=c.get("color", "#FF2020"), width=w)
    doc = cfg.get("doc")
    if doc:
        im = Image.open(doc["src"]).convert("RGB")
        m = Image.open(doc["mask"]).convert("L")
        bb = m.point(lambda v: 255 if v > 40 else 0).getbbox()
        im, m = im.crop(bb), m.crop(bb)
        if doc.get("beauty"):
            im = beautify(im, doc.get("beauty_strength", 1.0))
        s = doc["h"] / im.height
        size = (round(im.width * s), doc["h"])
        im, m = im.resize(size, Image.LANCZOS), m.resize(size, Image.LANCZOS)
        fb = doc.get("fade_bottom", 0)
        if fb:  # 아래 끝을 일자로 자르지 않고 어두운 그라데이션 속으로 사라지게 (2026-11-20)
            ramp = np.ones(m.height, np.float32)
            ramp[-fb:] = np.linspace(1, 0, fb)
            m = Image.fromarray((np.asarray(m, np.float32) * ramp[:, None]).astype(np.uint8))
        x, y = doc["x"], doc.get("y", H - doc["h"])
        if x < 0:  # 음수면 오른쪽 끝에서 그만큼 띄운다
            x = W - im.width + x + 1
        if doc.get("outline", 7):
            edge = m.filter(ImageFilter.MaxFilter(doc.get("outline", 7)))
            canvas.paste(Image.new("RGB", im.size, "white"), (x, y), edge)
        canvas.paste(im, (x, y), m)
        d = ImageDraw.Draw(canvas)
    for t in cfg.get("texts", []):
        f = ImageFont.truetype(AGGRO, t.get("size", 120))
        parts = t["parts"]
        tw = sum(d.textlength(p, font=f) for p, _ in parts)
        x = {"left": t["x"], "center": t["x"] - tw / 2, "right": t["x"] - tw}[t.get("align", "left")]
        for p, col in parts:
            d.text((x, t["y"]), p, font=f, fill=col, stroke_width=t.get("stroke", 12), stroke_fill="black", anchor="ls")
            x += d.textlength(p, font=f)
    canvas.save(out, quality=95)
    print("ok", out)


if __name__ == "__main__":
    main()
