#!/usr/bin/env python3
"""
orphan_figs.py
어느 문제에도 안 붙은 그림 214장의 정체를 가른다. Mathpix 호출 없음 = 비용 0원.

사용법:
    python3 scripts/orphan_figs.py --file 기하
    python3 scripts/orphan_figs.py --file 확률과통계 --show 30

무엇을 가르는가
    추출기는 문제 하나를 '줄 몇 번부터 몇 번까지' 로 잡는다.
    그 구간 안에 있던 그림은 문제에 붙고, 밖에 남은 것이 미귀속 그림이다.

    그래서 '어디에 남았는가' 로 가른다.

      문제앞      첫 문제가 나오기 전  → 단원 도입·개념 설명
      문제사이    문제와 다음 문제 사이 → 대개 예제 풀이
      문제뒤      마지막 문제 뒤
      문제없는쪽  그 쪽에서 문제를 하나도 못 뽑았다

    '문제사이' 가 많으면 경계를 너무 일찍 끊었을 가능성이 있으므로
    바로 앞 문제와의 거리도 함께 잰다.
"""

import argparse
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import extract as EX  # noqa: E402


def load_rows(stage, filters):
    runs = os.path.join(stage, "runs")
    if not os.path.isdir(runs):
        sys.exit(f"runs 폴더가 없습니다: {runs}")
    names = sorted(os.listdir(runs))
    if filters:
        names = [n for n in names if any(f in n for f in filters)]
    if not names:
        sys.exit("대상 run 폴더가 없습니다.")

    rows, pw = [], None
    for n in names:
        lj = os.path.join(runs, n, "result.lines.json")
        if not os.path.exists(lj):
            continue
        r, w = EX.load(lj)
        for x in r:
            x["_file"] = n
        rows.extend(r)
        if w:
            pw = max(pw or 0, w)
    if not rows:
        sys.exit("lines.json 을 찾지 못했습니다.")
    return rows, pw, names


def page_widths(rows):
    """쪽마다 픽셀 폭. Mathpix 가 주면 그걸, 없으면 오른쪽 끝으로 역산."""
    out, guess = {}, {}
    for ln in rows:
        key = (ln.get("_file"), ln.get("_page"))
        w = ln.get("_pw")
        if w:
            out[key] = w
            continue
        r = ln.get("region") or {}
        x, ww = r.get("top_left_x"), r.get("width")
        if isinstance(x, (int, float)) and isinstance(ww, (int, float)):
            guess[key] = max(guess.get(key, 0), x + ww)
    for k, v in guess.items():
        out.setdefault(k, v * 1.02)
    return out


def classify(problems, live, orphans):
    """미귀속 그림 하나하나를 네 갈래로 나눈다."""
    pos = {id(ln): i for i, ln in enumerate(live)}

    # 문제마다 (시작 줄 번호, 끝 줄 번호)
    spans = []
    for p in problems:
        idxs = [pos[id(b)] for b in p["body"] if id(b) in pos]
        if idxs:
            spans.append((min(idxs), max(idxs), p))
    spans.sort()

    # 쪽마다 문제가 있는지
    pages_with_problem = {(p["file"], p["page"]) for p in problems}

    out = []
    for f in orphans:
        i = pos.get(id(f))
        key = (f.get("_file"), f.get("_page"))
        prev_p = next_p = None
        for s, e, p in spans:
            if e < i:
                prev_p = (e, p)
            elif s > i and next_p is None:
                next_p = (s, p)

        if key not in pages_with_problem:
            kind = "문제없는쪽"
        elif prev_p is None:
            kind = "문제앞"
        elif next_p is None:
            kind = "문제뒤"
        else:
            kind = "문제사이"

        gap = None
        if prev_p is not None:
            fy = EX.ry(f)
            py = EX.ry(live[prev_p[0]])
            if isinstance(fy, (int, float)) and isinstance(py, (int, float)) \
                    and live[prev_p[0]].get("_page") == f.get("_page"):
                gap = fy - py

        out.append({
            "fig": f, "kind": kind, "idx": i,
            "prev": prev_p[1] if prev_p else None,
            "gap": gap,
        })
    return out


def wratio(f, pws):
    r = f.get("region") or {}
    w = r.get("width")
    pw = pws.get((f.get("_file"), f.get("_page")))
    if isinstance(w, (int, float)) and pw:
        return w / pw
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default="./stage0_out")
    ap.add_argument("--file", action="append", default=[])
    ap.add_argument("--show", type=int, default=15, help="사례 몇 개 보일지")
    args = ap.parse_args()

    rows, pw, names = load_rows(args.stage, args.file)
    problems, kept, dropped, live, st = EX.build(rows, pw)
    pws = page_widths(rows)
    orphans = st["orphan"]

    all_figs = [ln for ln in live if ln.get("type") in EX.FIGURE_TYPES]
    attached = sum(len(p["figs"]) + len(p["figs_guess"]) for p in problems)

    print(f"대상 run 폴더 {len(names)}개")
    for n in names:
        print(f"  {n}")
    print()
    print(f"문제 {len(problems)}개")
    print(f"그림 전체 {len(all_figs)}장 "
          f"= 문제에 붙은 것 {attached}장 + 미귀속 {len(orphans)}장")
    bg = st.get("dropped_bg")
    bg = bg if isinstance(bg, int) else len(bg or [])
    print(f"(폭이 너무 넓어 처음부터 버린 배경 그림 {bg}장은 위 숫자 밖)")
    print()

    items = classify(problems, live, orphans)

    print("== 어디에 남았나 ==")
    by_kind = defaultdict(list)
    for it in items:
        by_kind[it["kind"]].append(it)
    for k in ("문제앞", "문제사이", "문제뒤", "문제없는쪽"):
        v = by_kind.get(k, [])
        if not v:
            continue
        pct = len(v) / len(orphans) if orphans else 0
        print(f"  {k:<10} {len(v):>4}장  ({pct:.1%})")
    print()

    print("== 쪽 단위 ==")
    pages_all = {(ln.get("_file"), ln.get("_page")) for ln in live}
    pages_prob = {(p["file"], p["page"]) for p in problems}
    pages_orph = {(o["fig"].get("_file"), o["fig"].get("_page"))
                  for o in items}
    print(f"  OCR 한 쪽 {len(pages_all)}쪽")
    print(f"  문제를 뽑은 쪽 {len(pages_prob)}쪽")
    print(f"  미귀속 그림이 있는 쪽 {len(pages_orph)}쪽")
    print(f"  └ 그중 문제가 하나도 없는 쪽 {len(pages_orph - pages_prob)}쪽")
    print()

    print("== 크기 ==")
    ws = [w for w in (wratio(o["fig"], pws) for o in items) if w]
    if ws:
        ws.sort()
        big = sum(1 for w in ws if w > 0.45)
        print(f"  쪽 폭 대비 중앙값 {ws[len(ws)//2]:.0%}")
        print(f"  폭 45% 넘는 큰 그림 {big}장 ({big/len(ws):.1%})")
    print()

    print("== 문제사이에 남은 것 — 바로 앞 문제와의 세로 거리 ==")
    betw = [it for it in by_kind.get("문제사이", []) if it["gap"] is not None]
    if betw:
        gaps = sorted(it["gap"] for it in betw)
        near = sum(1 for g in gaps if g < 200)
        print(f"  같은 쪽에서 잰 것 {len(gaps)}장 / 중앙값 {gaps[len(gaps)//2]:.0f}px")
        print(f"  앞 문제에서 200px 안에 붙어 있는 것 {near}장")
        print("  (가까울수록 경계를 일찍 끊어 흘린 것일 가능성이 크다)")
    else:
        print("  없음")
    print()

    print(f"== 사례 (앞 {args.show}개) ==")
    print(f"{'갈래':<10} {'쪽':>4} {'폭':>5}  앞 문제 / 바로 앞 글줄")
    for it in items[:args.show]:
        f = it["fig"]
        w = wratio(f, pws)
        i = it["idx"]
        before = ""
        for j in range(i - 1, max(-1, i - 6), -1):
            t = EX.txt(live[j])
            if t:
                before = t[:46]
                break
        pv = it["prev"]
        tag = f"{pv['name']}{pv['num']}" if pv else "-"
        print(f"{it['kind']:<10} {str(f.get('_page')):>4} "
              f"{(f'{w:.0%}' if w else '?'):>5}  {tag} / {before}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
