"""자막 폰트를 준비한다.

기본 자막 폰트는 샌드박스 어그로체 M(SB Aggro Medium). 무료 폰트지만 저장소에는 넣지 않고
처음 실행할 때 눈누(noonnu) 웹폰트 저장소에서 받아 assets/fonts에 둔다. 받을 수 없으면 Pretendard를 쓴다.
"""
import urllib.request
from pathlib import Path

FONTS_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"

AGGRO_FILE = "SBAggroM.woff"
AGGRO_URL = "https://raw.githubusercontent.com/projectnoonnu/noonfonts_2108/main/SBAggroM.woff"
AGGRO = ("SB Aggro Medium", "SB Aggro Medium")          # (자막용, 제목용)
PRETENDARD = ("Pretendard ExtraBold", "Pretendard ExtraBold")


def caption_fonts() -> tuple[str, str]:
    """(자막 폰트 이름, 큰 글씨 폰트 이름). 어그로체가 없으면 받아 보고, 실패하면 Pretendard."""
    path = FONTS_DIR / AGGRO_FILE
    if not any(FONTS_DIR.glob("SBAggroM.*")):  # 직접 넣은 .ttf/.otf도 쓴다
        try:
            print("  자막 폰트(어그로체 M) 받는 중...")
            with urllib.request.urlopen(AGGRO_URL, timeout=30) as r:
                data = r.read()
            if not data.startswith(b"wOFF"):
                raise ValueError("폰트 파일이 아님")
            path.write_bytes(data)
        except Exception as e:  # 네트워크가 막혀 있어도 편집은 계속한다
            print(f"  어그로체를 받지 못해 Pretendard로 진행합니다 ({e}). "
                  f"직접 받아서 {path} 에 두면 다음부터 씁니다.")
            return PRETENDARD
    return AGGRO
