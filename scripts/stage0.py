#!/usr/bin/env python3
"""
stage0.py
Mathpix 0단계 측정 전체를 한 번에 실행하고, 하나의 리포트로 정리한다.

사용법:
    export MATHPIX_APP_ID=...
    export MATHPIX_APP_KEY=...
    python3 scripts/stage0.py ./s_scan ./stage0_out

하는 일:
    1. 가장 작은 파일부터 순서대로 처리 (스모크가 자연스럽게 먼저 돈다)
    2. 응답 필드명 자동 탐지 (문서와 달라도 알아서 맞춤)
    3. 전량 처리 + SSE 스트리밍 측정
    4. lines.json 구조/타입/좌표/번호패턴 전수 분석
    5. REPORT.md 한 파일로 정리

중단 후 재실행하면 이미 끝난 파일은 건너뛴다.

필요 패키지:
    pip install requests
"""

import argparse
import json
import os
import re
import sys
import time
import traceback
from collections import Counter, defaultdict
from datetime import datetime, timezone

import requests

API_BASE = "https://api.mathpix.com/v3/pdf"
POLL_INTERVAL = 3.0
POLL_TIMEOUT = 2400
PRICE_PER_PAGE_USD = 0.005
KRW_PER_USD = 1500
LOW_CONF = 0.90

# pdf_id / status 필드명 후보 (문서와 달라도 잡아내기 위함)
ID_KEYS = ("pdf_id", "id", "job_id", "request_id")
STATUS_KEYS = ("status", "state", "job_status")
DONE_VALUES = ("completed", "complete", "done", "success", "finished")
FAIL_VALUES = ("error", "failed", "failure", "cancelled")

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

KEYWORDS = ["예제", "유제", "문제", "유형", "탐구", "풀이", "해설", "정답",
            "개념", "확인", "연습", "단원", "학습", "생각", "활동", "보기"]


# ------------------------------------------------------------------ 공통

def log(msg=""):
    print(msg, flush=True)


def headers():
    app_id = os.environ.get("MATHPIX_APP_ID")
    app_key = os.environ.get("MATHPIX_APP_KEY")
    if not app_id or not app_key:
        sys.exit("MATHPIX_APP_ID / MATHPIX_APP_KEY 환경변수를 설정하세요.")
    return {"app_id": app_id, "app_key": app_key}


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def find_key(data, candidates):
    """응답 딕셔너리에서 후보 키 중 실제로 존재하는 것을 찾는다."""
    if not isinstance(data, dict):
        return None, None
    for k in candidates:
        if k in data and data[k]:
            return k, data[k]
    return None, None


# ------------------------------------------------------------------ API

def submit(pdf_path, out_dir):
    options = {
        "conversion_formats": {"docx": True},
        "streaming": True,
    }
    t0 = time.perf_counter()
    with open(pdf_path, "rb") as f:
        resp = requests.post(
            API_BASE, headers=headers(),
            files={"file": f},
            data={"options_json": json.dumps(options)},
            timeout=600,
        )
    elapsed = time.perf_counter() - t0

    body = resp.text
    with open(os.path.join(out_dir, "raw_submit.json"), "w",
              encoding="utf-8") as f:
        f.write(body)

    if resp.status_code != 200:
        raise RuntimeError(f"제출 실패 HTTP {resp.status_code}: {body[:300]}")

    data = json.loads(body)
    key, pdf_id = find_key(data, ID_KEYS)
    if not pdf_id:
        raise RuntimeError(f"pdf_id 를 못 찾음. 응답 키: {list(data.keys())}")

    return pdf_id, key, elapsed


def consume_stream(pdf_id, out_dir):
    url = f"{API_BASE}/{pdf_id}/stream"
    path = os.path.join(out_dir, "stream_events.jsonl")

    pages, confs, order = {}, {}, []
    total_pages, first_at = None, None
    t0 = time.perf_counter()

    with requests.get(url,
                      headers={**headers(), "Accept": "text/event-stream"},
                      stream=True, timeout=(30, 1200)) as resp, \
            open(path, "w", encoding="utf-8") as ev:
        resp.raise_for_status()
        for raw in resp.iter_lines(decode_unicode=True):
            if not raw:
                continue
            line = raw.strip()
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if not payload:
                continue

            el = time.perf_counter() - t0
            if first_at is None:
                first_at = el

            try:
                obj = json.loads(payload)
            except json.JSONDecodeError:
                ev.write(json.dumps({"elapsed": round(el, 3),
                                     "unparsed": payload[:500]},
                                    ensure_ascii=False) + "\n")
                continue

            ev.write(json.dumps({"elapsed": round(el, 3),
                                 "received_at": now_iso(), "event": obj},
                                ensure_ascii=False) + "\n")

            if "pdf_selected_len" in obj:
                total_pages = obj["pdf_selected_len"]
            idx = obj.get("page_idx")
            if idx is not None:
                pages[idx] = el
                order.append(idx)
                if "confidence" in obj:
                    confs[idx] = obj["confidence"]

    return {
        "first_event_sec": first_at,
        "stream_total_sec": time.perf_counter() - t0,
        "pages_received": len(pages),
        "total_pages_reported": total_pages,
        "page_confidence": confs,
        "out_of_order": sum(1 for a, b in zip(order, order[1:]) if b < a),
    }


def wait_done(pdf_id, out_dir):
    t0 = time.perf_counter()
    last = ""
    while time.perf_counter() - t0 < POLL_TIMEOUT:
        r = requests.get(f"{API_BASE}/{pdf_id}", headers=headers(), timeout=60)
        last = r.text
        r.raise_for_status()
        data = json.loads(last)
        _, status = find_key(data, STATUS_KEYS)
        s = str(status or "").lower()

        if s in DONE_VALUES:
            with open(os.path.join(out_dir, "raw_status.json"), "w",
                      encoding="utf-8") as f:
                f.write(last)
            return time.perf_counter() - t0
        if s in FAIL_VALUES:
            with open(os.path.join(out_dir, "raw_status.json"), "w",
                      encoding="utf-8") as f:
                f.write(last)
            raise RuntimeError(f"처리 실패: {last[:300]}")
        time.sleep(POLL_INTERVAL)
    raise TimeoutError(f"폴링 타임아웃: {last[:300]}")


def download(pdf_id, ext, dest):
    t0 = time.perf_counter()
    r = requests.get(f"{API_BASE}/{pdf_id}.{ext}",
                     headers=headers(), timeout=600)
    el = time.perf_counter() - t0
    if r.status_code != 200:
        return None, el, r.status_code
    with open(dest, "wb") as f:
        f.write(r.content)
    return len(r.content), el, 200


# ------------------------------------------------------------------ 분석

def walk_lines(obj, found=None):
    if found is None:
        found = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in ("lines", "line_data", "data") and isinstance(v, list):
                if v and isinstance(v[0], dict):
                    found.append((k, v))
            walk_lines(v, found)
    elif isinstance(obj, list):
        for it in obj:
            walk_lines(it, found)
    return found


def get_xy(line):
    for key in ("region", "bbox", "cnt"):
        v = line.get(key)
        if isinstance(v, dict):
            x = v.get("top_left_x", v.get("x"))
            y = v.get("top_left_y", v.get("y"))
            if x is not None:
                return x, y
        if isinstance(v, list) and v:
            if isinstance(v[0], (int, float)) and len(v) >= 2:
                return v[0], v[1]
            if isinstance(v[0], list) and v[0]:
                pts = [p for p in v if isinstance(p, list) and len(p) >= 2]
                if pts:
                    return min(p[0] for p in pts), min(p[1] for p in pts)
    for k in ("x", "left", "top_left_x"):
        if k in line:
            return line[k], line.get("y", line.get("top", None))
    return None, None


def get_text(line):
    for k in ("text", "value", "mmd", "latex"):
        v = line.get(k)
        if isinstance(v, str) and v.strip():
            return v
    return ""


def analyze_lines(path):
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)

    buckets = walk_lines(doc)
    if not buckets:
        return {"error": "줄 배열을 못 찾음",
                "top_keys": list(doc.keys())
                if isinstance(doc, dict) else str(type(doc))}

    key, lines = max(buckets, key=lambda kv: len(kv[1]))

    fields = Counter()
    for ln in lines:
        fields.update(ln.keys())

    types = Counter(str(ln.get("type", "-")) for ln in lines)
    subs = Counter(str(ln.get("subtype")) for ln in lines
                   if ln.get("subtype") is not None)

    xs = []
    for ln in lines:
        x, _ = get_xy(ln)
        if isinstance(x, (int, float)):
            xs.append(x)

    hits = defaultdict(list)
    for ln in lines:
        t = get_text(ln)
        if not t:
            continue
        for name, pat in NUMBER_PATTERNS:
            if pat.match(t):
                x, _ = get_xy(ln)
                hits[name].append((x, t[:60]))
                break

    all_text = "\n".join(get_text(ln) for ln in lines)
    kw = {k: all_text.count(k) for k in KEYWORDS if all_text.count(k)}

    sample_line = lines[0] if lines else {}

    return {
        "lines_key": key,
        "line_count": len(lines),
        "fields": dict(fields),
        "types": dict(types),
        "subtypes": dict(subs),
        "x_values": xs,
        "number_hits": {k: v for k, v in hits.items()},
        "keywords": kw,
        "sample_line": sample_line,
        "text_chars": len(all_text),
    }


def histogram(xs, bins=24, width=44):
    if not xs:
        return []
    lo, hi = min(xs), max(xs)
    span = max(hi - lo, 1)
    h = Counter(min(int((x - lo) / span * bins), bins - 1) for x in xs)
    peak = max(h.values())
    out = []
    for b in range(bins):
        left = lo + span * b / bins
        c = h.get(b, 0)
        out.append(f"    {left:8.0f} | {'#' * int(c / peak * width)} {c}")
    return out


# ------------------------------------------------------------------ 실행

def run_one(pdf_path, out_root):
    stem = os.path.splitext(os.path.basename(pdf_path))[0]
    out_dir = os.path.join(out_root, "runs", stem)
    os.makedirs(out_dir, exist_ok=True)

    done_marker = os.path.join(out_dir, "metrics.json")
    if os.path.exists(done_marker):
        log(f"  [건너뜀] {stem} (이미 완료)")
        with open(done_marker, encoding="utf-8") as f:
            return json.load(f)

    log(f"\n=== {stem} ===")
    wall0 = time.perf_counter()

    pdf_id, id_key, submit_sec = submit(pdf_path, out_dir)
    log(f"  제출 {submit_sec:.1f}s  ({id_key}={pdf_id})")

    try:
        st = consume_stream(pdf_id, out_dir)
        log(f"  첫이벤트 {st['first_event_sec']:.1f}s  "
            f"{st['pages_received']}p  스트림 {st['stream_total_sec']:.1f}s  "
            f"역전 {st['out_of_order']}")
    except Exception as e:
        log(f"  스트림 실패: {e}")
        st = {"error": str(e)}

    poll_sec = wait_done(pdf_id, out_dir)

    dl = {}
    for ext, fname in (("mmd", "result.mmd"),
                       ("lines.json", "result.lines.json"),
                       ("docx", "result.docx")):
        size, sec, code = download(pdf_id, ext,
                                   os.path.join(out_dir, fname))
        dl[ext] = {"bytes": size, "sec": round(sec, 2), "http": code}
        log(f"  {ext:<11} {sec:5.1f}s  "
            f"{f'{size:,}B' if size else f'HTTP {code}'}")

    wall = time.perf_counter() - wall0
    pages = (st.get("total_pages_reported") or st.get("pages_received") or 0)
    confs = list(st.get("page_confidence", {}).values())

    m = {
        "file": stem,
        "pdf_id": pdf_id,
        "id_key": id_key,
        "page_count": pages,
        "submit_sec": round(submit_sec, 2),
        "first_event_sec": round(st.get("first_event_sec") or 0, 2),
        "stream_total_sec": round(st.get("stream_total_sec") or 0, 2),
        "poll_after_stream_sec": round(poll_sec, 2),
        "wall_total_sec": round(wall, 2),
        "sec_per_page": round(wall / pages, 2) if pages else None,
        "out_of_order": st.get("out_of_order"),
        "conf_min": round(min(confs), 4) if confs else None,
        "conf_mean": round(sum(confs) / len(confs), 4) if confs else None,
        "low_conf_pages": sorted(i for i, c
                                 in st.get("page_confidence", {}).items()
                                 if c < LOW_CONF),
        "downloads": dl,
        "cost_usd": round(pages * PRICE_PER_PAGE_USD, 4),
    }

    lj = os.path.join(out_dir, "result.lines.json")
    if os.path.exists(lj) and os.path.getsize(lj) > 0:
        try:
            m["lines"] = analyze_lines(lj)
        except Exception as e:
            m["lines"] = {"error": f"{e}"}

    with open(done_marker, "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False, indent=2)
    return m


def build_report(rows, out_root):
    lines_out = []
    W = lines_out.append

    W("# Mathpix 0단계 측정 리포트")
    W("")
    W(f"생성: {now_iso()}")
    W("")

    ok = [r for r in rows if not r.get("error")]
    total_pages = sum(r.get("page_count") or 0 for r in ok)
    cost = total_pages * PRICE_PER_PAGE_USD

    W("## 1. 요약")
    W("")
    W(f"- 파일 {len(ok)}개 / {total_pages:,}페이지")
    W(f"- 비용 ${cost:,.2f} (약 {int(cost * KRW_PER_USD):,}원)")

    spp = [r["sec_per_page"] for r in ok if r.get("sec_per_page")]
    fe = [r["first_event_sec"] for r in ok if r.get("first_event_sec")]
    cm = [r["conf_mean"] for r in ok if r.get("conf_mean")]
    oo = sum(r.get("out_of_order") or 0 for r in ok)

    if spp:
        W(f"- 페이지당 처리시간: 평균 {sum(spp)/len(spp):.2f}s / "
          f"최대 {max(spp):.2f}s / 최소 {min(spp):.2f}s")
    if fe:
        W(f"- 첫 이벤트까지: 평균 {sum(fe)/len(fe):.2f}s / 최대 {max(fe):.2f}s")
    if cm:
        W(f"- 페이지 신뢰도: 평균 {sum(cm)/len(cm):.4f} / 최저 {min(cm):.4f}")
    W(f"- 페이지 순서 역전 총 {oo}회")

    id_keys = Counter(r.get("id_key") for r in ok if r.get("id_key"))
    if id_keys:
        W(f"- 응답 ID 필드명: {dict(id_keys)}")
    W("")

    W("## 2. 파일별 측정")
    W("")
    W("| 파일 | p | 제출 | 첫이벤트 | 스트림 | 전체 | s/p | 역전 | conf평균 | conf최저 | 저신뢰p |")
    W("|---|---|---|---|---|---|---|---|---|---|---|")
    for r in ok:
        W(f"| {r['file'][:32]} | {r.get('page_count')} | "
          f"{r.get('submit_sec')} | {r.get('first_event_sec')} | "
          f"{r.get('stream_total_sec')} | {r.get('wall_total_sec')} | "
          f"{r.get('sec_per_page')} | {r.get('out_of_order')} | "
          f"{r.get('conf_mean')} | {r.get('conf_min')} | "
          f"{len(r.get('low_conf_pages') or [])} |")
    W("")

    W("## 3. 다운로드 결과")
    W("")
    W("| 파일 | mmd | lines.json | docx |")
    W("|---|---|---|---|")
    for r in ok:
        d = r.get("downloads", {})

        def cell(e):
            v = d.get(e, {})
            b = v.get("bytes")
            return f"{b:,}B" if b else f"HTTP {v.get('http')}"

        W(f"| {r['file'][:32]} | {cell('mmd')} | "
          f"{cell('lines.json')} | {cell('docx')} |")
    W("")

    # ---- lines.json 통합 분석 ----
    W("## 4. lines.json 통합 분석")
    W("")

    all_fields = Counter()
    all_types = Counter()
    all_subs = Counter()
    all_kw = Counter()
    all_hits = defaultdict(list)
    all_x = []
    sample_line = None
    lines_key = None
    total_lines = 0
    errs = []

    for r in ok:
        L = r.get("lines")
        if not L:
            continue
        if L.get("error"):
            errs.append((r["file"], L["error"], L.get("top_keys")))
            continue
        lines_key = lines_key or L.get("lines_key")
        sample_line = sample_line or L.get("sample_line")
        total_lines += L.get("line_count", 0)
        all_fields.update(L.get("fields", {}))
        all_types.update(L.get("types", {}))
        all_subs.update(L.get("subtypes", {}))
        all_kw.update(L.get("keywords", {}))
        all_x.extend(L.get("x_values", []))
        for k, v in L.get("number_hits", {}).items():
            all_hits[k].extend(v)

    if errs:
        W("### 분석 실패")
        W("")
        for f, e, tk in errs:
            W(f"- {f}: {e} / 최상위키={tk}")
        W("")

    W(f"- 줄 배열 위치: `{lines_key}`")
    W(f"- 총 줄 수: {total_lines:,}")
    W("")

    W("### 4-1. 줄 객체 필드")
    W("")
    W("| 필드 | 등장 줄 수 | 비율 |")
    W("|---|---|---|")
    for f, c in all_fields.most_common():
        W(f"| `{f}` | {c:,} | {c/max(total_lines,1)*100:.1f}% |")
    W("")

    W("### 4-2. type 분포")
    W("")
    W("| type | 줄 수 |")
    W("|---|---|")
    for t, c in all_types.most_common():
        W(f"| `{t}` | {c:,} |")
    W("")

    if all_subs:
        W("### 4-3. subtype 분포")
        W("")
        W("| subtype | 줄 수 |")
        W("|---|---|")
        for t, c in all_subs.most_common():
            W(f"| `{t}` | {c:,} |")
        W("")

    W("### 4-4. x좌표 분포 (단 분리 판정용)")
    W("")
    if all_x:
        W(f"범위 {min(all_x):.0f} ~ {max(all_x):.0f}, 표본 {len(all_x):,}")
        W("")
        W("```")
        for l in histogram(all_x):
            W(l)
        W("```")
    else:
        W("좌표를 추출하지 못했습니다. 아래 sample_line 을 보고 파서를 고쳐야 합니다.")
    W("")

    W("### 4-5. 문제 번호 패턴 적중")
    W("")
    W("| 패턴 | 적중 | x범위 |")
    W("|---|---|---|")
    for name, _ in NUMBER_PATTERNS:
        items = all_hits.get(name)
        if not items:
            continue
        xs = [x for x, _ in items if isinstance(x, (int, float))]
        xr = f"{min(xs):.0f}~{max(xs):.0f}" if xs else "?"
        W(f"| {name} | {len(items)} | {xr} |")
    W("")
    W("적중 예시:")
    W("")
    W("```")
    for name, _ in NUMBER_PATTERNS:
        items = all_hits.get(name)
        if not items:
            continue
        W(f"[{name}]")
        for x, t in items[:6]:
            xs = f"{x:7.0f}" if isinstance(x, (int, float)) else "      ?"
            W(f"  {xs}  {t}")
    W("```")
    W("")

    if all_kw:
        W("### 4-6. 키워드 등장")
        W("")
        W("| 키워드 | 횟수 |")
        W("|---|---|")
        for k, c in sorted(all_kw.items(), key=lambda x: -x[1]):
            W(f"| {k} | {c:,} |")
        W("")

    W("### 4-7. 줄 객체 원본 샘플")
    W("")
    W("```json")
    W(json.dumps(sample_line, ensure_ascii=False, indent=2)[:2000])
    W("```")
    W("")

    failed = [r for r in rows if r.get("error")]
    if failed:
        W("## 5. 실패한 파일")
        W("")
        for r in failed:
            W(f"- **{r['file']}**: {r['error']}")
        W("")

    path = os.path.join(out_root, "REPORT.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines_out))
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf_dir")
    ap.add_argument("out_dir")
    ap.add_argument("--limit", type=int, default=None,
                    help="파일 N개만 처리")
    args = ap.parse_args()

    if not os.path.isdir(args.pdf_dir):
        sys.exit(f"폴더가 없습니다: {args.pdf_dir}")
    headers()
    os.makedirs(os.path.join(args.out_dir, "runs"), exist_ok=True)

    pdfs = [os.path.join(args.pdf_dir, p)
            for p in os.listdir(args.pdf_dir) if p.lower().endswith(".pdf")]
    if not pdfs:
        sys.exit("PDF가 없습니다.")

    # 작은 것부터: 스모크가 자연스럽게 먼저 돈다
    pdfs.sort(key=os.path.getsize)
    if args.limit:
        pdfs = pdfs[:args.limit]

    log(f"대상 {len(pdfs)}개 (작은 파일부터)")

    rows = []
    for i, p in enumerate(pdfs, 1):
        log(f"\n[{i}/{len(pdfs)}]")
        try:
            rows.append(run_one(p, args.out_dir))
        except Exception as e:
            stem = os.path.splitext(os.path.basename(p))[0]
            log(f"  [실패] {stem}: {e}")
            traceback.print_exc()
            rows.append({"file": stem, "error": str(e)[:300]})
            if i == 1:
                log("\n첫 파일부터 실패했습니다. "
                    f"{args.out_dir}/runs/{stem}/raw_submit.json 을 확인하세요.")
                break

    path = build_report(rows, args.out_dir)
    log("\n" + "=" * 60)
    log(f"리포트: {path}")
    log("이 파일 하나만 전달하면 됩니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
