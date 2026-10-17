#!/usr/bin/env bash
# 지마켓산스 볼드를 fonts/ 에 설치 (npm 패키지의 WOFF → OTF 변환)
# 지마켓산스는 G마켓이 무료 배포하는 폰트입니다. 라이선스: https://corp.gmarket.com/fonts/
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f fonts/GmarketSansBold.otf ] && { echo "이미 설치됨: fonts/GmarketSansBold.otf"; exit 0; }
tmp=$(mktemp -d)
(cd "$tmp" && npm pack --silent @noonnu/gmarketsansbold >/dev/null && tar xzf noonnu-gmarketsansbold-*.tgz)
python3 -m pip install -q fonttools >/dev/null 2>&1 || true
python3 - "$tmp/package/GmarketSansBold.woff" fonts/GmarketSansBold.otf <<'PY'
import sys
from fontTools.ttLib import TTFont
f = TTFont(sys.argv[1]); f.flavor = None
# 웹폰트 버전에는 공백 문자 매핑과 패밀리 이름이 빠져 있어 보충 (영상 자막 렌더러가 폰트를 찾을 수 있게)
blank = "KR1.1" if "KR1.1" in f.getGlyphOrder() else None
for t in f["cmap"].tables:
    if t.isUnicode() and blank:
        t.cmap.setdefault(0x20, blank)
        t.cmap.setdefault(0xA0, blank)
name = f["name"]
for pid, eid, lid in ((3, 1, 0x409), (1, 0, 0)):
    name.setName("GmarketSansBold", 1, pid, eid, lid)
    name.setName("GmarketSansBold", 4, pid, eid, lid)
f.save(sys.argv[2])
PY
rm -rf "$tmp"
echo "설치 완료: fonts/GmarketSansBold.otf"
