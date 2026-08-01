#!/usr/bin/env bash
# pull.sh - 최신 코드를 받아오고 환경을 맞춘다.
# 사용법:  bash pull.sh
#
# 주의: 이 스크립트는 자기 자신을 덮어쓴다.
# bash 는 파일을 조금씩 읽어가며 실행하므로, 실행 도중 파일이 바뀌면
# 엉뚱한 위치부터 읽어 문법 오류가 난다.
# 그래서 전체를 main() 함수로 감싸고, 호출과 exit 를 한 줄에 둔다.
# 함수 정의는 통째로 읽히고 exit 도 같은 줄에서 읽히므로
# 그 뒤에 파일이 바뀌어도 안전하다.
set -u

main() {
  local OWNER="Harin-Yang"
  local REPO="math-workbook-api"
  local WORKDIR="$HOME/mathocr"
  local TARBALL="https://codeload.github.com/$OWNER/$REPO/tar.gz/refs/heads/main"

  mkdir -p "$WORKDIR/scripts"
  cd "$WORKDIR" || exit 1

  echo "== 코드 동기화 =="
  local TMP
  TMP=$(mktemp -d)
  trap 'rm -rf "$TMP"' RETURN

  if ! curl -fsSL "$TARBALL" -o "$TMP/repo.tgz"; then
    echo "  실패: 저장소를 받지 못했습니다. 네트워크를 확인하세요."
    return 1
  fi

  if ! tar xzf "$TMP/repo.tgz" -C "$TMP" --strip-components=1; then
    echo "  실패: 압축 해제 오류"
    return 1
  fi

  local f
  for f in pull.sh \
           scripts/stage0.py scripts/analyze.py scripts/extract.py \
           scripts/run.sh scripts/run_analyze.sh scripts/run_extract.sh; do
    if [ -f "$TMP/$f" ]; then
      cp "$TMP/$f" "$f"
      echo "  OK   $f  ($(wc -l < "$f")줄)"
    else
      echo "  SKIP $f"
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
  if [ -d "$WORKDIR/samples/테스트자료_스캔본" ]; then
    ln -sfn "$WORKDIR/samples/테스트자료_스캔본" "$WORKDIR/s_scan"
    echo "  s_scan  -> $(ls s_scan | wc -l)개"
  fi
  if [ -d "$WORKDIR/samples/테스트자료_텍스트레이어" ]; then
    ln -sfn "$WORKDIR/samples/테스트자료_텍스트레이어" "$WORKDIR/s_text"
    echo "  s_text  -> $(ls s_text | wc -l)개"
  fi

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
  echo "  bash scripts/run_extract.sh   # 문제 추출 (무료)"
  echo "  bash scripts/run_analyze.sh   # 구조 분석 (무료)"
  echo "  bash scripts/run.sh           # Mathpix 측정 (과금)"
}

main "$@"; exit $?
