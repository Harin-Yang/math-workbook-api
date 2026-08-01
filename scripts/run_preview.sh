#!/usr/bin/env bash
# run_preview.sh - 추출 결과를 2단 조판 HTML 로 만든다. Mathpix 호출 없음 = 무료.
# 사용법:  bash scripts/run_preview.sh [파일명일부]
set -u
WORKDIR="$HOME/mathocr"
cd "$WORKDIR" || exit 1
# shellcheck disable=SC1091
source venv/bin/activate

FILTER="${1:-}"
OUT="PREVIEW.html"

if [ -n "$FILTER" ]; then
  python3 scripts/preview.py ./stage0_out "$OUT" --file "$FILTER" || exit 1
else
  python3 scripts/preview.py ./stage0_out "$OUT" || exit 1
fi

SIZE=$(du -h "$OUT" | cut -f1)
echo
echo "================================================================"
echo " 만들어진 파일: $WORKDIR/$OUT  ($SIZE)"
echo
echo " 내 PC 에서 아래를 실행해 내려받은 뒤 브라우저로 여세요:"
echo
echo "   scp root@$(hostname -I | awk '{print $1}'):~/mathocr/$OUT ."
echo
echo "================================================================"
