#!/usr/bin/env bash
# run_docx.sh - 추출한 문제를 좌우 2단 워드 문서로 만든다. Mathpix 호출 없음 = 무료.
#
# 사용법:
#   bash scripts/run_docx.sh <run폴더필터> [제목] [답쓸빈줄수]
#
# 예:
#   bash scripts/run_docx.sh "기하" "기하 문제집" 3
#   bash scripts/run_docx.sh "확률과통계" "확률과 통계 문제집" 5
set -u
WORKDIR="$HOME/mathocr"
cd "$WORKDIR" || exit 1
# shellcheck disable=SC1091
source venv/bin/activate

FILTER="${1:-}"
TITLE="${2:-추출 문제집}"
LINES="${3:-3}"

if [ -z "$FILTER" ]; then
  echo "run 폴더 필터가 필요합니다."
  echo "  bash scripts/run_grade.sh --list        # 폴더 이름 확인"
  echo "  bash scripts/run_docx.sh <필터> [제목] [답쓸빈줄수]"
  exit 1
fi

NAME="$(echo "$TITLE" | tr ' ' '_')"
OUT="out/${NAME}.docx"
mkdir -p out

ARGS=(--out "$OUT" --title "$TITLE" --answer-lines "$LINES")

OLDIFS="$IFS"
IFS=','
for part in $FILTER; do
  part="$(echo "$part" | sed 's/^ *//; s/ *$//')"
  [ -n "$part" ] && ARGS+=(--file "$part")
done
IFS="$OLDIFS"

python3 scripts/make_docx.py "${ARGS[@]}" || exit 1

echo
echo "================================================================"
echo " 내 PC 로 받아가려면 PowerShell 에서 아래 한 줄을 실행하세요"
echo "================================================================"
echo
echo "scp root@158.247.240.59:'~/mathocr/$OUT' \$env:USERPROFILE\\Downloads\\"
