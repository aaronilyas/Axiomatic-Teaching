"""Bottom status: ACP, banked/due counts, last gate."""

from __future__ import annotations

from textual.widgets import Static

from axiomatic_teaching.models import GateResult


class StatusBar(Static):
    DEFAULT_CSS = """
    StatusBar {
        height: 1;
        width: 1fr;
        background: #0e141b;
        color: #c5d0da;
        padding: 0 1;
    }
    """

    def __init__(self, **kwargs: object) -> None:
        super().__init__("", **kwargs)  # type: ignore[arg-type]

    def on_mount(self) -> None:
        self.refresh_status()

    def refresh_status(self) -> None:
        app = self.app
        connected = bool(getattr(app, "acp_connected", False))
        busy = bool(getattr(app, "acp_busy", False))
        message = str(getattr(app, "acp_message", "") or "")
        banked = int(getattr(app, "banked_count", 0) or 0)
        due = int(getattr(app, "due_count", 0) or 0)
        last: GateResult | None = getattr(app, "last_gate", None)
        if connected:
            acp = "[green]ACP ●[/] connected"
        else:
            acp = "[dim]ACP ○ not connected[/]"
        if message and not connected:
            acp = f"[dim]ACP ○ {escape_plain(message)}[/]"
        activity = "[yellow]BUSY[/]" if busy else "[dim]idle[/]"
        if last is None:
            gate = "[dim]gate —[/]"
        elif last.already_banked:
            gate = "[cyan]gate BANKED[/]"
        elif last.accepted:
            gate = "[green]gate PASS[/]"
        else:
            gate = "[red]gate FAIL[/]"
        self.update(
            f"{acp}  {activity}  ·  banked {banked}  ·  due {due}  ·  {gate}"
        )


def escape_plain(text: str) -> str:
    return text.replace("[", "\\[")
