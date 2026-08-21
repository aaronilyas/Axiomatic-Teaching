"""Keybinding help overlay."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Footer, Static


class HelpScreen(ModalScreen[None]):
    BINDINGS = [
        Binding("escape,q,question_mark", "dismiss", "Esc · Close help", show=True),
    ]

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static("Axiomatic Teaching", classes="panel-title"),
            Static(_HELP, id="help-body"),
            id="help-card",
        )
        yield Footer()

    def action_dismiss(self) -> None:
        self.dismiss(None)


_HELP = """[bold]Home[/]
  [cyan]n[/]          new lesson
  [cyan]enter[/]/[cyan]s[/]    study selected lesson (not drafts)
  [cyan]k[/]          knowledge bank
  [cyan]r[/]          due reviews
  [cyan]q[/]          quit
  [cyan]?[/]          this help

[bold]New lesson[/]
  Title and topic required. Success description optional (1–2 sentences).
  A single criterion is derived automatically from that text (or a default).
  [cyan]ctrl+enter[/] create
  [cyan]esc[/]        cancel

[bold]Study[/]
  [cyan]ctrl+s[/]     send
  [cyan]ctrl+c[/]     cancel turn
  [cyan]esc[/]        back (shutdown session)
  Completion is only via the [cyan]record_lesson_success[/] gate.
  Demo mode cannot bank; use Grok Build for the live gate.

[bold]Review[/]
  [cyan]1[/]/[cyan]a[/]        again
  [cyan]2[/]/[cyan]h[/]        hard
  [cyan]3[/]/[cyan]g[/]        good
  [cyan]4[/]/[cyan]e[/]        easy
  [cyan]esc[/]        back

[bold]Everywhere[/]
  [cyan]q[/]          quit (not while typing)
  [cyan]?[/]          help
"""
