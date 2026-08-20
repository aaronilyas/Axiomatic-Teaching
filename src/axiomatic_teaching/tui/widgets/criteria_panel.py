"""Current lesson success criteria with ✓/✗ from the last GateResult."""

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
        return "[green]✓[/]"
    if criterion.id in unmet_ids:
        return "[red]✗[/]"
    return "[green]✓[/]"


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
        yield Static("Success criteria", classes="panel-title")
        with VerticalScroll():
            yield Static("[dim]No lesson selected.[/]", id="criteria-body")

    def set_lesson(self, lesson: Lesson | None) -> None:
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
            body.update("[dim]This lesson has no criteria.[/]")
            return
        lines: list[str] = []
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
        unmet_reasons = {
            item.criterion_id: item.reason
            for item in (self._result.unmet if self._result is not None else [])
            if item.criterion_id
        }
        general = [
            item.reason
            for item in (self._result.unmet if self._result is not None else [])
            if not item.criterion_id
        ]
        for criterion in sorted(criteria, key=lambda item: item.sort_order):
            req = "req" if criterion.required else "opt"
            kind = criterion.kind
            mark = _mark(criterion, self._result)
            statement = escape(criterion.statement)
            lines.append(f"{mark} [{kind}/{req}] {statement}")
            reason = unmet_reasons.get(criterion.id)
            if reason:
                lines.append(f"   [red]{escape(reason)}[/]")
        for reason in general:
            lines.append(f"[red]{escape(reason)}[/]")
        body.update("\n".join(lines))
