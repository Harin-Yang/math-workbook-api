#!/usr/bin/env python3
"""
llm_filter.py
'표기 없이 지문으로 시작하는 문제 후보'를 LLM(gpt-5.6-luna)으로 판정한다.

왜 이 구조인가
    위치·모양 룰만으로는 개념 문단과 발문을 못 가른다 (v6 실험에서 증명).
    그래서 후보는 룰(UNMARKED)이 넓게 만들고, 채택 여부는 LLM 이 정한다.
    모델·프롬프트는 classifier_bench.py 로 잰 것을 그대로 쓴다
    (62건 실전 테스트에서 luna 96.8%, 표기 없는 서술형 22/22).

돈 규칙
    표기 있는 문제는 LLM 을 부르지 않는다. '지문' 후보만 판정한다.
    한 권에 후보 수십 개 = 약 10~20원. 호출이 실패한 후보는 버린다
    (지금까지처럼 안 잡히는 것 — 오검출을 내보내는 것보다 낫다).
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.request

DEFAULT_MODEL = "gpt-5.6-luna"

# LLM 에게 묻기 전에 룰로 거르는 후보들. 물어볼 필요도 없는 것들이다.
#   활동 코너: 탐구(오독: 밤구)·생각·공학 도구 활동은 문제가 아니다.
#   문장 조각: '이다. 이때 …' 처럼 문장 중간에서 시작하면 후보를 잘못 뜬 것이다.
PREFILTER_DROP = re.compile(
    r"^\s*(?:탐구|밤구|생각|활동|공학|컴퓨터)\s*[(\s]"
    r"|^\s*(?:이다|이므로|따라서|이때|그러므로|즉)[\s.,]"
    r"|프로그램을 이용")
CALL_TIMEOUT_SECONDS = 60
MAX_ITEM_CHARS = 700

# classifier_bench.py 와 같은 판정문. 여기를 고치면 벤치로 다시 재고 나서 쓸 것.
PROMPT = """수학 교과서에서 오려 낸 문단이 주어진다.
이 문단이 '학생에게 직접 풀라고 내는 문제'이면 문제, 아니면 아님이라고만 답하라.

문제: 값을 구하라/증명하라/그리라처럼 학생에게 시키는 독립된 문항.
아님: 개념 설명, 정의, 예제의 풀이 과정, 단원 도입 글,
탐구·생각열기·확인 활동과 그 소문항, 컴퓨터·공학 도구로 그려 보는 활동.

답은 반드시 '문제' 또는 '아님' 두 글자 중 하나만 쓴다."""


def paragraph_text(problem, txt) -> str:
    """후보의 본문을 판정용 한 덩어리 글로 만든다. (벤치와 같은 재료)"""
    parts = []
    for line in problem["body"]:
        text = txt(line)
        if text:
            parts.append(text)
    return "\n".join(parts)[:MAX_ITEM_CHARS]


def openai_judge(api_key: str | None = None, model: str | None = None):
    """문단 -> True(문제)/False(아님) 판정 함수를 만든다."""
    key = api_key or os.environ.get("OPENAI_API_KEY")
    chosen = model or os.environ.get("LLM_FILTER_MODEL") or DEFAULT_MODEL
    if not key:
        return None

    def judge(text: str) -> bool:
        body = json.dumps({
            "model": chosen,
            "messages": [
                {"role": "system", "content": PROMPT},
                {"role": "user", "content": text},
            ],
            "max_completion_tokens": 1000,
        }).encode()
        request = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=body, method="POST",
            headers={"Authorization": f"Bearer {key}",
                     "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=CALL_TIMEOUT_SECONDS) as response:
            data = json.loads(response.read())
        answer = (data["choices"][0]["message"]["content"] or "").strip()
        return "문제" in answer[:6]

    return judge


def filter_unmarked(problems, txt, judge, progress=None):
    """'지문' 후보를 판정해 통과한 것만 남긴다. 반환: (남은 문제들, 집계)

    judge 를 주입받으므로 시험에서는 가짜 판정으로 돌릴 수 있다.
    """
    kept = []
    asked = accepted = failed = 0
    total = sum(1 for p in problems if p["name"] == "지문")
    for problem in problems:
        if problem["name"] != "지문":
            kept.append(problem)
            continue
        text = paragraph_text(problem, txt)
        if PREFILTER_DROP.search(text.split("\n", 1)[0]):
            continue
        asked += 1
        if progress:
            progress(asked, total)
        try:
            ok = judge(text)
        except Exception:
            failed += 1
            time.sleep(1.0)
            continue
        if ok:
            accepted += 1
            kept.append(problem)
    return kept, {"asked": asked, "accepted": accepted, "failed": failed}
