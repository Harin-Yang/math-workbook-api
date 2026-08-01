#!/usr/bin/env python3
"""
analyze.py
이미 받아둔 lines.json 을 다시 분석한다. Mathpix 재호출 없음 = 비용 0원.

사용법:
    python3 scripts/analyze.py ./stage0_out ./ANALYSIS.md

stage0.py 의 분석 로직에 있던 버그를 고쳤다:
  - 페이지별 lines 배열 중 가장 큰 것 하나만 세던 문제 -> 전체 합산
  - page 번호를 잃어버리던 문제 -> 페이지 단위로 보존
판정 룰 설계에 필요한 교차표를 전부 뽑는다.
"""

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict

NUMBER_PATTERNS = [
    ("두자리_0N", re.compile(r"^\s*0\d(?!\d)")),
    ("숫자_점", re.compile(r"^\s*\d{1,3}\s*\.")),
    ("숫자_괄호", re.compile(r"^\s*\d{1,3}\s*\)")),
    ("숫자_단독", re.compile(r"^\s*\d{1,3}\s*$")),
    ("대괄호_범위", re.compile(r"^\s*[\[【]\s*\d{1,3}\s*[~\-–]\s*\d{1,3}")),
    ("유형_N", re.compile(r"^\s*유형\s*\d{1,3}")),
    ("예제_N", re.compile(r"^\s*(필수\s*)?예제\s*\d{0,3}")),
    ("유제_N", re.compile(r"^\s*유제\s*\d{0,3}")),
    ("문제_N", re.compile(r"^\s*문제\s*\d{0,3}")),
    ("탐구_N", re.compile(r"^\s*탐구\s*\d{0,3}")),
    ("원문자", re.compile(r"^\s*[①-⑳]")),
    ("괄호숫자", re.compile(r"^\s*[⑴-⒇]")),
]


def collect_pages(obj, out=None, page_hint=None):
    """중첩 어디에 있든 (페이지번호, lines배열) 쌍을 모두 모은다."""
    if out is None:
        out = []
    if isinstance(obj, dict):
        pg = obj.get("page", obj.get("page_idx", page_hint))
        if isinstance(obj.get("lines"), list) and obj["lines"] \
                and isinstance(obj["lines"][0], dict):
            out.append((pg, obj["lines"]))
        for v in obj.values():
            collect_pages(v, out, pg)
    elif isinstance(obj, list):
        for i, it in enumerate(obj):
            collect_pages(it, out, page_hint if page_hint is not None else i + 1)
    return out


def load_file(path):
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    pages = collect_pages(doc)
    rows = []
    for pg, lines in pages:
        for ln in lines:
            ln = dict(ln)
            ln["_page"] = pg
            rows.append(ln)
    top_keys = list(doc.keys()) if isinstance(doc, dict) else None
    return rows, len(pages), top_keys


def x_of(ln):
    r = ln.get("region") or {}
    return r.get("top_left_x")


def y_of(ln):
    r = ln.get("region") or {}
    return r.get("top_left_y")


def w_of(ln):
    r = ln.get("region") or {}
    return r.get("width")


def txt(ln):
    return (ln.get("text") or ln.get("text_display") or "").strip()


def hist(values, bins=24, width=40):
    vals = [v for v in values if isinstance(v, (int, float))]
    if not vals:
        return ["(없음)"]
    lo, hi = min(vals), max(vals)
    span = max(hi - lo, 1)
    h = Counter(min(int((v - lo) / span * bins), bins - 1) for v in vals)
    peak = max(h.values())
    return [f"  {lo + span * b / bins:7.0f} | "
            f"{'#' * int(h.get(b, 0) / peak * width)} {h.get(b, 0)}"
            for b in range(bins)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("stage_dir")
    ap.add_argument("out_md")
    ap.add_argument("--examples", type=int, default=8)
    args = ap.parse_args()

    runs = os.path.join(args.stage_dir, "runs")
    if not os.path.isdir(runs):
        sys.exit(f"runs 폴더가 없습니다: {runs}")

    W = []
    A = W.append

    all_rows = []
    per_file = []
    top_keys_seen = None

    for name in sorted(os.listdir(runs)):
        lj = os.path.join(runs, name, "result.lines.json")
        if not os.path.exists(lj):
            continue
        rows, npages, tk = load_file(lj)
        top_keys_seen = top_keys_seen or tk
        for r in rows:
            r["_file"] = name
        all_rows.extend(rows)
        per_file.append((name, npages, len(rows)))

    if not all_rows:
        sys.exit("lines.json 을 찾지 못했습니다.")

    total_pages = sum(p for _, p, _ in per_file)

    A("# lines.json 심층 분석")
    A("")
    A(f"- 파일 {len(per_file)}개 / 페이지 {total_pages} / 줄 {len(all_rows):,}")
    A(f"- 최상위 키: `{top_keys_seen}`")
    A(f"- 페이지당 평균 {len(all_rows)/max(total_pages,1):.1f}줄")
    A("")

    A("## 1. 파일별")
    A("")
    A("| 파일 | 페이지 | 줄 | 줄/p |")
    A("|---|---|---|---|")
    for n, p, l in per_file:
        A(f"| {n[:38]} | {p} | {l:,} | {l/max(p,1):.1f} |")
    A("")

    # ---- type ----
    types = Counter(r.get("type", "-") for r in all_rows)
    A("## 2. type 분포 (전체)")
    A("")
    A("| type | 줄 | 비율 |")
    A("|---|---|---|")
    for t, c in types.most_common():
        A(f"| `{t}` | {c:,} | {c/len(all_rows)*100:.1f}% |")
    A("")

    subs = Counter(r.get("subtype") for r in all_rows if r.get("subtype"))
    if subs:
        A("### subtype")
        A("")
        A("| subtype | 줄 |")
        A("|---|---|")
        for t, c in subs.most_common():
            A(f"| `{t}` | {c:,} |")
        A("")

    # ---- column ----
    A("## 3. column 필드 (Mathpix 자체 단 분리)")
    A("")
    cols = Counter(r.get("column") for r in all_rows)
    A("| column | 줄 |")
    A("|---|---|")
    for c, n in sorted(cols.items(), key=lambda x: (x[0] is None, x[0])):
        A(f"| {c} | {n:,} |")
    A("")
    A("### column x 좌표 범위")
    A("")
    A("| column | x최소 | x최대 | x중앙 | 줄 |")
    A("|---|---|---|---|---|")
    bycol = defaultdict(list)
    for r in all_rows:
        x = x_of(r)
        if isinstance(x, (int, float)):
            bycol[r.get("column")].append(x)
    for c in sorted(bycol, key=lambda v: (v is None, v)):
        xs = sorted(bycol[c])
        A(f"| {c} | {xs[0]:.0f} | {xs[-1]:.0f} | "
          f"{xs[len(xs)//2]:.0f} | {len(xs):,} |")
    A("")

    # ---- type x column ----
    A("## 4. type x column 교차")
    A("")
    colvals = sorted({r.get("column") for r in all_rows},
                     key=lambda v: (v is None, v))
    A("| type | " + " | ".join(str(c) for c in colvals) + " |")
    A("|---" * (len(colvals) + 1) + "|")
    cross = defaultdict(Counter)
    for r in all_rows:
        cross[r.get("type", "-")][r.get("column")] += 1
    for t, _ in types.most_common():
        A(f"| `{t}` | " +
          " | ".join(str(cross[t].get(c, 0)) for c in colvals) + " |")
    A("")

    # ---- x 히스토그램 ----
    A("## 5. x좌표 분포")
    A("")
    A("```")
    for l in hist([x_of(r) for r in all_rows]):
        A(l)
    A("```")
    A("")

    # ---- font_size ----
    A("## 6. font_size 분포 (type별)")
    A("")
    A("| type | 최소 | 중앙 | 최대 | 줄 |")
    A("|---|---|---|---|---|")
    byfs = defaultdict(list)
    for r in all_rows:
        fs = r.get("font_size")
        if isinstance(fs, (int, float)):
            byfs[r.get("type", "-")].append(fs)
    for t, _ in types.most_common():
        v = sorted(byfs.get(t, []))
        if not v:
            continue
        A(f"| `{t}` | {v[0]:.0f} | {v[len(v)//2]:.0f} | "
          f"{v[-1]:.0f} | {len(v):,} |")
    A("")

    # ---- 계층 ----
    A("## 7. 계층 구조")
    A("")
    has_parent = sum(1 for r in all_rows if r.get("parent_id"))
    has_child = sum(1 for r in all_rows if r.get("children_ids"))
    A(f"- parent_id 보유: {has_parent:,} ({has_parent/len(all_rows)*100:.1f}%)")
    A(f"- children_ids 보유: {has_child:,}")
    A(f"- 최상위(parent 없음): {len(all_rows)-has_parent:,}")
    A("")
    A("### 최상위 줄의 type 분포")
    A("")
    A("| type | 줄 |")
    A("|---|---|")
    for t, c in Counter(r.get("type", "-") for r in all_rows
                        if not r.get("parent_id")).most_common():
        A(f"| `{t}` | {c:,} |")
    A("")

    # ---- conversion_output ----
    co = Counter(r.get("conversion_output") for r in all_rows)
    A(f"- conversion_output: {dict(co)}")
    A("")

    # ---- page_info 내용 ----
    A("## 8. page_info 실제 내용 (제거 대상 확인)")
    A("")
    A("```")
    n = 0
    for r in all_rows:
        if r.get("type") == "page_info":
            A(f"  x={x_of(r):>5} y={y_of(r):>5} col={r.get('column')}  "
              f"{txt(r)[:60]}")
            n += 1
            if n >= 20:
                break
    A("```")
    A("")

    # ---- 객관식 ----
    A("## 9. multiple_choice 구조")
    A("")
    mcb = [r for r in all_rows if r.get("type") == "multiple_choice_block"]
    mco = [r for r in all_rows if r.get("type") == "multiple_choice_option"]
    A(f"- block {len(mcb)} / option {len(mco)}")
    A("")
    A("```")
    for r in mcb[:10]:
        A(f"  [block] file={r['_file'][:22]} p={r.get('_page')} "
          f"x={x_of(r)} y={y_of(r)} col={r.get('column')}")
        A(f"          {txt(r)[:70]}")
    for r in mco[:10]:
        A(f"  [option] x={x_of(r)} y={y_of(r)}  {txt(r)[:60]}")
    A("```")
    A("")

    # ---- 도형/그래프 ----
    A("## 10. diagram / chart / table")
    A("")
    A("| type | 개수 | subtype |")
    A("|---|---|---|")
    for t in ("diagram", "chart", "table", "figure_label"):
        items = [r for r in all_rows if r.get("type") == t]
        if not items:
            continue
        st = Counter(r.get("subtype") for r in items)
        A(f"| `{t}` | {len(items)} | {dict(st)} |")
    A("")
    A("```")
    for t in ("diagram", "chart"):
        for r in [x for x in all_rows if x.get("type") == t][:8]:
            A(f"  [{t}] p={r.get('_page')} x={x_of(r)} y={y_of(r)} "
              f"w={w_of(r)} col={r.get('column')} sub={r.get('subtype')}")
    A("```")
    A("")

    # ---- 번호 패턴 ----
    A("## 11. 문제 번호 패턴")
    A("")
    hits = defaultdict(list)
    for r in all_rows:
        t = txt(r)
        if not t:
            continue
        for name, pat in NUMBER_PATTERNS:
            if pat.match(t):
                hits[name].append(r)
                break

    A("| 패턴 | 적중 | x중앙 | font중앙 | 주요 type |")
    A("|---|---|---|---|---|")
    for name, _ in NUMBER_PATTERNS:
        items = hits.get(name)
        if not items:
            continue
        xs = sorted(x for x in (x_of(r) for r in items)
                    if isinstance(x, (int, float)))
        fs = sorted(f for f in (r.get("font_size") for r in items)
                    if isinstance(f, (int, float)))
        tp = Counter(r.get("type") for r in items).most_common(2)
        A(f"| {name} | {len(items)} | "
          f"{xs[len(xs)//2]:.0f} | {fs[len(fs)//2]:.0f} | {dict(tp)} |")
    A("")
    A("### 적중 예시")
    A("")
    A("```")
    for name, _ in NUMBER_PATTERNS:
        items = hits.get(name)
        if not items:
            continue
        A(f"[{name}]  {len(items)}건")
        for r in items[:args.examples]:
            A(f"  x={x_of(r):>5} y={y_of(r):>5} col={r.get('column')} "
              f"fs={r.get('font_size')} type={r.get('type')[:18]:<18} "
              f"{txt(r)[:52]}")
    A("```")
    A("")

    # ---- 컬럼 좌단 정렬 줄 ----
    A("## 12. 각 column 좌측 경계에 붙은 줄 (문제 시작 후보)")
    A("")
    A("```")
    for c in sorted(bycol, key=lambda v: (v is None, v)):
        xs = sorted(bycol[c])
        left = xs[0]
        tol = 25
        cands = [r for r in all_rows
                 if r.get("column") == c
                 and isinstance(x_of(r), (int, float))
                 and x_of(r) <= left + tol
                 and txt(r)]
        A(f"[column {c}] 좌단 x={left:.0f}±{tol}  해당 {len(cands)}줄")
        for r in cands[:14]:
            A(f"  x={x_of(r):>5} fs={r.get('font_size'):>3} "
              f"{str(r.get('type'))[:16]:<16} {txt(r)[:48]}")
        A("")
    A("```")
    A("")

    # ---- 텍스트 샘플 ----
    A("## 13. 한 페이지 원본 덤프 (구조 확인용)")
    A("")
    tgt_file = per_file[0][0]
    pg_rows = [r for r in all_rows if r["_file"] == tgt_file
               and r.get("_page") in (1, 2)]
    A(f"파일: {tgt_file}")
    A("")
    A("```")
    for r in sorted(pg_rows, key=lambda r: (r.get("column") or 0,
                                            y_of(r) or 0))[:60]:
        A(f"  p{r.get('_page')} c{r.get('column')} "
          f"x={x_of(r):>5} y={y_of(r):>5} fs={r.get('font_size'):>3} "
          f"{str(r.get('type'))[:17]:<17} {txt(r)[:46]}")
    A("```")
    A("")

    with open(args.out_md, "w", encoding="utf-8") as f:
        f.write("\n".join(W))
    print(f"완료: {args.out_md}")
    print(f"파일 {len(per_file)}개 / 페이지 {total_pages} / 줄 {len(all_rows):,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
