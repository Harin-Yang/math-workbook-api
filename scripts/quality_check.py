#!/usr/bin/env python3
"""
quality_check.py
처리 가능한 모든 파일(측정 자료 + 실전 테스트 캐시)의 결과물 품질을 한 표로 뽑는다.

무엇을 재는가 — 사람이 고칠 곳을 찾기 위한 지표들이다.
    1. 추출: 문제 수, 표기별 분포, 빈 문제(본문 0줄)·한 줄짜리 문제
    2. 수식: 변환 시도/성공/그림 대체 (라텍스 -> 워드·브라우저 수식)
    3. 경계: 종료 사유 분포 (간격·길이초과가 많으면 경계가 불안하다)
    4. 오독 위험: 문제 본문 안의 저신뢰(0.6 미만) OCR 줄 수와 사례
    5. 부스러기: 표기를 뗀 발문이 문장부호로 시작하는 경우

사용법:
    python3 scripts/quality_check.py [--json] > QUALITY.md
    (실전 테스트 캐시 폴더가 있으면 --extra <폴더> 로 더한다)
"""

import argparse
import glob
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import extract as EX  # noqa: E402
import latex2omml as L  # noqa: E402
import make_docx as MD  # noqa: E402

LOW_CONFIDENCE = 0.6


def check_file(name, path):
    rows, page_width = EX.load(path)
    for row in rows:
        row["_file"] = name
    problems, kept, dropped, live, stats = EX.build(rows, page_width)

    marks = Counter(p["name"] for p in problems)
    reasons = Counter(p["reason"] for p in problems)
    empty = sum(1 for p in problems if len(p["body"]) <= 1 and not p["figs"])

    # 수식 변환률 — 조판기가 하는 그대로 재현한다
    math_try = math_ok = math_fallback = 0
    scrap_heads = []
    low_lines = []
    for p in problems:
        units = MD.merge_lines(list(p["body"]))
        for k, u in enumerate(units):
            if "fig" in u:
                continue
            t = u["text"]
            if k == 0 and t:
                for _n, pat, _k in EX.START_PATTERNS:
                    m = pat.match(t)
                    if m:
                        t = t[m.end():].strip()
                        break
                # 조판기와 같은 청소를 거친 '뒤에도' 남는 부스러기만 결함으로 센다
                t = t.lstrip(" .．)〕]")
                if t and t[0] in ".)．〕]":
                    scrap_heads.append(t[:40])
            if t and (MD.HAS_MATH.search(t)
                      or any(EX.is_display_math(b) for b in u["lines"])):
                math_try += 1
                if MD.to_rich(t) is None:
                    math_fallback += 1
                else:
                    math_ok += 1
        for b in p["body"]:
            c = b.get("confidence")
            if isinstance(c, (int, float)) and c < LOW_CONFIDENCE and EX.txt(b):
                low_lines.append((round(c, 2), EX.txt(b)[:48]))

    low_lines.sort()
    return {
        "file": name,
        "pages": len({r.get("_page") for r in rows}),
        "problems": len(problems),
        "marks": dict(marks),
        "empty_or_one_line": empty,
        "math_try": math_try,
        "math_ok": math_ok,
        "math_fallback": math_fallback,
        "end_reasons": dict(reasons),
        "low_confidence_lines": len(low_lines),
        "low_examples": low_lines[:3],
        "scrap_heads": scrap_heads[:5],
        "scrap_count": len(scrap_heads),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", default="./stage0_out")
    parser.add_argument("--extra", action="append", default=[],
                        help="실전 테스트 캐시처럼 result.lines.json 이 든 폴더")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    targets = []
    runs = os.path.join(args.stage, "runs")
    for name in sorted(os.listdir(runs)):
        path = os.path.join(runs, name, "result.lines.json")
        if os.path.exists(path):
            targets.append((name, path))
    for folder in args.extra:
        for path in sorted(glob.glob(os.path.join(folder, "*", "result.lines.json"))):
            targets.append((f"(실전) {os.path.basename(os.path.dirname(path))[:12]}", path))

    reports = [check_file(name, path) for name, path in targets]

    if args.json:
        print(json.dumps(reports, ensure_ascii=False, indent=1))
        return 0

    out = ["# 품질 점검", ""]
    out.append("| 파일 | 쪽 | 문제 | 빈/한줄 | 수식 성공/시도 | 그림대체 | 저신뢰줄 | 부스러기 |")
    out.append("|---|---|---|---|---|---|---|---|")
    for r in reports:
        out.append(
            f"| {r['file'][:30]} | {r['pages']} | {r['problems']} "
            f"| {r['empty_or_one_line']} | {r['math_ok']}/{r['math_try']} "
            f"| {r['math_fallback']} | {r['low_confidence_lines']} | {r['scrap_count']} |")
    out.append("")
    for r in reports:
        if not (r["low_examples"] or r["scrap_heads"]):
            continue
        out.append(f"## {r['file']}")
        for c, t in r["low_examples"]:
            out.append(f"- 저신뢰 {c}: `{t}`")
        for t in r["scrap_heads"]:
            out.append(f"- 부스러기 발문: `{t}`")
        out.append("")
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
