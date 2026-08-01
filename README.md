# math-workbook-api

PDF 문제집에서 문제만 추출해 2단 조판 문서로 변환하는 파이프라인.

## 현재 단계

**0단계 — Mathpix 실측.** 처리 시간·신뢰도·`lines.json` 구조를 측정해 판정 룰 설계 근거를 확보한다.

## 서버에서 쓰는 법

### 최초 1회

```bash
mkdir -p ~/mathocr && cd ~/mathocr
curl -sO https://raw.githubusercontent.com/Harin-Yang/math-workbook-api/main/pull.sh
bash pull.sh
```

API 키를 등록한다.

```bash
cat > ~/mathocr/.env << 'EOF'
MATHPIX_APP_ID=발급받은_id
MATHPIX_APP_KEY=발급받은_key
EOF
```

### 이후 매번

```bash
cd ~/mathocr && bash pull.sh && bash scripts/run.sh
```

`pull.sh`가 최신 코드를 받아오고, `run.sh`가 측정을 돌린 뒤 리포트를 화면에 출력한다.

## 폴더 구조

```
~/mathocr/
├── .env                  API 키 (커밋 안 됨)
├── pull.sh               코드 동기화
├── scripts/
│   ├── stage0.py         0단계 측정 + 리포트
│   ├── run.sh            실행 래퍼
│   ├── dump_textlayer.py 텍스트레이어 진단
│   └── triage_samples.py 샘플 선별
├── samples/
│   ├── 테스트자료_스캔본/
│   └── 테스트자료_텍스트레이어/
├── s_scan -> samples/테스트자료_스캔본
├── s_text -> samples/테스트자료_텍스트레이어
└── stage0_out/
    ├── REPORT.md         측정 리포트
    └── runs/<파일명>/     원본 응답 일체
```

## 확정된 사실

| 항목 | 결론 |
|---|---|
| 산출물 형식 | DOCX (한/글 편집 가능) |
| 조판 | 좌우 2단 |
| OCR | Mathpix `v3/pdf` + SSE 스트리밍 |
| 텍스트레이어 활용 | **불가**. 수식 깨짐·읽기 순서 붕괴 확인 |
| 서버 | Vultr 2vCPU / 4GB / 80GB, Ubuntu 24.04, 서울 |
| 처리 방식 | 비동기 (큐 + 워커) |
| 페이지 단가 | Mathpix $0.005/p |

## 판정 목표

| 지표 | 목표 |
|---|---|
| 미탐지 누락 | 0% (누락 발생 시 반드시 경고 표시) |
| 오검출 | 5% 미만 |
| 그래프 오첨부 | 0% (애매하면 첨부하지 않음) |
