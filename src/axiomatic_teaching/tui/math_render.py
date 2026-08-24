"""Approximate LaTeX math as Unicode for ChatStream.

ChatStream stays a selectable, copyable RichLog. Complex multi-line layouts
(matrices, ``align``, and similar environments) remain approximate by design:
this module never emits images or terminal-graphics protocols.
"""

from __future__ import annotations

import re

from unicodeitplus import replace as unicodeit_replace

# $$ / \[...\] first so they are not eaten as single-dollar / leftover brackets.
# Optional extra backslash covers JSON-escaped \\( / \\[ forms.
_MATH_RE = re.compile(
    r"(?<!\\)\$\$(?P<dd>.*?)(?<!\\)\$\$"
    r"|(?:\\\\|\\)\[(?P<db>.*?)(?:\\\\|\\)\]"
    r"|(?:\\\\|\\)\((?P<ip>.*?)(?:\\\\|\\)\)"
    r"|(?<!\\)\$(?P<id>[^$\n]+)(?<!\\)\$",
    re.DOTALL,
)
_MATH_HINT = re.compile(r"\$|\\\(|\\\[")
_LEFTOVER_CMD = re.compile(r"\\[A-Za-z]+")
_STYLE_RE = re.compile(
    r"\\(?:displaystyle|textstyle|scriptstyle|scriptscriptstyle|limits|nolimits)"
    r"(?![A-Za-z])\s*"
)
_OPERATOR_RE = re.compile(
    r"\\("
    r"limsup|liminf|arcsin|arccos|arctan|"
    r"sinh|cosh|tanh|sin|cos|tan|cot|sec|csc|"
    r"exp|log|ln|lg|Pr|lim|inf|sup|max|min|"
    r"arg|det|dim|ker|gcd|hom|deg"
    r")(?![A-Za-z])"
)
_ALIAS_RES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\\emptyset(?![A-Za-z])"), r"\\varnothing"),
    (re.compile(r"\\vert(?![A-Za-z])"), r"\\mid"),
    (re.compile(r"\\lvert(?![A-Za-z])"), "|"),
    (re.compile(r"\\rvert(?![A-Za-z])"), "|"),
    (re.compile(r"\\implies(?![A-Za-z])"), r"\\Rightarrow"),
    (re.compile(r"\\iff(?![A-Za-z])"), r"\\Leftrightarrow"),
    (re.compile(r"\\qquad(?![A-Za-z])"), " "),
    (re.compile(r"\\quad(?![A-Za-z])"), " "),
    (re.compile(r"\\!"), ""),
)
_FRAC_NAMES = ("\\dfrac", "\\tfrac", "\\cfrac", "\\frac")
_VULGAR_FRACTIONS = {
    ("1", "2"): "½",
    ("1", "3"): "⅓",
    ("2", "3"): "⅔",
    ("1", "4"): "¼",
    ("3", "4"): "¾",
    ("1", "5"): "⅕",
    ("2", "5"): "⅖",
    ("3", "5"): "⅗",
    ("4", "5"): "⅘",
    ("1", "6"): "⅙",
    ("5", "6"): "⅚",
    ("1", "7"): "⅐",
    ("1", "8"): "⅛",
    ("3", "8"): "⅜",
    ("5", "8"): "⅝",
    ("7", "8"): "⅞",
    ("1", "9"): "⅑",
    ("1", "10"): "⅒",
}
_ATOMIC_FRAC = re.compile(r"^[A-Za-z0-9]+$")


def latex_to_unicode(text: str) -> str:
    """Replace delimited LaTeX math with a Unicode approximation.

    Detects ``\\(...\\)``, ``$...$``, ``\\[...\\]``, and ``$$...$$``. Inner
    LaTeX is converted with unicodeitplus; on any conversion error, empty
    result, or leftover unknown command the original match is kept. Surrounding
    non-math text is preserved exactly.

    Incomplete delimiters (typical while a stream chunk splits an expression)
    are left raw until a later complete match exists in the same string.
    """
    if not text or _MATH_HINT.search(text) is None:
        return text
    return _MATH_RE.sub(_replace_match, text)


def _replace_match(match: re.Match[str]) -> str:
    inner = next((group for group in match.groups() if group is not None), None)
    if inner is None or not inner.strip():
        return match.group(0)
    converted = _convert_inner(inner)
    return converted if converted is not None else match.group(0)


def _convert_inner(inner: str) -> str | None:
    try:
        prepared = _prepare_latex(inner)
        result = unicodeit_replace(prepared)
    except Exception:
        return None
    if not result or not str(result).strip():
        return None
    text = str(result)
    if _LEFTOVER_CMD.search(text):
        return None
    return text


def _prepare_latex(tex: str) -> str:
    text = _STYLE_RE.sub("", tex)
    for pattern, repl in _ALIAS_RES:
        text = pattern.sub(repl, text)
    text = _OPERATOR_RE.sub(r"\\text{\1}", text)
    return _replace_fracs(text)


def _replace_fracs(tex: str) -> str:
    pieces: list[str] = []
    i = 0
    length = len(tex)
    while i < length:
        name = _frac_at(tex, i)
        if name is None:
            pieces.append(tex[i])
            i += 1
            continue
        cursor = i + len(name)
        while cursor < length and tex[cursor].isspace():
            cursor += 1
        num, cursor = _consume_group(tex, cursor)
        if num is None:
            pieces.append(tex[i])
            i += 1
            continue
        while cursor < length and tex[cursor].isspace():
            cursor += 1
        den, cursor = _consume_group(tex, cursor)
        if den is None:
            pieces.append(tex[i])
            i += 1
            continue
        pieces.append(_format_frac(num, den))
        i = cursor
    return "".join(pieces)


def _frac_at(tex: str, index: int) -> str | None:
    for name in _FRAC_NAMES:
        if tex.startswith(name, index) and _command_boundary(tex, index + len(name)):
            return name
    return None


def _command_boundary(tex: str, index: int) -> bool:
    return index >= len(tex) or not tex[index].isalpha()


def _consume_group(tex: str, index: int) -> tuple[str | None, int]:
    if index >= len(tex):
        return None, index
    if tex[index] == "{":
        depth = 1
        cursor = index + 1
        while cursor < len(tex) and depth:
            char = tex[cursor]
            if char == "\\" and cursor + 1 < len(tex):
                cursor += 2
                continue
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
            cursor += 1
        if depth != 0:
            return None, index
        return tex[index + 1 : cursor - 1], cursor
    if tex[index] == "\\":
        cursor = index + 1
        if cursor < len(tex) and tex[cursor].isalpha():
            while cursor < len(tex) and tex[cursor].isalpha():
                cursor += 1
        else:
            cursor = min(cursor + 1, len(tex))
        return tex[index:cursor], cursor
    return tex[index], index + 1


def _format_frac(num: str, den: str) -> str:
    n = _replace_fracs(num).strip()
    d = _replace_fracs(den).strip()
    vulgar = _VULGAR_FRACTIONS.get((n, d))
    if vulgar is not None:
        return vulgar
    n_part = n if _is_atomic_frac(n) else f"({n})"
    d_part = d if _is_atomic_frac(d) else f"({d})"
    return f"{n_part}/{d_part}"


def _is_atomic_frac(part: str) -> bool:
    if not part:
        return False
    if part in _VULGAR_FRACTIONS.values():
        return True
    if len(part) == 1:
        return True
    return _ATOMIC_FRAC.fullmatch(part) is not None
