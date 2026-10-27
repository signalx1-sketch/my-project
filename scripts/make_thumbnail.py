"""썸네일: 레퍼런스(dybUda36l7A)의 톤만 따르고 배치는 바꾼다 (2026-10-27: 똑같이 베끼지 않기).
밝은 흰 배경, 왼쪽 원장님, 오른쪽 흐린 관련 장면, 오른쪽 위 빨간 키워드, 손글씨 괄호, 아래 노란/흰 큰 글자 두 줄(검은 테두리).
글자는 어그로체 M(SBAggroM), 손글씨는 나눔펜체.

사용법: python scripts/make_thumbnail.py 원장님프레임.png 배경이미지 결과.jpg 설정.json
설정 예: {"keyword": ["피부염 진단,", "병원마다 다르다면?"], "hand": ["(난치 피부", "18년 본 원장)"],
          "line1": "피부염, 병원 가기 전에", "line2": "‘이 3가지’만 외우세요", "doc_crop": [660, 260, 1370, 1060],
          "bg_blur": 5, "bg_x": 200}
"""
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
AGGRO = str(ROOT / "assets" / "fonts" / "SBAggroM.woff")
PEN = str(ROOT / "assets" / "fonts" / "thumb" / "NanumPenScript-Regular.ttf")
W, H = 1280, 720


def fit(d, s, size, maxw):
    f = ImageFont.truetype(AGGRO, size)
    while d.textlength(s, font=f) > maxw and size > 40:
        size -= 2
        f = ImageFont.truetype(AGGRO, size)
    return f


def main():
    doc_p, bg_p, out, cfg_p = sys.argv[1:5]
    cfg = json.loads(Path(cfg_p).read_text(encoding="utf-8"))
    canvas = Image.new("RGB", (W, H), "white")
    # 오른쪽: 흐리고 밝게 만든 관련 장면
    bg = Image.open(bg_p).convert("RGB")
    bg = bg.resize((int(bg.width * H / bg.height), H))
    x0 = cfg.get("bg_x", 0)
    bg = bg.crop((x0, 0, x0 + 760, H)).filter(ImageFilter.GaussianBlur(cfg.get("bg_blur", 5)))
    bg = Image.blend(ImageEnhance.Brightness(bg).enhance(1.45), Image.new("RGB", bg.size, "white"), 0.45)
    canvas.paste(bg, (W - 760, 0))
    # 왼쪽: 원장님 (오른쪽 가장자리를 흰 배경으로 부드럽게)
    doc = Image.open(doc_p).convert("RGB").crop(tuple(cfg.get("doc_crop", [660, 260, 1370, 1060]))).resize((640, 720))
    doc = ImageEnhance.Brightness(doc).enhance(1.08)
    mask = Image.new("L", doc.size, 255)
    md = ImageDraw.Draw(mask)
    for i in range(130):
        md.line([(639 - i, 0), (639 - i, H)], fill=int(255 * i / 130))
    canvas.paste(doc, (0, 0), mask)
    d = ImageDraw.Draw(canvas)

    def text(xy, s, font, fill, stroke, sw, anchor="la"):
        d.text(xy, s, font=font, fill=fill, stroke_width=sw, stroke_fill=stroke, anchor=anchor)

    kf = ImageFont.truetype(AGGRO, 66)
    for i, s in enumerate(cfg["keyword"]):
        text((960, 150 + i * 84), s, kf, "#F0384A", "white", 10, "ma")
    pen = ImageFont.truetype(PEN, 54)
    for i, s in enumerate(cfg.get("hand", [])):
        text((40, 30 + i * 52), s, pen, "#111111", "white", 3)
    f1 = fit(d, cfg["line1"], 112, W - 80)
    f2 = fit(d, cfg["line2"], 112, W - 80)
    text((W // 2, 452), cfg["line1"], f1, "#FFF200", "black", 12, "ma")
    text((W // 2, 584), cfg["line2"], f2, "white", "black", 12, "ma")
    canvas.save(out, quality=95)


if __name__ == "__main__":
    main()
