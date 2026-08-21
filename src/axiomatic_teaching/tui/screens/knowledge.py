"""Banked lessons, concepts, relations, stored evidence."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Header, OptionList, Static
from textual.widgets.option_list import Option

from axiomatic_teaching.models import BankedLessonSummary, Completion, Concept, Criterion, Lesson
from axiomatic_teaching.tui import format_dt, format_relation
from axiomatic_teaching.tui.screens.confirm_delete import ConfirmDeleteScreen
from axiomatic_teaching.tui.widgets.status_bar import StatusBar

if TYPE_CHECKING:
    from axiomatic_teaching.app import AxiomaticApp


class KnowledgeScreen(Screen[None]):
    app: AxiomaticApp

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Esc · Go back"),
        Binding("d", "delete_lesson", "d · Delete selected lesson"),
        Binding("question_mark", "app.help", "? · Show help"),
    ]

    def __init__(self, lesson_id: str | None = None) -> None:
        super().__init__()
        self._select_id = lesson_id
        self._banked: dict[str, BankedLessonSummary] = {}

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="knowledge-body"):
            with Vertical(id="knowledge-lessons", classes="panel"):
                yield Static("Banked lessons", classes="panel-title")
                yield OptionList(id="knowledge-list", compact=True)
            with Vertical(id="knowledge-detail"):
                with VerticalScroll(id="knowledge-evidence", classes="panel"):
                    yield Static("Evidence", classes="panel-title")
                    yield Static("[dim]Select a banked lesson.[/]", id="evidence-body")
                with VerticalScroll(id="knowledge-graph", classes="panel"):
                    yield Static("Concepts · relations", classes="panel-title")
                    yield Static("[dim]No concepts yet.[/]", id="graph-body")
        yield StatusBar()
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = "Knowledge"
        self.refresh_data()
        self.query_one(StatusBar).refresh_status()

    def refresh_data(self) -> None:
        banked = self.app.list_banked()
        self._banked = {item.id: item for item in banked}
        widget = self.query_one("#knowledge-list", OptionList)
        if not banked:
            widget.set_options(
                [Option("[dim]Nothing banked yet.[/]", id="__empty__", disabled=True)]
            )
            self._render_graph(None)
            return
        widget.set_options(
            [
                Option(
                    f"{item.title}  [dim]{item.topic}[/]",
                    id=item.id,
                )
                for item in banked
            ]
        )
        target = self._select_id if self._select_id in self._banked else banked[0].id
        try:
            widget.highlighted = widget.get_option_index(target)
        except Exception:
            pass
        self._show_lesson(target)

    @on(OptionList.OptionHighlighted, "#knowledge-list")
    @on(OptionList.OptionSelected, "#knowledge-list")
    def _picked(self, event: OptionList.OptionMessage) -> None:
        lesson_id = event.option_id
        if not lesson_id or lesson_id.startswith("__"):
            return
        self._show_lesson(lesson_id)

    def action_delete_lesson(self) -> None:
        lesson_id = self._select_id
        if not lesson_id or lesson_id not in self._banked:
            self.notify("Select a banked lesson first.")
            return
        try:
            lesson = self.app.repository.get_lesson(lesson_id)
        except Exception as exc:
            self.notify(f"Could not load lesson: {exc}", severity="error")
            return
        if lesson is None:
            self.notify("Lesson not found.", severity="error")
            return
        self._confirm_delete(lesson)

    def _confirm_delete(self, lesson: Lesson) -> None:
        def _after(confirmed: bool | None) -> None:
            if not confirmed:
                return
            try:
                self.app.repository.delete_lesson(lesson.id)
            except Exception as exc:
                self.notify(f"Could not delete lesson: {exc}", severity="error")
                return
            self.notify(f"Deleted “{lesson.title}”.")
            self._select_id = None
            self.refresh_data()
            try:
                self.app.refresh_counts()
                self.query_one(StatusBar).refresh_status()
            except Exception:
                pass

        self.app.push_screen(ConfirmDeleteScreen(lesson), _after)

    def _show_lesson(self, lesson_id: str) -> None:
        self._select_id = lesson_id
        summary = self._banked.get(lesson_id)
        completion: Completion | None = None
        criteria = []
        try:
            lesson = self.app.repository.get_lesson(lesson_id)
            if lesson is not None:
                criteria = list(lesson.criteria)
        except Exception:
            criteria = []
        try:
            completion = self.app.repository.get_completion(lesson_id)
        except Exception as exc:
            self.query_one("#evidence-body", Static).update(
                f"[red]Could not load evidence: {exc}[/]"
            )
        else:
            self.query_one("#evidence-body", Static).update(
                _format_evidence(summary, completion, criteria)
            )
        self._render_graph(lesson_id)

    def _render_graph(self, lesson_id: str | None) -> None:
        concepts: list[Concept] = []
        try:
            concepts = self.app.repository.list_concepts(lesson_id)
        except Exception:
            try:
                concepts = self.app.repository.list_concepts()
            except Exception:
                concepts = []
        relations = []
        try:
            if lesson_id:
                relations = self.app.repository.one_hop_relations(lesson_id)
            else:
                relations = self.app.repository.list_relations()
        except Exception:
            try:
                relations = self.app.repository.list_relations()
            except Exception:
                relations = []
        lines = ["[bold]Concepts[/]"]
        if concepts:
            for concept in concepts:
                desc = f" — {concept.description}" if concept.description else ""
                lines.append(f"• {concept.name}{desc}")
        else:
            lines.append("[dim]None yet.[/]")
        lines.append("")
        lines.append("[bold]Relations[/]")
        if relations:
            for relation in relations:
                lines.append(format_relation(relation, concepts))
        else:
            lines.append("[dim]None yet.[/]")
        self.query_one("#graph-body", Static).update("\n".join(lines))


def _format_evidence(
    summary: BankedLessonSummary | None,
    completion: Completion | None,
    criteria: list[Criterion] | None = None,
) -> str:
    lines: list[str] = []
    if summary is not None:
        lines.append(f"[bold]{summary.title}[/]  [dim]{summary.topic}[/]")
        if summary.description:
            lines.append(summary.description)
        if summary.completed_at:
            lines.append(f"[dim]banked {format_dt(summary.completed_at)}[/]")
        if summary.concepts:
            lines.append("[dim]concepts: " + ", ".join(summary.concepts) + "[/]")
        lines.append("")
    if criteria:
        lines.append("[bold]Success[/]")
        if len(criteria) == 1:
            lines.append(criteria[0].statement)
        else:
            for criterion in criteria:
                lines.append(f"• {criterion.statement}")
        lines.append("")
    if completion is None:
        lines.append("[dim]No stored evidence.[/]")
        return "\n".join(lines)
    if completion.notes:
        lines.append(f"[italic]{completion.notes}[/]")
        lines.append("")
    lines.append("[bold]Evidence[/]  [dim](read-only)[/]")
    lines.append(_render_evidence_payload(completion.evidence))
    return "\n".join(lines)


def _render_evidence_payload(evidence: Any) -> str:
    if not evidence:
        return "[dim]Empty.[/]"
    items: list[Any]
    if isinstance(evidence, dict) and "evidence" in evidence:
        items = evidence["evidence"] if isinstance(evidence["evidence"], list) else [evidence]
    elif isinstance(evidence, list):
        items = evidence
    elif isinstance(evidence, dict):
        pretty_items: list[str] = []
        for key, value in evidence.items():
            if isinstance(value, dict) and "text" in value:
                met = value.get("met")
                mark = "✓" if met else ("✗" if met is False else "·")
                pretty_items.append(f"{mark} [{key}] {value.get('text')}")
            else:
                pretty_items.append(f"[{key}] {value}")
        return "\n".join(pretty_items) if pretty_items else "[dim]Empty.[/]"
    else:
        return json.dumps(evidence, indent=2, default=str)
    lines: list[str] = []
    for item in items:
        if isinstance(item, dict):
            criterion = item.get("criterion_id") or item.get("id") or ""
            text = item.get("text") or item.get("evidence") or str(item)
            met = item.get("met")
            mark = "✓" if met else ("✗" if met is False else "·")
            prefix = f"{mark} "
            if criterion:
                prefix += f"[{criterion}] "
            lines.append(prefix + str(text))
        else:
            lines.append(str(item))
    return "\n".join(lines) if lines else json.dumps(evidence, indent=2, default=str)
