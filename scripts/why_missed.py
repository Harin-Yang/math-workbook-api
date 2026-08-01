#!/usr/bin/env python3
"""
why_missed.py
채점에서 '미검출' 로 나온 문제가 왜 빠졌는지 원본 줄에서 찾아 분류한다.
Mathpix 재호출 없음 = 비용 0원.

사용법:
    python3 scripts/why_missed.py --tag 기하 --file 기하
    python3 scripts/why_missed.py --tag 확통 --file 확률과통계

grade.py 가 남긴 grade_out/<태그>.detail.json 의 미검출 목록을 읽어,
각 문제가 OCR 원본의 어느 줄에 해당하는지 찾은 뒤 아래로 나눈다.

  원본에없음   OCR 이 아예 안 읽었다. 추출 룰로는 손댑 수 없다.
  표기있음     '문제 N' 표기가 근처에 있는데 시작으로 안 잡혔다. 룰로 잡을 수 있다.
  흡수됨       앞 문제의 본문에 딸려 들어갔다. 끝 판정 문제다.
  표기없음     지문으로 시작한다. 룰로는 어렵다.

'표기있음' 이 많으면 룰을 더 고칠 여지가 있고,
'표기없음' 이 대부분이면 판정 모델이 필요하다는 뜻이다.
"""

import argparse
import json
import os
import re
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import extract as EX  # noqa: E402

HANGUL = re.compile(r"[가-힣]+")
IMG_MD = re.compile(r"!\[[^\]]*\]\([^)]*\)")
TEX = re.compile(r"\\[A-Za-z]+\*?|\$[^$]*\$|\\\(.*?\\\)|\\\[.*?\\\]", re.S)

NEAR = 3          # 이 줄 수 안에 표기가 있으면 '표기있음'
MIN_SIM = 0.18    # 이 아래면 원본에 없는 것으로 본다


def norm(t):
    t = IMG_MD.sub(" ", t)
    t = TEX.sub(" ", t)
    return "".join(HANGUL.findall(t))


def grams(s, n=3):
    if not s:
        return set()
    if len(s) <= n:
        return {s}
    return {s[i:i + n] for i in range(len(s) - n + 1)}


def sim(a, b):
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if not inter:
        return 0.0
    return inter / (len(a) + len(b) - inter)


def load_lines(stage_dir, filters):
    runs = os.path.join(stage_dir, "runs")
    names = sorted(os.listdir(runs))
    if filters:
        names = [n for n in names if any(f in n for f in filters)]
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
        sys.exit("대상 run 폴더가 없습니다.")
    return rows, pw, names


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--file", action="append", default=[])
    ap.add_argument("--stage", default="./stage0_out")
    ap.add_argument("--outdir", default="./grade_out")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    detail = os.path.join(args.outdir, f"{args.tag}.detail.json")
    if not os.path.exists(detail):
        sys.exit(f"채점 결과가 없습니다: {detail}\n먼저 run_grade.sh 를 돌리세요.")
    with open(detail, encoding="utf-8") as f:
        d = json.load(f)
    missed = d.get("missed", [])
    if not missed:
        print("미검출이 없습니다.")
        return 0

    rows, pw, names = load_lines(args.stage, args.file)
    problems, kept, dropped_x, live, st = EX.build(rows, pw)

    # 이미 어떤 문제의 본문으로 들어간 줄
    inside = {}
    for p in problems:
        for b in p["body"]:
            inside[id(b)] = p

    kept_idx = {c["idx"] for c in kept}
    live_g = [grams(norm(EX.txt(ln))) for ln in live]

    out = []
    for m in missed:
        want = grams(norm(m["ref_head"]))
        best, best_s = -1, 0.0
        for i, g in enumerate(live_g):
            s = sim(want, g)
            if s > best_s:
                best_s, best = s, i

        if best < 0 or best_s < MIN_SIM:
            out.append({**m, "why": "원본에없음", "sim": round(best_s, 2),
                        "where": "", "detail": ""})
            continue

        ln = live[best]
        where = f"{str(ln.get('_file'))[:22]} p{ln.get('_page')}"

        # 근처에 표기가 있는가
        marker = None
        for k in range(max(0, best - NEAR), min(len(live), best + NEAR + 1)):
            mm = EX.match_start(live[k])
            if mm:
                marker = (k, mm[0], mm[1])
                break

        host = inside.get(id(ln))

        if marker and marker[0] not in kept_idx:
            why = "표기있음"
            det = f"'{marker[1]} {marker[2]}' 이 있는데 시작으로 안 잡힘"
        elif host is not None:
            why = "흡수됨"
            det = f"[{host['name']} {host['num']}] p{host['page']} 본문에 딸려 들어감"
        elif marker:
            why = "표기있음"
            det = f"'{marker[1]} {marker[2]}' 이 다른 문제로 잡힘"
        else:
            why = "표기없음"
            det = EX.txt(ln)[:60]

        out.append({**m, "why": why, "sim": round(best_s, 2),
                    "where": where, "detail": det})

    cnt = Counter(o["why"] for o in out)

    W = []
    A = W.append
    A(f"# 미검출 원인 분석 — {args.tag}")
    A("")
    A(f"- 대상 run 폴더 {len(names)}개")
    A(f"- 미검출 {len(out)}개")
    A("")

    A("## 1. 원인별")
    A("")
    A("| 원인 | 개수 | 뜻 |")
    A("|---|---|---|")
    meaning = {
        "원본에없음": "OCR 이 아예 안 읽음. 추출 룰로는 손댑 수 없음",
        "표기있음": "'문제 N' 이 있는데 시작으로 안 잡힘. 룰로 잡을 수 있음",
        "흡수됨": "앞 문제 본문에 딸려 들어감. 끝 판정 문제",
        "표기없음": "지문으로 시작. 룰로는 어려움",
    }
    for w, n in cnt.most_common():
        A(f"| {w} | {n} | {meaning.get(w,'')} |")
    A("")

    for w, _ in cnt.most_common():
        rows_w = [o for o in out if o["why"] == w]
        A(f"## {w} ({len(rows_w)}개)")
        A("")
        A("| 기준번호 | 쪽 | 닮음 | 위치 | 설명 | 첫 줄 |")
        A("|---|---|---|---|---|---|")
        for o in rows_w:
            A(f"| {o['ref_num']} | {o['ref_page']} | {o['sim']} | "
              f"{o['where']} | {o['detail'][:48]} | {o['ref_head'][:34]} |")
        A("")

    out_md = args.out or os.path.join(args.outdir, f"WHY_{args.tag}.md")
    with open(out_md, "w", encoding="utf-8") as f:
        f.write("\n".join(W))

    print(f"완료: {out_md}")
    print(" / ".join(f"{w} {n}" for w, n in cnt.most_common()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
