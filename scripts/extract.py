#!/usr/bin/env python3
"""
extract.py  v2
lines.json 에서 문제만 골라낸다. Mathpix 재호출 없음 = 비용 0원.

사용법:
    python3 scripts/extract.py ./stage0_out ./EXTRACT.md

v1 에서 고친 것:
  1. 파일 경계를 넘어 다음 교재까지 빨아들이던 버그 (782줄/917줄 문제)
  2. x 위치 학습을 전체 통합 -> 파일별로 (편집이 다른 교재가 통째로 제외되던 문제)
  3. 번호 파싱: '문제 9100 이상' -> 9 로 보정 (OCR 이 번호와 본문을 붙여 읽음)
  4. 문제의 '끝'을 능동 판정: 발문의 명령형 어미 + 소문항 그룹으로 경계 확정
"""

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict

# ---- 문제 시작 표기 ----
# 번호는 넉넉히 읽고 뒤에서 시퀀스로 보정한다.
START_PATTERNS = [
    ("문제", re.compile(r"^\s*문제\s*(\d{1,4})"),                 "문제"),
    ("예제", re.compile(r"^\s*(?:필수\s*)?예제\s*(\d{1,4})"),      "예제"),
    ("유제", re.compile(r"^\s*유제\s*(\d{1,4})"),                 "유제"),
    ("탐구", re.compile(r"^\s*(?:탐구|밤구)\s*[\(（]?\s*(\d{1,3})"), "탐구"),
    ("유형", re.compile(r"^\s*유형\s*(\d{1,3})"),                 "유형"),
    ("확인", re.compile(r"^\s*확인\s*문제\s*(\d{1,3})"),           "문제"),
    ("두자리", re.compile(r"^\s*(0\d)(?!\d)"),                    "번호"),
]

# 발문 끝을 알리는 명령형 어미.
# 어미 뒤에 '(단, a>0)' 같은 단서 괄호가 붙어도 발문의 끝으로 본다.
ORDER_END = re.compile(
    r"(?:시오|하라|보자|구해라|말해라)"
    r"\s*[.．,，]?\s*"
    r"(?:[(（][^)）]{0,60}[)）])?"
    r"\s*[.．]?\s*$")

# 소문항 표기
SUB_ITEM = re.compile(r"^\s*[(（\[]\s*\d{1,2}\s*[)）\]]|^\s*[①-⑳]|^\s*[⑴-⒇]")

# 예제의 풀이/답
SOLUTION = re.compile(r"^\s*(풀이|답|정답)\b|^\s*(풀이|답|정답)\s")

BODY_TYPES = {"text", "math", "list_item", "multiple_choice_block",
              "multiple_choice_option", "section_header", "equation_number",
              "table", "simple_cell", "complex_cell", "table_row",
              "table_column", "form_field", "figure_label"}

DROP_TYPES = {"page_info"}
FIGURE_TYPES = {"diagram", "chart"}

# 이어붙는 줄 (한 문장이 여러 줄로 쪼개진 것)
CONTINUE_SUBTYPES = {"continues_line_space", "continues_line_no_space",
                     "continues_line_newline"}

MAX_TITLE_FONT = 60
FIGURE_MAX_WIDTH_RATIO = 0.75
MAX_BODY_LINES = 60          # 이보다 길면 끝을 못 찾은 것으로 보고 자름
MAX_PAGE_SPAN = 1            # 문제 하나가 걸칠 수 있는 페이지 넘김 횟수


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
            rows.append(d)
    return rows, (max(widths) if widths else None)


def rx(ln):
    return (ln.get("region") or {}).get("top_left_x")


def ry(ln):
    return (ln.get("region") or {}).get("top_left_y")


def rw(ln):
    return (ln.get("region") or {}).get("width")


def txt(ln):
    return (ln.get("text") or ln.get("text_display") or "").strip()


def is_image_md(t):
    return t.startswith("![](") or "\\includegraphics" in t


def is_display_math(ln):
    t = txt(ln)
    return ln.get("type") == "math" or t.startswith("\\[") or t.startswith("$$")


def match_start(ln):
    t = txt(ln)
    if not t or is_image_md(t):
        return None
    fs = ln.get("font_size")
    if isinstance(fs, (int, float)) and fs > MAX_TITLE_FONT:
        return None
    for name, pat, kind in START_PATTERNS:
        m = pat.match(t)
        if m:
            return name, m.group(1), kind, t
    return None


def fix_number(raw, prev):
    """
    OCR 이 번호와 본문을 붙여 읽은 것을 앞 번호 흐름으로 보정한다.

    앞에서부터 한 자리씩 늘려 후보를 만들고,
      1순위: 직전 번호 + 1 과 정확히 일치하는 후보
      2순위: 직전 번호보다 큰 후보 중 가장 작은 것
    을 택한다.

      직전 8 + '9100' -> 9      (문제 9 / 100 이상 ...)
      직전 2 + '33'   -> 3      (문제 3 / 3개의 ...)
      직전 13 + '14'  -> 14     (정상)
      직전 9 + '10'   -> 10     (정상)
      첫 문제 + '12'  -> 1      (예제 1 / 2명의 ...)
    """
    if raw is None:
        return None, False
    cands = [int(raw[:k]) for k in range(1, len(raw) + 1)]

    want = (prev + 1) if prev is not None else None
    if want is not None and want in cands:
        pick = want
    elif prev is not None:
        bigger = [c for c in cands if c > prev]
        pick = min(bigger) if bigger else cands[0]
    else:
        pick = cands[0]

    return pick, (pick != cands[-1])


def find_end(live, start, hard_end, kind):
    """
    문제의 끝 위치를 찾는다. start 는 발문 줄 인덱스.
    반환: (끝 인덱스(미포함), 종료 사유)
    """
    head = live[start]
    head_file = head.get("_file")
    seen_order = bool(ORDER_END.search(txt(head)))

    i = start + 1
    page_span = 0
    prev_page = head.get("_page")

    while i < hard_end:
        ln = live[i]
        t = txt(ln)
        typ = ln.get("type")

        # 파일이 바뀌면 무조건 종료
        if ln.get("_file") != head_file:
            return i, "파일경계"

        # 페이지 넘김 한도
        pg = ln.get("_page")
        if isinstance(pg, int) and isinstance(prev_page, int) and pg != prev_page:
            page_span += 1
            prev_page = pg
            if page_span > MAX_PAGE_SPAN:
                return i, "페이지초과"

        # 개념 설명 시작
        if typ == "section_header":
            return i, "단원제목"

        # 길이 한도
        if i - start >= MAX_BODY_LINES:
            return i, "길이초과"

        # 그림/수식/이어붙는 줄/빈 줄은 항상 포함
        if typ in FIGURE_TYPES or is_display_math(ln) or not t:
            i += 1
            continue
        if ln.get("subtype") in CONTINUE_SUBTYPES:
            i += 1
            continue

        # 소문항은 항상 포함
        if SUB_ITEM.match(t):
            i += 1
            continue

        # 예제/유제는 풀이·답까지 포함
        if kind in ("예제", "유제") and SOLUTION.match(t):
            i += 1
            continue

        if not seen_order:
            # 아직 발문이 안 끝났다 -> 계속 읽는다
            i += 1
            if ORDER_END.search(t):
                seen_order = True
            continue

        # 발문이 끝났는데 소문항이 아닌 서술문 -> 여기서 종료
        return i, "본문종료"

    return hard_end, "다음문제"


def build(rows, page_width):
    figmax = page_width * FIGURE_MAX_WIDTH_RATIO if page_width else None

    # 1) 버릴 줄
    live, dropped_bg = [], 0
    for ln in rows:
        if ln.get("type") in DROP_TYPES:
            continue
        if ln.get("conversion_output") is False:
            continue
        if ln.get("type") in FIGURE_TYPES and figmax:
            w = rw(ln)
            if isinstance(w, (int, float)) and w > figmax:
                dropped_bg += 1
                continue
        live.append(ln)

    # 2) 읽기 순서
    live.sort(key=lambda ln: (
        ln.get("_file") or "",
        ln.get("_page") or 0,
        ln.get("line") if isinstance(ln.get("line"), int) else 10 ** 6,
        ry(ln) or 0))

    # 3) 시작 후보
    cands = []
    for i, ln in enumerate(live):
        if ln.get("parent_id"):
            continue
        if ln.get("type") not in BODY_TYPES:
            continue
        m = match_start(ln)
        if m:
            cands.append({"idx": i, "line": ln, "name": m[0],
                          "raw": m[1], "kind": m[2]})

    # 4) 파일별 x 대역 학습
    byfile = defaultdict(list)
    for c in cands:
        byfile[c["line"].get("_file")].append(c)

    bands = {}
    for fname, cs in byfile.items():
        xs = [rx(c["line"]) for c in cs
              if isinstance(rx(c["line"]), (int, float))]
        if not xs:
            bands[fname] = None
            continue
        b = Counter(int(x // 50) for x in xs)
        top = b.most_common(1)[0][0]
        bands[fname] = ((top + 0.5) * 50, 90)

    kept, dropped_x = [], []
    for c in cands:
        band = bands.get(c["line"].get("_file"))
        x = rx(c["line"])
        if band is None or not isinstance(x, (int, float)) \
                or abs(x - band[0]) <= band[1]:
            kept.append(c)
        else:
            dropped_x.append(c)

    # 5) 번호 보정 (파일 + 표기별로 흐름 추적)
    prev = {}
    for c in kept:
        key = (c["line"].get("_file"), c["name"])
        num, fixed = fix_number(c["raw"], prev.get(key))
        c["num"] = num
        c["num_fixed"] = fixed
        if num is not None:
            prev[key] = num

    # 6) 경계 확정
    problems = []
    used_fig = set()
    for n, c in enumerate(kept):
        start = c["idx"]
        hard = kept[n + 1]["idx"] if n + 1 < len(kept) else len(live)
        end, reason = find_end(live, start, hard, c["kind"])
        body = live[start:end]
        figs = [b for b in body if b.get("type") in FIGURE_TYPES]
        for f in figs:
            used_fig.add(id(f))
        problems.append({
            "name": c["name"], "num": c["num"], "raw": c["raw"],
            "num_fixed": c["num_fixed"], "kind": c["kind"],
            "file": c["line"].get("_file"),
            "page": c["line"].get("_page"),
            "x": rx(c["line"]), "font": c["line"].get("font_size"),
            "head": txt(c["line"])[:90],
            "body": body, "lines": len(body),
            "figs": figs, "reason": reason,
            "trimmed": hard - end,
        })

    orphan = [ln for ln in live
              if ln.get("type") in FIGURE_TYPES and id(ln) not in used_fig]

    return problems, kept, dropped_x, live, {
        "dropped_bg": dropped_bg, "orphan": orphan, "bands": bands}


def check_sequence(problems):
    warns = []
    groups = defaultdict(list)
    for p in problems:
        if p["num"] is not None:
            groups[(p["file"], p["name"])].append(p["num"])
    for (fname, name), nums in groups.items():
        run = []
        for v in nums:
            if run and v <= run[-1]:
                gaps = sorted(set(range(run[0], run[-1] + 1)) - set(run))
                if gaps:
                    warns.append(
                        f"[{str(fname)[:24]}] {name} {run[0]}~{run[-1]} 결손 {gaps[:12]}")
                run = [v]
            else:
                run.append(v)
        if run:
            gaps = sorted(set(range(run[0], run[-1] + 1)) - set(run))
            if gaps:
                warns.append(
                    f"[{str(fname)[:24]}] {name} {run[0]}~{run[-1]} 결손 {gaps[:12]}")
    return warns


def render(problems, kept, dropped_x, live, rows, pw, out_md, samples, st):
    W = []
    A = W.append

    A("# 문제 추출 결과 v2")
    A("")
    A(f"- 전체 줄 {len(rows):,} -> 유효 줄 {len(live):,}")
    A(f"- 시작 후보 {len(kept)+len(dropped_x)} -> 채택 {len(kept)} "
      f"/ 위치이탈 제외 {len(dropped_x)}")
    A(f"- 추출 문제 {len(problems)}개")
    A("")

    A("## 1. 표기별")
    A("")
    A("| 표기 | 개수 | 본문줄 중앙 | 본문줄 최대 | 그림 |")
    A("|---|---|---|---|---|")
    byname = defaultdict(list)
    for p in problems:
        byname[p["name"]].append(p)
    for name, ps in sorted(byname.items(), key=lambda kv: -len(kv[1])):
        ls = sorted(p["lines"] for p in ps)
        A(f"| {name} | {len(ps)} | {ls[len(ls)//2]} | {ls[-1]} | "
          f"{sum(len(p['figs']) for p in ps)} |")
    A("")

    A("## 2. 경계 종료 사유")
    A("")
    A("| 사유 | 문제 수 |")
    A("|---|---|")
    for r, c in Counter(p["reason"] for p in problems).most_common():
        A(f"| {r} | {c} |")
    A("")

    A("## 3. 번호 보정")
    A("")
    fixed = [p for p in problems if p["num_fixed"]]
    A(f"- 보정된 번호 {len(fixed)}건")
    if fixed:
        A("")
        A("```")
        for p in fixed[:15]:
            A(f"  '{p['raw']}' -> {p['num']}   {p['head'][:56]}")
        A("```")
    A("")

    A("## 4. 경고")
    A("")
    warns = check_sequence(problems)
    empty = [p for p in problems if p["lines"] <= 1]
    huge = [p for p in problems if p["lines"] >= MAX_BODY_LINES]
    if empty:
        A(f"- 본문이 거의 없는 문제 {len(empty)}개")
    if huge:
        A(f"- 길이 한도에 걸린 문제 {len(huge)}개 (끝을 못 찾음)")
    A(f"- 어느 문제에도 안 붙은 그림 {len(st['orphan'])}장")
    for w in warns[:20]:
        A(f"- {w}")
    if not (warns or empty or huge or st["orphan"]):
        A("- 없음")
    A("")

    A("## 5. 파일별 x 대역")
    A("")
    A("| 파일 | 중심 x | 문제 수 |")
    A("|---|---|---|")
    cnt = Counter(p["file"] for p in problems)
    for f, band in st["bands"].items():
        A(f"| {str(f)[:36]} | {band[0] if band else '-'} | {cnt.get(f,0)} |")
    A("")

    A("## 6. 위치를 벗어나 제외한 후보")
    A("")
    A("```")
    for c in dropped_x[:20]:
        A(f"  x={rx(c['line'])} p={c['line'].get('_page')} "
          f"{txt(c['line'])[:64]}")
    if not dropped_x:
        A("  없음")
    A("```")
    A("")

    A(f"## 7. 추출된 문제 (앞 {samples}개)")
    A("")
    for p in problems[:samples]:
        A(f"### [{p['name']} {p['num']}] p{p['page']} "
          f"본문{p['lines']}줄 그림{len(p['figs'])}장 "
          f"종료={p['reason']}")
        A("")
        A("```")
        for b in p["body"][:20]:
            t = txt(b)
            if is_image_md(t):
                t = "<그림>"
            A(f"  {str(b.get('type'))[:14]:<14} {t[:74]}")
        if p["lines"] > 20:
            A(f"  ... 외 {p['lines']-20}줄")
        A("```")
        A("")

    A("## 8. 전체 목록")
    A("")
    A("| # | 표기 | 번호 | p | 본문줄 | 그림 | 종료 | 첫 줄 |")
    A("|---|---|---|---|---|---|---|---|")
    for i, p in enumerate(problems, 1):
        A(f"| {i} | {p['name']} | {p['num']} | {p['page']} | "
          f"{p['lines']} | {len(p['figs'])} | {p['reason']} | "
          f"{p['head'][:40]} |")
    A("")

    with open(out_md, "w", encoding="utf-8") as f:
        f.write("\n".join(W))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("stage_dir")
    ap.add_argument("out_md")
    ap.add_argument("--file", default=None)
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

    problems, kept, dropped, live, st = build(all_rows, pw)
    render(problems, kept, dropped, live, all_rows, pw,
           args.out_md, args.samples, st)

    print(f"완료: {args.out_md}")
    print(f"파일 {len(names)}개 / 줄 {len(all_rows):,} / 문제 {len(problems)}개")
    return 0


if __name__ == "__main__":
    sys.exit(main())
