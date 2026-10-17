"""병원 비포앤애프터 사진을 쇼츠 중간에 끼워 넣는 카드 생성.

사진 폴더 구조 (before_after/ 아래):
    아토피/01_before.jpg, 01_after.jpg, 01.txt(선택: "치료 6개월" 같은 설명)
    지루성피부염/...
파일 이름은 "<번호>_before" / "<번호>_after" (또는 "_전" / "_후").
"""
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from .config import OUT_W, ROOT
from .styles import font_path

BA_DIR = ROOT / "before_after"
CATEGORIES = ["아토피", "지루성피부염", "주사피부염·홍조", "접촉성피부염", "모낭염·여드름", "기타"]
IMG_EXT = {".jpg", ".jpeg", ".png", ".webp"}
BEFORE_KEYS, AFTER_KEYS = ("before", "전"), ("after", "후")

CARD_W, CARD_H = OUT_W, 860
YELLOW, WHITE, GRAY = (255, 228, 0), (255, 255, 255), (170, 170, 170)


def find_pairs(category: str, base: Path = BA_DIR) -> list[dict]:
    """카테고리 폴더에서 (before, after, note) 쌍 목록."""
    folder = base / category
    if not folder.is_dir():
        return []
    groups: dict[str, dict] = {}
    singles = []
    for f in sorted(folder.iterdir()):
        if f.suffix.lower() not in IMG_EXT:
            continue
        m = re.match(r"(.+?)[_\- ]?(before|after|전|후)$", f.stem, re.I)
        if not m:  # 전·후가 한 장에 합쳐진 사진
            note = folder / f"{f.stem}.txt"
            singles.append({"id": f.stem, "image": f,
                            "note": note.read_text(encoding="utf-8").strip() if note.exists() else ""})
            continue
        key, kind = m.group(1), m.group(2).lower()
        g = groups.setdefault(key, {"id": key})
        g["before" if kind in BEFORE_KEYS else "after"] = f
    pairs = []
    for key, g in groups.items():
        if "before" in g and "after" in g:
            note = folder / f"{key}.txt"
            g["note"] = note.read_text(encoding="utf-8").strip() if note.exists() else ""
            pairs.append(g)
    return pairs + singles


def _font(px: int):
    p = font_path("GmarketSansBold") or font_path("Black Han Sans")
    return ImageFont.truetype(str(p), px)


def _photo(path: Path | None, size: tuple[int, int], label: str) -> Image.Image:
    if path and Path(path).exists():
        img = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
        return ImageOps.fit(img, size, Image.LANCZOS)
    # 사진이 아직 없을 때 자리 표시
    img = Image.new("RGB", size, (70, 70, 70))
    d = ImageDraw.Draw(img)
    d.text((size[0] // 2, size[1] // 2), f"{label}\n사진 자리", font=_font(44), fill=(200, 200, 200),
           anchor="mm", align="center")
    return img


def make_photo(image: Path, out: Path, box: tuple[int, int] = (OUT_W, 860), min_h: int = 620) -> Path:
    """전·후가 합쳐진 사진 한 장을 영상 자리에 꽉 차게 (레퍼런스 방식).
    사진이 영상보다 낮으면 검은 바탕을 깔아 뒤의 영상(원본 자막 등)이 보이지 않게 함."""
    img = ImageOps.exif_transpose(Image.open(image)).convert("RGB")
    scale = min(box[0] / img.width, box[1] / img.height)
    img = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
    canvas = Image.new("RGB", (box[0], max(img.height, min_h)), (0, 0, 0))
    canvas.paste(img, ((canvas.width - img.width) // 2, (canvas.height - img.height) // 2))
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out)
    return out


def make_card(before: Path | None, after: Path | None, out: Path, *, title: str = "실제 치료 전·후",
              note: str = "", disclaimer: str = "※ 개인에 따라 결과는 다를 수 있습니다") -> Path:
    card = Image.new("RGBA", (CARD_W, CARD_H), (0, 0, 0, 0))
    d = ImageDraw.Draw(card)
    d.rounded_rectangle((20, 0, CARD_W - 20, CARD_H), radius=36, fill=(12, 12, 12, 235))
    d.text((CARD_W // 2, 62), title, font=_font(58), fill=YELLOW, anchor="mm")

    pw, ph, gap, top = 486, 620, 28, 120
    x0 = (CARD_W - pw * 2 - gap) // 2
    for i, (path, label, color) in enumerate([(before, "BEFORE", GRAY), (after, "AFTER", YELLOW)]):
        x = x0 + i * (pw + gap)
        card.paste(_photo(path, (pw, ph), label), (x, top))
        f = _font(36)
        tw = d.textlength(label, font=f)
        d.rounded_rectangle((x + 16, top + 16, x + 16 + tw + 36, top + 76), radius=12, fill=color)
        d.text((x + 34, top + 46), label, font=f, fill=(0, 0, 0), anchor="lm")
    y = top + ph + 52
    if note:
        d.text((CARD_W // 2, y), note, font=_font(44), fill=WHITE, anchor="mm")
        y += 50
    d.text((CARD_W // 2, min(y, CARD_H - 30)), disclaimer, font=_font(26), fill=GRAY, anchor="mm")
    out.parent.mkdir(parents=True, exist_ok=True)
    card.save(out)
    return out
