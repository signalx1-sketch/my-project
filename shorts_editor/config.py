import os
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FONTS_DIR = ROOT / "fonts"
DATA_DIR = Path(os.environ.get("SHORTS_DATA_DIR", ROOT / "data"))

OUT_W, OUT_H, OUT_FPS = 1080, 1920, 30


@dataclass
class Options:
    count: int = 3                 # 만들 쇼츠 개수
    min_len: float = 20.0          # 쇼츠 최소 길이(초)
    max_len: float = 45.0          # 쇼츠 최대 길이(초)
    layout: str = "black"          # black: 검은 배경 + 가운데 원본 / blur: 흐린 배경 / crop: 세로로 꽉 차게
    use_ai: bool = True            # Claude로 구간·문구 선정 (API 키 없으면 자동 분석으로 대체)
    transcribe: bool = True        # 음성 인식(자막)
    language: str | None = "ko"
    whisper_model: str = os.environ.get("WHISPER_MODEL", "small")
    cut_silence: bool = True       # 말 없는 구간 잘라내기(점프컷)
    teaser: bool = True            # 클립 속 하이라이트를 맨 앞에 미리보기로 붙이기
    zoom_punch: bool = False       # 컷마다 살짝 줌인/아웃 (기본 끔: 정신없다는 피드백)
    progress_bar: bool = False     # 하단 진행바
    header_style: str = "bar"      # bar: 상단 검은 바 / float: 배경 없이 외곽선 문구
    # 톤앤매너 (기본값: 더마허브 — 상단 지마켓산스 볼드 노랑 350pt, 자막 지마켓산스 볼드 이탤릭 흰색 250pt)
    header_font: str = "GmarketSansBold"
    header_pt: float = 350
    header_color: str = "#FBC600"  # 비우면 [대괄호]만 노란색
    caption_font: str = "GmarketSansBold"
    caption_pt: float = 250
    caption_color: str = "#FFFFFF"
    caption_italic: bool = True
    caption_highlight: bool = False
    pt_scale: float = 0.33         # pt → 화면 픽셀 배율 (레퍼런스 실측: 350pt → 116px, 250pt → 83px)
    crop_bottom: int = 0           # 원본 하단을 잘라낼 픽셀 수 (원본에 자막이 박혀 있을 때)
    cta_text: str = ""             # 마지막 3초 하단 문구 (예: "풀영상은 고정 댓글에서")
    related_text: str = "풀영상확인 ↓"  # 자막 아래 계속 떠 있는 연관 동영상 유도 문구 (비우면 없음)
    related_y: float = 0.794       # 그 문구의 세로 위치(화면 높이 비율). 0.895는 모바일 앱 제목·채널명에 가려져 올림
    photo_min_sec: float = 4.0     # 비포앤애프터 사진 최소 노출 시간

    @classmethod
    def from_dict(cls, d: dict) -> "Options":
        fields = cls.__dataclass_fields__
        return cls(**{k: v for k, v in d.items() if k in fields})

    def text_style(self):
        from .styles import TextStyle
        return TextStyle(header_font=self.header_font, header_pt=self.header_pt, header_color=self.header_color,
                         header_bar=self.header_style == "bar", caption_font=self.caption_font,
                         caption_pt=self.caption_pt, caption_color=self.caption_color,
                         caption_italic=self.caption_italic, caption_highlight=self.caption_highlight,
                         pt_scale=self.pt_scale)

    def to_dict(self) -> dict:
        return asdict(self)
