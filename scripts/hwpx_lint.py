#!/usr/bin/env python3
"""
hwpx_lint.py
만든 HWPX 를 열어 보지 않고도 구조를 검수한다 (한/글 없이 잡을 수 있는 것 전부).

사용법:
    python3 scripts/hwpx_lint.py <파일.hwpx> [작업문서.json]

검사 항목:
  1. XML 문법 (section0, header, content.hpf)
  2. 참조 무결성 — charPrIDRef/paraPrIDRef/borderFillIDRef 가 header 에 있는가
  3. 그림 — hp:pic 수 = BinData 수 = manifest 항목 수, binaryItemIDRef 연결
  4. 2단 설정 (colCount=2)
  5. 수식 — script 비어 있지 않은가, 폭이 단 폭을 넘지 않는가
  6. 작업 문서를 주면: 문제 라벨 수·수식 수·그림 수가 문서와 맞는가
  7. 조판 잣대 — 곁그림(문제 우측상단)이 본문 흐름(treatAsChar=1)으로
     들어가 있으면 경고 (미리보기와 다른 배치)

결과: 문제 없으면 "통과", 있으면 항목별로 찍는다. 종료 코드 0/1.
"""

import json
import re
import sys
import zipfile
from xml.etree import ElementTree

EQ_MAX_WIDTH = 20268   # 2단 한 단의 글 너비 (hwpxexport 와 같은 값)
MATH = re.compile(r"\\\((.*?)\\\)", re.S)


def lint(hwpx_path, doc_path=None):
    problems = []
    warns = []
    with zipfile.ZipFile(hwpx_path) as z:
        names = z.namelist()
        sec = z.read("Contents/section0.xml").decode("utf-8")
        hdr = z.read("Contents/header.xml").decode("utf-8")
        hpf = z.read("Contents/content.hpf").decode("utf-8")
        bindata = [n for n in names if n.startswith("BinData/")]

    # 1. XML 문법
    for label, xml in (("section0", sec), ("header", hdr), ("content.hpf", hpf)):
        try:
            ElementTree.fromstring(xml)
        except ElementTree.ParseError as e:
            problems.append(f"XML 깨짐({label}): {e}")

    # 2. 참조 무결성
    char_ids = set(re.findall(r'<hh:charPr id="(\d+)"', hdr))
    para_ids = set(re.findall(r'<hh:paraPr id="(\d+)"', hdr))
    fill_ids = set(re.findall(r'<hh:borderFill id="(\d+)"', hdr))
    for ref, pool, name in (
        ("charPrIDRef", char_ids, "글자 서식"),
        ("paraPrIDRef", para_ids, "문단 서식"),
        ("borderFillIDRef", fill_ids, "테두리 서식"),
    ):
        used = set(re.findall(rf'{ref}="(\d+)"', sec))
        missing = used - pool
        if missing:
            problems.append(f"{name} 미정의 참조: {sorted(missing)}")

    # 3. 그림 연결
    pics = re.findall(r"<hp:pic[ >]", sec)
    img_refs = re.findall(r'binaryItemIDRef="([^"]+)"', sec)
    manifest = re.findall(r'<opf:item id="([^"]+)"', hpf)
    if len(pics) != len(bindata):
        problems.append(f"그림 수 불일치: 본문 {len(pics)} vs BinData {len(bindata)}")
    dangling = [r for r in img_refs if not any(r in m for m in manifest)]
    if dangling:
        problems.append(f"manifest 에 없는 그림 참조: {dangling[:5]}")

    # 3-2. 줄 좌표 금지 — 진품에는 없고, 넣으면 '문서 손상·변조 의심' 경고가
    #      뜬다 (실물 사고 2회: 측정판 시절 + 2026-08-13 v15). 영구 금지.
    if "linesegarray" in sec:
        problems.append("linesegarray 발견 — 한/글이 손상·변조 의심 경고를 띄운다 (금지)")

    # 4. 2단
    cols = re.findall(r'colCount="(\d+)"', sec)
    if "2" not in cols:
        problems.append(f"2단 설정 없음 (colCount={cols or '없음'})")

    # 5. 수식
    scripts = re.findall(r"<hp:script>(.*?)</hp:script>", sec, re.S)
    empty = sum(1 for s in scripts if not s.strip())
    if empty:
        problems.append(f"빈 수식 {empty}개")
    eq_widths = [int(w) for w in re.findall(
        r'<hp:equation[^>]*>\s*<hp:sz width="(\d+)"', sec)]
    wide = [w for w in eq_widths if w > EQ_MAX_WIDTH]
    if wide:
        problems.append(f"단 폭을 넘는 수식 {len(wide)}개 (최대 {max(wide)})")

    # 7. 곁그림 배치 잣대
    inline_pics = len(re.findall(
        r'<hp:pic[^>]*>(?:(?!</hp:pic>).)*?treatAsChar="1"', sec, re.S))
    if inline_pics:
        warns.append(f"그림 {inline_pics}장이 본문 흐름(inline) — 미리보기의 "
                     f"우측상단 곁그림 배치와 다르다")

    # 6. 작업 문서 대조
    if doc_path:
        doc = json.load(open(doc_path, encoding="utf-8"))
        live = [p for p in doc.get("problems", []) if not p.get("deleted")]
        want_eq = sum(len(MATH.findall(u.get("text") or ""))
                      for p in live for u in p.get("units", [])
                      if u.get("kind") == "text")
        want_pic = sum(1 for p in live for u in p.get("units", [])
                       if u.get("kind") != "text")
        labels = sum(1 for p in live if (p.get("label") or "").strip())
        # 라벨 문단은 라벨 글자 서식(굵은 청색)으로만 나온다
        label_paras = len(re.findall(r'charPrIDRef="8"', sec))
        if label_paras < labels:
            problems.append(f"문제 라벨 문단 부족: 문서 {labels} vs 본문 {label_paras}")
        n_eq = len(re.findall(r"<hp:equation[ >]", sec))
        if n_eq < want_eq:
            problems.append(f"수식 부족: 문서 {want_eq} vs 본문 {n_eq}"
                            f" (변환 실패 {want_eq - n_eq}건이 글자로 남음)")
        if len(pics) < want_pic:
            problems.append(f"그림 부족: 문서 {want_pic} vs 본문 {len(pics)}")

    return problems, warns


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    problems, warns = lint(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
    for w in warns:
        print(f"[주의] {w}")
    if problems:
        for p in problems:
            print(f"[문제] {p}")
        sys.exit(1)
    print("통과 — 구조 검수에서 잡힌 문제 없음")


if __name__ == "__main__":
    main()
