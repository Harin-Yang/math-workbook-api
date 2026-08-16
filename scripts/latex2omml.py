#!/usr/bin/env python3
"""
latex2omml.py
Mathpix 가 준 LaTeX 를 워드 수식(OMML)으로 옮긴다. 외부 패키지 없음, 비용 0원.

왜 필요한가
    워드 문서에서 수식은 OMML 이라는 전용 형식이어야 편집된다.
    LaTeX 글자를 그냥 넣으면 \\frac{1}{2} 라는 글씨가 그대로 찍힌다.
    python-docx 에는 변환 기능이 없어서 예전에는 수식을 그림으로 박았다.

무엇을 옮기는가
    교재에 실제로 나온 문법만 옮긴다. 세어 보니 스무 가지 남짓이면 다 덮였다.
    분수 / 근호 / 위아래 첨자 / 벡터·화살표 / 윗줄 / 괄호 / 그리스 문자 / 기호.

    모르는 문법을 만나면 Unsupported 를 던진다.
    부르는 쪽이 그 줄만 예전처럼 그림으로 박으면 된다. 절대 틀린 수식을 내보내지 않는다.

같은 나무에서 세 가지를 뽑는다
    to_omml()        워드용
    to_mathml()      브라우저 미리보기용 (요즘 브라우저는 MathML 을 그대로 그린다)
    to_hwp_script()  한/글용 (한/글 수식 편집기의 자체 스크립트, 한컴 공식 스펙 rev1.3)
    한 벌로 만들어야 미리보기·DOCX·HWPX 가 어긋나지 않는다.

시험:
    python3 scripts/latex2omml.py --selftest
"""

import re
import sys
from xml.sax.saxutils import escape

M_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"


class Unsupported(Exception):
    """옮길 수 없는 문법. 부르는 쪽에서 그림으로 되돌린다."""


# ── 기호표 ───────────────────────────────────────────────────────────
SYMBOL = {
    # 그리스
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ε",
    "varepsilon": "ε", "zeta": "ζ", "eta": "η", "theta": "θ",
    "vartheta": "ϑ", "iota": "ι", "kappa": "κ", "lambda": "λ", "mu": "μ",
    "nu": "ν", "xi": "ξ", "pi": "π", "rho": "ρ", "sigma": "σ", "tau": "τ",
    "upsilon": "υ", "phi": "φ", "varphi": "φ", "chi": "χ", "psi": "ψ",
    "omega": "ω",
    "Gamma": "Γ", "Delta": "Δ", "Theta": "Θ", "Lambda": "Λ", "Xi": "Ξ",
    "Pi": "Π", "Sigma": "Σ", "Phi": "Φ", "Psi": "Ψ", "Omega": "Ω",
    # 연산·관계
    "times": "×", "div": "÷", "pm": "±", "mp": "∓", "cdot": "·",
    "neq": "≠", "ne": "≠", "leq": "≤", "le": "≤", "geq": "≥", "ge": "≥",
    "ll": "≪", "gg": "≫", "approx": "≈", "sim": "∼", "simeq": "≃",
    "equiv": "≡", "cong": "≅", "propto": "∝",
    # 집합·논리
    "cap": "∩", "cup": "∪", "subset": "⊂", "subseteq": "⊆",
    "supset": "⊃", "supseteq": "⊇", "in": "∈", "notin": "∉",
    "emptyset": "∅", "varnothing": "∅", "mid": "∣", "setminus": "∖",
    "complement": "∁",
    # 도형·기하
    "angle": "∠", "triangle": "△", "square": "□", "perp": "⊥",
    "parallel": "∥", "circ": "∘", "prime": "′", "degree": "°",
    # 화살표
    "rightarrow": "→", "to": "→", "leftarrow": "←",
    "leftrightarrow": "↔", "Rightarrow": "⇒", "Leftarrow": "⇐",
    "Leftrightarrow": "⇔", "longrightarrow": "⟶",
    # 점·기타
    "cdots": "⋯", "ldots": "…", "dots": "…", "vdots": "⋮", "ddots": "⋱",
    "infty": "∞", "partial": "∂", "nabla": "∇", "forall": "∀",
    "exists": "∃", "neg": "¬", "therefore": "∴", "because": "∵",
    "sum": "∑", "prod": "∏", "int": "∫", "oint": "∮",
    "lim": "lim", "log": "log", "ln": "ln", "exp": "exp",
    "min": "min", "max": "max", "gcd": "gcd",
    "sin": "sin", "cos": "cos", "tan": "tan",
    "sec": "sec", "csc": "csc", "cot": "cot",
    "arcsin": "arcsin", "arccos": "arccos", "arctan": "arctan",
    "sinh": "sinh", "cosh": "cosh", "tanh": "tanh",
    "P": "P", "C": "C", "H": "H",
}

# 로만체(똑바로 선 글씨)로 찍어야 하는 것 — 함수 이름들
ROMAN_WORDS = {
    "lim", "log", "ln", "exp", "min", "max", "gcd",
    "sin", "cos", "tan", "sec", "csc", "cot",
    "arcsin", "arccos", "arctan", "sinh", "cosh", "tanh",
}

# 공백류
SPACES = {"quad": " ", "qquad": "  ", ",": " ", ";": " ", ":": " ",
          "!": "", " ": " ", "thinspace": " ", "enspace": " "}

# 액센트 (윗기호)
ACCENT = {
    "vec": "⃗", "overrightarrow": "⃗", "overleftarrow": "⃖",
    "hat": "̂", "widehat": "̂", "tilde": "̃", "widetilde": "̃",
    "dot": "̇", "ddot": "̈",
}

OPEN_CLOSE = {
    "(": ")", "[": "]", "\\{": "\\}", "|": "|", "\\|": "\\|",
    "\\langle": "\\rangle", ".": ".",
}

DELIM_CHAR = {
    "\\{": "{", "\\}": "}", "\\langle": "⟨", "\\rangle": "⟩",
    "\\|": "‖", "\\lfloor": "⌊", "\\rfloor": "⌋",
    "\\lceil": "⌈", "\\rceil": "⌉", ".": "",
}

TOKEN = re.compile(r"""
    (?P<cmd>\\[a-zA-Z]+)
  | (?P<esc>\\[^a-zA-Z])
  | (?P<open>\{)
  | (?P<close>\})
  | (?P<sup>\^)
  | (?P<sub>_)
  | (?P<amp>&)
  | (?P<sp>\s+)
  | (?P<ch>[^\\{}\^_&\s])
""", re.X)


def tokenize(s):
    out, i = [], 0
    while i < len(s):
        m = TOKEN.match(s, i)
        if not m:
            raise Unsupported(f"읽을 수 없는 글자: {s[i]!r}")
        i = m.end()
        kind = m.lastgroup
        if kind == "sp":
            continue
        out.append((kind, m.group()))
    return out


# ── 파서 ─────────────────────────────────────────────────────────────
class Parser:
    def __init__(self, toks):
        self.t = toks
        self.i = 0

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else (None, None)

    def next(self):
        v = self.peek()
        self.i += 1
        return v

    def parse(self, stop_close=False):
        nodes = []
        while self.i < len(self.t):
            kind, val = self.peek()
            if kind == "close":
                if stop_close:
                    return _clean(nodes)
                raise Unsupported("짝이 안 맞는 }")
            atom = self.atom()
            if atom is None:
                continue
            atom = self.scripts(atom)
            nodes.append(atom)
        return _clean(nodes)

    def group(self):
        """{ ... } 하나를 읽는다. 없으면 원자 하나."""
        kind, val = self.peek()
        if kind == "open":
            self.next()
            inner = self.parse(stop_close=True)
            k2, _ = self.next()
            if k2 != "close":
                raise Unsupported("} 가 없다")
            return inner
        a = self.atom()
        if a is None:
            raise Unsupported("인자가 없다")
        return [a]

    def scripts(self, base):
        """원자 뒤의 ^ _ 를 붙인다."""
        sup = sub = None
        while True:
            kind, val = self.peek()
            if kind == "sup" and sup is None:
                self.next()
                sup = self.group()
            elif kind == "sub" and sub is None:
                self.next()
                sub = self.group()
            else:
                break
        if sup is not None and sub is not None:
            return {"k": "subsup", "base": [base], "sub": sub, "sup": sup}
        if sup is not None:
            return {"k": "sup", "base": [base], "sup": sup}
        if sub is not None:
            return {"k": "sub", "base": [base], "sub": sub}
        return base

    def atom(self):
        kind, val = self.next()

        if kind == "open":
            self.i -= 1
            return {"k": "row", "e": self.group()}

        if kind == "ch":
            # OCR 이 평행 기호 ∥ 를 빗금 두 개로 읽는다. 교재에 나온 22곳이 전부
            # 평행이고 '두 번 나누기' 로 쓴 곳은 하나도 없어서 되돌려 놓는다.
            if val == "/" and self.peek() == ("ch", "/"):
                self.next()
                return {"k": "run", "t": "∥", "sty": "p"}
            # LaTeX 의 ~ 는 줄바꿈 없는 공백이다. 물결로 찍으면 안 된다.
            if val == "~":
                return {"k": "run", "t": " ", "sty": "p"}
            return {"k": "run", "t": val, "sty": "i" if val.isalpha() else "p"}

        if kind == "amp":
            raise Unsupported("표 형식(&)")

        if kind == "esc":
            c = val[1]
            if c in "{}%$#_&":
                return {"k": "run", "t": c, "sty": "p"}
            if c == "\\":
                raise Unsupported("줄바꿈(\\\\)")
            if c in SPACES:
                return {"k": "run", "t": SPACES[c], "sty": "p"}
            raise Unsupported(f"모르는 기호: {val}")

        if kind != "cmd":
            raise Unsupported(f"모르는 조각: {val}")

        name = val[1:]

        if name in ("begin", "end"):
            raise Unsupported("여러 줄 수식 환경")

        if name in SPACES:
            return {"k": "run", "t": SPACES[name], "sty": "p"}

        if name == "frac" or name == "dfrac" or name == "tfrac":
            n = self.group()
            d = self.group()
            return {"k": "frac", "n": n, "d": d}

        if name == "sqrt":
            deg = None
            # \sqrt[n]{x} 의 [n]
            if self.peek()[1] == "[":
                self.next()
                deg = []
                while self.peek()[1] != "]":
                    if self.peek()[0] is None:
                        raise Unsupported("] 가 없다")
                    a = self.atom()
                    if a is not None:
                        deg.append(a)
                self.next()
            e = self.group()
            return {"k": "rad", "deg": deg, "e": e}

        if name in ACCENT:
            return {"k": "acc", "chr": ACCENT[name], "e": self.group()}

        if name in ("overline", "bar"):
            return {"k": "bar", "pos": "top", "e": self.group()}

        if name == "underline":
            return {"k": "bar", "pos": "bot", "e": self.group()}

        if name in ("mathrm", "text", "textrm", "mathsf", "operatorname",
                    "mathbf", "mathit", "mathcal", "mathbb"):
            inner = self.group()
            sty = "b" if name == "mathbf" else (
                "i" if name == "mathit" else "p")
            return {"k": "style", "sty": sty, "e": inner}

        if name in ("left", "right"):
            return self.delim(name)

        if name in SYMBOL:
            txt = SYMBOL[name]
            sty = "p" if (name in ROMAN_WORDS or not txt.isalpha()) else "i"
            return {"k": "run", "t": txt, "sty": sty}

        raise Unsupported(f"모르는 명령: \\{name}")

    def delim(self, which):
        if which == "right":
            raise Unsupported("짝 없는 \\right")
        kind, val = self.next()
        if kind == "cmd":
            val = "\\" + val[1:]
        opener = DELIM_CHAR.get(val, val)

        inner = []
        depth = 0
        while True:
            kind, val = self.peek()
            if kind is None:
                raise Unsupported("\\right 가 없다")
            if kind == "cmd" and val == "\\left":
                depth += 1
            if kind == "cmd" and val == "\\right" and depth == 0:
                self.next()
                k2, v2 = self.next()
                closer = DELIM_CHAR.get(v2, v2)
                return {"k": "delim", "open": opener, "close": closer,
                        "e": _clean(inner)}
            if kind == "cmd" and val == "\\right":
                depth -= 1
            a = self.atom()
            if a is not None:
                inner.append(self.scripts(a))


def parse(latex):
    return Parser(tokenize(latex)).parse()


# ── 빈 칸을 없애는 뒷정리 ─────────────────────────────────────────────
#
# 워드·한/글은 수식의 빈 칸을 '네모 상자' 로 그린다.
# ₄P₂ 같은 앞첨자를 Mathpix 는 `{ }_{4} \mathrm{P}_{2}` 로 준다.
# 이걸 그대로 옮기면 밑이 빈 첨자가 되어 문장 맨 앞에 상자가 붙는다.
# 그래서 앞첨자 전용 구조(m:sPre)로 접어 넣고, 빈 칸은 아예 만들지 않는다.

# 남는 칸을 이걸로 메워 상자를 막는다. 눈에 안 보이는 글자라 escape 로 적는다.
ZWSP = "​"


def _is_hole(n):
    """밑이 빈 첨자인가. `{ }_{4}` 가 이렇게 들어온다."""
    if n.get("k") not in ("sub", "sup", "subsup"):
        return False
    b = n.get("base") or []
    return len(b) == 1 and b[0].get("k") == "row" and not b[0].get("e")


def _fold_pre(nodes):
    """밑이 빈 첨자 + 바로 뒤 글자 -> 앞첨자 한 덩어리."""
    out, i = [], 0
    while i < len(nodes):
        n = nodes[i]
        if _is_hole(n):
            if i + 1 >= len(nodes):
                raise Unsupported("앞첨자 뒤에 올 글자가 없다")
            out.append({"k": "pre", "base": [nodes[i + 1]],
                        "sub": n.get("sub"), "sup": n.get("sup")})
            i += 2
            continue
        out.append(n)
        i += 1
    return out


def _fold_bars(nodes):
    """짝지은 세로줄 |...| 을 절댓값 괄호로 접는다.

    `|\\overrightarrow{AC}|` 을 낱글자 그대로 두면 뷰어에 따라
    나눗셈 기호로 잘못 읽어 엉뚱한 기호를 찍는다. 괄호 구조로 만들어 둔다.
    """
    pos = [i for i, n in enumerate(nodes)
           if n.get("k") == "run" and n.get("t") == "|"]
    if len(pos) < 2 or len(pos) % 2:
        return nodes
    out, i, pairs = [], 0, dict(zip(pos[0::2], pos[1::2]))
    while i < len(nodes):
        if i in pairs:
            j = pairs[i]
            out.append({"k": "delim", "open": "|", "close": "|",
                        "e": nodes[i + 1:j]})
            i = j + 1
            continue
        out.append(nodes[i])
        i += 1
    return out


def _clean(nodes):
    return _fold_bars(_fold_pre(nodes))


# ── OMML 내보내기 (워드용) ────────────────────────────────────────────
def _o_run(text, sty):
    pr = ""
    if sty == "p":
        pr = '<m:rPr><m:sty m:val="p"/></m:rPr>'
    elif sty == "b":
        pr = '<m:rPr><m:sty m:val="b"/></m:rPr>'
    return f"<m:r>{pr}<m:t xml:space=\"preserve\">{escape(text)}</m:t></m:r>"


def _oq(nodes, sty, what):
    """수식의 한 칸을 채운다. 비면 Unsupported.

    빈 칸을 그대로 내보내면 워드·한/글이 그 자리에 네모 상자를 그린다.
    그 상자가 글머리기호처럼 문장 앞에 붙어 보인다. 비느니 그림으로 되돌린다.
    """
    s = _o(nodes or [], sty)
    if not s:
        raise Unsupported(f"빈 {what}")
    return s


def _o(nodes, sty=None):
    out = []
    for n in nodes:
        k = n["k"]
        if k == "run":
            out.append(_o_run(n["t"], sty or n["sty"]))
        elif k == "row":
            out.append(_o(n["e"], sty))
        elif k == "style":
            out.append(_o(n["e"], n["sty"]))
        elif k == "frac":
            out.append(f"<m:f><m:fPr><m:ctrlPr/></m:fPr>"
                       f"<m:num>{_oq(n['n'], sty, '분자')}</m:num>"
                       f"<m:den>{_oq(n['d'], sty, '분모')}</m:den></m:f>")
        elif k == "rad":
            if n["deg"]:
                out.append(f"<m:rad><m:radPr><m:ctrlPr/></m:radPr>"
                           f"<m:deg>{_oq(n['deg'], sty, '근호 지수')}</m:deg>"
                           f"<m:e>{_oq(n['e'], sty, '근호 안')}</m:e></m:rad>")
            else:
                out.append(f'<m:rad><m:radPr><m:degHide m:val="1"/>'
                           f"<m:ctrlPr/></m:radPr><m:deg/>"
                           f"<m:e>{_oq(n['e'], sty, '근호 안')}</m:e></m:rad>")
        elif k == "sup":
            out.append(f"<m:sSup><m:sSupPr><m:ctrlPr/></m:sSupPr>"
                       f"<m:e>{_oq(n['base'], sty, '밑')}</m:e>"
                       f"<m:sup>{_oq(n['sup'], sty, '윗첨자')}</m:sup></m:sSup>")
        elif k == "sub":
            out.append(f"<m:sSub><m:sSubPr><m:ctrlPr/></m:sSubPr>"
                       f"<m:e>{_oq(n['base'], sty, '밑')}</m:e>"
                       f"<m:sub>{_oq(n['sub'], sty, '아래첨자')}</m:sub></m:sSub>")
        elif k == "subsup":
            out.append(f"<m:sSubSup><m:sSubSupPr><m:ctrlPr/></m:sSubSupPr>"
                       f"<m:e>{_oq(n['base'], sty, '밑')}</m:e>"
                       f"<m:sub>{_oq(n['sub'], sty, '아래첨자')}</m:sub>"
                       f"<m:sup>{_oq(n['sup'], sty, '윗첨자')}</m:sup>"
                       f"</m:sSubSup>")
        elif k == "pre":
            # 앞첨자 ₄P₂. 안 쓰는 칸은 보이지 않는 글자로 메워 상자를 막는다.
            sb = _o(n["sub"], sty) if n.get("sub") else _o_run(ZWSP, "p")
            sp = _o(n["sup"], sty) if n.get("sup") else _o_run(ZWSP, "p")
            out.append(f"<m:sPre><m:sPrePr><m:ctrlPr/></m:sPrePr>"
                       f"<m:sub>{sb}</m:sub><m:sup>{sp}</m:sup>"
                       f"<m:e>{_oq(n['base'], sty, '앞첨자의 밑')}</m:e>"
                       f"</m:sPre>")
        elif k == "acc":
            out.append(f'<m:acc><m:accPr><m:chr m:val="{escape(n["chr"])}"/>'
                       f"<m:ctrlPr/></m:accPr>"
                       f"<m:e>{_oq(n['e'], sty, '기호 밑')}</m:e></m:acc>")
        elif k == "bar":
            out.append(f'<m:bar><m:barPr><m:pos m:val="{n["pos"]}"/>'
                       f"<m:ctrlPr/></m:barPr>"
                       f"<m:e>{_oq(n['e'], sty, '줄 안')}</m:e></m:bar>")
        elif k == "delim":
            out.append(f'<m:d><m:dPr><m:begChr m:val="{escape(n["open"])}"/>'
                       f'<m:endChr m:val="{escape(n["close"])}"/>'
                       f"<m:ctrlPr/></m:dPr>"
                       f"<m:e>{_oq(n['e'], sty, '괄호 안')}</m:e></m:d>")
        else:
            raise Unsupported(f"내보낼 수 없는 조각: {k}")
    return "".join(out)


def to_omml(latex):
    """LaTeX -> <m:oMath> XML 조각. 못 옮기면 Unsupported."""
    body = _o(parse(latex))
    if not body.strip():
        raise Unsupported("빈 수식")
    return f'<m:oMath xmlns:m="{M_NS}">{body}</m:oMath>'


# ── MathML 내보내기 (브라우저 미리보기용) ──────────────────────────────

# 윗기호의 결합 문자 -> 화면용 보통 글자
ACCENT_SPACING = {"⃗": "→", "⃖": "←", "̂": "^", "̃": "~",
                  "̇": "˙", "̈": "¨"}

def _m(nodes, sty=None):
    out = []
    for n in nodes:
        k = n["k"]
        if k == "run":
            s = sty or n["sty"]
            t = escape(n["t"])
            if not n["t"].strip():
                out.append(f"<mspace width='.25em'></mspace>")
            elif n["t"].isdigit():
                out.append(f"<mn>{t}</mn>")
            elif n["t"].isalpha():
                if s == "p":
                    out.append(f"<mi mathvariant='normal'>{t}</mi>")
                else:
                    out.append(f"<mi>{t}</mi>")
            elif n["t"] in ("(", ")", "[", "]", "{", "}", "|"):
                # 일반 괄호는 늘이지 않는다. 브라우저는 줄 맨 앞의 여는 괄호만
                # 분수 높이로 길게 늘여 여닫이 짝이 안 맞아 보인다 (실물 확인).
                # 늘어나는 괄호는 \left \right(delim)만 쓴다.
                out.append(f"<mo stretchy='false'>{t}</mo>")
            else:
                out.append(f"<mo>{t}</mo>")
        elif k == "row":
            out.append(f"<mrow>{_m(n['e'], sty)}</mrow>")
        elif k == "style":
            out.append(f"<mrow>{_m(n['e'], n['sty'])}</mrow>")
        elif k == "frac":
            out.append(f"<mfrac><mrow>{_m(n['n'], sty)}</mrow>"
                       f"<mrow>{_m(n['d'], sty)}</mrow></mfrac>")
        elif k == "rad":
            if n["deg"]:
                out.append(f"<mroot><mrow>{_m(n['e'], sty)}</mrow>"
                           f"<mrow>{_m(n['deg'], sty)}</mrow></mroot>")
            else:
                out.append(f"<msqrt>{_m(n['e'], sty)}</msqrt>")
        elif k == "sup":
            out.append(f"<msup><mrow>{_m(n['base'], sty)}</mrow>"
                       f"<mrow>{_m(n['sup'], sty)}</mrow></msup>")
        elif k == "sub":
            out.append(f"<msub><mrow>{_m(n['base'], sty)}</mrow>"
                       f"<mrow>{_m(n['sub'], sty)}</mrow></msub>")
        elif k == "subsup":
            out.append(f"<msubsup><mrow>{_m(n['base'], sty)}</mrow>"
                       f"<mrow>{_m(n['sub'], sty)}</mrow>"
                       f"<mrow>{_m(n['sup'], sty)}</mrow></msubsup>")
        elif k == "pre":
            sb = f"<mrow>{_m(n['sub'], sty)}</mrow>" if n.get("sub") \
                else "<none/>"
            sp = f"<mrow>{_m(n['sup'], sty)}</mrow>" if n.get("sup") \
                else "<none/>"
            out.append(f"<mmultiscripts><mrow>{_m(n['base'], sty)}</mrow>"
                       f"<mprescripts/>{sb}{sp}</mmultiscripts>")
        elif k == "acc":
            # 결합 문자는 홀로 서지 못해 브라우저가 빈 칸으로 그린다.
            # 화면용에는 보통 글자(→ 등)로 바꿔 얹는다. 워드용(OMML)은 결합 문자가 맞다.
            chho = ACCENT_SPACING.get(n["chr"], n["chr"])
            out.append(f"<mover accent='true'><mrow>{_m(n['e'], sty)}</mrow>"
                       f"<mo stretchy='true'>{escape(chho)}</mo></mover>")
        elif k == "bar":
            # 윗줄 기호(¯)는 글꼴이 늘여 주지 않아 두 글자 위에서도 짧게 보인다
            # (Latin Modern·STIX 모두 실물 확인). mover 대신 테두리 선으로 긋는다
            # — 폭이 내용에 정확히 맞는다. CSS 는 조판 CSS(.ovl/.unl)에 있다.
            cls = "ovl" if n["pos"] == "top" else "unl"
            out.append(f"<mrow class='{cls}'>{_m(n['e'], sty)}</mrow>")
        elif k == "delim":
            o = escape(n["open"]) if n["open"] else ""
            c = escape(n["close"]) if n["close"] else ""
            out.append(f"<mrow><mo stretchy='true'>{o}</mo>"
                       f"<mrow>{_m(n['e'], sty)}</mrow>"
                       f"<mo stretchy='true'>{c}</mo></mrow>")
        else:
            raise Unsupported(f"내보낼 수 없는 조각: {k}")
    return "".join(out)


def _mathml_inner(latex, display=False):
    m = to_mathml(latex, display)
    return re.sub(r"^<math[^>]*>|</math>$", "", m)


def _cases_to_mathml(match):
    body = match.group(1)
    rows = [r.strip() for r in re.split(r"\\\\", body) if r.strip()]
    trs = []
    for row in rows:
        cols = [c.strip() for c in row.split("&")]
        tds = "".join(f"<mtd>{_mathml_inner(c)}</mtd>" for c in cols if c)
        trs.append(f"<mtr>{tds}</mtr>")
    return ("<mrow><mo>{</mo><mtable columnalign='left'>"
            + "".join(trs) + "</mtable></mrow>")


def to_mathml(latex, display=False):
    latex = _normalize_cases(latex)
    if "\\begin{cases}" in latex:
        pieces = []
        pos = 0
        for mm in CASES_RE.finditer(latex):
            pre = latex[pos:mm.start()].strip()
            if pre:
                pieces.append(_mathml_inner(pre, display))
            pieces.append(_cases_to_mathml(mm))
            pos = mm.end()
        tail = latex[pos:].strip()
        if tail:
            pieces.append(_mathml_inner(tail, display))
        mode = ' display="block"' if display else ""
        return f'<math xmlns="http://www.w3.org/1998/Math/MathML"{mode}><mrow>' \
               + "".join(pieces) + "</mrow></math>"
    body = _m(parse(latex))
    if not body.strip():
        raise Unsupported("빈 수식")
    d = "block" if display else "inline"
    return (f"<math xmlns='http://www.w3.org/1998/Math/MathML' "
            f"display='{d}'><mrow>{body}</mrow></math>")


# ── 한/글 수식 스크립트 내보내기 (HWPX 용) ───────────────────────────
#
# 한/글 수식 편집기는 자체 스크립트를 쓴다 (한컴 공식 스펙 '수식' rev 1.3).
#   분수 a over b / 근호 sqrt {x} / 첨자 ^{ } _{ } / 벡터 vec {x} / 윗줄 bar {x}
#   괄호 LEFT ( ... RIGHT ) / 앞첨자 LSUB
# 기호는 한/글 명령이 있으면 그걸 쓰고, 없으면 유니코드 글자를 그대로 둔다
# (수식 편집기는 유니코드 글자를 받아들인다).

HWP_SYMBOL = {
    "×": "times", "÷": "div", "±": "+-", "∓": "-+",
    "≠": "!=", "≤": "leq", "≥": "geq", "≡": "==",
    "∈": "in", "∉": "notin", "⊂": "subset", "⊆": "subseteq",
    "∩": "cap", "∪": "cup", "→": "rarrow", "←": "larrow",
    "⇒": "RARROW", "⇔": "LRARROW", "∞": "inf", "∴": "therefore",
    "∵": "because", "∑": "sum", "∏": "prod", "∫": "int",
    "π": "pi", "α": "alpha", "β": "beta", "γ": "gamma", "θ": "theta",
    "λ": "lambda", "μ": "mu", "σ": "sigma", "ω": "omega", "Δ": "DELTA",
    "⋯": "cdots", "…": "ldots", "∥": "parallel", "⊥": "perp",
    "√": "sqrt",
}

# 한/글 스크립트에서 특별한 뜻을 갖는 글자. 글자 그대로 내보낼 땐 따옴표로 감싼다.
_HWP_SPECIAL = set("{}^_&#~`\"")


def _hs_run(text, sty):
    del sty
    out = []
    for ch in text:
        if ch in HWP_SYMBOL:
            out.append(" " + HWP_SYMBOL[ch] + " ")
        elif ch in _HWP_SPECIAL:
            out.append('"' + ch + '"')
        else:
            out.append(ch)
    return "".join(out)


def _hs(nodes, sty=None):
    out = []
    for n in nodes:
        k = n["k"]
        if k == "run":
            out.append(_hs_run(n["t"], sty or n["sty"]))
        elif k == "row":
            out.append("{" + _hs(n["e"], sty) + "}")
        elif k == "style":
            body = _hs(n["e"], n["sty"])
            # 로만체 강제is rm — 함수 이름·단위가 이탤릭이 되는 것을 막는다
            out.append("{rm {" + body + "}}" if n["sty"] == "p" else "{" + body + "}")
        elif k == "frac":
            out.append("{" + _hs(n["n"], sty) + "} over {" + _hs(n["d"], sty) + "}")
        elif k == "rad":
            if n["deg"]:
                # n제곱근은 root n of 표기 — ^{n} sqrt 는 한/글이 못 읽어
                # 빈 수식이 된다 (실물: 수식문법시험 [5][7] 안 보임, [6] 정상).
                out.append("root " + _hs(n["deg"], sty) + " of {" + _hs(n["e"], sty) + "}")
            else:
                out.append("sqrt {" + _hs(n["e"], sty) + "}")
        elif k == "sup":
            out.append("{" + _hs(n["base"], sty) + "} ^{" + _hs(n["sup"], sty) + "}")
        elif k == "sub":
            base = _hs(n["base"], sty)
            plain = re.sub(r"[{}\s]|rm", "", base)
            if plain in ("lim", "min", "max"):
                # 극한류는 아래끝(from) — _{} 로 쓰면 한/글이 옆에 붙인다 (실물).
                out.append(base + " from {" + _hs(n["sub"], sty) + "}")
            else:
                out.append("{" + base + "} _{" + _hs(n["sub"], sty) + "}")
        elif k == "subsup":
            out.append("{" + _hs(n["base"], sty) + "} _{" + _hs(n["sub"], sty)
                       + "} ^{" + _hs(n["sup"], sty) + "}")
        elif k == "pre":
            inner = "{" + _hs(n["base"], sty) + "}"
            if n.get("sub"):
                inner += " LSUB {" + _hs(n["sub"], sty) + "}"
            if n.get("sup"):
                inner += " LSUP {" + _hs(n["sup"], sty) + "}"
            out.append(inner)
        elif k == "acc":
            cmd = {"⃗": "vec", "⃖": "vec", "̂": "hat", "̃": "tilde",
                   "̇": "dot", "̈": "ddot"}.get(n["chr"])
            if cmd is None:
                raise Unsupported(f"한/글로 못 옮기는 윗기호: {n['chr']!r}")
            out.append(cmd + " {" + _hs(n["e"], sty) + "}")
        elif k == "bar":
            if n["pos"] == "top":
                out.append("bar {" + _hs(n["e"], sty) + "}")
            else:
                out.append("under {" + _hs(n["e"], sty) + "}")
        elif k == "delim":
            opener = n["open"] or "("
            closer = n["close"] or ")"
            inner = _hs(n["e"], sty)
            tall = re.search(r"\bover\b|\bsqrt\b|\broot\b|\bpile\b|\bsum\b"
                             r"|\bint\b|\bfrom\b", inner)
            if tall or opener in "{}" or closer in "{}":
                out.append("LEFT " + opener + " " + inner + " RIGHT " + closer)
            else:
                # 키 작은 내용은 평괄호 — LEFT( 는 자동 확대라 OCR 이 섞어 쓴
                # 평괄호와 크기가 어긋난다 (실물: 미래엔 예제3 닫는 괄호만 큼).
                out.append(opener + " " + inner + " " + closer)
        else:
            raise Unsupported(f"한/글로 내보낼 수 없는 조각: {k}")
    return " ".join(part for part in out if part.strip())


CASES_RE = re.compile(r"\\begin\{cases\}(.*?)\\end\{cases\}", re.S)
# Mathpix 는 조건별 함수를 \left\{\begin{array}{ll}…\end{array}\right. 로 쓴다
ARRAY_CASES_RE = re.compile(
    r"\\left\\?\{\s*\\begin\{array\}\{[a-z ]*\}(.*?)\\end\{array\}\s*\\right\s*\.",
    re.S)


def _normalize_cases(latex):
    return ARRAY_CASES_RE.sub(lambda m: "\\begin{cases}" + m.group(1) + "\\end{cases}",
                              latex)


def _cases_to_pile(match):
    body = match.group(1)
    rows = [r.strip() for r in re.split(r"\\\\", body) if r.strip()]
    parts = []
    for row in rows:
        cols = [c.strip() for c in row.split("&")]
        parts.append(" ~~ ".join(_hs(parse(c), None) for c in cols if c))
    return "LEFT \\{ pile{" + " # ".join(parts) + "}"


def to_hwp_script(latex):
    """LaTeX -> 한/글 수식 스크립트. 못 옮기면 Unsupported."""
    latex = _normalize_cases(latex)
    if "\\begin{cases}" in latex:
        # 조건별 함수 — 왼쪽 큰 중괄호 + 세로 쌓기(pile) (미래엔 20쪽 실측)
        out = []
        pos = 0
        for m in CASES_RE.finditer(latex):
            pre = latex[pos:m.start()].strip()
            if pre:
                out.append(_hs(parse(pre), None))
            out.append(_cases_to_pile(m))
            pos = m.end()
        tail = latex[pos:].strip()
        if tail:
            out.append(_hs(parse(tail), None))
        return " ".join(out)
    body = _hs(parse(latex))
    if not body.strip():
        raise Unsupported("빈 수식")
    return body


# ── 줄 하나를 글자와 수식으로 가르기 ─────────────────────────────────
SPLIT = re.compile(
    r"\\\[(?P<disp>.*?)\\\]"
    r"|\\\((?P<inl>.*?)\\\)"
    r"|\$\$(?P<dd>.*?)\$\$"
    r"|\$(?P<d>.*?)\$",
    re.S)


def segments(text):
    """('t', 글자) 와 ('m', LaTeX, 큰수식인지) 로 가른다."""
    out, pos = [], 0
    for m in SPLIT.finditer(text):
        if m.start() > pos:
            out.append(("t", text[pos:m.start()]))
        disp = m.group("disp") is not None or m.group("dd") is not None
        body = (m.group("disp") or m.group("inl")
                or m.group("dd") or m.group("d") or "")
        out.append(("m", body, disp))
        pos = m.end()
    if pos < len(text):
        out.append(("t", text[pos:]))
    return out


def has_math(text):
    return any(s[0] == "m" for s in segments(text))


# ── 자체 시험 ────────────────────────────────────────────────────────
CASES = [
    r"\frac{x^{2}}{4}+\frac{y^{2}}{9}=1",
    r"\overline{\mathrm{PF}}=\overline{\mathrm{PH}}",
    r"\sqrt{5}",
    r"\overrightarrow{\mathrm{AB}}+\overrightarrow{\mathrm{BC}}",
    r"\vec{a} \neq \vec{0}",
    r"\left(\sqrt{5}, 0\right)",
    r"10 \mathrm{~m} / \mathrm{s}",
    r"\sin \theta \times \cos \theta",
    r"\mathrm{P}(A \cap B)=\mathrm{P}(A) \mathrm{P}(B)",
    r"x_{1}^{2}",
    r"\triangle \mathrm{ABH} \equiv \triangle \mathrm{ACH}",
    r"\frac{\sqrt{3}}{2} \pi",
    r"{ }_{5} \mathrm{P}_{2}",
    r"{ }_{n} \Pi_{r}",
    r"n(S)={ }_{7} \mathrm{C}_{3}=35",
    r"|\overrightarrow{\mathrm{AC}}|",
]


def selftest():
    bad = 0
    for c in CASES:
        try:
            o = to_omml(c)
            m = to_mathml(c)
            h = to_hwp_script(c)
            assert o.startswith("<m:oMath") and m.startswith("<math") and h.strip()
            print(f"  OK   {c[:56]}")
        except Exception as e:
            bad += 1
            print(f"  실패 {c[:56]}  -> {e}")
    print(f"\n{len(CASES) - bad}/{len(CASES)} 통과")
    return 1 if bad else 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    for line in sys.stdin:
        line = line.strip()
        if line:
            try:
                print(to_omml(line))
            except Unsupported as e:
                print(f"[못 옮김] {e}", file=sys.stderr)
