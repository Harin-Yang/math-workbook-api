#!/usr/bin/env bash
# pull.sh - 최신 코드를 받아오고 환경을 맞춘다.
# 사용법:  bash pull.sh
#
# 자기 자신이 갱신되면 새 버전으로 한 번 다시 실행한다.
# (파일 목록이 바뀌었을 때 두 번 돌려야 하는 문제를 없애기 위함)
set -u

REPO_RAW="https://raw.githubusercontent.com/Harin-Yang/math-workbook-api/main"
WORKDIR="$HOME/mathocr"
FILES=(
  "pull.sh"
  "scripts/stage0.py"
  "scripts/analyze.py"
  "scripts/run.sh"
  "scripts/run_analyze.sh"
)

mkdir -p "$WORKDIR/scripts"
cd "$WORKDIR" || exit 1

# ---- 1) 자기 자신 먼저 갱신 ----
SELF_RELOADED="${PULL_SH_RELOADED:-0}"
if [ "$SELF_RELOADED" = "0" ]; then
  OLD_SUM=""
  [ -f pull.sh ] && OLD_SUM=$(md5sum pull.sh | cut -d' ' -f1)
  if curl -fsSL "$REPO_RAW/pull.sh?$(date +%s)" -o pull.sh.tmp 2>/dev/null; then
    NEW_SUM=$(md5sum pull.sh.tmp | cut -d' ' -f1)
    mv pull.sh.tmp pull.sh
    if [ "$OLD_SUM" != "$NEW_SUM" ]; then
      echo "== pull.sh 갱신됨. 새 버전으로 재실행 =="
      echo
      PULL_SH_RELOADED=1 exec bash pull.sh
    fi
  else
    rm -f pull.sh.tmp
  fi
fi

# ---- 2) 나머지 파일 ----
echo "== 코드 동기화 =="
for f in "${FILES[@]}"; do
  [ "$f" = "pull.sh" ] && continue
  if curl -fsSL "$REPO_RAW/$f?$(date +%s)" -o "$f.tmp" 2>/dev/null; then
    mv "$f.tmp" "$f"
    echo "  OK   $f"
  else
    rm -f "$f.tmp"
    echo "  SKIP $f (저장소에 없음)"
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
  echo "  없음. ~/mathocr/.env 파일에 아래 두 줄을 넣으세요:"
  echo "    MATHPIX_APP_ID=..."
  echo "    MATHPIX_APP_KEY=..."
fi

echo
echo "동기화 완료. 명령:"
echo "  bash scripts/run.sh          # Mathpix 측정 (과금)"
echo "  bash scripts/run_analyze.sh  # 기존 결과 재분석 (무료)"
