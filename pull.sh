#!/usr/bin/env bash
# pull.sh - 최신 코드를 받아오고 환경을 맞춘다.
# 사용법:  bash pull.sh
set -u

REPO_RAW="https://raw.githubusercontent.com/Harin-Yang/math-workbook-api/main"
WORKDIR="$HOME/mathocr"
FILES=(
  "pull.sh"
  "scripts/stage0.py"
  "scripts/dump_textlayer.py"
  "scripts/triage_samples.py"
  "scripts/run.sh"
)

mkdir -p "$WORKDIR/scripts"
cd "$WORKDIR" || exit 1

echo "== 코드 동기화 =="
for f in "${FILES[@]}"; do
  if curl -fsSL "$REPO_RAW/$f?$(date +%s)" -o "$f.tmp"; then
    mv "$f.tmp" "$f"
    echo "  OK   $f"
  else
    rm -f "$f.tmp"
    echo "  SKIP $f (없음)"
  fi
done
chmod +x scripts/*.sh 2>/dev/null

echo
echo "== 파이썬 환경 =="
if [ ! -d venv ]; then
  echo "  venv 생성"
  python3 -m venv venv
fi
# shellcheck disable=SC1091
source venv/bin/activate
pip install -q --upgrade pip
pip install -q requests pypdf pillow
echo "  requests / pypdf / pillow 준비됨"

echo
echo "== 샘플 링크 =="
[ -d "$WORKDIR/samples/테스트자료_스캔본" ] && \
  ln -sfn "$WORKDIR/samples/테스트자료_스캔본" "$WORKDIR/s_scan" && echo "  s_scan  -> $(ls s_scan | wc -l)개"
[ -d "$WORKDIR/samples/테스트자료_텍스트레이어" ] && \
  ln -sfn "$WORKDIR/samples/테스트자료_텍스트레이어" "$WORKDIR/s_text" && echo "  s_text  -> $(ls s_text | wc -l)개"

echo
echo "== API 키 =="
if [ -f "$WORKDIR/.env" ]; then
  # shellcheck disable=SC1091
  set -a; source "$WORKDIR/.env"; set +a
fi
if [ -n "${MATHPIX_APP_KEY:-}" ]; then
  echo "  설정됨"
else
  echo "  없음. 아래를 실행하세요 (한 번만):"
  echo
  echo "    cat > ~/mathocr/.env << 'EOF'"
  echo "    MATHPIX_APP_ID=발급받은_id"
  echo "    MATHPIX_APP_KEY=발급받은_key"
  echo "    EOF"
fi

echo
echo "동기화 완료. 다음 명령:"
echo "  bash scripts/run.sh"
