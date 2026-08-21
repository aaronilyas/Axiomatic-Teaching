"""Current lesson success criterion with ✓/✗ from the last GateResult."""

from __future__ import annotations

from rich.markup import escape

from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.widgets import Static

from axiomatic_teaching.models import Criterion, GateResult, Lesson


def _mark(criterion: Criterion, result: GateResult | None) -> str:
    if result is None:
        return "[dim]○[/]"
    unmet_ids = {item.criterion_id for item in result.unmet if item.criterion_id}
    if result.accepted:
        if criterion.required:
            return "[green]✓[/]"
        return "[dim]○[/]" if criterion.id not in unmet_ids else "[red]✗[/]"
    if criterion.id in unmet_ids:
        return "[red]✗[/]"
    return "[dim]○[/]"


class CriteriaPanel(Vertical):
    DEFAULT_CSS = """
    CriteriaPanel {
        height: 1fr;
        width: 1fr;
        border: tall #1e2a36;
        background: #0c1117;
        padding: 0 1;
    }
    """

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._lesson: Lesson | None = None
        self._result: GateResult | None = None

    def compose(self) -> ComposeResult:
        yield Static("Success", classes="panel-title")
        with VerticalScroll():
            yield Static("[dim]No lesson selected.[/]", id="criteria-body")

    def set_lesson(self, lesson: Lesson | None) -> None:
        if self._lesson is None or lesson is None or self._lesson.id != lesson.id:
            self._result = None
        self._lesson = lesson
        self._refresh_body()

    def apply_gate(self, result: GateResult | None) -> None:
        self._result = result
        self._refresh_body()

    def _refresh_body(self) -> None:
        try:
            body = self.query_one("#criteria-body", Static)
        except Exception:
            return
        lesson = self._lesson
        if lesson is None:
            body.update("[dim]No lesson selected.[/]")
            return
        criteria = list(lesson.criteria)
        if not criteria:
            body.update("[dim]This lesson has no success criterion.[/]")
            return
        lines: list[str] = []
        if lesson.success_description:
            lines.append(escape(lesson.success_description))
            lines.append("")
        if self._result is not None:
            if self._result.already_banked:
                lines.append("[cyan]Already banked.[/]")
            elif self._result.accepted:
                lines.append("[green]Gate PASS[/]")
            else:
                lines.append("[red]Gate FAIL[/]")
            if self._result.message:
                lines.append(f"[dim]{escape(self._result.message)}[/]")
            lines.append("")
        unmet_reasons: dict[str, list[str]] = {}
        general: list[str] = []
        for item in self._result.unmet if self._result is not None else []:
            if item.criterion_id:
                unmet_reasons.setdefault(item.criterion_id, []).append(item.reason)
            else:
                general.append(item.reason)
        for criterion in sorted(criteria, key=lambda item: item.sort_order):
            mark = _mark(criterion, self._result)
            statement = escape(criterion.statement)
            if lesson.success_description and statement == escape(lesson.success_description):
                lines.append(f"{mark} Gate")
            else:
                lines.append(f"{mark} {statement}")
            extras = []
            if criterion.min_evidence_chars:
                extras.append(f"min {criterion.min_evidence_chars} chars")
            if criterion.keywords:
                extras.append("keywords: " + ", ".join(criterion.keywords))
            if extras:
                lines.append(f"   [dim]{escape(' · '.join(extras))}[/]")
            for reason in unmet_reasons.get(criterion.id, []):
                lines.append(f"   [red]{escape(reason)}[/]")
        for reason in general:
            lines.append(f"[red]{escape(reason)}[/]")
        body.update("\n".join(lines))
