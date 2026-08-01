#!/usr/bin/env bash
# pull.sh - 최신 코드를 받아오고 환경을 맞춘다.
# 사용법:  bash pull.sh
#
# raw.githubusercontent.com 은 CDN 캐시 때문에 최대 5분간 옛 파일을 준다.
# 그래서 최신 커밋 해시를 먼저 알아낸 뒤, 해시가 박힌 주소로 받는다.
# 해시 주소는 절대 캐시되지 않으므로 항상 최신본이 온다.
set -u

OWNER="Harin-Yang"
REPO="math-workbook-api"
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

# ---- 최신 커밋 해시 ----
SHA=$(curl -fsSL "https://api.github.com/repos/$OWNER/$REPO/commits/main" \
      | grep -m1 '"sha"' | cut -d'"' -f4)

if [ -n "${SHA:-}" ]; then
  BASE="https://raw.githubusercontent.com/$OWNER/$REPO/$SHA"
  echo "== 커밋 ${SHA:0:8} =="
else
  BASE="https://raw.githubusercontent.com/$OWNER/$REPO/main"
  echo "== 커밋 확인 실패, main 기준 (캐시된 파일일 수 있음) =="
fi
echo

fetch() {  # fetch <경로>  -> 성공 0
  curl -fsSL "$BASE/$1" -o "$1.tmp" 2>/dev/null || return 1
  [ -s "$1.tmp" ] || { rm -f "$1.tmp"; return 1; }
  mv "$1.tmp" "$1"
}

# ---- 1) 자기 자신 먼저 ----
if [ "${PULL_SH_RELOADED:-0}" = "0" ]; then
  OLD=""
  [ -f pull.sh ] && OLD=$(md5sum pull.sh | cut -d' ' -f1)
  if fetch "pull.sh"; then
    NEW=$(md5sum pull.sh | cut -d' ' -f1)
    if [ "$OLD" != "$NEW" ]; then
      echo "pull.sh 갱신됨. 새 버전으로 재실행"
      echo
      PULL_SH_RELOADED=1 exec bash pull.sh
    fi
  fi
fi

# ---- 2) 나머지 ----
echo "== 코드 동기화 =="
for f in "${FILES[@]}"; do
  [ "$f" = "pull.sh" ] && continue
  if fetch "$f"; then
    echo "  OK   $f  ($(wc -l < "$f")줄)"
  else
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
