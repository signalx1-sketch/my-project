"""썸네일: 레퍼런스(dybUda36l7A)의 톤만 따르고 배치는 바꾼다 (2026-10-27: 똑같이 베끼지 않기).
밝은 흰 배경, 왼쪽 원장님, 오른쪽 흐린 관련 장면, 오른쪽 위 빨간 키워드, 손글씨 괄호, 아래 노란/흰 큰 글자 두 줄(검은 테두리).
글자는 어그로체 M(SBAggroM), 손글씨는 나눔펜체.

사용법: python scripts/make_thumbnail.py 원장님프레임.png 배경이미지 결과.jpg 설정.json
설정 예: {"keyword": ["피부염 진단,", "병원마다 다르다면?"], "hand": ["(난치 피부", "18년 본 원장)"],
          "line1": "피부염, 병원 가기 전에", "line2": "‘이 3가지’만 외우세요", "doc_crop": [660, 260, 1370, 1060],
          "bg_blur": 5, "bg_x": 200}
"""
import json
import re
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


def beautify(img: Image.Image, strength: float = 1.0) -> Image.Image:
    """뽀샤시 보정: 피부 결만 부드럽게 (눈, 안경테, 입술처럼 경계가 뚜렷한 곳은 그대로), 피부톤만 살짝 밝고 화사하게."""
    import numpy as np
    a = np.asarray(img).astype(np.float32)
    ycc = np.asarray(img.convert("YCbCr")).astype(np.float32)
    cb, cr = ycc[..., 1], ycc[..., 2]
    skin = ((cr > 135) & (cr < 178) & (cb > 85) & (cb < 130)).astype(np.float32)
    skin = np.asarray(Image.fromarray((skin * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(5))).astype(np.float32) / 255
    smooth = np.asarray(img.filter(ImageFilter.GaussianBlur(2.6))).astype(np.float32)
    diff = np.abs(a - smooth).max(axis=2)
    keep_edges = np.exp(-(diff / 10.0) ** 2)  # 차이가 큰 곳(경계)은 거의 안 바꾼다
    w = (skin * keep_edges * 0.85 * strength)[..., None]
    a = a * (1 - w) + smooth * w
    lift = (skin * 0.10 * strength)[..., None]  # 피부만 살짝 밝게
    a = a + (255 - a) * lift
    out = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
    return ImageEnhance.Brightness(out).enhance(1.03)


def even_tone(img: Image.Image, regions: list) -> Image.Image:
    """색소침착 정리: 지정한 영역(원장님 사진 기준 [x0, y0, x1, y1])에서 주변보다 어두운 얼룩만 주변 피부색까지 밝힌다.
    피부 결(잔무늬)은 그대로 두고 낮은 주파수의 톤만 맞추므로 자연스럽다."""
    import numpy as np
    a = np.asarray(img).astype(np.float32)
    low = np.asarray(img.filter(ImageFilter.GaussianBlur(9))).astype(np.float32)
    ycc = np.asarray(img.convert("YCbCr")).astype(np.float32)
    skin = ((ycc[..., 2] > 135) & (ycc[..., 2] < 178) & (ycc[..., 1] > 85) & (ycc[..., 1] < 130) & (ycc[..., 0] > 90))
    skin = Image.fromarray((skin * 255).astype(np.uint8)).filter(ImageFilter.MinFilter(9)).filter(ImageFilter.GaussianBlur(4))
    skin = (np.asarray(skin).astype(np.float32) / 255)[..., None]  # 얼굴 가장자리 밖(의자, 배경)은 건드리지 않는다
    for x0, y0, x1, y1 in regions:
        cx, cy, rx, ry = (x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) / 2, (y1 - y0) / 2
        yy, xx = np.mgrid[0:a.shape[0], 0:a.shape[1]]
        r = ((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2
        m = np.clip((1.0 - r) / 0.45, 0, 1)[..., None]  # 가장자리는 부드럽게
        sk = skin[y0:y1, x0:x1, 0].reshape(-1) > 0.5
        patch = low[y0:y1, x0:x1].reshape(-1, 3)[sk]
        lum = patch.mean(axis=1)
        target = patch[lum >= np.percentile(lum, 75)].mean(axis=0)
        gain = np.clip(target - low, 0, None)  # 어두운 곳만 올린다
        a = a + gain * m * skin
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


def before_after(doc_p, out, cfg):
    """비포·애프터 얼굴 근접샷으로 화면을 꽉 채우고, 원장님은 오려서 오른쪽, 글자는 아래 두 줄 (2026-11-02)."""
    import numpy as np
    def cover(src):  # 빈 곳은 애프터 장면을 흐리게 깔아 메운다
        im = Image.open(src).convert("RGB")
        sc = max(W / im.width, H / im.height)
        im = im.resize((int(im.width * sc), int(im.height * sc))).crop((0, 0, W, H))
        return ImageEnhance.Brightness(im.filter(ImageFilter.GaussianBlur(20))).enhance(0.9)

    canvas = cover(cfg["after"]["src"])

    def panel(src, box, w, h):
        im = Image.open(src).convert("RGB").crop(tuple(box))
        sc = max(w / im.width, h / im.height)
        im = im.resize((int(im.width * sc), int(im.height * sc)), Image.LANCZOS)
        im = im.crop(((im.width - w) // 2, 0, (im.width - w) // 2 + w, h))
        return im.filter(ImageFilter.UnsharpMask(2, 60, 2))

    b, a = cfg["before"], cfg["after"]
    bw, aw, ax = cfg.get("before_w", 560), cfg.get("after_w", 560), cfg.get("after_x", 480)
    canvas.paste(panel(b["src"], b["box"], bw, H), (0, 0))
    ap = panel(a["src"], a["box"], aw, H)
    if a.get("flip"):  # 얼굴이 원장님 쪽을 보면 가려지므로 좌우를 뒤집어 비포 쪽을 보게
        ap = ap.transpose(Image.FLIP_LEFT_RIGHT)
    fade = Image.new("L", ap.size, 255)
    fd = ImageDraw.Draw(fade)
    for i in range(80):  # 양쪽 가장자리를 부드럽게 (비포 쪽, 오른쪽 끝)
        fd.line([(i, 0), (i, H)], fill=int(255 * i / 80))
        fd.line([(aw - 1 - i, 0), (aw - 1 - i, H)], fill=int(255 * i / 80))
    canvas.paste(ap, (ax, 0), fade)
    d = ImageDraw.Draw(canvas)
    # 빨간 >> 화살표
    cx, cy, s = cfg.get("arrow", [ax + 10, 250, 62])
    for k in range(2):
        x = cx + k * s * 0.75
        d.polygon([(x - s * 0.5, cy - s), (x - s * 0.1, cy - s), (x + s * 0.5, cy), (x - s * 0.1, cy + s),
                   (x - s * 0.5, cy + s), (x + s * 0.1, cy)], fill="#E8202A", outline="black", width=5)
    # 원장님 (오려서 오른쪽 아래)
    doc = Image.open(doc_p).convert("RGB")
    if cfg.get("beauty"):
        doc = beautify(doc, cfg.get("beauty_strength", 1.0))
    m = Image.open(cfg["doc_mask"]).convert("L")
    box = tuple(cfg.get("doc_box", [640, 320, 1500, 1080]))
    doc, m = doc.crop(box), m.crop(box)
    dh = cfg.get("doc_h", 560)
    sc = dh / doc.height
    doc = ImageEnhance.Brightness(doc.resize((int(doc.width * sc), dh), Image.LANCZOS)).enhance(1.06)
    m = m.resize(doc.size, Image.LANCZOS)
    canvas.paste(doc, (W - doc.width + cfg.get("doc_dx", 40), H - dh), m)
    # 아래쪽 어둡게 (글자 받침)
    shade = Image.new("L", (W, H), 0)
    sd = ImageDraw.Draw(shade)
    top = H - cfg.get("shade_h", 300)
    for y in range(top, H):
        sd.line([(0, y), (W, y)], fill=int(200 * (y - top) / (H - top)))
    canvas = Image.composite(Image.new("RGB", (W, H), "black"), canvas, shade)
    d = ImageDraw.Draw(canvas)
    size, sw = cfg.get("big_size", 120), cfg.get("big_stroke", 14)
    y = H - cfg.get("bottom", 22) - int(size * cfg.get("line_gap", 1.02)) * len(cfg["big"])
    for row in cfg["big"]:
        txt, color = row[0], row[1]
        opt = row[3] if len(row) > 3 else {}
        f = fit(d, txt, size, W - 60)
        fs = f.size
        if opt.get("banner"):
            w = d.textlength(txt, font=f) + 60
            d.polygon([(14, y + fs * 0.1 + 8), (14 + w, y + fs * 0.1 - 4), (22 + w, y + fs * 1.1 - 6), (8, y + fs * 1.1 + 6)],
                      fill=opt["banner"])
        x, base = 36, y + fs
        for part in re.split(r"(\d+)", txt):
            if not part:
                continue
            big_num = part.isdigit() and opt.get("num_scale", 1.0) != 1.0
            pf = ImageFont.truetype(f.path, int(fs * opt["num_scale"])) if big_num else f
            d.text((x, base), part, font=pf, fill=color, stroke_width=sw, stroke_fill="black", anchor="ls")
            x += d.textlength(part, font=pf)
        y += int(size * cfg.get("line_gap", 1.02))
    canvas.save(out, quality=95)


def main():
    doc_p, bg_p, out, cfg_p = sys.argv[1:5]
    cfg = json.loads(Path(cfg_p).read_text(encoding="utf-8"))
    if cfg.get("layout") == "before_after":  # 배경 이미지 인자는 쓰지 않는다
        return before_after(doc_p, out, cfg)
    text_left = cfg.get("layout") == "text_left"  # 원장님 오른쪽, 글자는 전부 왼쪽 단에
    canvas = Image.new("RGB", (W, H), "white")
    # 흐리고 밝게 만든 관련 장면 (원장님 반대편)
    bg = Image.open(bg_p).convert("RGB")
    bg = bg.resize((int(bg.width * H / bg.height), H))
    x0 = cfg.get("bg_x", 0)
    bg = bg.crop((x0, 0, x0 + 760, H)).filter(ImageFilter.GaussianBlur(cfg.get("bg_blur", 5)))
    if cfg.get("bg_wash", True):  # 흐리고 하얗게 (글자가 검은 테두리 없이도 읽히게)
        bg = Image.blend(ImageEnhance.Brightness(bg).enhance(1.45), Image.new("RGB", bg.size, "white"), 0.45)
    else:  # 장면을 살린다 (두꺼운 검은 테두리 글자와 함께, 2026-11-02 고성과 썸네일 참고)
        bg = ImageEnhance.Brightness(bg).enhance(cfg.get("bg_bright", 0.9))
    canvas.paste(bg, (0, 0) if text_left else (W - 760, 0))
    # 원장님 (배경 쪽 가장자리를 흰 배경으로 부드럽게)
    doc = Image.open(doc_p).convert("RGB").crop(tuple(cfg.get("doc_crop", [660, 260, 1370, 1060]))).resize((640, 720))
    doc = ImageEnhance.Brightness(doc).enhance(1.08)
    if cfg.get("spots"):
        doc = even_tone(doc, cfg["spots"])
    if cfg.get("beauty"):
        doc = beautify(doc, cfg.get("beauty_strength", 1.0))
    if cfg.get("doc_bg") and cfg.get("doc_mask"):  # 원장님만 오려서 뒤에 관련 장면을 은은하게 (2026-11-02)
        box = tuple(cfg.get("doc_crop", [660, 260, 1370, 1060]))
        pm = Image.open(cfg["doc_mask"]).convert("L").crop(box).resize((640, 720))
        sc = Image.open(cfg["doc_bg"]).convert("RGB")
        sc = sc.resize((int(sc.width * 720 / sc.height), 720))
        bx = cfg.get("doc_bg_x", (sc.width - 640) // 2)
        sc = sc.crop((bx, 0, bx + 640, 720)).filter(ImageFilter.GaussianBlur(cfg.get("doc_bg_blur", 6)))
        sc = Image.blend(ImageEnhance.Brightness(sc).enhance(1.1), Image.new("RGB", sc.size, "white"), cfg.get("doc_bg_wash", 0.35))
        sc.paste(doc, (0, 0), pm)
        doc = sc
    mask = Image.new("L", doc.size, 255)
    md = ImageDraw.Draw(mask)
    for i in range(130):
        x = i if text_left else 639 - i
        md.line([(x, 0), (x, H)], fill=int(255 * i / 130))
    canvas.paste(doc, (W - 640, 0) if text_left else (0, 0), mask)
    d = ImageDraw.Draw(canvas)

    def text(xy, s, font, fill, stroke, sw, anchor="la"):
        d.text(xy, s, font=font, fill=fill, stroke_width=sw, stroke_fill=stroke, anchor=anchor)

    pen = ImageFont.truetype(PEN, 50)
    if text_left:
        col = cfg.get("col_w", 760)
        y = 34
        for s in cfg.get("hand", []):
            text((44, y), s, pen, "#111111", "white", 3)
            y += 50
        y += 10
        kf = ImageFont.truetype(AGGRO, 58)
        for s in cfg["keyword"]:
            text((44, y), s, kf, "#F0384A", "white", 9)
            y += 72
        big = cfg["big"]  # [(문구, 색, 테두리색)] 줄마다
        size = cfg.get("big_size", 112)
        lh = int(size * 1.05)
        total = sum(int((r[3] if len(r) > 3 else {}).get("size", size) * cfg.get("line_gap", 1.05)) for r in big)
        y = max(y + 14, H - cfg.get("bottom", 24) - total)
        sw = cfg.get("big_stroke", 13)
        for row in big:
            s, color = row[0], row[1]
            stroke = row[2] if len(row) > 2 else "black"
            opt = row[3] if len(row) > 3 else {}
            f = fit(d, s, opt.get("size", size), col - 60)
            fs = f.size
            if opt.get("banner"):  # 글자 뒤 비스듬한 띠
                n = opt.get("banner_lines", 1)  # 여러 줄을 한 띠로 (다음 줄 글자 폭까지 덮는다)
                w = max(d.textlength(r[0], font=fit(d, r[0], size, col - 60)) for r in big[big.index(row):big.index(row) + n]) + 70
                top, bot = y + fs * 0.08, y + fs * 0.07 + int(size * cfg.get("line_gap", 1.05)) * (n - 1) + fs * 1.05
                d.polygon([(14, top + 10), (14 + w, top - 6), (24 + w, bot - 8), (8, bot + 6)], fill=opt["banner"])
            ns = opt.get("num_scale", 1.0)
            if ns != 1.0:  # 숫자만 크게 (밑줄 맞춤)
                x, base = 40, y + fs
                for part in re.split(r"(\d+)", s):
                    if not part:
                        continue
                    pf = ImageFont.truetype(f.path, int(fs * ns)) if part.isdigit() else f
                    text((x, base), part, pf, opt.get("num_color", color) if part.isdigit() else color, stroke, sw, "ls")
                    x += d.textlength(part, font=pf)
            else:
                text((40, y), s, f, color, stroke, sw)
            y += int(opt.get("size", size) * cfg.get("line_gap", 1.05))
    else:
        kf = ImageFont.truetype(AGGRO, 66)
        for i, s in enumerate(cfg["keyword"]):
            text((960, 150 + i * 84), s, kf, "#F0384A", "white", 10, "ma")
        for i, s in enumerate(cfg.get("hand", [])):
            text((40, 30 + i * 52), s, pen, "#111111", "white", 3)
        f1 = fit(d, cfg["line1"], 112, W - 80)
        f2 = fit(d, cfg["line2"], 112, W - 80)
        text((W // 2, 452), cfg["line1"], f1, "#FFF200", "black", 12, "ma")
        text((W // 2, 584), cfg["line2"], f2, "white", "black", 12, "ma")
    canvas.save(out, quality=95)


if __name__ == "__main__":
    main()
