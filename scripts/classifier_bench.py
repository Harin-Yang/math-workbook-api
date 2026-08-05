#!/usr/bin/env python3
"""
classifier_bench.py
'이 문단이 학생에게 풀라는 문제인가' 판정을 LLM 모델별로 실전 테스트한다.

시험셋을 어떻게 만드는가 — 사람 라벨 없이, 기준 파일로 자동 라벨한다.
    1. 추출기를 느슨한 모드(UNMARKED)로 돌려 '표기 없이 지문으로 시작하는 후보'를 모은다.
    2. 각 후보를 기준 파일(신사고 편집본)의 문제들과 한글 뼈대로 대조한다.
         기준 문제를 절반 이상 담고 있으면  -> 정답 '문제'
         어느 기준과도 거의 안 겹치면      -> 정답 '아님' (개념·활동 문단)
         애매한 중간은 버린다.
    3. 표기가 있어서 이미 잡는 문제 일부를 '쉬운 양성'으로 섞는다 (기본기 확인용).

돌리는 법:
    OPENAI_API_KEY 가 환경에 있어야 한다.
    python3 scripts/classifier_bench.py --models gpt-5.6-luna,gpt-5.6
"""

import argparse
import json
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import extract as EX  # noqa: E402
import grade as G  # noqa: E402
import make_docx as MD  # noqa: E402
import parse_ref as PR  # noqa: E402

SUBJECTS = [
    ("기하", "refs/[기하][신사고][문제편집].pdf"),
    ("확률과통계", "refs/[확률과통계][신사고][문제편집].pdf"),
]

# 겹침은 3글자 조각(트라이그램) 포함률로 잰다. 문자열 부분수열 방식은
# 개념 문단도 흔한 한글 조각 때문에 절반쯤 겹친 것으로 잘못 재서 라벨이 무너졌다.
POSITIVE_MIN = 0.55   # 기준 문제 조각을 이만큼 담으면 '문제'
NEGATIVE_MAX = 0.20   # 어느 기준과도 이 이하로만 겹치면 '아님'
ITEM_CHARS = 700
EASY_POSITIVES_PER_SUBJECT = 8

PROMPT = """수학 교과서에서 오려 낸 문단이 주어진다.
이 문단이 '학생에게 직접 풀라고 내는 문제'이면 문제, 아니면 아님이라고만 답하라.

문제: 값을 구하라/증명하라/그리라처럼 학생에게 시키는 독립된 문항.
아님: 개념 설명, 정의, 예제의 풀이 과정, 탐구·생각열기 같은 활동 안내, 단원 도입 글.

답은 반드시 '문제' 또는 '아님' 두 글자 중 하나만 쓴다."""


def paragraph_of(problem):
    """문제 후보의 본문을 사람이 읽을 한 덩어리 글로 만든다."""
    units = MD.merge_lines(list(problem["body"]))
    parts = []
    for unit in units:
        if "fig" in unit:
            parts.append("[그림]")
            continue
        if unit["text"]:
            parts.append(unit["text"])
    return "\n".join(parts)[:ITEM_CHARS]


DEFINITION_TAIL = __import__("re").compile(r"(라고 한다|라 한다|이라고 한다|고 부른다)")


def negative_blocks(rows):
    """정의상 문제가 아닌 블록을 뽑는다 — 라벨을 매칭에 기대지 않는다.

    1. 풀이·증명으로 시작하는 블록: 예제의 풀이 과정이다.
    2. '~라고 한다' 로 맺는 정의 문단(시킴 어미 없음): 개념 설명이다.
    """
    out = []
    lines = [r for r in rows if EX.txt(r) and r.get("type") in EX.BODY_TYPES]
    i = 0
    while i < len(lines):
        t = EX.txt(lines[i])
        take = 0
        if EX.SOLUTION.match(t):
            take = 5
        elif DEFINITION_TAIL.search(t) and not EX.ORDER_END.search(t):
            take = 3
        if take:
            chunk = []
            for k in range(i, min(i + take, len(lines))):
                tk = EX.txt(lines[k])
                if EX.ORDER_END.search(tk) or EX.match_start(lines[k]):
                    break
                chunk.append(tk)
            merged = " ".join(chunk)
            if len(G.normalize(merged)) >= 30 and not EX.ORDER_END.search(merged):
                out.append(merged[:ITEM_CHARS])
                i += max(1, len(chunk))
                continue
        i += 1
    return out


NEGATIVES_PER_SUBJECT = 12


def build_items():
    EX.UNMARKED = True
    items = []
    for subject, ref_pdf in SUBJECTS:
        refs = PR.parse(ref_pdf)["problems"]
        ref_gram_sets = [G.grams(G.normalize(r["text"])) for r in refs]

        names = [n for n in sorted(os.listdir("stage0_out/runs")) if subject in n]
        rows = []
        for name in names:
            got, _w = EX.load(f"stage0_out/runs/{name}/result.lines.json")
            for row in got:
                row["_file"] = name
            rows.extend(got)
        problems, *_ = EX.build(rows, None)

        for merged in negative_blocks(rows)[:NEGATIVES_PER_SUBJECT]:
            items.append({"subject": subject, "kind": "음성",
                          "label": "아님", "text": merged})

        easy = 0
        for problem in problems:
            text = paragraph_of(problem)
            if len(G.normalize(text)) < 20:
                continue
            if problem["name"] != "지문":
                if easy < EASY_POSITIVES_PER_SUBJECT:
                    items.append({"subject": subject, "kind": "쉬운양성",
                                  "label": "문제", "text": G.strip_marker(text)})
                    easy += 1
                continue
            cand_grams = G.grams(G.normalize(text))
            best = 0.0
            for ref_grams in ref_gram_sets:
                if not ref_grams:
                    continue
                best = max(best, len(ref_grams & cand_grams) / len(ref_grams))
            if best >= POSITIVE_MIN:
                items.append({"subject": subject, "kind": "어려운양성",
                              "label": "문제", "text": text})
            # 매칭이 낮다고 음성으로 삼지 않는다 — 기준에 없는 진짜 문제일 수 있다.
    return items


def ask(model, text, key):
    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": PROMPT},
            {"role": "user", "content": text},
        ],
        "max_completion_tokens": 2000,
    }).encode()
    request = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=body, method="POST",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        data = json.loads(response.read())
    answer = (data["choices"][0]["message"]["content"] or "").strip()
    usage = data.get("usage", {})
    return answer, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", default="gpt-5.6")
    parser.add_argument("--dump", default=None, help="시험셋을 JSON 으로 저장만 한다")
    args = parser.parse_args()

    items = build_items()
    counts = {}
    for item in items:
        counts[item["kind"]] = counts.get(item["kind"], 0) + 1
    print(f"시험셋 {len(items)}건: {counts}", file=sys.stderr)
    if args.dump:
        with open(args.dump, "w", encoding="utf-8") as stream:
            json.dump(items, stream, ensure_ascii=False, indent=1)
        return 0

    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        sys.exit("OPENAI_API_KEY 가 없습니다.")

    for model in args.models.split(","):
        model = model.strip()
        right = 0
        wrong = []
        tokens_in = tokens_out = 0
        for item in items:
            try:
                answer, used_in, used_out = ask(model, item["text"], key)
            except Exception as error:
                print(f"[{model}] 호출 실패: {error}", file=sys.stderr)
                answer, used_in, used_out = "", 0, 0
            tokens_in += used_in
            tokens_out += used_out
            verdict = "문제" if "문제" in answer[:6] else "아님"
            if verdict == item["label"]:
                right += 1
            else:
                wrong.append((item["kind"], item["label"], answer[:12], item["text"][:42]))
            time.sleep(0.3)

        by_kind = {}
        for item in items:
            by_kind.setdefault(item["kind"], [0, 0])
            by_kind[item["kind"]][1] += 1
        for kind, label, answer, text in wrong:
            by_kind[kind][0] += 1

        print(f"\n===== {model}")
        print(f"정확도 {right}/{len(items)} = {right / len(items):.3f}   "
              f"토큰 입력 {tokens_in:,} / 출력 {tokens_out:,}")
        for kind, (bad, total) in sorted(by_kind.items()):
            print(f"  {kind}: {total - bad}/{total}")
        for kind, label, answer, text in wrong[:8]:
            print(f"  틀림[{kind}] 정답={label} 답={answer!r}  {text}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
