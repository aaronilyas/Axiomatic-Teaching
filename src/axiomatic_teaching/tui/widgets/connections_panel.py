"""One-hop concept relations plus due reviews for the current lesson."""

from __future__ import annotations

from collections.abc import Sequence

from rich.markup import escape

from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.widgets import Static

from axiomatic_teaching.models import BankedLessonSummary, Concept, ConceptRelation, DueReview
from axiomatic_teaching.tui import format_dt, format_relation


class ConnectionsPanel(Vertical):
    DEFAULT_CSS = """
    ConnectionsPanel {
        height: 1fr;
        width: 1fr;
        border: tall #1e2a36;
        background: #0c1117;
        padding: 0 1;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("Connections · due", classes="panel-title")
        with VerticalScroll():
            yield Static("[dim]No connections.[/]", id="connections-body")

    def show(
        self,
        relations: Sequence[ConceptRelation],
        due: Sequence[DueReview],
        concepts: Sequence[Concept] | None = None,
        related: Sequence[BankedLessonSummary] | None = None,
        style_notes: Sequence[str] | None = None,
    ) -> None:
        try:
            body = self.query_one("#connections-body", Static)
        except Exception:
            return
        lines: list[str] = ["[bold]Connections[/]"]
        if relations:
            for relation in relations:
                lines.append(escape(format_relation(relation, concepts)))
        else:
            lines.append("[dim]None yet.[/]")
        if related:
            lines.append("")
            lines.append("[bold]Related banked[/]")
            for item in related:
                topic = f"  [dim]{escape(item.topic)}[/]" if item.topic else ""
                lines.append(f"{escape(item.title)}{topic}")
        if style_notes:
            lines.append("")
            lines.append("[bold]Style[/]")
            for note in style_notes:
                lines.append(f"[dim]{escape(note)}[/]")
        lines.append("")
        lines.append("[bold]Due reviews[/]")
        if due:
            for card in due:
                when = format_dt(card.due)
                lines.append(f"{escape(card.title)}  [dim]{when}[/]")
        else:
            lines.append("[dim]Nothing due.[/]")
        body.update("\n".join(lines))
