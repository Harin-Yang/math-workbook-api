#!/usr/bin/env python3
"""
grade.py  v1
기준 파일(수기 편집본) 과 추출 결과를 자동 대조해 점수를 낸다.
Mathpix 재호출 없음 = 비용 0원.

사용법:
    python3 scripts/grade.py --list
    python3 scripts/grade.py --ref <기준.pdf> --file <run폴더필터> --tag 기하

무엇을 하는가
  1. 기준 파일을 parse_ref 로 읽어 문제 목록을 만든다
  2. stage0_out/runs/*/result.lines.json 을 extract 로 읽어 추출 문제를 만든다
  3. 두 목록을 읽는 순서를 지키며 정렬 대조(alignment)한다
  4. 완전일치 / 잘림 / 넘침 / 부분일치 / 미검출 / 오검출 로 집계한다
  5. 점수를 history.jsonl 에 쌓아 다음 실행 때 증감을 보여준다 (회귀 테스트)

왜 한글만 비교하는가
  기준 파일(한/글 -> PDF) 은 텍스트를 뽑으면 수식과 숫자가 통째로 사라진다.
  추출 결과(Mathpix) 에는 수식이 살아 있다. 그대로 비교하면 전부 불일치가 된다.
  그래서 양쪽에서 수식·숫자·영문을 걷어내고 '한글 뼈대' 만 비교한다.
  --keep-math 를 주면 수식을 남기고 비교한다 (기준 파일이 수식을 보존할 때만 의미 있음).
"""

import argparse
import difflib
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import extract as EX          # noqa: E402
import parse_ref as PR        # noqa: E402

# ---- 판정 기준값 ----
MIN_SIM = 0.35        # 이 아래는 같은 문제로 보지 않는다
OK = 0.85             # 완전일치로 인정할 겹침 비율
MIN_CHARS = 6         # 한글 뼈대가 이보다 짧으면 판정 보류
GAP_MAX = 15          # 매칭된 두 문제 사이가 이보다 벌어지면 '범위 밖'

IMG_MD = re.compile(r"!\[[^\]]*\]\([^)]*\)")
INC_GRAPHICS = re.compile(r"\\includegraphics(?:\[[^\]]*\])?\{[^}]*\}")
DISPLAY_MATH = re.compile(r"\$\$.*?\$\$|\\\[.*?\\\]", re.S)
INLINE_MATH = re.compile(r"\$[^$]*\$|\\\(.*?\\\)", re.S)
TEX_CMD = re.compile(r"\\[A-Za-z]+\*?")
HANGUL = re.compile(r"[가-힣]+")
NOT_KEEP = re.compile(r"[^가-힣0-9A-Za-z]+")


# ------------------------------------------------------------------ 정규화

def strip_marker(t):
    """'문제 12', '예제 3' 같은 앞머리 표기를 떼어낸다."""
    for _name, pat, _kind in EX.START_PATTERNS:
        m = pat.match(t)
        if m:
            return t[m.end():]
    return t


def normalize(t, keep_math=False):
    t = IMG_MD.sub(" ", t)
    t = INC_GRAPHICS.sub(" ", t)
    if not keep_math:
        t = DISPLAY_MATH.sub(" ", t)
        t = INLINE_MATH.sub(" ", t)
    t = TEX_CMD.sub(" ", t)
    t = t.replace("$", " ")
    if keep_math:
        return NOT_KEEP.sub("", t)
    return "".join(HANGUL.findall(t))


def grams(s, n=3):
    if not s:
        return set()
    if len(s) <= n:
        return {s}
    return {s[i:i + n] for i in range(len(s) - n + 1)}


def overlap(a, b):
    """a(기준) 와 b(추출) 의 겹침. 반환 (recall, precision)."""
    if not a or not b:
        return 0.0, 0.0
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    common = sum(bl.size for bl in sm.get_matching_blocks())
    return common / len(a), common / len(b)


# ------------------------------------------------------------------ 자료 적재

def list_runs(stage_dir):
    runs = os.path.join(stage_dir, "runs")
    if not os.path.isdir(runs):
        return []
    return sorted(n for n in os.listdir(runs)
                  if os.path.exists(os.path.join(runs, n, "result.lines.json")))


def load_extracted(stage_dir, filters):
    runs = os.path.join(stage_dir, "runs")
    names = list_runs(stage_dir)
    if filters:
        names = [n for n in names if any(f in n for f in filters)]
    if not names:
        sys.exit("대상 run 폴더가 없습니다. --list 로 이름을 확인하세요.")

    all_rows, pw = [], None
    for n in names:
        rows, w = EX.load(os.path.join(runs, n, "result.lines.json"))
        for r in rows:
            r["_file"] = n
        all_rows.extend(rows)
        if w:
            pw = max(pw or 0, w)

    problems, kept, dropped_x, live, st = EX.build(all_rows, pw)

    out = []
    for p in problems:
        parts = []
        for k, b in enumerate(p["body"]):
            t = EX.txt(b)
            if not t or EX.is_image_md(t):
                continue
            if k == 0:
                t = strip_marker(t)
            parts.append(t)
        out.append({
            "name": p["name"], "num": p["num"], "kind": p["kind"],
            "file": p["file"], "page": p["page"], "lines": p["lines"],
            "reason": p["reason"],
            "figs": len(p["figs"]) + len(p["figs_guess"]),
            "text": re.sub(r"\s+", " ", " ".join(parts)).strip(),
            "head": p["head"],
        })
    return out, names, st, len(all_rows)


def load_reference(ref_pdf, ref_json, reuse):
    """기준 파일을 읽는다.

    기본은 매번 PDF 를 다시 읽는다. 파서를 고쳤는데 옛 결과가 재활용되면
    점수가 안 바뀌어 원인을 찾기 어렵기 때문이다.
    --ref-json 으로 경로를 직접 준 경우에만 있는 파일을 재활용한다.
    """
    if reuse and ref_json and os.path.exists(ref_json):
        with open(ref_json, encoding="utf-8") as f:
            return json.load(f)
    d = PR.parse(ref_pdf)
    if ref_json:
        with open(ref_json, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
    return d


# ------------------------------------------------------------------ 정렬 대조

def align(ref_g, ext_g, min_sim):
    """읽는 순서를 지키며 최대 유사도 짝짓기. 반환 [(기준i, 추출j, 유사도)]"""
    n, m = len(ref_g), len(ext_g)
    S = [[0.0] * (m + 1) for _ in range(n + 1)]
    B = [[0] * (m + 1) for _ in range(n + 1)]      # 0=짝 1=기준건너뜀 2=추출건너뜀
    sims = [[0.0] * m for _ in range(n)]

    for i in range(1, n + 1):
        gi = ref_g[i - 1]
        li = len(gi)
        Si, Sp, Bi, si = S[i], S[i - 1], B[i], sims[i - 1]
        for j in range(1, m + 1):
            gj = ext_g[j - 1]
            s = 0.0
            if li and gj:
                inter = len(gi & gj)
                if inter:
                    s = inter / (li + len(gj) - inter)
            si[j - 1] = s
            up, left = Sp[j], Si[j - 1]
            if up >= left:
                best, ch = up, 1
            else:
                best, ch = left, 2
            if s >= min_sim:
                d = Sp[j - 1] + s
                if d > best:
                    best, ch = d, 0
            Si[j] = best
            Bi[j] = ch

    pairs = []
    i, j = n, m
    while i > 0 and j > 0:
        c = B[i][j]
        if c == 0:
            pairs.append((i - 1, j - 1, sims[i - 1][j - 1]))
            i -= 1
            j -= 1
        elif c == 1:
            i -= 1
        else:
            j -= 1
    pairs.reverse()
    return pairs


def in_scope(matched_ref_idx, total_ref, gap_max):
    """OCR 하지 않은 단원은 채점 범위에서 뺀다."""
    scope = set(matched_ref_idx)
    ms = sorted(matched_ref_idx)
    for a, b in zip(ms, ms[1:]):
        if b - a - 1 <= gap_max:
            scope.update(range(a + 1, b))
    return scope


def out_of_scope_ranges(scope, total_ref):
    outs, run = [], []
    for i in range(total_ref):
        if i in scope:
            if run:
                outs.append((run[0], run[-1]))
                run = []
        else:
            run.append(i)
    if run:
        outs.append((run[0], run[-1]))
    return outs


# ------------------------------------------------------------------ 채점

def judge(refs, exts, keep_math, min_sim, ok, gap_max):
    rn = [normalize(r["text"], keep_math) for r in refs]
    en = [normalize(e["text"], keep_math) for e in exts]
    pairs = align([grams(s) for s in rn], [grams(s) for s in en], min_sim)

    scope = in_scope([p[0] for p in pairs], len(refs), gap_max)

    results = []
    matched_ext = set()
    for i, j, s in pairs:
        matched_ext.add(j)
        rec, pre = overlap(rn[i], en[j])
        if len(rn[i]) < MIN_CHARS and len(en[j]) < MIN_CHARS:
            v = "판정보류"
        elif rec >= ok and pre >= ok:
            v = "완전일치"
        elif rec < ok and pre >= ok:
            v = "잘림"
        elif rec >= ok and pre < ok:
            v = "넘침"
        else:
            v = "부분일치"
        results.append({
            "verdict": v, "sim": round(s, 3),
            "recall": round(rec, 3), "precision": round(pre, 3),
            "ref_num": refs[i]["num"], "ref_page": refs[i]["page"],
            "ref_section": refs[i]["section"],
            "ref_head": refs[i]["text"][:110],
            "ref_chars": len(rn[i]),
            "ext_name": exts[j]["name"], "ext_num": exts[j]["num"],
            "ext_file": exts[j]["file"], "ext_page": exts[j]["page"],
            "ext_head": exts[j]["text"][:110],
            "ext_chars": len(en[j]),
            "ext_reason": exts[j]["reason"],
        })

    missed = [{
        "ref_num": refs[i]["num"], "ref_page": refs[i]["page"],
        "ref_section": refs[i]["section"], "ref_head": refs[i]["text"][:110],
    } for i in sorted(scope) if i not in {p[0] for p in pairs}]

    false = [{
        "ext_name": exts[j]["name"], "ext_num": exts[j]["num"],
        "ext_file": exts[j]["file"], "ext_page": exts[j]["page"],
        "ext_lines": exts[j]["lines"], "ext_reason": exts[j]["reason"],
        "ext_head": exts[j]["text"][:110],
    } for j in range(len(exts)) if j not in matched_ext]

    return results, missed, false, scope


def score_of(results, missed, false, scope, refs, exts):
    c = Counter(r["verdict"] for r in results)
    n_scope = len(scope)
    return {
        "기준_전체": len(refs),
        "기준_범위내": n_scope,
        "추출_전체": len(exts),
        "완전일치": c.get("완전일치", 0),
        "잘림": c.get("잘림", 0),
        "넘침": c.get("넘침", 0),
        "부분일치": c.get("부분일치", 0),
        "판정보류": c.get("판정보류", 0),
        "미검출": len(missed),
        "오검출": len(false),
        "정확도": round(c.get("완전일치", 0) / n_scope, 4) if n_scope else 0.0,
        "누락률": round(len(missed) / n_scope, 4) if n_scope else 0.0,
        "오검출률": round(len(false) / len(exts), 4) if exts else 0.0,
    }


# ------------------------------------------------------------------ 이력

def read_history(path, tag):
    if not os.path.exists(path):
        return None
    last = None
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            if d.get("tag") == tag:
                last = d
    return last


def append_history(path, entry):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def delta_str(now, before, key, lower_is_better):
    if not before or key not in before.get("score", {}):
        return "-"
    d = now[key] - before["score"][key]
    if abs(d) < 1e-9:
        return "0"
    mark = ""
    if lower_is_better:
        mark = " 개선" if d < 0 else " 악화"
    else:
        mark = " 개선" if d > 0 else " 악화"
    if isinstance(d, float):
        return f"{d:+.4f}{mark}"
    return f"{d:+d}{mark}"


# ------------------------------------------------------------------ 리포트

def report(out_md, tag, refd, run_names, score, before, results, missed,
           false, scope, refs, exts, st, args):
    W = []
    A = W.append

    A(f"# 채점 결과 — {tag}")
    A("")
    A(f"- 기준 파일 `{refd['file']}` : {refd['pages']}쪽 / 문제 {len(refs)}개")
    A(f"- 추출 대상 run 폴더 {len(run_names)}개 : {', '.join(run_names)}")
    A(f"- 비교 방식 : {'수식 포함' if args.keep_math else '한글 뼈대만'} "
      f"/ 최소유사도 {args.min_sim} / 일치기준 {args.ok}")
    A("")

    A("## 1. 점수")
    A("")
    A("| 지표 | 값 | 직전 대비 |")
    A("|---|---|---|")
    rows = [
        ("기준 문제 (전체)", "기준_전체", False),
        ("기준 문제 (채점 범위)", "기준_범위내", False),
        ("추출 문제", "추출_전체", False),
        ("완전일치", "완전일치", False),
        ("잘림", "잘림", True),
        ("넘침", "넘침", True),
        ("부분일치", "부분일치", True),
        ("판정보류", "판정보류", True),
        ("미검출", "미검출", True),
        ("오검출", "오검출", True),
        ("정확도", "정확도", False),
        ("누락률 (목표 0)", "누락률", True),
        ("오검출률 (목표 <0.05)", "오검출률", True),
    ]
    for label, key, low in rows:
        A(f"| {label} | {score[key]} | {delta_str(score, before, key, low)} |")
    A("")
    if before:
        A(f"직전 실행: {before.get('time')} (`{before.get('note') or '-'}`)")
    else:
        A("직전 실행 기록 없음 — 이번이 기준점이 된다.")
    A("")

    A("## 2. 판정 분포")
    A("")
    A("| 판정 | 개수 | 뜻 |")
    A("|---|---|---|")
    meaning = {
        "완전일치": "기준 문장을 거의 그대로 담았다",
        "잘림": "기준 문장의 일부가 빠졌다 (경계를 너무 일찍 끊음)",
        "넘침": "기준에 없는 문장이 섞였다 (경계를 너무 늦게 끊음)",
        "부분일치": "빠짐과 섞임이 동시에 있다",
        "판정보류": "한글이 너무 짧아 비교 불가 (수식만 있는 문제)",
    }
    for v, n in Counter(r["verdict"] for r in results).most_common():
        A(f"| {v} | {n} | {meaning.get(v,'')} |")
    A("")

    A("## 3. 미검출 — 기준에 있는데 못 찾은 문제")
    A("")
    if not missed:
        A("없음")
    else:
        A(f"{len(missed)}개")
        A("")
        A("| 기준번호 | 쪽 | 소단원 | 첫 줄 |")
        A("|---|---|---|---|")
        for m in missed[:60]:
            A(f"| {m['ref_num']} | {m['ref_page']} | {m['ref_section']} | "
              f"{m['ref_head'][:48]} |")
        if len(missed) > 60:
            A(f"| ... | | | 외 {len(missed)-60}개 |")
    A("")

    A("## 4. 오검출 — 추출했는데 기준에 없는 것")
    A("")
    if not false:
        A("없음")
    else:
        A(f"{len(false)}개")
        A("")
        A("| 표기 | 번호 | 파일 | 쪽 | 본문줄 | 종료 | 첫 줄 |")
        A("|---|---|---|---|---|---|---|")
        for m in false[:60]:
            A(f"| {m['ext_name']} | {m['ext_num']} | {str(m['ext_file'])[:20]} | "
              f"{m['ext_page']} | {m['ext_lines']} | {m['ext_reason']} | "
              f"{m['ext_head'][:44]} |")
        if len(false) > 60:
            A(f"| ... | | | | | | 외 {len(false)-60}개 |")
    A("")

    A("## 5. 경계 오류 사례")
    A("")
    for v in ("잘림", "넘침", "부분일치"):
        bad = sorted([r for r in results if r["verdict"] == v],
                     key=lambda r: r["recall"] if v != "넘침" else r["precision"])
        if not bad:
            continue
        A(f"### {v} ({len(bad)}개, 나쁜 순 앞 8개)")
        A("")
        A("```")
        for r in bad[:8]:
            A(f"[기준 {r['ref_num']}] p{r['ref_page']}  "
              f"담김 {r['recall']:.2f} / 군더더기없음 {r['precision']:.2f}")
            A(f"  기준: {r['ref_head'][:96]}")
            A(f"  추출: {r['ext_head'][:96]}   (종료={r['ext_reason']})")
            A("")
        A("```")
        A("")

    A("## 6. 채점 범위 밖 (OCR 하지 않은 단원으로 판단)")
    A("")
    outs = out_of_scope_ranges(scope, len(refs))
    if not outs:
        A("없음 — 기준 파일 전체가 채점 대상이다.")
    else:
        A("| 기준번호 구간 | 문제 수 | 소단원 |")
        A("|---|---|---|")
        for a, b in outs:
            secs = sorted({str(refs[k]["section"]) for k in range(a, b + 1)})
            A(f"| {refs[a]['num']} ~ {refs[b]['num']} | {b-a+1} | "
              f"{', '.join(secs)[:60]} |")
    A("")

    A("## 7. 추출기 자체 경고")
    A("")
    A(f"- 어느 문제에도 안 붙은 그림 {len(st['orphan'])}장")
    A(f"- 발문이 그림을 가리키는데 그림이 없는 문제 {len(st.get('need_fig', []))}개")
    A("")

    with open(out_md, "w", encoding="utf-8") as f:
        f.write("\n".join(W))


# ------------------------------------------------------------------ 진입점

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", default=None, help="기준 파일 PDF")
    ap.add_argument("--ref-json", default=None,
                    help="기준 파싱 결과를 이 경로에서 재사용한다 (기본은 매번 새로 읽음)")
    ap.add_argument("--stage", default="./stage0_out")
    ap.add_argument("--file", action="append", default=[],
                    help="run 폴더 이름에 포함될 조각. 여러 번 줄 수 있다")
    ap.add_argument("--tag", default=None, help="이력에 남길 이름")
    ap.add_argument("--outdir", default="./grade_out")
    ap.add_argument("--note", default="", help="이력에 남길 메모 (룰 버전 등)")
    ap.add_argument("--keep-math", action="store_true")
    ap.add_argument("--min-sim", type=float, default=MIN_SIM)
    ap.add_argument("--ok", type=float, default=OK)
    ap.add_argument("--gap-max", type=int, default=GAP_MAX)
    ap.add_argument("--list", action="store_true", help="run 폴더 이름만 출력")
    args = ap.parse_args()

    if args.list:
        names = list_runs(args.stage)
        if not names:
            print(f"runs 폴더가 비어 있습니다: {args.stage}/runs")
            return 1
        for n in names:
            print(n)
        return 0

    if not args.ref:
        sys.exit("--ref 로 기준 파일 PDF 를 지정하세요. (--list 로 run 폴더 확인)")

    tag = args.tag or os.path.splitext(os.path.basename(args.ref))[0]
    os.makedirs(args.outdir, exist_ok=True)
    reuse = bool(args.ref_json)
    ref_json = args.ref_json or os.path.join(args.outdir, f"{tag}.ref.json")

    refd = load_reference(args.ref, ref_json, reuse)
    refs = refd["problems"]
    if not refs:
        sys.exit("기준 파일에서 문제를 찾지 못했습니다.")

    exts, run_names, st, n_rows = load_extracted(args.stage, args.file)

    results, missed, false, scope = judge(
        refs, exts, args.keep_math, args.min_sim, args.ok, args.gap_max)
    score = score_of(results, missed, false, scope, refs, exts)

    hist = os.path.join(args.outdir, "history.jsonl")
    before = read_history(hist, tag)

    out_md = os.path.join(args.outdir, f"GRADE_{tag}.md")
    report(out_md, tag, refd, run_names, score, before, results, missed,
           false, scope, refs, exts, st, args)

    detail = os.path.join(args.outdir, f"{tag}.detail.json")
    with open(detail, "w", encoding="utf-8") as f:
        json.dump({"tag": tag, "score": score, "pairs": results,
                   "missed": missed, "false": false}, f,
                  ensure_ascii=False, indent=2)

    append_history(hist, {
        "tag": tag,
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "note": args.note,
        "ref": os.path.basename(args.ref),
        "runs": run_names,
        "params": {"min_sim": args.min_sim, "ok": args.ok,
                   "gap_max": args.gap_max, "keep_math": args.keep_math},
        "score": score,
    })

    print(f"완료: {out_md}")
    print(f"기준 {score['기준_전체']}개 (채점 범위 {score['기준_범위내']}) / "
          f"추출 {score['추출_전체']}개")
    print(f"완전일치 {score['완전일치']} / 잘림 {score['잘림']} / "
          f"넘침 {score['넘침']} / 부분일치 {score['부분일치']} / "
          f"보류 {score['판정보류']}")
    print(f"미검출 {score['미검출']} / 오검출 {score['오검출']}")
    print(f"정확도 {score['정확도']:.3f} / 누락률 {score['누락률']:.3f} / "
          f"오검출률 {score['오검출률']:.3f}")
    if before:
        d = score["정확도"] - before["score"]["정확도"]
        print(f"직전 대비 정확도 {d:+.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
