#!/usr/bin/env python3
"""
extract.py
lines.json 에서 문제만 골라낸다. Mathpix 재호출 없음 = 비용 0원.

사용법:
    python3 scripts/extract.py ./stage0_out ./EXTRACT.md

판정 근거 (263페이지 실측 데이터):
  - '문제 N' 202건이 x=361 부근, 글자크기 32, type=text 에 몰려 있음
  - '예제 N' 53건이 x=363, 크기 32
  - '탐구 N' 45건이 x=384, 크기 27
  - page_info(머리말/꾬말말) 806줄은 전부 버림
  - conversion_output=False 인 줄은 중복 요소이므로 버림
"""

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict

# 문제 시작 표기 후보. (이름, 정규식, 유형)
START_PATTERNS = [
    ("문제",   re.compile(r"^\s*문제\s*(\d{1,3})"),                "문제"),
    ("예제",   re.compile(r"^\s*(?:필수\s*)?예제\s*(\d{1,3})"),     "예제"),
    ("유제",   re.compile(r"^\s*유제\s*(\d{1,3})"),                "유제"),
    ("탐구",   re.compile(r"^\s*탐구\s*[\(（]?\s*(\d{1,3})"),       "탐구"),
    ("유형",   re.compile(r"^\s*유형\s*(\d{1,3})"),                "유형"),
    ("확인",   re.compile(r"^\s*확인\s*문제\s*(\d{1,3})"),          "문제"),
    ("두자리", re.compile(r"^\s*(0\d)(?!\d)"),                     "번호"),
    ("숫자점", re.compile(r"^\s*(\d{1,3})\s*[.)]\s+\S"),           "번호"),
]

# 문제 본문이 될 수 있는 줄 종류
BODY_TYPES = {"text", "math", "list_item", "multiple_choice_block",
              "multiple_choice_option", "section_header", "equation_number",
              "table", "simple_cell", "complex_cell", "table_row",
              "table_column", "form_field", "figure_label"}

# 무조건 버리는 줄 종류
DROP_TYPES = {"page_info"}

# 문제에 붙일 수 있는 그림 종류
FIGURE_TYPES = {"diagram", "chart"}

# 단원 제목처럼 지나치게 큰 글자는 문제 번호가 아님
MAX_TITLE_FONT = 60

# 페이지 폭 대비 이 비율을 넘는 그림은 배경/장식으로 간주
FIGURE_MAX_WIDTH_RATIO = 0.75


def collect_pages(obj, out=None, hint=None):
    if out is None:
        out = []
    if isinstance(obj, dict):
        pg = obj.get("page", obj.get("page_idx", hint))
        if isinstance(obj.get("lines"), list) and obj["lines"] \
                and isinstance(obj["lines"][0], dict):
            out.append((pg, obj, obj["lines"]))
        for v in obj.values():
            collect_pages(v, out, pg)
    elif isinstance(obj, list):
        for i, it in enumerate(obj):
            collect_pages(it, out, hint if hint is not None else i + 1)
    return out


def load(path):
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    rows, widths = [], []
    for pg, pageobj, lines in collect_pages(doc):
        w = pageobj.get("image_width") or pageobj.get("width")
        if isinstance(w, (int, float)):
            widths.append(w)
        for ln in lines:
            d = dict(ln)
            d["_page"] = pg
            d["_page_width"] = w
            rows.append(d)
    return rows, (max(widths) if widths else None)


def rx(ln):
    return (ln.get("region") or {}).get("top_left_x")


def ry(ln):
    return (ln.get("region") or {}).get("top_left_y")


def rw(ln):
    return (ln.get("region") or {}).get("width")


def rh(ln):
    return (ln.get("region") or {}).get("height")


def txt(ln):
    return (ln.get("text") or ln.get("text_display") or "").strip()


def is_image_md(t):
    return t.startswith("![](") or "\\includegraphics" in t


def match_start(ln):
    """문제 시작 줄이면 (표기이름, 번호, 유형) 반환, 아니면 None."""
    t = txt(ln)
    if not t or is_image_md(t):
        return None
    fs = ln.get("font_size")
    if isinstance(fs, (int, float)) and fs > MAX_TITLE_FONT:
        return None
    for name, pat, kind in START_PATTERNS:
        m = pat.match(t)
        if m:
            try:
                num = int(m.group(1))
            except (ValueError, IndexError):
                num = None
            return name, num, kind
    return None


def learn_x_band(cands):
    """시작 후보들의 x 최빈 구간을 학습한다."""
    xs = sorted(x for x in (rx(c["line"]) for c in cands)
                if isinstance(x, (int, float)))
    if not xs:
        return None, None
    buckets = Counter(int(x // 50) for x in xs)
    top = buckets.most_common(1)[0][0]
    center = (top + 0.5) * 50
    return center, 60


def build(rows, page_width):
    """문제 단위로 묶는다."""
    figmax = page_width * FIGURE_MAX_WIDTH_RATIO if page_width else None

    # 1) 버릴 줄 제거
    live, dropped_bg = [], 0
    for ln in rows:
        if ln.get("type") in DROP_TYPES:
            continue
        if ln.get("conversion_output") is False:
            continue
        # 페이지 폭을 거의 다 차지하는 그림 = 배경/장식
        if ln.get("type") in FIGURE_TYPES and figmax:
            w = rw(ln)
            if isinstance(w, (int, float)) and w > figmax:
                dropped_bg += 1
                continue
        live.append(ln)

    # 2) 페이지 -> 읽기 순서 정렬
    def order_key(ln):
        return (ln.get("_file") or "",
                ln.get("_page") or 0,
                ln.get("line") if isinstance(ln.get("line"), int) else 10**6,
                ry(ln) or 0)

    live.sort(key=order_key)

    # 3) 시작 후보 수집
    cands = []
    for i, ln in enumerate(live):
        if ln.get("parent_id"):
            continue
        if ln.get("type") not in BODY_TYPES:
            continue
        m = match_start(ln)
        if m:
            cands.append({"idx": i, "line": ln, "name": m[0],
                          "num": m[1], "kind": m[2]})

    # 4) x 구간 학습 후 벗어난 후보 제거
    center, tol = learn_x_band(cands)
    kept, dropped_x = [], []
    for c in cands:
        x = rx(c["line"])
        if center is None or not isinstance(x, (int, float)) \
                or abs(x - center) <= tol:
            kept.append(c)
        else:
            dropped_x.append(c)

    # 5) 경계 확정 + 그림 귀속 (본문 안에 들어온 그림만 붙인다)
    problems = []
    used_fig = set()
    for n, c in enumerate(kept):
        start = c["idx"]
        end = kept[n + 1]["idx"] if n + 1 < len(kept) else len(live)
        body = live[start:end]
        figs = [b for b in body if b.get("type") in FIGURE_TYPES]
        for f in figs:
            used_fig.add(id(f))
        problems.append({
            "name": c["name"], "num": c["num"], "kind": c["kind"],
            "page": c["line"].get("_page"),
            "file": c["line"].get("_file"),
            "x": rx(c["line"]), "y": ry(c["line"]),
            "font": c["line"].get("font_size"),
            "head": txt(c["line"])[:90],
            "body": body,
            "lines": len(body),
            "figs": figs,
        })

    # 6) 어느 문제에도 안 붙은 그림 = 확인 필요
    orphan_figs = [ln for ln in live
                   if ln.get("type") in FIGURE_TYPES and id(ln) not in used_fig]

    stats = {"dropped_bg": dropped_bg, "orphan_figs": orphan_figs}
    return problems, kept, dropped_x, live, stats


def check_sequence(problems):
    """표기별 번호 연속성을 확인해 결손을 찾는다."""
    warns = []
    byname = defaultdict(list)
    for p in problems:
        if p["num"] is not None:
            byname[p["name"]].append(p["num"])
    for name, nums in byname.items():
        run = []
        for v in nums:
            if run and v <= run[-1]:
                gaps = sorted(set(range(run[0], run[-1] + 1)) - set(run))
                if gaps:
                    warns.append(f"{name} 번호 {run[0]}~{run[-1]} 구간 결손: {gaps}")
                run = [v]
            else:
                run.append(v)
        if run:
            gaps = sorted(set(range(run[0], run[-1] + 1)) - set(run))
            if gaps:
                warns.append(f"{name} 번호 {run[0]}~{run[-1]} 구간 결손: {gaps}")
    return warns


def render(problems, kept, dropped_x, live, rows, page_width, out_md,
           samples, stats):
    W = []
    A = W.append

    A("# 문제 추출 결과 v1")
    A("")
    A(f"- 전체 줄 {len(rows):,} -> 유효 줄 {len(live):,}")
    A(f"- 제거: 머리말/꾬말말·중복 {len(rows)-len(live)-stats['dropped_bg']:,}줄, "
      f"배경 그림 {stats['dropped_bg']}장")
    A(f"- 시작 후보 {len(kept)+len(dropped_x)} -> 채택 {len(kept)} "
      f"/ 위치이탈 제외 {len(dropped_x)}")
    A(f"- 추출 문제 {len(problems)}개")
    if page_width:
        A(f"- 페이지 폭 {page_width}")
    A("")

    A("## 1. 표기별 개수")
    A("")
    A("| 표기 | 개수 | x중앙 | 글자크기중앙 | 본문줄 중앙 |")
    A("|---|---|---|---|---|")
    byname = defaultdict(list)
    for p in problems:
        byname[p["name"]].append(p)
    for name, ps in sorted(byname.items(), key=lambda kv: -len(kv[1])):
        xs = sorted(p["x"] for p in ps if isinstance(p["x"], (int, float)))
        fs = sorted(p["font"] for p in ps
                    if isinstance(p["font"], (int, float)))
        ls = sorted(p["lines"] for p in ps)
        A(f"| {name} | {len(ps)} | "
          f"{xs[len(xs)//2] if xs else '-'} | "
          f"{fs[len(fs)//2] if fs else '-'} | "
          f"{ls[len(ls)//2]} |")
    A("")

    A("## 2. 그림 귀속")
    A("")
    withfig = [p for p in problems if p["figs"]]
    orphans = stats["orphan_figs"]
    A(f"- 그림이 붙은 문제 {len(withfig)}개 "
      f"(총 {sum(len(p['figs']) for p in problems)}장)")
    A(f"- 어느 문제에도 안 붙은 그림 {len(orphans)}장  <- 확인 필요")
    if orphans:
        A("")
        A("```")
        for f in orphans[:15]:
            A(f"  p{f.get('_page')} x={rx(f)} y={ry(f)} w={rw(f)} "
              f"{f.get('type')}")
        A("```")
    A("")

    A("## 3. 경고")
    A("")
    warns = check_sequence(problems)
    empty = [p for p in problems if p["lines"] <= 1]
    huge = [p for p in problems if p["lines"] > 60]
    if empty:
        A(f"- 본문이 거의 없는 문제 {len(empty)}개 (경계 오판 가능)")
    if huge:
        A(f"- 본문이 60줄을 넘는 문제 {len(huge)}개 (끝을 못 찾았을 가능성)")
    for w in warns[:25]:
        A(f"- {w}")
    if not warns and not empty and not huge:
        A("- 없음")
    A("")

    A("## 4. 위치를 벗어나 제외한 후보")
    A("")
    A("```")
    for c in dropped_x[:20]:
        A(f"  x={rx(c['line'])} fs={c['line'].get('font_size')} "
          f"p={c['line'].get('_page')} {txt(c['line'])[:60]}")
    if not dropped_x:
        A("  없음")
    A("```")
    A("")

    A(f"## 5. 추출된 문제 (앞 {samples}개)")
    A("")
    for p in problems[:samples]:
        A(f"### [{p['name']} {p['num']}] p{p['page']} "
          f"x={p['x']} 크기={p['font']} 본문{p['lines']}줄 "
          f"그림{len(p['figs'])}장")
        A("")
        A("```")
        for b in p["body"][:18]:
            t = txt(b)
            if is_image_md(t):
                t = f"<그림 {b.get('type')}>"
            A(f"  {str(b.get('type'))[:16]:<16} {t[:76]}")
        if p["lines"] > 18:
            A(f"  ... 외 {p['lines']-18}줄")
        A("```")
        A("")

    A("## 6. 전체 문제 목록")
    A("")
    A("| # | 표기 | 번호 | p | x | 본문줄 | 그림 | 첫 줄 |")
    A("|---|---|---|---|---|---|---|---|")
    for i, p in enumerate(problems, 1):
        A(f"| {i} | {p['name']} | {p['num']} | {p['page']} | {p['x']} | "
          f"{p['lines']} | {len(p['figs'])} | {p['head'][:44]} |")
    A("")

    with open(out_md, "w", encoding="utf-8") as f:
        f.write("\n".join(W))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("stage_dir")
    ap.add_argument("out_md")
    ap.add_argument("--file", default=None, help="특정 파일만")
    ap.add_argument("--samples", type=int, default=12)
    args = ap.parse_args()

    runs = os.path.join(args.stage_dir, "runs")
    if not os.path.isdir(runs):
        sys.exit(f"runs 폴더가 없습니다: {runs}")

    names = sorted(os.listdir(runs))
    if args.file:
        names = [n for n in names if args.file in n]
    if not names:
        sys.exit("대상 파일이 없습니다.")

    all_rows, pw = [], None
    for n in names:
        lj = os.path.join(runs, n, "result.lines.json")
        if not os.path.exists(lj):
            continue
        rows, w = load(lj)
        for r in rows:
            r["_file"] = n
        all_rows.extend(rows)
        if w:
            pw = max(pw or 0, w)

    if not all_rows:
        sys.exit("lines.json 을 찾지 못했습니다.")

    problems, kept, dropped, live, stats = build(all_rows, pw)
    render(problems, kept, dropped, live, all_rows, pw,
           args.out_md, args.samples, stats)

    print(f"완료: {args.out_md}")
    print(f"파일 {len(names)}개 / 줄 {len(all_rows):,} / 문제 {len(problems)}개")
    return 0


if __name__ == "__main__":
    sys.exit(main())
