#!/usr/bin/env bash
# run.sh - 0단계 측정을 실행하고 리포트를 출력한다.
# 사용법:  bash scripts/run.sh  [대상폴더]  [출력폴더]
set -u

WORKDIR="$HOME/mathocr"
cd "$WORKDIR" || exit 1

TARGET="${1:-./s_scan}"
OUT="${2:-./stage0_out}"

# shellcheck disable=SC1091
source venv/bin/activate

if [ -f "$WORKDIR/.env" ]; then
  set -a; source "$WORKDIR/.env"; set +a
fi

if [ -z "${MATHPIX_APP_KEY:-}" ]; then
  echo "MATHPIX_APP_KEY 가 없습니다. ~/mathocr/.env 를 만드세요."
  exit 1
fi

if [ ! -d "$TARGET" ]; then
  echo "대상 폴더가 없습니다: $TARGET"
  exit 1
fi

echo "대상: $TARGET"
echo "출력: $OUT"
echo

python3 scripts/stage0.py "$TARGET" "$OUT" 2>&1 | tee "$OUT.log"

echo
echo "================================================================"
echo " 아래 전체를 복사해서 전달하세요"
echo "================================================================"
echo
cat "$OUT/REPORT.md" 2>/dev/null || echo "리포트가 생성되지 않았습니다. $OUT.log 를 확인하세요."
