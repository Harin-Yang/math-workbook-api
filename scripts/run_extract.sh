#!/usr/bin/env bash
# run_extract.sh - 문제 추출을 실행하고 결과를 출력한다. Mathpix 호출 없음 = 무료.
set -u
WORKDIR="$HOME/mathocr"
cd "$WORKDIR" || exit 1
# shellcheck disable=SC1091
source venv/bin/activate

STAGE="${1:-./stage0_out}"
OUT="${2:-./EXTRACT.md}"

python3 scripts/extract.py "$STAGE" "$OUT" || exit 1

echo
echo "================================================================"
echo " 아래 전체를 복사해서 전달하세요"
echo "================================================================"
echo
cat "$OUT"
