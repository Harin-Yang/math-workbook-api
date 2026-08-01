#!/usr/bin/env python3
"""
preview.py
추출한 문제를 2단 조판 HTML 로 만든다. 브라우저로 열어 눈으로 검수하는 용도.
Mathpix 재호출 없음 = 비용 0원.

사용법:
    python3 scripts/preview.py ./stage0_out ./PREVIEW.html
    python3 scripts/preview.py ./stage0_out ./PREVIEW.html --file 지수
    python3 scripts/preview.py ./stage0_out ./PREVIEW.html --no-solution

옵션:
    --file          파일명 일부로 대상 교재 한정
    --no-solution   예제의 풀이·답을 빼고 발문만 (시험지용)
    --limit         문제 개수 상한

수식은 MathJax 로 렌더링하므로 인터넷 연결이 있어야 제대로 보인다.
그림은 Mathpix CDN 주소를 그대로 쓴다. (30일 후 만료)
"""

import argparse
import html
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from extract import (load, build, txt, rx, ry, is_image_md,
                     FIGURE_TYPES, SOLUTION)

IMG_MD = re.compile(r"!\[\]\((https?://[^)]+)\)")
IMG_TEX = re.compile(r"\\includegraphics\[[^\]]*\]\{(https?://[^}]+)\}")

CSS = """
:root { --ink:#1a1a1a; --line:#d8d8d8; --accent:#2d6cdf; --warn:#c0392b; }
* { box-sizing: border-box; }
body {
  font-family: 'Malgun Gothic','Apple SD Gothic Neo',sans-serif;
  color: var(--ink); margin:0; padding:0; background:#f4f4f6;
  font-size: 14px; line-height: 1.65;
}
.toolbar {
  position: sticky; top:0; z-index:10; background:#fff;
  border-bottom:1px solid var(--line); padding:10px 20px;
  display:flex; gap:16px; align-items:center; flex-wrap:wrap;
  font-size:13px;
}
.toolbar b { font-size:15px; }
.toolbar label { cursor:pointer; user-select:none; }
.sheet {
  background:#fff; margin:20px auto; padding:26px 30px;
  width: 210mm; min-height: 297mm;
  box-shadow:0 1px 4px rgba(0,0,0,.12);
}
.cols { column-count:2; column-gap:26px; column-rule:1px solid var(--line); }
.q {
  break-inside: avoid; page-break-inside: avoid;
  margin:0 0 20px; padding:0 0 14px;
  border-bottom:1px dashed #e8e8e8;
}
.q-head { font-weight:700; margin-bottom:6px; }
.q-tag {
  display:inline-block; min-width:2.6em; margin-right:6px;
  color:var(--accent); font-weight:700;
}
.q-body p { margin:3px 0; }
.q-body .sub { margin-left:.9em; }
.q-body img { max-width:100%; display:block; margin:8px auto; }
.q-meta {
  font-size:11px; color:#999; margin-top:6px;
}
.q.flag { background:#fff8f8; }
.q.flag .q-meta { color:var(--warn); }
.sol { color:#555; background:#fafafa; padding:4px 8px; margin-top:6px;
       border-left:2px solid #ddd; }
body.hide-sol .sol { display:none; }
body.hide-meta .q-meta { display:none; }
.filehead {
  break-after: column; break-inside: avoid;
  font-size:16px; font-weight:700; margin:0 0 14px;
  padding-bottom:6px; border-bottom:2px solid var(--ink);
  column-span: all;
}
@media print {
  body { background:#fff; }
  .toolbar { display:none; }
  .sheet { box-shadow:none; margin:0; width:auto; padding:12mm; }
}
"""

JS = """
function tog(cls, on){ document.body.classList.toggle(cls, !on); }
"""


def img_urls(t):
    return IMG_MD.findall(t) + IMG_TEX.findall(t)


def to_html(line, keep_solution=True):
    t = txt(line)
    typ = line.get("type")

    if typ in FIGURE_TYPES or is_image_md(t):
        out = []
        for u in img_urls(t):
            out.append(f'<img src="{html.escape(u)}" loading="lazy">')
        return "".join(out)

    if not t:
        return ""

    cls = ""
    if SOLUTION.match(t):
        cls = ' class="sol"'
        if not keep_solution:
            return ""
    elif re.match(r"^\s*[(（\[]\s*\d{1,2}\s*[)）\]]|^\s*[①-⑳]", t):
        cls = ' class="sub"'

    return f"<p{cls}>{html.escape(t)}</p>"


def render(problems, out_path, title, keep_solution, limit):
    if limit:
        problems = problems[:limit]

    parts = []
    A = parts.append

    A("<!doctype html><html lang='ko'><head><meta charset='utf-8'>")
    A(f"<title>{html.escape(title)}</title>")
    A("<script>window.MathJax={tex:{inlineMath:[['\\\\(','\\\\)']],"
      "displayMath:[['\\\\[','\\\\]']]},options:{skipHtmlTags:['script','style']}};"
      "</script>")
    A("<script async src='https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js'></script>")
    A(f"<style>{CSS}</style><script>{JS}</script></head><body>")

    total_fig = sum(len(p["figs"]) + len(p.get("figs_guess") or [])
                    for p in problems)
    A("<div class='toolbar'>")
    A(f"<b>{html.escape(title)}</b>")
    A(f"<span>문제 {len(problems)}개 · 그림 {total_fig}장</span>")
    A("<label><input type='checkbox' checked "
      "onchange=\"tog('hide-sol',this.checked)\"> 풀이·답 보기</label>")
    A("<label><input type='checkbox' checked "
      "onchange=\"tog('hide-meta',this.checked)\"> 진단정보 보기</label>")
    A("<span style='color:#999'>Ctrl+P 로 인쇄하면 실제 2단 조판을 확인할 수 있습니다</span>")
    A("</div>")

    cur_file = None
    open_sheet = False
    for p in problems:
        if p["file"] != cur_file:
            if open_sheet:
                A("</div></div>")
            cur_file = p["file"]
            A("<div class='sheet'>")
            A(f"<div class='filehead'>{html.escape(str(cur_file))}</div>")
            A("<div class='cols'>")
            open_sheet = True

        flag = ""
        notes = []
        if p["lines"] <= 1:
            notes.append("본문 1줄")
        if p.get("figs_guess"):
            notes.append(f"그림 {len(p['figs_guess'])}장 위치추정")
        if p["reason"] in ("길이초과", "페이지초과"):
            notes.append(f"경계 불확실({p['reason']})")
        if p["num_fixed"]:
            notes.append(f"번호 보정 '{p['raw']}'->{p['num']}")
        if notes:
            flag = " flag"

        A(f"<div class='q{flag}'>")
        A(f"<div class='q-head'><span class='q-tag'>"
          f"{html.escape(p['name'])} {p['num']}</span>"
          f"{html.escape(p['head'])}</div>")
        A("<div class='q-body'>")
        for b in p["body"][1:]:
            A(to_html(b, keep_solution))
        for f in (p.get("figs_guess") or []):
            A(to_html(f, keep_solution))
        A("</div>")
        meta = f"p{p['page']} · {p['lines']}줄 · 종료 {p['reason']}"
        if notes:
            meta += " · " + " · ".join(notes)
        A(f"<div class='q-meta'>{html.escape(meta)}</div>")
        A("</div>")

    if open_sheet:
        A("</div></div>")
    A("</body></html>")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(parts))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("stage_dir")
    ap.add_argument("out_html")
    ap.add_argument("--file", default=None)
    ap.add_argument("--no-solution", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
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
    title = args.file if args.file else f"문제 추출 미리보기 ({len(names)}개 교재)"
    render(problems, args.out_html, title,
           not args.no_solution, args.limit)

    print(f"완료: {args.out_html}")
    print(f"문제 {len(problems)}개 / 교재 {len(names)}개")
    return 0


if __name__ == "__main__":
    sys.exit(main())
