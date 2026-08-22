"""Pure tests for HTML present: wrap, write, URI, parse, deliver (no Textual)."""

from __future__ import annotations

import os
from pathlib import Path, PureWindowsPath

import pytest

from axiomatic_teaching.present import (
    DEMO_SAVED,
    ERROR_EMPTY,
    ERROR_TOO_LARGE,
    FRAGMENT_FOOTNOTE,
    MAX_PRESENT_BYTES,
    SUCCESS_OPENED,
    SUCCESS_NO_BROWSER,
    PresentHtmlRequest,
    deliver_present,
    file_uri,
    open_present_file,
    parse_present_html,
    parse_present_output,
    wrap_lesson_html,
    write_present_html,
)


def test_wrap_fragment_is_self_contained() -> None:
    wrapped = wrap_lesson_html("<p>Bayes updates a prior.</p>", "Bayes", "p { color: navy; }")
    doc = wrapped.document
    assert doc.lstrip().lower().startswith("<!doctype html>")
    assert "<title>Bayes</title>" in doc
    assert "<p>Bayes updates a prior.</p>" in doc
    assert "p { color: navy; }" in doc
    assert "<style>" in doc
    assert FRAGMENT_FOOTNOTE in doc
    assert wrapped.is_full_document is False
    assert wrapped.css_inlined is True
    assert "<script>" not in doc.lower()


def test_wrap_escapes_title() -> None:
    wrapped = wrap_lesson_html("<p>Hi</p>", '<script>x</script>')
    assert "<title>&lt;script&gt;x&lt;/script&gt;</title>" in wrapped.document
    assert "<script>x</script>" not in wrapped.document


def test_wrap_strips_style_breakout_in_css() -> None:
    wrapped = wrap_lesson_html("<p>Hi</p>", "T", "body{color:red}</style><script>alert(1)</script>")
    assert "</style><script>" not in wrapped.document.lower()
    assert "body{color:red}" in wrapped.document


def test_wrap_full_document_not_double_wrapped() -> None:
    source = (
        "<!DOCTYPE html><html><head><title>Old</title></head>"
        "<body><h1>Full</h1></body></html>"
    )
    wrapped = wrap_lesson_html(source, "New", "h1 { color: teal; }")
    assert wrapped.is_full_document is True
    assert wrapped.document.lower().count("<!doctype") == 1
    assert wrapped.document.lower().count("<html") == 1
    assert "<title>New</title>" in wrapped.document
    assert "h1 { color: teal; }" in wrapped.document
    assert "<h1>Full</h1>" in wrapped.document
    assert FRAGMENT_FOOTNOTE not in wrapped.document


def test_wrap_full_document_css_backrefs_are_literal() -> None:
    source = (
        "<!DOCTYPE html><html><head><title>Old</title></head>"
        "<body><h1>Full</h1></body></html>"
    )
    css = r'.x::before { content: "\2713"; }'
    wrapped = wrap_lesson_html(source, "T", css)
    assert r"\2713" in wrapped.document
    assert wrapped.document.lower().count("<html") == 1


def test_wrap_strips_script_tags() -> None:
    wrapped = wrap_lesson_html("<p>Hi</p><script>alert(1)</script>", "T")
    assert wrapped.scripts_stripped is True
    assert "alert(1)" not in wrapped.document
    assert "<script>" not in wrapped.document.lower()


def test_file_uri_uses_as_uri(tmp_path: Path) -> None:
    path = tmp_path / "present-001.html"
    path.write_text("<html></html>", encoding="utf-8")
    uri = file_uri(path)
    assert uri.startswith("file://")
    assert "present-001.html" in uri
    assert "\\" not in uri


def test_windows_path_as_uri_contract() -> None:
    uri = PureWindowsPath(r"C:\Users\a\lessons\id\present-001.html").as_uri()
    assert uri == "file:///C:/Users/a/lessons/id/present-001.html"


def test_write_present_html_increments(tmp_path: Path) -> None:
    first = write_present_html(tmp_path, "<p>one</p>")
    second = write_present_html(tmp_path, "<p>two</p>")
    assert first.name == "present-001.html"
    assert second.name == "present-002.html"
    assert first.read_text(encoding="utf-8") == "<p>one</p>"
    assert second.read_text(encoding="utf-8") == "<p>two</p>"


def test_write_present_html_skips_existing(tmp_path: Path) -> None:
    (tmp_path / "present-001.html").write_text("kept", encoding="utf-8")
    path = write_present_html(tmp_path, "<p>next</p>")
    assert path.name == "present-002.html"
    assert (tmp_path / "present-001.html").read_text(encoding="utf-8") == "kept"


def test_deliver_empty_html_does_not_write(tmp_path: Path) -> None:
    calls: list[str] = []
    result = deliver_present(
        tmp_path,
        PresentHtmlRequest(html="  "),
        opener=lambda uri: calls.append(uri) or True,
    )
    assert result.ok is False
    assert result.message == ERROR_EMPTY
    assert calls == []
    assert list(tmp_path.glob("present-*.html")) == []


def test_deliver_oversize_does_not_write(tmp_path: Path) -> None:
    huge = "<p>" + ("x" * (MAX_PRESENT_BYTES + 10)) + "</p>"
    result = deliver_present(tmp_path, PresentHtmlRequest(html=huge), open_browser=False)
    assert result.ok is False
    assert result.message == ERROR_TOO_LARGE
    assert list(tmp_path.glob("present-*.html")) == []


def test_deliver_demo_skips_opener(tmp_path: Path) -> None:
    calls: list[str] = []
    result = deliver_present(
        tmp_path,
        PresentHtmlRequest(html="<p>Hi</p>", title="Hi"),
        open_browser=False,
        opener=lambda uri: calls.append(uri) or True,
    )
    assert result.ok is True
    assert result.opened is False
    assert result.written is True
    assert result.path is not None
    assert result.path.name == "present-001.html"
    assert result.message == DEMO_SAVED
    assert calls == []
    assert "Hi" in result.path.read_text(encoding="utf-8")


def test_deliver_opener_true(tmp_path: Path) -> None:
    calls: list[str] = []
    result = deliver_present(
        tmp_path,
        PresentHtmlRequest(html="<p>Hi</p>", title="Hi"),
        opener=lambda uri: calls.append(uri) or True,
    )
    assert result.ok is True
    assert result.opened is True
    assert result.message == SUCCESS_OPENED
    assert len(calls) == 1
    assert calls[0].startswith("file://")
    assert "present-001.html" in calls[0]


def test_deliver_opener_false_includes_uri(tmp_path: Path) -> None:
    result = deliver_present(
        tmp_path,
        PresentHtmlRequest(html="<p>Hi</p>"),
        opener=lambda uri: False,
    )
    assert result.ok is True
    assert result.opened is False
    assert result.written is True
    assert result.uri.startswith("file://")
    assert SUCCESS_NO_BROWSER.format(uri=result.uri) == result.message


def test_deliver_opener_raises_still_writes(tmp_path: Path) -> None:
    def boom(_uri: str) -> bool:
        raise RuntimeError("no display")

    result = deliver_present(
        tmp_path,
        PresentHtmlRequest(html="<p>Hi</p>"),
        opener=boom,
    )
    assert result.ok is True
    assert result.opened is False
    assert result.path is not None
    assert result.path.is_file()
    assert "file://" in result.message


def test_parse_present_html_flat_and_nested() -> None:
    flat = parse_present_html({"html": "<p>A</p>", "title": "T", "css": "p{}"})
    assert flat is not None
    assert flat.html == "<p>A</p>"
    assert flat.title == "T"
    assert flat.css == "p{}"

    nested = parse_present_html({"arguments": {"html": "<p>B</p>", "title": "B"}})
    assert nested is not None
    assert nested.html == "<p>B</p>"

    grok = parse_present_html({"input": {"html": "<p>C</p>"}})
    assert grok is not None
    assert grok.html == "<p>C</p>"

    assert parse_present_html({}) is None
    assert parse_present_html(None) is None
    assert parse_present_html({"title": "nope"}) is None


def test_parse_present_html_unwraps_grok_use_tool_envelopes() -> None:
    envelope = parse_present_html(
        {
            "tool_name": "axiomatic__present_lesson_html",
            "tool_input": {"html": "<p>Hi</p>", "title": "Fig"},
        }
    )
    assert envelope is not None
    assert envelope.html == "<p>Hi</p>"
    assert envelope.title == "Fig"

    json_tool_input = parse_present_html(
        {
            "tool_name": "axiomatic__present_lesson_html",
            "tool_input": '{"html": "<p>Hi</p>", "title": "Fig"}',
        }
    )
    assert json_tool_input is not None
    assert json_tool_input.html == "<p>Hi</p>"
    assert json_tool_input.title == "Fig"

    json_raw = parse_present_html(
        '{"tool_name": "axiomatic__present_lesson_html",'
        ' "tool_input": {"html": "<p>Hi</p>", "title": "Fig"}}'
    )
    assert json_raw is not None
    assert json_raw.html == "<p>Hi</p>"
    assert json_raw.title == "Fig"

    wrapped_value = parse_present_html({"value": {"html": "<p>Hi</p>", "title": "Fig"}})
    assert wrapped_value is not None
    assert wrapped_value.html == "<p>Hi</p>"

    content_block = parse_present_html({"html": {"text": "<p>Hi</p>"}, "title": "Fig"})
    assert content_block is not None
    assert content_block.html == "<p>Hi</p>"
    assert content_block.title == "Fig"

    list_blocks = parse_present_html(
        {"html": [{"type": "text", "text": "<p>Hi</p>"}], "title": "Fig"}
    )
    assert list_blocks is not None
    assert list_blocks.html == "<p>Hi</p>"

    params = parse_present_html({"params": {"html": "<p>P</p>"}})
    assert params is not None
    assert params.html == "<p>P</p>"

    args = parse_present_html({"args": {"html": "<p>A</p>"}})
    assert args is not None
    assert args.html == "<p>A</p>"

    camel = parse_present_html({"toolInput": {"html": "<p>C</p>", "css": "p{}"}})
    assert camel is not None
    assert camel.html == "<p>C</p>"
    assert camel.css == "p{}"


def test_parse_present_html_ignores_agent_path() -> None:
    req = parse_present_html(
        {"html": "<p>X</p>", "path": "/tmp/evil.html", "filename": "../escape.html"}
    )
    assert req is not None
    assert req.html == "<p>X</p>"
    assert not hasattr(req, "path") or not getattr(req, "path", None)


def test_parse_present_output_unwraps_grok_envelope() -> None:
    payload = {
        "type": "MCP",
        "tool_name": "present_lesson_html",
        "server_name": "axiomatic",
        "output": {
            "OkayOutput": '{"ok": true, "open_status": "host_pending", "opened": null}'
        },
    }
    parsed = parse_present_output(payload)
    assert parsed is not None
    assert parsed["ok"] is True
    assert parsed["open_status"] == "host_pending"

    rejected = parse_present_output(
        {"content": [{"type": "text", "text": '{"ok": false, "error": "html must not be empty"}'}]}
    )
    assert rejected is not None
    assert rejected["ok"] is False


def test_agent_path_is_not_used_for_write(tmp_path: Path) -> None:
    req = parse_present_html({"html": "<p>Safe</p>", "path": str(tmp_path / "evil.html")})
    assert req is not None
    result = deliver_present(tmp_path, req, open_browser=False)
    assert result.path is not None
    assert result.path.name == "present-001.html"
    assert not (tmp_path / "evil.html").exists()


def test_windows_opener_uses_startfile_filesystem_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    called: list[str] = []

    def fake_startfile(path: str) -> None:
        called.append(path)

    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setattr(os, "startfile", fake_startfile, raising=False)
    result = deliver_present(tmp_path, PresentHtmlRequest(html="<p>Hi</p>", title="Hi"))
    assert result.ok is True
    assert result.written is True
    assert result.opened is True
    assert result.path is not None
    assert result.path.name == "present-001.html"
    assert result.path.is_file()
    assert called == [os.fspath(result.path.resolve())]
    assert not called[0].startswith("file:")
    assert result.uri.startswith("file://")
    assert "\\" not in result.uri
    real = os.fspath(result.path.resolve())
    if len(real) >= 2 and real[1] == ":":
        assert f"{real[0].upper()}:" in result.uri or f"/{real[0].upper()}:" in result.uri.upper()


def test_windows_opener_false_still_leaves_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    called: list[str] = []
    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setattr(os, "startfile", lambda path: called.append(path), raising=False)
    result = deliver_present(
        tmp_path,
        PresentHtmlRequest(html="<p>Hi</p>"),
        open_browser=False,
    )
    assert result.ok is True
    assert result.opened is False
    assert result.written is True
    assert result.path is not None
    assert result.path.is_file()
    assert called == []
    assert result.uri.startswith("file://")
    assert "\\" not in result.uri


def test_windows_startfile_failure_still_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(_path: str) -> None:
        raise OSError("no association")

    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setattr(os, "startfile", boom, raising=False)
    result = deliver_present(tmp_path, PresentHtmlRequest(html="<p>Hi</p>"))
    assert result.ok is True
    assert result.opened is False
    assert result.path is not None
    assert result.path.is_file()
    assert SUCCESS_NO_BROWSER.format(uri=result.uri) == result.message
    assert "\\" not in result.uri


def test_open_present_file_nt_calls_startfile_not_uri(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "present-001.html"
    path.write_text("<html></html>", encoding="utf-8")
    called: list[str] = []
    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setattr(os, "startfile", lambda p: called.append(p), raising=False)
    assert open_present_file(path) is True
    assert called == [os.fspath(path.resolve())]
    uri = file_uri(path)
    assert uri.startswith("file://")
    assert "\\" not in uri
