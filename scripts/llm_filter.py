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
    r"^\s*(?:탐구|밤구|생각|활[동롱몽공옹]|횔동|공학|컴퓨터)\s*[(\s\d]"
    r"|^\s*(?:이다|이므로|따라서|이때|그러므로|즉|이와 같은|이처럼|위에서)[\s.,]"
    r"|^\s*보기\b"          # 개념 확인용 보기 상자로 시작하면 문제가 아니다
    r"|^\s*준\W{0,2}비\W{0,2}학\W{0,2}습"   # 준|비|학|습 코너 (비상 실측)
    r"|프로그램을 이용"
    r"|^\S*[ㄱ-ㅎㅏ-ㅣ]")   # 첫 낱말에 홀낱자가 섞이면 오독 조각이다 (쥴ㄹ…)
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


def _openai_call(key: str, model: str, system: str, user: str) -> str:
    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
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
    return (data["choices"][0]["message"]["content"] or "").strip()


def openai_judge(api_key: str | None = None, model: str | None = None):
    """문단 -> True(문제)/False(아님) 판정 함수를 만든다."""
    key = api_key or os.environ.get("OPENAI_API_KEY")
    chosen = model or os.environ.get("LLM_FILTER_MODEL") or DEFAULT_MODEL
    if not key:
        return None

    def judge(text: str) -> bool:
        return "문제" in _openai_call(key, chosen, PROMPT, text)[:6]

    return judge


def openai_ask(api_key: str | None = None, model: str | None = None):
    """(지시문, 본문) -> 답 글자를 돌려주는 일반 질의 함수를 만든다. (경계 묻기용)"""
    key = api_key or os.environ.get("OPENAI_API_KEY")
    chosen = model or os.environ.get("LLM_FILTER_MODEL") or DEFAULT_MODEL
    if not key:
        return None

    def ask(system: str, user: str) -> str:
        return _openai_call(key, chosen, system, user)

    return ask


def filter_unmarked(problems, txt, judge, progress=None):
    """'지문' 후보를 판정해 통과한 것만 남긴다. 반환: (남은 문제들, 집계)

    judge 를 주입받으므로 시험에서는 가짜 판정으로 돌릴 수 있다.
    """
    kept = []
    asked = accepted = failed = 0
    JUDGED = ("지문", "활동의심")   # 활동의심 = '…해 보자' 뿐인 약한 표기 (활동/문제 경계)
    total = sum(1 for p in problems if p["name"] in JUDGED)
    for problem in problems:
        if problem["name"] not in JUDGED:
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


# ── 지문형 문제의 경계 다시 묻기 ─────────────────────────────────────
# 표기 없는 문제는 여러 문단(도입 + 지시 + 소문항)으로 구성되기도 한다.
# 룰은 문단 하나만 후보로 뜨므로 반쪽 회수(잘림)가 남는다 (기하 31 등 실측).
# 채택된 지문 문제마다 앞뒤 이웃 문단을 번호 붙여 보여 주고
# '문제 하나가 어느 문단들로 이루어지는가'를 한 번 더 묻는다.

BOUNDARY_PROMPT = """수학 교과서에서 이어진 문단들이 번호와 함께 주어진다.
그중 ★ 표시된 문단은 학생에게 내는 문제(의 일부)다.

이 문제 하나가 어느 문단들로 이루어지는지 골라라.
- 문제의 상황 설명(도입)이 앞 문단에, 소문항·지시가 뒤 문단에 있을 수 있다.
- 개념 설명, 정의, 예제의 풀이 과정, 읽을거리(수학 이야기)는 문제의 일부가 아니다.
- 확실하지 않으면 ★ 문단 하나만 골라라.

답은 문제에 속하는 번호만 쉼표로 쓴다. (예: 2,3  또는 3)"""

BOUNDARY_MAX_BLOCKS = 2       # 앞뒤로 각각 최대 몇 문단까지 보여 줄지
BOUNDARY_BLOCK_CHARS = 400


def _block_ranges(live, txt, line_gap, thr, claimed, file_name, start, step):
    """start 에서 step 방향으로 이웃 문단 구간 [(s, e)…] 을 가까운 순서로 모은다."""
    blocks = []
    j = start
    edge = None                 # 지금 모으는 블록의 바깥쪽 끝
    inner = None                #                  안쪽 끝 (문제와 가까운 쪽)
    while 0 <= j < len(live) and len(blocks) < BOUNDARY_MAX_BLOCKS:
        ln = live[j]
        if id(ln) in claimed or ln.get("_file") != file_name \
                or ln.get("type") == "section_header":
            break
        neighbor = live[j - step] if 0 <= j - step < len(live) else None
        g = None
        if neighbor is not None:
            pair = (neighbor, ln) if step == 1 else (ln, neighbor)
            g = line_gap(pair[0], pair[1])
        if inner is not None and thr and g is not None and g > thr:
            blocks.append((min(edge, inner), max(edge, inner)))
            edge = inner = None
            continue            # j 는 새 블록의 첫 줄로 다시 본다
        if inner is None:
            inner = j
        edge = j
        j += step
    if inner is not None and len(blocks) < BOUNDARY_MAX_BLOCKS:
        blocks.append((min(edge, inner), max(edge, inner)))
    return blocks


def _block_text(live, txt, s, e):
    parts = []
    for ln in live[s:e + 1]:
        t = txt(ln)
        if t and not t.startswith("!["):
            parts.append(t)
    return " ".join(parts)[:BOUNDARY_BLOCK_CHARS]


def refine_boundaries(problems, live, txt, line_gap, gap_thr, ask, progress=None):
    """채택된 '지문' 문제의 경계를 이웃 문단까지 보여 주고 LLM 에게 다시 묻는다.

    반환: (문제들, 집계). ask 를 주입받으므로 시험에서는 가짜 답으로 돌릴 수 있다.
    """
    index_of = {id(ln): i for i, ln in enumerate(live)}
    claimed = {id(ln) for p in problems for ln in p["body"]}
    # 지문 + 약한 표기(번호·번호점) — 활동 상자('찾아보기 1, 2')의 소문항 하나만
    # 잡히는 경우가 있다 (기하 기준 31 실측). 앞줄이 다른 문제에 속하면
    # 물어볼 이웃이 없어 질의가 생기지 않으므로 보통 문제에는 비용이 안 든다.
    # 활동의심도 묻는다 — 이름만 바뀐 약한 표기라, 빼면 도입 문단을 못 넓혀
    # 기준에 실린 활동 문제가 조각으로 남아 미검출이 된다 (신사고 미적분 실측 2건).
    def _fill_in(p):
        # 빈칸 문제는 발문 어미("써넣으시오.") 뒤로 유도 과정(□ 포함)이 이어져
        # 어미 절단으로 잘린다 (동아 실측: 정적분 넓이 유도) — 표기가 강해도 묻는다.
        return any("써넣" in (txt(l) or "") for l in p["body"])

    targets = [p for p in problems
               if p["name"] in ("지문", "번호", "번호점", "활동의심") or _fill_in(p)]
    asked = widened = failed = 0
    for p in targets:
        file_name = p["body"][0].get("_file")
        thr = gap_thr.get(file_name) if gap_thr else None
        s = index_of.get(id(p["body"][0]))
        e = index_of.get(id(p["body"][-1]))
        if s is None or e is None:
            continue
        before = _block_ranges(live, txt, line_gap, thr, claimed, file_name, s - 1, -1)
        after = _block_ranges(live, txt, line_gap, thr, claimed, file_name, e + 1, +1)
        # 풀이·증명·답으로 시작하는 블록은 문제의 일부일 수 없다 — 이웃 후보에서
        # 뺀다 (지학사 실측: 루나가 예제 풀이를 다음 문제 앞에 붙였다).
        _sol = re.compile(r"^\s*(풀이|증명|답)\b")
        before = [b for b in before
                  if _block_text(live, txt, *b) and not _sol.match(_block_text(live, txt, *b))]
        after = [b for b in after
                 if _block_text(live, txt, *b) and not _sol.match(_block_text(live, txt, *b))]
        if not before and not after:
            continue

        ordered = list(reversed(before)) + [(s, e)] + after
        anchor = len(before) + 1
        lines = []
        for k, (bs, be) in enumerate(ordered, 1):
            star = " ★" if k == anchor else ""
            lines.append(f"[{k}]{star} {_block_text(live, txt, bs, be)}")
        asked += 1
        if progress:
            progress(asked, len(targets))
        try:
            answer = ask(BOUNDARY_PROMPT, "\n\n".join(lines))
        except Exception:
            failed += 1
            time.sleep(1.0)
            continue
        picked = {int(n) for n in re.findall(r"\d+", answer) if 1 <= int(n) <= len(ordered)}
        if anchor not in picked:
            continue
        # ★ 를 포함해 이어진 구간만 인정한다 (건너뛴 선택은 무시)
        lo = anchor
        while lo - 1 in picked:
            lo -= 1
        hi = anchor
        while hi + 1 in picked:
            hi += 1
        if lo == anchor and hi == anchor:
            continue
        new_s = ordered[lo - 1][0]
        new_e = ordered[hi - 1][1]
        p["body"] = live[new_s:new_e + 1]
        for ln in p["body"]:
            claimed.add(id(ln))
        for ln in p["body"]:
            t = txt(ln)
            if t:
                p["head"] = t
                break
        widened += 1
    return problems, {"asked": asked, "widened": widened, "failed": failed}
