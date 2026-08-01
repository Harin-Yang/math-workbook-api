#!/usr/bin/env python3
"""
parse_ref.py
테스트 기준 파일(수기 편집본 PDF)에서 문제 단위를 뽑아낸다.
이 결과가 추출 정확도의 채점 기준이 된다.

사용법:
    python3 scripts/parse_ref.py <기준파일.pdf> <출력.json> [--report 출력.md]

편집본의 공통 신호:
  - 문제 시작은 'N.N)' (표시번호.각주번호) 형태. 두 번호가 항상 같다.
  - 소단원은 'N-N-N. 제목'. 출판사에 따라 번호가 제목 앞/뒤에 온다.
  - 해설은 '[정답 및 해설]' 또는 '[빠른 정답]' 이후 전부
  - 머리말/꼬리말/워터마크는 여러 쪽에 반복되는 줄로 자동 식별
"""

import argparse
import json
import logging
import os
import re
import sys
import warnings
from collections import Counter

for _n in ("pypdf", "pypdf._reader", "pypdf.generic",
           "pypdf.generic._data_structures", "pypdf.generic._image_inline"):
    logging.getLogger(_n).setLevel(logging.CRITICAL)
warnings.filterwarnings("ignore")

from pypdf import PdfReader

# 문제 시작. 앞 번호는 표시 번호, 뒤 번호는 해설 연결용 각주.
# '순열13.13)' 처럼 한글 바로 뒤에 붙어 나오는 경우가 있어 앞 조건을 느슨히 둔다.
# 대신 '두 번호가 같을 것' + '번호가 커질 것' 두 조건으로 오탐을 막는다.
Q_START = re.compile(r"(?<![\d.])(\d{1,3})\.\s?(\d{1,3})\)")
# 소단원 제목. 두 형태를 모두 본다.
#   '1-1-1. 여러 가지 순열'  (번호가 앞)
#   '여러 가지 순열1-1-1.'    (번호가 뒤 - 교학사 편집)
SECTION_AFTER = re.compile(r"(\d+-\d+-\d+)\.\s*([가-힣A-Za-z][^\d]{0,28})")
SECTION_BEFORE = re.compile(r"([가-힣][^\d|]{0,28}?)(\d+-\d+-\d+)\.")
# 해설 시작. PDF 추출 과정에서 대괄호가 앞으로 밀리는 경우가 있어 느슨히 둔다.
SOLUTION_HEAD = re.compile(r"\[?\s*\]?\s*(정답 및 해설|빠른 정답)\s*\]?")
# 꼬리말 페이지 번호
PAGE_MARK = re.compile(r"^\s*\|\s*\d+\s*\|\s*$")

BLOCK_LABELS = [
    "기초 문제", "기본 문제", "심화 문제", "서술형", "사고력 UP",
    "중단원 마무리", "대단원 마무리", "스스로 확인하기", "스스로 마무리하기",
    "생각 키우기", "생각을 넓히는 수학",
]


def learn_boilerplate(pages, min_ratio=0.4):
    """여러 쪽에 반복되는 줄 = 머리말/꼬리말/워터마크."""
    c = Counter()
    for txt in pages:
        for s in {ln.strip() for ln in (txt or "").splitlines()
                  if len(ln.strip()) >= 4}:
            c[s] += 1
    need = max(2, int(len(pages) * min_ratio))
    return [s for s, n in c.items() if n >= need]


def page_texts(path):
    reader = PdfReader(path, strict=False)
    out = []
    for p in reader.pages:
        try:
            out.append(p.extract_text() or "")
        except Exception:
            out.append("")
    return out


def build_stream(pages, boiler):
    """머리말 등을 뺀 뒤 (문자위치 -> 쪽번호) 를 유지하며 한 덩어리로 잇는다."""
    parts, page_at = [], []
    pos = 0
    for pi, txt in enumerate(pages, 1):
        keep = []
        for raw in (txt or "").splitlines():
            s = raw.strip()
            if not s or PAGE_MARK.match(s):
                continue
            if s in boiler:
                continue
            keep.append(s)
        chunk = " ".join(keep)
        if not chunk:
            continue
        parts.append(chunk)
        page_at.append((pos, pi))
        pos += len(chunk) + 1
    return " ".join(parts), page_at


def page_of(offset, page_at):
    pg = page_at[0][1] if page_at else 1
    for start, p in page_at:
        if start <= offset:
            pg = p
        else:
            break
    return pg


def norm(t):
    return re.sub(r"\s+", " ", t).strip()


def parse(path):
    pages = page_texts(path)
    boiler = learn_boilerplate(pages)
    stream, page_at = build_stream(pages, boiler)

    # 해설 이후는 잘라낸다
    m = SOLUTION_HEAD.search(stream)
    solution = ""
    if m:
        solution = stream[m.end():]
        stream = stream[:m.start()]

    # 두 번호가 같고, 번호가 앞 문제보다 큰 것만 문제 시작으로 인정한다
    starts, prev = [], 0
    for mm in Q_START.finditer(stream):
        a, b = int(mm.group(1)), int(mm.group(2))
        if a != b or a <= prev:
            continue
        starts.append(mm)
        prev = a

    problems = []
    for i, mm in enumerate(starts):
        end = starts[i + 1].start() if i + 1 < len(starts) else len(stream)
        raw = stream[mm.end():end]

        section = None
        block = None
        best = -1
        for sm in SECTION_AFTER.finditer(stream[:mm.start()]):
            if sm.start() > best:
                best = sm.start()
                section = f"{sm.group(1)}. {norm(sm.group(2))}"
        for sm in SECTION_BEFORE.finditer(stream[:mm.start()]):
            if sm.start() > best:
                best = sm.start()
                section = f"{sm.group(2)}. {norm(sm.group(1))}"

        tail = stream[max(0, mm.start() - 120):mm.start()]
        for lb in BLOCK_LABELS:
            if lb in tail:
                block = lb

        text = norm(raw)
        # 본문 끝에 다음 소단원 제목이 붙어 있으면 떼어낸다
        text = re.sub(r"\s*\d+-\d+-\d+\.\s*[^\d]{0,30}$", "", text)
        text = re.sub(r"\s*[가-힣][^\d|]{0,28}?\d+-\d+-\d+\.\s*$", "", text)
        for lb in BLOCK_LABELS:
            text = re.sub(rf"\s*\[?{re.escape(lb)}\]?\s*$", "", text)

        problems.append({
            "num": int(mm.group(1)),
            "footnote": int(mm.group(2)),
            "section": section,
            "block": block,
            "page": page_of(mm.start(), page_at),
            "text": text,
            "head": text[:100],
            "chars": len(text),
        })

    return {
        "file": os.path.basename(path),
        "pages": len(pages),
        "boilerplate": boiler,
        "problems": problems,
        "solution_chars": len(solution),
    }


def report(d, out_md):
    W = []
    A = W.append
    ps = d["problems"]

    A(f"# 기준 파일 분석: {d['file']}")
    A("")
    A(f"- {d['pages']}쪽 / 문제 {len(ps)}개 / 해설 {d['solution_chars']:,}자")
    A("")

    A("## 자동으로 걷어낸 머리말·꼬리말·워터마크")
    A("")
    A("```")
    for b in d["boilerplate"][:10]:
        A(f"  {b[:74]}")
    A("```")
    A("")

    A("## 소단원")
    A("")
    A("| 소단원 | 문제 수 |")
    A("|---|---|")
    for s, n in Counter(p["section"] for p in ps).most_common():
        A(f"| {s} | {n} |")
    A("")

    blocks = Counter(p["block"] for p in ps)
    if len(blocks) > 1:
        A("## 구획")
        A("")
        A("| 구획 | 문제 수 |")
        A("|---|---|")
        for b, n in blocks.most_common():
            A(f"| {b} | {n} |")
        A("")

    nums = [p["num"] for p in ps]
    gaps = sorted(set(range(min(nums), max(nums) + 1)) - set(nums)) if nums else []
    A("## 번호 검증")
    A("")
    A(f"- 범위 {min(nums) if nums else '-'} ~ {max(nums) if nums else '-'}")
    A(f"- 결손 {gaps[:20] if gaps else '없음'}")
    A(f"- 표시번호 != 각주번호 : "
      f"{sum(1 for p in ps if p['num'] != p['footnote'])}건")
    A("")

    lens = sorted(p["chars"] for p in ps)
    A("## 본문 길이(글자)")
    A("")
    A(f"- 최소 {lens[0]} / 중앙 {lens[len(lens)//2]} / 최대 {lens[-1]}")
    long = [p for p in ps if p["chars"] > 600]
    if long:
        A(f"- 600자 초과 {len(long)}개 (경계 오판 의심)")
        for p in long[:5]:
            A(f"    [{p['num']}] {p['head'][:60]}")
    A("")

    A("## 문제 예시 (앞 6개)")
    A("")
    A("```")
    for p in ps[:6]:
        A(f"[{p['num']}] p{p['page']} <{p['section']}>")
        A(f"    {p['text'][:150]}")
        A("")
    A("```")

    with open(out_md, "w", encoding="utf-8") as f:
        f.write("\n".join(W))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("out_json")
    ap.add_argument("--report", default=None)
    args = ap.parse_args()

    d = parse(args.pdf)
    with open(args.out_json, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    if args.report:
        report(d, args.report)

    print(f"완료: {args.out_json}")
    print(f"{d['pages']}쪽 / 문제 {len(d['problems'])}개")
    return 0


if __name__ == "__main__":
    sys.exit(main())
