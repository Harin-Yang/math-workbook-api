#!/usr/bin/env python3
"""
probe.py
추출기가 문제 시작을 왜 못 찾았는지 보려고 원본 줄을 그대로 들여다본다.
Mathpix 재호출 없음 = 비용 0원.

사용법:
    python3 scripts/probe.py ./stage0_out /tmp/PROBE.md --file 이차곡선
    python3 scripts/probe.py ./stage0_out /tmp/PROBE.md --file 이차곡선 --pages 6-9

기본은 '문제 시작일 수도 있는 줄' 만 골라 보여준다.
  - '문제 / 예제 / 유제 / 탐구 / 유형' 이 들어간 줄
  - 숫자 1~3자리만 덩그러니 있는 줄 (번호가 따로 떨어져 나온 경우)

--pages 를 주면 그 쪽의 모든 줄을 순서대로 보여준다.

칸 뜻
  type    줄의 종류 (본문·수식·도형)
  x / y   쪽 안에서의 위치
  font    글자 크기
  par     윗줄에 딸린 줄인지 (값이 있으면 최상위 줄이 아님 -> 시작 후보에서 빠진다)
  out     최종 문서 포함 여부 (False 면 추출기가 버린 줄)
"""

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import extract as EX  # noqa: E402

MARKER = re.compile(r"(문제|예제|유제|탐구|밤구|유형|확인\s*문제)")
ONLY_NUM = re.compile(r"^[\(（\[]?\s*(\d{1,3})\s*[\)）\]\.]?$")


def rows_of(stage_dir, filters):
    runs = os.path.join(stage_dir, "runs")
    if not os.path.isdir(runs):
        sys.exit(f"runs 폴더가 없습니다: {runs}")
    names = sorted(os.listdir(runs))
    if filters:
        names = [n for n in names if any(f in n for f in filters)]
    out = []
    for n in names:
        lj = os.path.join(runs, n, "result.lines.json")
        if not os.path.exists(lj):
            continue
        rows, _w = EX.load(lj)
        for r in rows:
            r["_file"] = n
        out.extend(rows)
    if not out:
        sys.exit("대상 파일이 없습니다. --file 값을 확인하세요.")
    out.sort(key=lambda ln: (
        ln.get("_file") or "",
        ln.get("_page") or 0,
        ln.get("line") if isinstance(ln.get("line"), int) else 10 ** 6,
        (ln.get("region") or {}).get("top_left_y") or 0))
    return out, names


def fmt(ln):
    r = ln.get("region") or {}
    t = EX.txt(ln)
    if EX.is_image_md(t):
        t = "<그림>"
    return (f"p{str(ln.get('_page')):>3} "
            f"{str(ln.get('type'))[:12]:<12} "
            f"x{str(r.get('top_left_x')):>5} "
            f"y{str(r.get('top_left_y')):>5} "
            f"font{str(ln.get('font_size')):>4} "
            f"par{'Y' if ln.get('parent_id') else '.'} "
            f"out{'F' if ln.get('conversion_output') is False else '.'}  "
            f"{t[:62]}")


def parse_pages(s):
    if not s:
        return None
    if "-" in s:
        a, b = s.split("-", 1)
        return set(range(int(a), int(b) + 1))
    return {int(s)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("stage_dir")
    ap.add_argument("out_md")
    ap.add_argument("--file", action="append", default=[])
    ap.add_argument("--pages", default=None, help="예: 6-9")
    ap.add_argument("--context", type=int, default=2,
                    help="후보 줄 앞뒤로 함께 보여줄 줄 수")
    args = ap.parse_args()

    rows, names = rows_of(args.stage_dir, args.file)
    pages = parse_pages(args.pages)

    W = []
    A = W.append
    A("# 원본 줄 들여다보기")
    A("")
    A(f"- 대상 파일 {len(names)}개: {', '.join(names)}")
    A(f"- 전체 줄 {len(rows):,}")
    A("")

    if pages:
        A(f"## {args.pages}쪽 전체 줄")
        A("")
        A("```")
        for ln in rows:
            if ln.get("_page") in pages:
                A("  " + fmt(ln))
        A("```")
    else:
        hits = []
        for i, ln in enumerate(rows):
            t = EX.txt(ln)
            if not t or EX.is_image_md(t):
                continue
            if MARKER.search(t[:14]) or ONLY_NUM.match(t):
                hits.append(i)

        A(f"## 문제 시작 후보로 보이는 줄 {len(hits)}개")
        A("")
        A("```")
        shown = set()
        for i in hits:
            lo = max(0, i - args.context)
            hi = min(len(rows), i + args.context + 1)
            if lo in shown:
                pass
            else:
                A("  " + "-" * 90)
            for j in range(lo, hi):
                if j in shown:
                    continue
                shown.add(j)
                mark = ">>" if j == i else "  "
                A(f"{mark}" + fmt(rows[j]))
        A("```")

    A("")
    with open(args.out_md, "w", encoding="utf-8") as f:
        f.write("\n".join(W))

    print(f"완료: {args.out_md}")
    print(f"파일 {len(names)}개 / 줄 {len(rows):,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
