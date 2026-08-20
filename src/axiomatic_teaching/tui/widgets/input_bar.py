"""Multiline prompt plus Send button."""

from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.message import Message
from textual.widgets import Button, TextArea


class InputBar(Horizontal):
    DEFAULT_CSS = """
    InputBar {
        height: 6;
        width: 1fr;
        background: #0c1117;
        border: tall #1e2a36;
    }
    InputBar TextArea {
        width: 1fr;
        height: 1fr;
        background: #080b0f;
        border: none;
        padding: 0 1;
    }
    InputBar Button {
        width: 12;
        height: 3;
        margin: 1 1 1 0;
        dock: right;
    }
    """

    class Submitted(Message):
        def __init__(self, bar: InputBar, text: str) -> None:
            super().__init__()
            self.bar = bar
            self.text = text

        @property
        def control(self) -> InputBar:
            return self.bar

    def compose(self) -> ComposeResult:
        yield TextArea(id="prompt", show_line_numbers=False)
        yield Button("Send", id="send", variant="primary")

    def on_mount(self) -> None:
        area = self.query_one("#prompt", TextArea)
        area.show_line_numbers = False
        area.tooltip = "ctrl+s send · ctrl+c cancel"

    @property
    def text(self) -> str:
        return self.query_one("#prompt", TextArea).text

    def clear(self) -> None:
        self.query_one("#prompt", TextArea).clear()

    def focus_input(self) -> None:
        self.query_one("#prompt", TextArea).focus()

    def take(self) -> str:
        text = self.text.strip()
        if text:
            self.clear()
        return text

    def submit(self) -> None:
        text = self.take()
        if not text:
            return
        self.post_message(self.Submitted(self, text))

    @on(Button.Pressed, "#send")
    def _send_clicked(self) -> None:
        self.submit()
