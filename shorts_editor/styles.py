"""상단 문구·자막 서체 설정 (채널 톤앤매너)."""
from dataclasses import dataclass
from functools import lru_cache

from .config import FONTS_DIR

# ASS에 쓰는 폰트 이름 → fonts/ 안의 파일
FONT_FILES = {
    "GmarketSansBold": "GmarketSansBold.otf",
    "Black Han Sans": "BlackHanSans.ttf",
}
FALLBACK_FONT = "Black Han Sans"


@dataclass
class TextStyle:
    header_font: str = "GmarketSansBold"
    header_pt: float = 350          # 상단 문구 크기 (pt_scale을 곱해 화면 픽셀로 변환, 화면 폭에 맞게 자동 축소)
    header_color: str = "#FFE400"   # 비우면 [대괄호]만 노란색인 2톤
    header_bar: bool = True         # 상단 검은 바
    caption_font: str = "GmarketSansBold"
    caption_pt: float = 250
    caption_color: str = "#FFFFFF"
    caption_italic: bool = True     # 자막을 오른쪽으로 눕힘
    caption_highlight: bool = False  # 강조 단어 색 바꾸기
    highlight_color: str = "#FFE400"
    pt_scale: float = 0.3           # pt → 1080×1920 화면 픽셀 (350pt → 105px)

    def resolved(self) -> "TextStyle":
        """폰트 파일이 없으면 기본 폰트로 대체."""
        s = TextStyle(**self.__dict__)
        if not font_path(s.header_font):
            s.header_font = FALLBACK_FONT
        if not font_path(s.caption_font):
            s.caption_font = FALLBACK_FONT
        return s


def font_path(name: str):
    f = FONTS_DIR / FONT_FILES.get(name, f"{name}.ttf")
    return f if f.exists() else None


def ass_color(hex_color: str) -> str:
    h = hex_color.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H00{b}{g}{r}&".upper()


@lru_cache(maxsize=16)
def _pil_font(name: str, px: int):
    from PIL import ImageFont
    p = font_path(name)
    return ImageFont.truetype(str(p), px) if p else None


def text_width(name: str, px: float, text: str) -> float:
    f = _pil_font(name, 100)
    if f is None:
        return len(text) * px * 0.95
    return f.getlength(text) * px / 100
