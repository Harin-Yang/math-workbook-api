#!/usr/bin/env python3
"""
llm_extract_test.py
실험: OCR 원문을 룰 없이 통째로 루나에게 넘겨 문제 추출을 시키면 어떤가.

방법
    쪽 텍스트를 4쪽 단위(1쪽 겹침)로 잘라 보낸다 — 문제가 쪽을 넘는 경우 대비.
    루나가 돌려준 문제 목록을 겹침 제거 후, 기존 채점기(judge)로 채점한다.
    토큰 사용량을 실측해 비용을 계산할 재료를 남긴다.

사용법
    OPENAI_API_KEY=... python3 scripts/llm_extract_test.py \
        "stage0_out/runs/<run>/result.lines.json" "refs/<기준>.pdf" <태그>
"""

import json
import os
import re
import sys
import time
import urllib.request
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import extract as EX               # noqa: E402
import grade as G                  # noqa: E402

MODEL = os.environ.get("LLM_FILTER_MODEL") or "gpt-5.6-luna"
CHUNK = 4          # 한 번에 보낼 쪽 수
OVERLAP = 1        # 겹칠 쪽 수

PROMPT = """수학 교과서를 OCR 로 읽은 원문이 쪽 번호와 함께 주어진다.
학생에게 직접 풀라고 내는 문제만 전부 골라, 각 문제의 전체 본문을
원문 그대로(수식 표기 \\( \\) 포함, 소문항 포함) 옮겨 적어라.

빼야 하는 것: 개념 설명·정의·공식 정리 칸, 예제의 풀이 과정, 단원 도입 글,
'~해 보자' 체의 탐구·활동·생각열기와 그 소문항, 차례, 머리말.
넣어야 하는 것: 문제·예제의 발문과 소문항 전체 (풀이는 빼고 발문만),
연습문제·단원 마무리 문제.

JSON 배열로만 답하라. 다른 말은 쓰지 마라.
형식: [{"page": 쪽번호(정수), "text": "문제 전체 본문"}]
문제가 하나도 없으면 []."""


def call(key, user_text):
    body = json.dumps({
        "model": MODEL,
        "messages": [{"role": "system", "content": PROMPT},
                     {"role": "user", "content": user_text}],
        "max_completion_tokens": 16000,
    }).encode()
    request = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=body, method="POST",
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=300) as response:
        data = json.loads(response.read())
    usage = data.get("usage", {})
    return (data["choices"][0]["message"]["content"] or "").strip(), usage


def main():
    lines_path, ref_pdf, tag = sys.argv[1], sys.argv[2], sys.argv[3]
    key = os.environ["OPENAI_API_KEY"]

    rows, _pw = EX.load(lines_path)
    pages = defaultdict(list)
    for ln in rows:
        t = EX.txt(ln)
        if t:
            pages[ln.get("_page") or 0].append(t)
    page_nums = sorted(pages)
    print(f"쪽 수 {len(page_nums)}, 글자 수 {sum(len(t) for ts in pages.values() for t in ts)}")

    # 쪽 묶음
    chunks = []
    i = 0
    while i < len(page_nums):
        chunks.append(page_nums[i:i + CHUNK])
        i += CHUNK - OVERLAP
    print(f"루나 호출 {len(chunks)}번 예정")

    problems = []
    tok_in = tok_out = 0
    for n, chunk in enumerate(chunks, 1):
        text = "\n\n".join(
            f"[{p}쪽]\n" + "\n".join(pages[p]) for p in chunk)
        try:
            answer, usage = call(key, text)
        except Exception as e:
            print(f"  {n}/{len(chunks)} 실패: {e}", file=sys.stderr)
            time.sleep(2)
            continue
        tok_in += usage.get("prompt_tokens", 0)
        tok_out += usage.get("completion_tokens", 0)
        answer = re.sub(r"^```(?:json)?|```$", "", answer.strip(), flags=re.M).strip()
        try:
            items = json.loads(answer)
        except json.JSONDecodeError:
            # 수식 역슬래시(\log 등)가 JSON 이스케이프를 깨는 경우 — 살려 읽는다
            repaired = re.sub(r'\\(?![\\/"bfnrtu])', r"\\\\", answer)
            try:
                items = json.loads(repaired)
            except json.JSONDecodeError:
                print(f"  {n}/{len(chunks)} JSON 아님 ({answer[:60]!r})", file=sys.stderr)
                continue
        for it in items:
            if isinstance(it, dict) and it.get("text"):
                problems.append({"page": it.get("page"), "text": str(it["text"])})
        print(f"  {n}/{len(chunks)} 완료 — 누적 문제 {len(problems)}", file=sys.stderr)

    # 겹침 제거 — 겹친 쪽에서 같은 문제가 두 번 온다. 뼈대 0.85+ 는 같은 문제.
    uniq = []
    seen_g = []
    for p in problems:
        g = G.grams(G.normalize(p["text"]))
        dup = False
        for g2 in seen_g:
            if g and g2:
                inter = len(g & g2)
                if inter and inter / min(len(g), len(g2)) >= 0.85:
                    dup = True
                    break
        if not dup:
            uniq.append(p)
            seen_g.append(g)
    print(f"겹침 제거: {len(problems)} -> {len(uniq)}")

    # 채점기 형식으로
    exts = [{"name": "LLM", "num": k + 1, "raw": None, "num_fixed": False,
             "kind": "문제", "file": tag, "page": p.get("page"),
             "x": None, "font": None, "head": p["text"][:90],
             "body": [], "lines": 1, "figs": [], "figs_guess": [],
             "reason": "llm", "text": p["text"]}
            for k, p in enumerate(uniq)]

    refd = G.load_reference(ref_pdf, None, False)
    refs = refd["problems"]
    ORDER_ANY = re.compile(r"시오|하라|하여라|[여아으]라[.．\s]|구하|답하|서술|증명|풀어|쓰라|[?？]|인가|는가")
    refs = [r for r in refs if ORDER_ANY.search(r["text"])]

    results, missed, false, scope, rescued, dup_pairs = G.judge(
        refs, exts, False, 0.35, 0.85, 15, 0.45)
    score = G.score_of(results, missed, false, scope, refs, exts, dup_pairs)
    print(json.dumps({k: score[k] for k in
                      ("기준_범위내", "추출_전체", "완전일치", "잘림", "넘침",
                       "부분일치", "미검출", "오검출", "짝중복", "정확도",
                       "누락률", "오검출률")}, ensure_ascii=False, indent=1))
    print(f"토큰: 입력 {tok_in} / 출력 {tok_out}")
    out = {"tag": tag, "problems": uniq, "score": score,
           "tokens": {"in": tok_in, "out": tok_out}}
    with open(f"grade_out/LLM추출_{tag}.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"저장: grade_out/LLM추출_{tag}.json")


if __name__ == "__main__":
    main()
