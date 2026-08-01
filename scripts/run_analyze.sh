#!/usr/bin/env bash
# run_analyze.sh - 이미 받아둔 lines.json 을 재분석한다. Mathpix 호출 없음 = 비용 0원.
set -u
WORKDIR="$HOME/mathocr"
cd "$WORKDIR" || exit 1
# shellcheck disable=SC1091
source venv/bin/activate

STAGE="${1:-./stage0_out}"
OUT="${2:-./ANALYSIS.md}"

python3 scripts/analyze.py "$STAGE" "$OUT" || exit 1

echo
echo "================================================================"
echo " 아래 전체를 복사해서 전달하세요"
echo "================================================================"
echo
cat "$OUT"
