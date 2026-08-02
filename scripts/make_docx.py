#!/usr/bin/env python3
"""
make_docx.py
추출한 문제를 좌우 2단 워드 문서로 조판한다. Mathpix 재호출 없음 = 비용 0원.

사용법:
    python3 scripts/make_docx.py --file 기하 --out out/기하.docx
    python3 scripts/make_docx.py --file 확률과통계 --out out/확통.docx --answer-lines 5

수식을 어떻게 넣는가
    지금은 '원본 페이지에서 그 자리를 오려낸 그림' 으로 넣는다.
    Mathpix 가 모든 줄의 좌표를 주므로 원본 PDF 의 그 사각형만 그려내면 된다.

    대신 그 줄은 편집할 수 없다. 수식을 한/글에서 고칠 수 있어야 하면
    LaTeX -> OMML 변환기를 붙여야 하는데, 그건 조판이 통과된 뒤에 한다.
    수식이 없는 줄은 진짜 글자로 들어가므로 편집된다.

크기를 어떻게 맞추는가
    오려낸 조각을 각자 원본 크기대로 넣으면 크기가 들쎄날쎄해진다.
    파일마다 '본문 한 줄이 껉 찹을 때의 폭' 을 배워 그걸 칼럼 폭에 맞춘다.
    원본에서의 상대 크기가 그대로 유지된다.

필요한 것
    pip install python-docx pymupdf
    원본 PDF 가 samples/테스트자료_스캔본/<run 폴더 이름>.pdf 에 있어야 한다.
"""

import argparse
import os
import re
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import extract as EX  # noqa: E402

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None

try:
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml.ns import qn
    from docx.shared import Mm, Pt, RGBColor
except ImportError:
    Document = None

# 수식이 들어 있는 줄인지
HAS_MATH = re.compile(r"\\\(|\\\[|\$|\\begin\{|\\frac|\\sqrt|\\overline|"
                      r"\\mathrm|\\vec|\\overrightarrow|\\angle|\\triangle")

PAD = 6            # 오려낼 때 사방으로 남길 여백 (픽셀)
A4_W_MM = 210
MARGIN_MM = 14
GAP_MM = 7


def col_width_mm():
    return (A4_W_MM - MARGIN_MM * 2 - GAP_MM) / 2


def find_source_pdf(pdf_dirs, run_name):
    """run 폴더 이름과 같은 이름의 원본 PDF 를 찾는다."""
    for d in pdf_dirs:
        if not os.path.isdir(d):
            continue
        for ext in (".pdf", ".PDF"):
            p = os.path.join(d, run_name + ext)
            if os.path.exists(p):
                return p
        for n in os.listdir(d):
            if n.lower().endswith(".pdf") and os.path.splitext(n)[0] == run_name:
                return os.path.join(d, n)
    return None


def learn_body_width(rows):
    """파일마다 '본문 한 줄이 껉 찹을 때의 픽셀 폭' 을 배운다.

    오려낸 조각을 각자 원본 크기대로 넣으면 크기가 들쎄날쎄해진다.
    본문 폭을 칼럼 폭에 맞춰 두면 원본에서의 상대 크기가 그대로 유지된다.
    (원본에서 한 줄을 껉 채우던 것은 칼럼도 껉 채우고, 절반짜리는 절반)

    큰 그림이 폭을 부풀리지 않게 위쪽 10% 는 버리고 그 다음 값을 쓴다.
    """
    per = defaultdict(list)
    for ln in rows:
        if ln.get("type") in EX.FIGURE_TYPES:
            continue
        w = (ln.get("region") or {}).get("width")
        if isinstance(w, (int, float)) and w > 0:
            per[ln.get("_file")].append(w)
    out = {}
    for fname, ws in per.items():
        ws.sort()
        out[fname] = ws[int(len(ws) * 0.90)] if ws else None
    return out


def learn_page_widths(rows):
    """쪽마다 픽셀 폭을 정한다. 반환: {(파일, 쪽): 폭}

    Mathpix 가 page_width 를 주면 그걸 쓴다.
    없으면 그 쪽 줄들의 오른쪽 끝 최댓값으로 역산한다.
    """
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
    for key, v in guess.items():
        if key not in out:
            out[key] = v * 1.02
    return out


class Cropper:
    """원본 PDF 에서 필요한 사각형만 그려낸다."""

    def __init__(self, pdf_dirs, out_dir, body_widths=None):
        self.pdf_dirs = pdf_dirs
        self.out_dir = out_dir
        self.body_widths = body_widths or {}
        self.docs = {}       # run 이름 -> fitz.Document (없으면 None)
        self.pix = {}        # (run, page) -> (page, scale, 폭, 높이)
        self.n = 0
        self.fail = {}       # 실패 사유별 건수
        os.makedirs(out_dir, exist_ok=True)

    def note(self, why):
        self.fail[why] = self.fail.get(why, 0) + 1

    def doc_for(self, run_name):
        if run_name in self.docs:
            return self.docs[run_name]
        path = find_source_pdf(self.pdf_dirs, run_name)
        d = None
        if path and fitz:
            try:
                d = fitz.open(path)
            except Exception:
                d = None
        self.docs[run_name] = d
        return d

    def page_of(self, run_name, page_no, image_width):
        """(페이지, 배율, 픽셀폭, 픽셀높이). 못 얻으면 첫 값이 None.

        페이지 전체를 미리 그려두지 않는다. PyMuPDF 1.28 에서
        fitz.Pixmap(pixmap, IRect) 로 잘라내기가 깨져서,
        필요한 사각형만 clip 으로 바로 그리는 방식으로 바꿨다.
        """
        key = (run_name, page_no)
        if key in self.pix:
            return self.pix[key]
        d = self.doc_for(run_name)
        out = (None, 1.0, 0, 0)
        if d is not None and isinstance(page_no, int) \
                and 1 <= page_no <= d.page_count and image_width:
            pg = d[page_no - 1]
            scale = image_width / pg.rect.width
            out = (pg, scale,
                   int(round(pg.rect.width * scale)),
                   int(round(pg.rect.height * scale)))
        self.pix[key] = out
        return out

    def crop(self, ln, image_width):
        """줄 하나를 오려 PNG 로 저장한다. 반환: (경로, 폭 mm) 또는 None"""
        if fitz is None:
            self.note("pymupdf없음")
            return None
        r = ln.get("region") or {}
        x, y = r.get("top_left_x"), r.get("top_left_y")
        w, h = r.get("width"), r.get("height")
        if not all(isinstance(v, (int, float)) for v in (x, y, w, h)):
            self.note("좌표없음")
            return None
        if w <= 0 or h <= 0:
            self.note("크기0")
            return None
        if not image_width:
            self.note("쪽폭모름")
            return None

        pg, scale, pw_px, ph_px = self.page_of(ln.get("_file"),
                                               ln.get("_page"), image_width)
        if pg is None:
            self.note("원본쪽없음")
            return None

        x0 = max(0, int(x) - PAD)
        y0 = max(0, int(y) - PAD)
        x1 = min(pw_px, int(x + w) + PAD)
        y1 = min(ph_px, int(y + h) + PAD)
        if x1 <= x0 or y1 <= y0:
            self.note("범위밖")
            return None

        # 픽셀 사각형을 원본 점 단위로 되돌려 그 부분만 그린다
        clip = fitz.Rect(x0 / scale, y0 / scale, x1 / scale, y1 / scale)
        try:
            sub = pg.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=clip)
        except Exception as e:
            self.note(f"자르기실패({type(e).__name__})")
            return None

        self.n += 1
        path = os.path.join(self.out_dir, f"crop_{self.n:05d}.png")
        try:
            sub.save(path)
        except Exception as e:
            self.note(f"저장실패({type(e).__name__})")
            return None

        # 크기 환산.
        # 본문 폭을 배웠으면 그걸 칼럼 폭에 맞춘다. 원본에서의 상대 크기가 유지된다.
        # 못 배워으면 원본의 실제 물리 크기(점 -> mm)로 넣는다.
        body = self.body_widths.get(ln.get("_file"))
        if body:
            mm = (x1 - x0) / body * col_width_mm()
        else:
            mm = (x1 - x0) / scale * 25.4 / 72
        return path, mm


def set_two_columns(section, gap_mm=GAP_MM):
    """구역을 2단으로 만든다. python-docx 에 기능이 없어 XML 을 직접 건드린다."""
    sectPr = section._sectPr
    found = sectPr.xpath("./w:cols")
    if found:
        cols = found[0]
    else:
        cols = sectPr.makeelement(qn("w:cols"), {})
        sectPr.append(cols)
    cols.set(qn("w:num"), "2")
    cols.set(qn("w:space"), str(int(gap_mm * 56.7)))   # mm -> twips
    cols.set(qn("w:equalWidth"), "1")


def set_border(p, edge="bottom", size=6, color="BBBBBB"):
    """문단에 선을 하나 긋는다. 문제 사이를 눈으로 가르는 용도."""
    pPr = p._p.get_or_add_pPr()
    found = pPr.xpath("./w:pBdr")
    if found:
        bdr = found[0]
    else:
        bdr = pPr.makeelement(qn("w:pBdr"), {})
        pPr.append(bdr)
    el = bdr.makeelement(qn(f"w:{edge}"), {})
    el.set(qn("w:val"), "single")
    el.set(qn("w:sz"), str(size))
    el.set(qn("w:space"), "2")
    el.set(qn("w:color"), color)
    bdr.append(el)


def add_label(doc, text):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(10)
    p.paragraph_format.space_after = Pt(2)
    p.paragraph_format.keep_with_next = True
    run = p.add_run(text)
    run.bold = True
    run.font.size = Pt(9)
    run.font.color.rgb = RGBColor(0x55, 0x55, 0x55)
    return p


def add_text(doc, text, keep=True):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(2)
    p.paragraph_format.keep_with_next = keep
    run = p.add_run(text)
    run.font.size = Pt(10)
    return p


def add_image(doc, path, width_mm, keep=True):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(1)
    p.paragraph_format.space_after = Pt(1)
    p.paragraph_format.keep_with_next = keep
    run = p.add_run()
    w = min(width_mm, col_width_mm())
    try:
        run.add_picture(path, width=Mm(w))
    except Exception:
        run.add_text("[그림 넣기 실패]")
    return p


def add_answer_space(doc, lines):
    """답 쓸 자리. 빈 여백이면 어디 쓰는지 모르므로 얙은 밑줄을 깔다."""
    for k in range(lines):
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(4)
        p.paragraph_format.space_after = Pt(0)
        p.paragraph_format.keep_with_next = (k < lines - 1)
        p.add_run(" ").font.size = Pt(10)
        set_border(p, "bottom", 4, "DDDDDD")


def add_separator(doc):
    """문제와 문제 사이를 가르는 선."""
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(6)
    p.paragraph_format.space_after = Pt(0)
    p.add_run("").font.size = Pt(2)
    set_border(p, "bottom", 8, "999999")
    return p


def build(problems, page_widths, cropper, out_path, title, answer_lines):
    doc = Document()

    sec = doc.sections[0]
    sec.page_width = Mm(210)
    sec.page_height = Mm(297)
    sec.left_margin = Mm(MARGIN_MM)
    sec.right_margin = Mm(MARGIN_MM)
    sec.top_margin = Mm(14)
    sec.bottom_margin = Mm(14)
    set_two_columns(sec)

    style = doc.styles["Normal"]
    style.font.name = "맑은 고딕"
    style.element.rPr.rFonts.set(qn("w:eastAsia"), "맑은 고딕")
    style.font.size = Pt(10)

    head = doc.add_paragraph()
    head.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = head.add_run(title)
    r.bold = True
    r.font.size = Pt(13)

    cur_file = None
    n_img, n_fail = 0, 0

    for p in problems:
        if p["file"] != cur_file:
            cur_file = p["file"]
            hp = doc.add_paragraph()
            hp.paragraph_format.space_before = Pt(12)
            hp.paragraph_format.keep_with_next = True
            hr = hp.add_run(str(cur_file))
            hr.bold = True
            hr.font.size = Pt(11)

        num = p["num"] if p["num"] is not None else ""
        add_label(doc, f"{p['name']} {num}   (원본 {p['page']}쪽)")

        body = list(p["body"])
        for f in list(p["figs"]) + list(p["figs_guess"]):
            if f not in body:
                body.append(f)

        for k, b in enumerate(body):
            last = (k == len(body) - 1)
            t = EX.txt(b)
            typ = b.get("type")
            iw = page_widths.get((b.get("_file"), b.get("_page")))

            if typ in EX.FIGURE_TYPES or EX.is_image_md(t) or \
                    (t and HAS_MATH.search(t)) or EX.is_display_math(b):
                got = cropper.crop(b, iw)
                if got:
                    add_image(doc, got[0], got[1], keep=not last)
                    n_img += 1
                else:
                    n_fail += 1
                    if t and not EX.is_image_md(t):
                        add_text(doc, t, keep=not last)
                continue

            if not t:
                continue
            if k == 0:
                for _name, pat, _kind in EX.START_PATTERNS:
                    m = pat.match(t)
                    if m:
                        t = t[m.end():].strip()
                        break
                if not t:
                    continue
            add_text(doc, t, keep=not last)

        add_answer_space(doc, answer_lines)
        add_separator(doc)

    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".",
                exist_ok=True)
    doc.save(out_path)
    return n_img, n_fail


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default="./stage0_out")
    ap.add_argument("--file", action="append", default=[],
                    help="run 폴더 이름에 포함될 조각. 여러 번 줄 수 있다")
    ap.add_argument("--out", default="./out/문제집.docx")
    ap.add_argument("--title", default="추출 문제집")
    ap.add_argument("--answer-lines", type=int, default=3,
                    help="문제마다 답 쓸 빈 줄 수")
    ap.add_argument("--pdfdir", action="append", default=[],
                    help="원본 PDF 폴더. 기본은 samples/테스트자료_스캔본 등")
    ap.add_argument("--cropdir", default="./out/_crops")
    args = ap.parse_args()

    if Document is None:
        sys.exit("python-docx 가 없습니다.  pip install python-docx pymupdf")
    if fitz is None:
        print("경고: pymupdf 가 없어 수식·그림을 넣을 수 없습니다.")

    runs = os.path.join(args.stage, "runs")
    if not os.path.isdir(runs):
        sys.exit(f"runs 폴더가 없습니다: {runs}")
    names = sorted(os.listdir(runs))
    if args.file:
        names = [n for n in names if any(f in n for f in args.file)]
    if not names:
        sys.exit("대상 run 폴더가 없습니다.")

    all_rows, pw = [], None
    for n in names:
        lj = os.path.join(runs, n, "result.lines.json")
        if not os.path.exists(lj):
            continue
        rows, w = EX.load(lj)
        for r in rows:
            r["_file"] = n
        all_rows.extend(rows)
        if w:
            pw = max(pw or 0, w)

    if not all_rows:
        sys.exit("lines.json 을 찾지 못했습니다.")

    page_widths = learn_page_widths(all_rows)
    problems, kept, dropped, live, st = EX.build(all_rows, pw)

    pdf_dirs = args.pdfdir or [
        "samples/테스트자료_스캔본",
        "samples/테스트자료_텍스트레이어",
        "s_scan", "s_text",
    ]
    body_widths = learn_body_width(all_rows)
    cropper = Cropper(pdf_dirs, args.cropdir, body_widths)

    n_img, n_fail = build(problems, page_widths, cropper, args.out,
                          args.title, args.answer_lines)

    print(f"완료: {args.out}")
    print(f"문제 {len(problems)}개 / 오려낸 그림 {n_img}장 / 실패 {n_fail}건")
    if cropper.fail:
        print("실패 사유:", ", ".join(f"{k} {v}" for k, v in
                                    sorted(cropper.fail.items())))
    missing = [k for k, v in cropper.docs.items() if v is None]
    if missing:
        print("원본 PDF 를 못 찾은 파일:")
        for m in missing:
            print(f"  {m}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
