#!/bin/bash
# 영상 편집 도구를 설치한다. 클라우드 컨테이너는 세션마다 새로 만들어져서 설치한 도구가 사라지므로
# 새 세션에서 한 번 돌린다 (환경의 Setup script나 세션 시작 훅에 등록해 두면 자동).
# 이미 설치돼 있으면 건너뛰고, 하나가 실패해도 나머지는 계속 설치한다.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TOOLS="$HOME/tools"
HF_VERSION="0.8.191"
mkdir -p "$TOOLS"
export DO_NOT_TRACK=1 HYPERFRAMES_NO_TELEMETRY=1

step() { echo "[setup] $*" >&2; }

step "파이썬 패키지 (음성 인식, 슬라이드 읽기, 폰트 변환)"
pip install -q -r "$ROOT/requirements.txt" >&2 || step "pip 설치 실패"

if ! command -v soffice >/dev/null || ! command -v pdftoppm >/dev/null; then
  step "LibreOffice / poppler (슬라이드 그리기)"
  (apt-get update -qq && apt-get install -y -qq libreoffice-impress poppler-utils) >&2 || step "LibreOffice 설치 실패"
fi

step "HyperFrames $HF_VERSION + 렌더용 크롬 + 스킬"
(cd "$TOOLS" && npx -y "hyperframes@$HF_VERSION" browser ensure) >&2 || step "HyperFrames 크롬 준비 실패"
(cd "$TOOLS" && npx -y "hyperframes@$HF_VERSION" skills update) >&2 || step "HyperFrames 스킬 설치 실패"

if [ ! -f "$ROOT/assets/vendor/gsap.min.js" ]; then
  step "GSAP (CDN이 막혀 있어 npm에서 받는다)"
  tmp=$(mktemp -d)
  (cd "$tmp" && npm pack gsap@3.14.2 --silent && tar xzf gsap-3.14.2.tgz package/dist/gsap.min.js \
    && mkdir -p "$ROOT/assets/vendor" && cp package/dist/gsap.min.js "$ROOT/assets/vendor/") >&2 || step "GSAP 실패"
  rm -rf "$tmp"
fi

step "Remotion"
(cd "$ROOT/remotion" && npm install --silent --no-audit --no-fund) >&2 || step "Remotion 설치 실패"

if [ ! -d "$TOOLS/OpenMontage/.git" ]; then
  step "OpenMontage"
  git clone --depth 1 https://github.com/calesthio/OpenMontage "$TOOLS/OpenMontage" >&2 || step "OpenMontage 받기 실패"
fi
pip install -q pyyaml pydantic jsonschema python-dotenv >&2 || step "OpenMontage 의존성 실패"

step "끝"
