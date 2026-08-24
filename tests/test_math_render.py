"""LaTeX → Unicode approximation for ChatStream tutor text."""

from __future__ import annotations

import pytest
from textual.app import App

from axiomatic_teaching.acp_client.events import StreamChunk
from axiomatic_teaching.tui.math_render import latex_to_unicode
from axiomatic_teaching.tui.widgets.chat_stream import ChatStream


def _chat_text(chat: ChatStream) -> str:
    chunks: list[str] = []
    plains: list[str] = []
    for line in getattr(chat, "lines", []):
        chunks.append(str(line))
        segments = getattr(line, "_segments", None)
        if segments:
            plains.append("".join(getattr(seg, "text", "") for seg in segments))
    return "\n".join(chunks) + "\n" + "".join(plains)


def test_no_math_unchanged() -> None:
    assert latex_to_unicode("What is a prior in your own words?") == (
        "What is a prior in your own words?"
    )
    assert latex_to_unicode("") == ""
    assert latex_to_unicode("cost is $5") == "cost is $5"


def test_simple_inline_frac() -> None:
    out = latex_to_unicode(r"\(P(A)=\frac{1}{8}\)")
    assert r"\(" not in out
    assert r"\frac" not in out
    assert "1/8" in out or "⅛" in out
    assert "P(A)" in out or "𝑃(𝐴)" in out


def test_inline_log_and_text() -> None:
    out = latex_to_unicode(r"\(\log_2 P(A \text{ and } B)\)")
    assert r"\log" not in out
    assert r"\text" not in out
    assert r"\(" not in out
    assert "2" in out or "₂" in out
    assert "and" in out
    assert "log" in out.lower() or "𝑙𝑜𝑔" in out


def test_display_math_and_mixed_text() -> None:
    src = "A fair die has \\(P(A)=\\frac{1}{8}\\) and also\n\\[\n\\frac{1}{2}\n\\]\ndone."
    out = latex_to_unicode(src)
    assert out.startswith("A fair die has ")
    assert "done." in out
    assert r"\frac" not in out
    assert r"\[" not in out
    assert "1/8" in out or "⅛" in out
    assert "1/2" in out or "½" in out


def test_dollar_and_double_dollar_delimiters() -> None:
    inline = latex_to_unicode(r"See $P(A)=\frac{1}{8}$ now.")
    assert inline.startswith("See ")
    assert inline.endswith(" now.")
    assert r"\frac" not in inline
    assert "1/8" in inline or "⅛" in inline

    display = latex_to_unicode("Total:\n$$\\alpha + \\beta$$\nend")
    assert "Total:" in display
    assert "end" in display
    assert r"\alpha" not in display
    assert "𝛼" in display and "𝛽" in display


def test_escaped_backslash_paren_form() -> None:
    out = latex_to_unicode(r"\\(P(A)=\frac{1}{8}\\)")
    assert r"\frac" not in out
    assert "1/8" in out or "⅛" in out


def test_unknown_command_falls_back_to_original() -> None:
    raw = r"keep \(\notacommandxyz{z}\) raw"
    assert latex_to_unicode(raw) == raw

    mixed = r"ok \(\alpha\) and bad \(\notacommandxyz{z}\)"
    out = latex_to_unicode(mixed)
    assert r"\alpha" not in out
    assert "ok " in out
    assert r"\notacommandxyz{z}" in out
    assert r"\(\notacommandxyz{z}\)" in out


def test_malformed_and_empty_left_original() -> None:
    unclosed = r"start \(P(A)=\frac{1}{8} end"
    assert latex_to_unicode(unclosed) == unclosed
    empty = r"empty \(\) here"
    assert latex_to_unicode(empty) == empty
    nested = r"\( \( x \) \)"
    # Nested/malformed delimiters must not crash; original is acceptable.
    latex_to_unicode(nested)


def test_long_expression_still_converts() -> None:
    inner = r"P(A_1 \cap A_2 \cap A_3)=\frac{1}{8}" + r"+ \alpha" * 80
    src = r"\(" + inner + r"\)"
    out = latex_to_unicode(src)
    assert r"\(" not in out
    assert r"\frac" not in out
    assert r"\alpha" not in out
    assert "1/8" in out or "⅛" in out


@pytest.mark.asyncio
async def test_chat_stream_renders_math_and_plain_text() -> None:
    class Harness(App):
        def compose(self):
            yield ChatStream()

    app = Harness()
    async with app.run_test(size=(80, 24)) as pilot:
        chat = app.query_one(ChatStream)
        chat.append_stream(StreamChunk(text="Hello from the tutor.\n", role="agent"))
        chat.append_stream(
            StreamChunk(text=r"Compute \(P(A)=\frac{1}{8}\)." + "\n", role="agent")
        )
        chat.append_stream(
            StreamChunk(text=r"Then \(\log_2 P(A \text{ and } B)\).", role="agent")
        )
        chat._flush_partial()
        await pilot.pause()
        text = _chat_text(chat)
        assert "Hello from the tutor." in text
        assert "Compute " in text
        assert "Then " in text
        assert r"\frac" not in text
        assert r"\log" not in text
        assert r"\(" not in text
        assert "1/8" in text or "⅛" in text
        assert "tutor" in text.lower()


@pytest.mark.asyncio
async def test_chat_stream_partial_flush_converts_complete_math() -> None:
    class Harness(App):
        def compose(self):
            yield ChatStream()

    app = Harness()
    async with app.run_test(size=(80, 24)) as pilot:
        chat = app.query_one(ChatStream)
        chat.append_stream(
            StreamChunk(text=r"If \(P(A)=\frac{1}{8}\), what is P(A)?", role="agent")
        )
        chat._flush_partial()
        await pilot.pause()
        text = _chat_text(chat)
        assert "If " in text
        assert "what is P(A)?" in text
        assert r"\frac" not in text
        assert "1/8" in text or "⅛" in text


@pytest.mark.asyncio
async def test_chat_stream_incomplete_math_stays_raw_until_complete() -> None:
    class Harness(App):
        def compose(self):
            yield ChatStream()

    app = Harness()
    async with app.run_test(size=(80, 24)) as pilot:
        chat = app.query_one(ChatStream)
        chat.append_stream(StreamChunk(text=r"See \(P(A)=", role="agent"))
        assert r"\(" in chat._stream_buffer
        chat.append_stream(StreamChunk(text=r"\frac{1}{8}\)", role="agent"))
        chat._flush_partial()
        await pilot.pause()
        text = _chat_text(chat)
        assert r"\frac" not in text
        assert "1/8" in text or "⅛" in text


@pytest.mark.asyncio
async def test_chat_stream_system_and_user_skip_math_render() -> None:
    class Harness(App):
        def compose(self):
            yield ChatStream()

    app = Harness()
    async with app.run_test(size=(80, 24)) as pilot:
        chat = app.query_one(ChatStream)
        chat.write_system(r"ACP \(P(A)=\frac{1}{8}\)")
        chat.append_user(r"I typed \(x^2\)")
        await pilot.pause()
        text = _chat_text(chat)
        assert r"\frac" in text
        assert r"\(x^2\)" in text
