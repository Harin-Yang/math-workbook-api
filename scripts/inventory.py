#!/usr/bin/env python3
"""
inventory.py
자료 폴더를 훑어 실제 파일 형식을 판별하고 목록을 만든다.
파일을 열거나 고치지 않는다. 읽기만 한다.

사용법 (내 PC, PowerShell):
    python inventory.py "C:\\Users\\didgk\\Downloads\\교과서 모음_문제풀이"

산출:
    화면에 요약 (그대로 복사해 전달)
    inventory.csv 에 전체 목록

필요 패키지:
    pip install pypdf     (없어도 동작. PDF 페이지 수만 생략)
"""

import argparse
import csv
import hashlib
import logging
import os
import sys
import warnings
import zipfile
from collections import Counter, defaultdict

for _n in ("pypdf", "pypdf._reader", "pypdf.generic",
           "pypdf.generic._data_structures", "pypdf.generic._image_inline"):
    logging.getLogger(_n).setLevel(logging.CRITICAL)
warnings.filterwarnings("ignore")

try:
    from pypdf import PdfReader
    HAS_PYPDF = True
except ImportError:
    HAS_PYPDF = False

# 형식별 한글 이름과 처리 가능 여부
KIND_INFO = {
    "hwpx":       ("한글 hwpx", "바로 사용 가능"),
    "docx":       ("워드 docx", "바로 사용 가능"),
    "hwp":        ("한글 hwp (구형)", "hwpx 로 변환 필요"),
    "doc":        ("워드 doc (구형)", "docx 로 변환 필요"),
    "pdf_text":   ("PDF (글자 있음)", "바로 사용 가능"),
    "pdf_scan":   ("PDF (스캔 이미지)", "OCR 필요"),
    "zip_images": ("이미지 묶음", "OCR 필요"),
    "pptx":       ("파워포인트", "변환 필요"),
    "xlsx":       ("엑셀", "대상 아님"),
    "text":       ("텍스트", "바로 사용 가능"),
    "image":      ("낱장 이미지", "OCR 필요"),
    "zip_other":  ("압축파일", "풀어야 함"),
    "unknown":    ("판별 불가", "확인 필요"),
    "error":      ("읽기 실패", "확인 필요"),
}

IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tif")


def sha256_of(path, chunk=4 * 1024 * 1024):
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            while True:
                b = f.read(chunk)
                if not b:
                    break
                h.update(b)
    except OSError:
        return ""
    return h.hexdigest()


def sniff_zip(path):
    """ZIP 계열 안을 들여다보고 실제 종류를 가린다."""
    try:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
    except Exception:
        return "error", 0

    joined = "\n".join(names[:400])

    if "Contents/section0.xml" in joined:
        return "hwpx", 0
    if "mimetype" in names and any("hwp" in n for n in names[:5]):
        return "hwpx", 0
    if any(n.startswith("Contents/") for n in names) and \
            ("settings.xml" in joined or "version.xml" in joined):
        return "hwpx", 0
    if "word/document.xml" in joined:
        return "docx", 0
    if "ppt/presentation.xml" in joined:
        return "pptx", 0
    if "xl/workbook.xml" in joined:
        return "xlsx", 0

    imgs = [n for n in names if n.lower().endswith(IMAGE_EXTS)]
    if imgs and len(imgs) >= max(1, len(names) * 0.5):
        return "zip_images", len(imgs)

    return "zip_other", 0


def sniff_pdf(path):
    if not HAS_PYPDF:
        return "pdf_text", None
    try:
        r = PdfReader(path, strict=False)
        pages = len(r.pages)
        t = ""
        for p in r.pages[:3]:
            t += (p.extract_text() or "")
        return ("pdf_text" if len(t.strip()) > 50 else "pdf_scan"), pages
    except Exception:
        return "error", 0


def sniff(path):
    """반환: (종류, 페이지수 또는 0)"""
    try:
        with open(path, "rb") as f:
            head = f.read(16)
    except OSError:
        return "error", 0

    if head[:4] == b"PK\x03\x04":
        return sniff_zip(path)
    if head[:5] == b"%PDF-":
        return sniff_pdf(path)
    # 한글 hwp 5.0 / 옛 워드 doc = 복합문서(CFB) 형식
    if head[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        ext = os.path.splitext(path)[1].lower()
        if ext in (".doc", ".xls", ".ppt"):
            return "doc", 0
        return "hwp", 0
    if head[:3] == b"\xff\xd8\xff" or head[:8] == b"\x89PNG\r\n\x1a\n":
        return "image", 0

    try:
        with open(path, "rb") as f:
            s = f.read(4096)
        s.decode("utf-8")
        return "text", 0
    except (UnicodeDecodeError, OSError):
        return "unknown", 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("--csv", default="inventory.csv")
    args = ap.parse_args()

    if not os.path.isdir(args.root):
        sys.exit(f"폴더가 없습니다: {args.root}")

    files = []
    for dirpath, _, names in os.walk(args.root):
        for n in sorted(names):
            p = os.path.join(dirpath, n)
            if os.path.isfile(p):
                files.append(p)

    if not files:
        sys.exit("파일이 없습니다.")

    print(f"파일 {len(files)}개 조사 중...\n")

    rows = []
    for i, p in enumerate(files, 1):
        sys.stdout.write(f"\r  [{i}/{len(files)}] {os.path.basename(p)[:44]:<46}")
        sys.stdout.flush()
        kind, pages = sniff(p)
        rows.append({
            "rel": os.path.relpath(p, args.root),
            "name": os.path.basename(p),
            "folder": os.path.dirname(os.path.relpath(p, args.root)) or "(최상위)",
            "ext": os.path.splitext(p)[1].lower(),
            "kind": kind,
            "pages": pages or "",
            "size_mb": round(os.path.getsize(p) / 1024 / 1024, 2),
            "sha256": sha256_of(p),
        })
    sys.stdout.write("\r" + " " * 70 + "\r")

    byhash = defaultdict(list)
    for r in rows:
        if r["sha256"]:
            byhash[r["sha256"]].append(r)
    dups = {k: v for k, v in byhash.items() if len(v) > 1}

    print("=" * 66)
    print("형식별 집계")
    print("=" * 66)
    kc = Counter(r["kind"] for r in rows)
    for k, c in kc.most_common():
        label, action = KIND_INFO.get(k, (k, "?"))
        pg = sum(int(r["pages"]) for r in rows
                 if r["kind"] == k and str(r["pages"]).isdigit())
        pgs = f"  {pg:,}쪽" if pg else ""
        print(f"  {label:<20} {c:>4}개{pgs:<10}  {action}")

    print()
    print("=" * 66)
    print("폴더별")
    print("=" * 66)
    fc = defaultdict(lambda: [0, Counter()])
    for r in rows:
        fc[r["folder"]][0] += 1
        fc[r["folder"]][1][r["kind"]] += 1
    for f, (c, kinds) in sorted(fc.items(), key=lambda x: -x[1][0]):
        top = ", ".join(f"{KIND_INFO.get(k,(k,))[0]} {v}"
                        for k, v in kinds.most_common(3))
        print(f"  {f[:40]:<42} {c:>4}개   {top}")

    print()
    print("=" * 66)
    print("파일 목록")
    print("=" * 66)
    for r in sorted(rows, key=lambda x: (x["folder"], x["name"])):
        label = KIND_INFO.get(r["kind"], (r["kind"],))[0]
        pg = f" {r['pages']}쪽" if r["pages"] else ""
        print(f"  [{label:<14}]{pg:>6}  {r['rel'][:64]}")

    if dups:
        print()
        print("=" * 66)
        print(f"내용이 같은 중복 {len(dups)}건")
        print("=" * 66)
        for g in list(dups.values())[:12]:
            print(f"  {g[0]['name'][:44]}  ({len(g)}개)")
            for r in g:
                print(f"     {r['rel'][:60]}")

    with open(args.csv, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["rel", "name", "folder", "ext",
                                          "kind", "pages", "size_mb",
                                          "sha256"])
        w.writeheader()
        w.writerows(rows)

    print()
    print(f"전체 {len(rows)}개 / 고유 {len(byhash)}개")
    print(f"상세: {os.path.abspath(args.csv)}")
    print()
    print("위 '형식별 집계' 부터 '파일 목록' 까지 복사해서 전달하세요.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
