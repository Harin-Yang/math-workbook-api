#!/usr/bin/env bash
# run_grade.sh - 기준 파일과 추출 결과를 대조해 점수를 낸다. Mathpix 호출 없음 = 무료.
#
# 사용법:
#   bash scripts/run_grade.sh --list
#       stage0_out/runs 안의 폴더 이름을 보여준다. 아래 <필터>에 쓸 조각을 여기서 고른다.
#
#   bash scripts/run_grade.sh <기준.pdf> <필터> [태그] [메모]
#       <필터>  run 폴더 이름에 들어 있는 글자. 쉼표로 여러 개.
#       [태그]  점수 이력에 남길 이름. 생략하면 기준 파일 이름.
#       [메모]  이번 실행이 어떤 룰인지 적어 두는 칸. 예: "v3 원본"
#
# 예:
#   bash scripts/run_grade.sh "samples/기준/기하.pdf" "이차곡선,벡터,공간도형" 기하 "v3 원본"
set -u
WORKDIR="$HOME/mathocr"
cd "$WORKDIR" || exit 1
# shellcheck disable=SC1091
source venv/bin/activate

STAGE="${STAGE:-./stage0_out}"
OUTDIR="${OUTDIR:-./grade_out}"

if [ "${1:-}" = "--list" ]; then
  python3 scripts/grade.py --list --stage "$STAGE"
  exit $?
fi

REF="${1:-}"
FILTER="${2:-}"
TAG="${3:-}"
NOTE="${4:-}"

if [ -z "$REF" ]; then
  echo "기준 파일 PDF 경로가 필요합니다."
  echo "  bash scripts/run_grade.sh --list                     # run 폴더 확인"
  echo "  bash scripts/run_grade.sh <기준.pdf> <필터> [태그] [메모]"
  exit 1
fi

if [ ! -f "$REF" ]; then
  echo "기준 파일이 없습니다: $REF"
  exit 1
fi

ARGS=(--ref "$REF" --stage "$STAGE" --outdir "$OUTDIR")

if [ -n "$FILTER" ]; then
  OLDIFS="$IFS"
  IFS=','
  for part in $FILTER; do
    part="$(echo "$part" | sed 's/^ *//; s/ *$//')"
    [ -n "$part" ] && ARGS+=(--file "$part")
  done
  IFS="$OLDIFS"
fi

[ -n "$TAG" ] && ARGS+=(--tag "$TAG")
[ -n "$NOTE" ] && ARGS+=(--note "$NOTE")

python3 scripts/grade.py "${ARGS[@]}" || exit 1

NAME="${TAG:-$(basename "${REF%.*}")}"
OUT="$OUTDIR/GRADE_${NAME}.md"

echo
echo "================================================================"
echo " 아래 전체를 복사해서 전달하세요"
echo "================================================================"
echo
cat "$OUT"
