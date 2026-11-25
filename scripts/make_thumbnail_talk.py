"""원장님이 시청자에게 말하는 형 썸네일 (2026-11-25, 레퍼런스: 메이드영 '윤곽수술을 고민하는 모두에게 말씀드립니다').

왼쪽에 굵은 흰 글자 3줄(핵심어는 노란 상자에 검은 글자), 오른쪽에 원장님 누끼를 크게, 원장님 머리 위에 초록 필기체 한마디.
배경은 장면 사진을 어둡고 살짝 흐리게 깔고, 테두리는 초록 둥근 틀.

사용법: python scripts/make_thumbnail_talk.py 설정.json 결과.jpg
설정: {"bg": {"src", "scale", "anchor", "at", "blur", "dark"}, "frame": {"color", "width", "radius"},
       "tag": 작은 머리말, "lines": [[[글자, "box"|"white"|색], ...], ...], "size", "x", "y", "gap",
       "sub": [작은 글자 줄...], "doc": {"src", "mask", "h", "x", "y", "beauty"},
       "hand": {"lines": [...], "x", "y", "size", "color", "angle"}}
"""
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageEnhance

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from make_thumbnail import beautify  # noqa: E402

W, H = 1280, 720
BOLD = str(ROOT / "assets" / "fonts" / "SBAggroM.woff")  # 채널 메인 폰트 어그로체 M (2026-11-25 사용자)
SEMI = str(ROOT / "assets" / "fonts" / "Pretendard-Bold.otf")
HAND = str(ROOT / "assets" / "fonts" / "thumb" / "NanumPenScript-Regular.ttf")


def background(spec):
    im = Image.open(spec["src"]).convert("RGB")
    s = spec.get("scale", max(W / im.width, H / im.height))
    im = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
    ax, ay = spec.get("anchor", [im.width / s / 2, im.height / s / 2])
    tx, ty = spec.get("at", [W / 2, H / 2])
    canvas = Image.new("RGB", (W, H))
    canvas.paste(im, (round(tx - ax * s), round(ty - ay * s)))
    canvas = canvas.filter(ImageFilter.GaussianBlur(spec.get("blur", 3)))
    canvas = ImageEnhance.Brightness(canvas).enhance(spec.get("dark", 0.45))
    # 글자 쪽(왼쪽)은 조금 더 어둡게
    grad = Image.linear_gradient("L").rotate(90).resize((W, H))
    shade = Image.new("RGB", (W, H), "black")
    canvas = Image.composite(canvas, shade, grad.point(lambda v: int(255 - (255 - v) * spec.get("left_dark", 0.45))))
    return canvas


STROKE = {"w": 8, "c": "#111111"}  # 설정 "stroke": 테두리 굵기, "stroke_color": 테두리 색 (밝은 배경엔 흰 테두리에 검은 글자)


def text_line(draw, x, y, parts, font, box_pad=(14, 6)):
    for txt, color in parts:
        w = draw.textlength(txt, font=font)
        if color.startswith("box"):  # "box" = 노란 상자에 검은 글자, "box:#바탕:#글자" = 색 지정 (예: 빨간 상자에 흰 글자)
            _, bg, fg = (color.split(":") + ["#FFE600", "#111111"])[:3] if ":" in color else ("box", "#FFE600", "#111111")
            bb = draw.textbbox((x, y), txt, font=font)
            pad = (round(font.size * 0.12), round(font.size * 0.08))
            draw.rectangle((bb[0] - pad[0] + 8, bb[1] - pad[1] + 8, bb[2] + pad[0] + 8, bb[3] + pad[1] + 8), fill="#111111")  # 그림자
            draw.rectangle((bb[0] - pad[0], bb[1] - pad[1], bb[2] + pad[0], bb[3] + pad[1]), fill=bg)
            draw.text((x, y), txt, font=font, fill=fg, stroke_width=3 if fg.lower() in ("white", "#ffffff") else 0, stroke_fill="#111111")
            x += w + box_pad[0] + 4
        else:
            draw.text((x, y), txt, font=font, fill=color, stroke_width=STROKE["w"], stroke_fill=STROKE["c"])
            x += w


def main():
    cfg = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    STROKE.update(w=cfg.get("stroke", 8), c=cfg.get("stroke_color", "#111111"))
    img = background(cfg["bg"])
    if cfg.get("shade_bottom"):  # 아래 글자 자리만 어둡게 (사진 가득형처럼)
        st, al = cfg["shade_bottom"]
        g = Image.linear_gradient("L").resize((W, H - int(H * st))).point(lambda v: int(v * al / 255))
        mask = Image.new("L", (W, H), 0); mask.paste(g, (0, int(H * st)))
        img = Image.composite(Image.new("RGB", (W, H), "black"), img, mask)

    d = cfg["doc"]
    doc = Image.open(d["src"]).convert("RGB")
    if d.get("beauty"):
        doc = beautify(doc)
    # 누끼 바깥의 옅은 회색은 상자 테두리처럼 비치니 잘라 낸다
    mask = Image.open(d["mask"]).convert("L").point(lambda v: 255 if v > 128 else 0).filter(ImageFilter.GaussianBlur(1.2))
    s = d["h"] / doc.height
    doc = doc.resize((round(doc.width * s), d["h"]), Image.LANCZOS)
    mask = mask.resize(doc.size, Image.LANCZOS)
    # 원장님 뒤 은은한 그림자로 배경과 떼어 놓는다
    sh = Image.new("L", img.size, 0)
    sh.paste(mask, (d["x"] + 10, d["y"] + 10))
    img = Image.composite(Image.new("RGB", img.size, "black"), img, sh.filter(ImageFilter.GaussianBlur(18)).point(lambda v: v * 0.55))
    img.paste(doc, (d["x"], d["y"]), mask)

    draw = ImageDraw.Draw(img)
    if cfg.get("tag"):
        f = ImageFont.truetype(SEMI, 26)
        tw = draw.textlength(cfg["tag"], font=f)
        x0, y0 = cfg["x"], cfg["y"] - 62
        draw.rounded_rectangle((x0, y0, x0 + tw + 36, y0 + 44), radius=22, fill=(20, 24, 22))
        draw.text((x0 + 18, y0 + 7), cfg["tag"], font=f, fill="white")
    y = cfg["y"]
    for line in cfg["lines"]:
        # 줄마다 설정 가능: {"parts", "fit": 이 폭에 꽉 차게 글자 크기 맞춤, "size", "align": "left"|"center", "cx": 가운데 x}
        if isinstance(line, list):
            line = {"parts": line}
        size = line.get("size", cfg.get("size", 110))
        if line.get("fit") or cfg.get("fit"):
            fw = line.get("fit") or cfg["fit"]
            probe = ImageFont.truetype(BOLD, 100)
            tw = sum(draw.textlength(t, font=probe) for t, _ in line["parts"])
            size = int(100 * fw / tw)
        f = ImageFont.truetype(BOLD, size)
        x = cfg["x"]
        if line.get("align", cfg.get("align")) == "center":
            tw = sum(draw.textlength(t, font=f) for t, _ in line["parts"])
            x = round(line.get("cx", cfg.get("cx", W / 2)) - tw / 2)
        top = f.getbbox("가")[1]  # 글자 위 빈 공간을 빼고 촘촘히 쌓는다
        text_line(draw, x, y - top, line["parts"], f)
        y += round(size * cfg.get("gap", 1.22) - (0 if not cfg.get("tight") else 0))
    if cfg.get("sub"):
        fs = ImageFont.truetype(SEMI, 34)
        y += 10
        for line in cfg["sub"]:
            draw.text((cfg["x"], y), line, font=fs, fill="#E8E8E8", stroke_width=2, stroke_fill="#111111")
            y += 46

    hcfg = cfg.get("hand")
    if hcfg:
        fh = ImageFont.truetype(HAND, hcfg.get("size", 64))
        layer = Image.new("RGBA", (1100, 400), (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        ly = 10
        for line in hcfg["lines"]:
            for dx in (0, 1, 2):  # 펜 글씨가 가늘어 조금 두껍게
                ld.text((20 + dx, ly), line, font=fh, fill=hcfg.get("color", "#3BE37A"), stroke_width=5, stroke_fill="#0B2A16")
            ly += round(hcfg.get("size", 64) * 0.95)
        layer = layer.crop(layer.getbbox()).rotate(hcfg.get("angle", 6), expand=True, resample=Image.BICUBIC)
        img.paste(layer, (hcfg["x"], hcfg["y"]), layer)

    fr = cfg.get("frame")
    if fr:
        border = Image.new("L", img.size, 0)
        ImageDraw.Draw(border).rounded_rectangle((0, 0, W - 1, H - 1), radius=fr.get("radius", 36), outline=255, width=fr.get("width", 16))
        img = Image.composite(Image.new("RGB", img.size, fr.get("color", "#2F9E6E")), img, border)
    img.save(sys.argv[2], quality=93)
    print("ok", sys.argv[2])


if __name__ == "__main__":
    main()
