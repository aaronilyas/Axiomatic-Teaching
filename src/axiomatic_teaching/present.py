"""Assemble, write, and open self-contained lesson HTML for `present_lesson_html`.

The MCP handler validates and returns structured JSON. The TUI writes the file
into the per-lesson workspace and opens it (``os.startfile`` on Windows).
"""

from __future__ import annotations

import html as html_lib
import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PRESENT_TOOL_NAME = "present_lesson_html"
PRESENT_FILENAME_PREFIX = "present-"
HTML_MAX_CHARS = 1_000_000
CSS_MAX_CHARS = 200_000
TITLE_MAX_CHARS = 200
MAX_PRESENT_BYTES = 1_048_576

DEFAULT_PRESENT_CSS = """\
:root { color-scheme: light dark; }
html { font-family: ui-sans-serif, system-ui, sans-serif; line-height: 1.5; }
body { max-width: 44rem; margin: 2rem auto; padding: 0 1.25rem; }
img, svg { max-width: 100%; height: auto; }
pre, code { font-family: ui-monospace, Menlo, Consolas, monospace; }
pre { overflow-x: auto; }
.axiomatic-footnote { margin-top: 2.5rem; font-size: 0.85rem; opacity: 0.7; }
"""

FRAGMENT_FOOTNOTE = (
    '<p class="axiomatic-footnote">'
    "Questions stay in the Axiomatic Teaching chat — this page is reading only."
    "</p>"
)

SUCCESS_OPENED = "Lesson page opened in your browser. Return here when you're ready."
SUCCESS_NO_BROWSER = (
    "Could not open a browser. Open this file then return here: {uri}"
)
DEMO_SAVED = (
    "Demo mode saved a lesson page but did not open a browser. "
    "Return here when you're ready."
)
ERROR_EMPTY = "Could not present lesson page: HTML was empty."
ERROR_TOO_LARGE = "Could not present lesson page: HTML was too large."
ERROR_NO_WORKSPACE = "Could not present lesson page: no lesson workspace."
ERROR_WRITE = "Could not present lesson page: {exc}"
ERROR_TOOL_FAILED = "Could not present lesson page: the tutor tool failed."
ERROR_REJECTED = "Could not present lesson page: {reason}"

_PRESENT_RE = re.compile(r"^present-(\d+)\.html$", re.IGNORECASE)
_SCRIPT_RE = re.compile(r"<script\b[^>]*>.*?</script>", re.IGNORECASE | re.DOTALL)
_SCRIPT_EMPTY_RE = re.compile(r"<script\b[^>]*/>", re.IGNORECASE)
_SCRIPT_UNCLOSED_RE = re.compile(r"<script\b[^>]*>.*", re.IGNORECASE | re.DOTALL)
_HEAD_CLOSE_RE = re.compile(r"</head\s*>", re.IGNORECASE)
_TITLE_RE = re.compile(r"<title\b[^>]*>.*?</title>", re.IGNORECASE | re.DOTALL)
_HTML_TAG_RE = re.compile(r"<html\b[^>]*>", re.IGNORECASE)
_HEAD_OPEN_RE = re.compile(r"<head\b", re.IGNORECASE)
_STYLE_CLOSE_RE = re.compile(r"</style", re.IGNORECASE)

_NEST_KEYS = (
    "arguments",
    "input",
    "params",
    "data",
    "raw_input",
    "result",
    "output",
    "structuredContent",
    "structured_content",
    "content",
    "text",
    "OkayOutput",
)


@dataclass(slots=True, frozen=True)
class PresentHtmlRequest:
    html: str
    title: str = ""
    css: str = ""


@dataclass(slots=True, frozen=True)
class WrappedHtml:
    document: str
    title: str
    is_full_document: bool
    css_inlined: bool
    scripts_stripped: bool


@dataclass(slots=True, frozen=True)
class PresentHtmlResult:
    ok: bool
    path: Path | None = None
    uri: str = ""
    opened: bool = False
    written: bool = False
    message: str = ""
    scripts_stripped: bool = False
    is_full_document: bool = False
    css_inlined: bool = False
    bytes: int = 0


def is_full_document(html: str) -> bool:
    head = html.lstrip("\ufeff \t\r\n")[:256].lower()
    return head.startswith("<!doctype") or head.startswith("<html")


def strip_scripts(html: str) -> tuple[str, bool]:
    stripped, n1 = _SCRIPT_RE.subn("", html)
    stripped, n2 = _SCRIPT_EMPTY_RE.subn("", stripped)
    stripped, n3 = _SCRIPT_UNCLOSED_RE.subn("", stripped)
    return stripped, (n1 + n2 + n3) > 0


def sanitize_css(css: str) -> str:
    return _STYLE_CLOSE_RE.sub("", css)


def wrap_lesson_html(html: str, title: str = "", css: str = "") -> WrappedHtml:
    """Build a self-contained document. Never injects JavaScript."""
    source = html.lstrip("\ufeff")
    stripped, scripts_stripped = strip_scripts(source)
    full = is_full_document(stripped)
    safe_css = sanitize_css(css)
    raw_title = (title or "").strip()
    safe_title = html_lib.escape(raw_title or "Lesson", quote=True)
    if full:
        document = stripped
        if raw_title:
            document = _apply_title(document, safe_title)
        css_inlined = False
        if safe_css.strip():
            document = _inject_style(document, safe_css.strip())
            css_inlined = True
        return WrappedHtml(
            document=document,
            title=raw_title,
            is_full_document=True,
            css_inlined=css_inlined,
            scripts_stripped=scripts_stripped,
        )
    extra = f"\n{safe_css.strip()}\n" if safe_css.strip() else ""
    document = (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{safe_title}</title>\n"
        "<style>\n"
        f"{DEFAULT_PRESENT_CSS}"
        f"{extra}"
        "</style>\n"
        "</head>\n"
        "<body>\n"
        f"{stripped}\n"
        f"{FRAGMENT_FOOTNOTE}\n"
        "</body>\n"
        "</html>\n"
    )
    return WrappedHtml(
        document=document,
        title=raw_title or "Lesson",
        is_full_document=False,
        css_inlined=True,
        scripts_stripped=scripts_stripped,
    )


def next_present_index(workspace: Path) -> int:
    try:
        names = [path.name for path in workspace.iterdir()]
    except FileNotFoundError:
        return 1
    used = [
        int(match.group(1))
        for name in names
        if (match := _PRESENT_RE.match(name))
    ]
    return max(used, default=0) + 1


def next_present_path(workspace: Path) -> Path:
    return workspace / f"present-{next_present_index(workspace):03d}.html"


def write_present_html(workspace: Path, document: str) -> Path:
    workspace.mkdir(parents=True, exist_ok=True)
    n = next_present_index(workspace)
    while True:
        path = workspace / f"present-{n:03d}.html"
        try:
            with path.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(document)
            return path
        except FileExistsError:
            n += 1


def file_uri(path: Path) -> str:
    return path.resolve().as_uri()


def open_present_file(
    path: Path,
    *,
    opener: Callable[[str], bool] | None = None,
) -> bool:
    real = path.resolve()
    if opener is not None:
        try:
            return bool(opener(file_uri(real)))
        except Exception:
            return False
    if os.name == "nt":
        startfile = getattr(os, "startfile", None)
        if not callable(startfile):
            return False
        try:
            startfile(os.fspath(real))
            return True
        except Exception:
            return False
    try:
        import webbrowser

        return bool(webbrowser.open_new_tab(file_uri(real)))
    except Exception:
        return False


def parse_present_html(payload: object) -> PresentHtmlRequest | None:
    """Extract html/title/css from a tool-call payload (Grok MCP envelopes included)."""
    blob = _find_html_dict(payload, depth=0)
    if blob is None:
        return None
    html = str(blob.get("html") or "").strip()
    if not html:
        return None
    return PresentHtmlRequest(
        html=html,
        title=str(blob.get("title") or ""),
        css=str(blob.get("css") or ""),
    )


def parse_present_output(payload: object) -> dict[str, Any] | None:
    """Unwrap MCP envelopes until a dict with a boolean ``ok`` is found."""
    return _find_ok_dict(payload, depth=0)


def deliver_present(
    workspace: Path,
    request: PresentHtmlRequest,
    *,
    open_browser: bool = True,
    opener: Callable[[str], bool] | None = None,
) -> PresentHtmlResult:
    html = request.html.strip()
    if not html:
        return PresentHtmlResult(ok=False, message=ERROR_EMPTY)
    try:
        wrapped = wrap_lesson_html(html, request.title, request.css)
    except Exception as exc:
        return PresentHtmlResult(ok=False, message=ERROR_WRITE.format(exc=exc))
    encoded = wrapped.document.encode("utf-8")
    if len(encoded) > MAX_PRESENT_BYTES:
        return PresentHtmlResult(ok=False, message=ERROR_TOO_LARGE)
    try:
        path = write_present_html(workspace, wrapped.document)
    except OSError as exc:
        return PresentHtmlResult(ok=False, message=ERROR_WRITE.format(exc=exc))
    uri = file_uri(path)
    common = {
        "path": path,
        "uri": uri,
        "written": True,
        "scripts_stripped": wrapped.scripts_stripped,
        "is_full_document": wrapped.is_full_document,
        "css_inlined": wrapped.css_inlined,
        "bytes": len(encoded),
    }
    if not open_browser:
        return PresentHtmlResult(
            ok=True,
            opened=False,
            message=DEMO_SAVED,
            **common,
        )
    opened = open_present_file(path, opener=opener)
    message = SUCCESS_OPENED if opened else SUCCESS_NO_BROWSER.format(uri=uri)
    return PresentHtmlResult(ok=True, opened=opened, message=message, **common)


def _apply_title(document: str, escaped_title: str) -> str:
    replacement = f"<title>{escaped_title}</title>"
    if _TITLE_RE.search(document):
        return _TITLE_RE.sub(lambda _m: replacement, document, count=1)
    return _inject_into_head(document, replacement)


def _inject_style(document: str, css: str) -> str:
    block = f"<style>\n{css}\n</style>"
    if _HEAD_CLOSE_RE.search(document):
        return _HEAD_CLOSE_RE.sub(lambda _m: block + "\n</head>", document, count=1)
    return _inject_into_head(document, block)


def _inject_into_head(document: str, snippet: str) -> str:
    if _HEAD_OPEN_RE.search(document):
        if _HEAD_CLOSE_RE.search(document):
            return _HEAD_CLOSE_RE.sub(snippet + "\n</head>", document, count=1)
        return document + snippet
    match = _HTML_TAG_RE.search(document)
    head = f"<head>\n{snippet}\n</head>"
    if match:
        return document[: match.end()] + head + document[match.end() :]
    return head + document


def _find_html_dict(payload: object, depth: int) -> dict[str, Any] | None:
    if depth > 6 or payload is None:
        return None
    if isinstance(payload, list):
        for item in payload:
            found = _find_html_dict(item, depth + 1)
            if found is not None:
                return found
        return None
    blob = _coerce_dict(payload)
    if blob is None:
        return None
    html = blob.get("html")
    if isinstance(html, str) and html.strip():
        return blob
    for key in _NEST_KEYS:
        if key in blob:
            found = _find_html_dict(blob[key], depth + 1)
            if found is not None:
                return found
    return None


def _find_ok_dict(payload: object, depth: int) -> dict[str, Any] | None:
    if depth > 6 or payload is None:
        return None
    if isinstance(payload, list):
        for item in payload:
            found = _find_ok_dict(item, depth + 1)
            if found is not None:
                return found
        return None
    blob = _coerce_dict(payload)
    if blob is None:
        return None
    if isinstance(blob.get("ok"), bool):
        return blob
    for key in _NEST_KEYS:
        if key in blob:
            found = _find_ok_dict(blob[key], depth + 1)
            if found is not None:
                return found
    return None


def _coerce_dict(payload: object) -> dict[str, Any] | None:
    if isinstance(payload, dict):
        return payload
    if not isinstance(payload, str):
        return None
    text = payload.strip()
    if not text:
        return None
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(line for line in lines if not line.strip().startswith("```")).strip() or text
    try:
        parsed = json.loads(text)
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None
