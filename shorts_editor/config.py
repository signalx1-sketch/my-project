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
    layout: str = "blur"           # blur: 흐린 배경 + 원본 전체 / crop: 세로로 꽉 차게 자르기
    use_ai: bool = True            # Claude로 구간·문구 선정 (API 키 없으면 자동 분석으로 대체)
    transcribe: bool = True        # 음성 인식(자막)
    language: str | None = "ko"
    whisper_model: str = os.environ.get("WHISPER_MODEL", "small")
    cut_silence: bool = True       # 말 없는 구간 잘라내기(점프컷)
    teaser: bool = True            # 클립 속 하이라이트를 맨 앞에 미리보기로 붙이기
    zoom_punch: bool = True        # 컷마다 살짝 줌인/아웃
    progress_bar: bool = True      # 하단 진행바
    font: str = "Black Han Sans"

    @classmethod
    def from_dict(cls, d: dict) -> "Options":
        fields = cls.__dataclass_fields__
        return cls(**{k: v for k, v in d.items() if k in fields})

    def to_dict(self) -> dict:
        return asdict(self)
