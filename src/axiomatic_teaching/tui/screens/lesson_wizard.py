"""New-lesson wizard. Criteria cannot be skipped."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pydantic import ValidationError
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    OptionList,
    Select,
    Static,
    Switch,
    TextArea,
)
from textual.widgets.option_list import Option

from axiomatic_teaching.config import DEFAULT_MIN_EVIDENCE_CHARS
from axiomatic_teaching.models import (
    CriterionDraft,
    CriterionKind,
    Lesson,
    LessonStatus,
    NewLessonSpec,
)
from axiomatic_teaching.tui import split_csv

if TYPE_CHECKING:
    from axiomatic_teaching.app import AxiomaticApp

_STEPS = (
    ("title", "Title", "Required. What is this lesson called?"),
    ("topic", "Topic", "Required. Subject or domain."),
    ("description", "Description", "Optional. What will you study?"),
    ("tags", "Tags", "Optional. Comma-separated tags."),
    ("success", "Success description", "Optional free-text success condition."),
    ("criteria", "Success criteria", "Required. At least one required criterion."),
)

_KIND_OPTIONS = [(kind.value.capitalize(), kind.value) for kind in CriterionKind]


@dataclass
class _CriterionForm:
    kind: CriterionKind = CriterionKind.EXPLAIN
    statement: str = ""
    required: bool = True
    min_evidence_chars: int = DEFAULT_MIN_EVIDENCE_CHARS
    keywords: list[str] = field(default_factory=list)


class LessonWizard(Screen[Lesson | None]):
    app: AxiomaticApp

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("ctrl+enter", "advance", "Next / Create", priority=True),
        Binding("question_mark", "app.help", "Help"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._step = 0
        self._values = {
            "title": "",
            "topic": "",
            "description": "",
            "tags": "",
            "success": "",
        }
        self._criteria: list[_CriterionForm] = [_CriterionForm()]
        self._crit_index = 0

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with VerticalScroll(id="wizard-card"):
            yield Static(id="wizard-step-label", classes="panel-title")
            yield Static(id="wizard-hint", classes="muted")
            with Vertical(id="step-fields"):
                yield Label("Value", id="field-label")
                yield Input(id="field-text")
                yield TextArea(id="field-long", show_line_numbers=False)
            with Vertical(id="step-criteria"):
                yield Static(
                    "Each lesson needs ≥1 required criterion. Keywords are the gate: "
                    "evidence must contain every keyword (case-insensitive) and be at least "
                    "N characters of the learner's own words. Kind guides the tutor; the "
                    "gate ignores kind. Ctrl+Enter creates.",
                    classes="muted",
                    id="crit-help",
                )
                with Horizontal(id="criteria-editor"):
                    yield OptionList(id="crit-list", compact=True)
                    with Vertical(id="crit-form"):
                        yield Label("Kind")
                        yield Select(
                            _KIND_OPTIONS,
                            value=CriterionKind.EXPLAIN.value,
                            allow_blank=False,
                            id="crit-kind",
                        )
                        yield Label("Statement")
                        yield TextArea(id="crit-statement", show_line_numbers=False)
                        with Horizontal(id="crit-required-row"):
                            yield Label("Required")
                            yield Switch(value=True, id="crit-required")
                        yield Label("Min evidence chars")
                        yield Input(
                            value=str(DEFAULT_MIN_EVIDENCE_CHARS),
                            type="integer",
                            id="crit-min",
                        )
                        yield Label("Keywords (comma-separated)")
                        yield Input(id="crit-keywords")
                        with Horizontal(id="crit-buttons"):
                            yield Button("Add", id="crit-add")
                            yield Button("Remove", id="crit-remove")
                            yield Button("Up", id="crit-up")
                            yield Button("Down", id="crit-down")
            with Horizontal(id="wizard-nav"):
                yield Button("Back", id="wizard-back")
                yield Button("Next", id="wizard-next", variant="primary")
                yield Button("Create lesson", id="wizard-create", variant="success")
                yield Button("Cancel", id="wizard-cancel")
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = "New lesson"
        self._show_step()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_advance(self) -> None:
        key = _STEPS[self._step][0]
        if key == "criteria":
            self._create()
        else:
            self._next()

    def _show_step(self) -> None:
        key, title, hint = _STEPS[self._step]
        total = len(_STEPS)
        self.query_one("#wizard-step-label", Static).update(
            f"Step {self._step + 1}/{total} — {title}"
        )
        self.query_one("#wizard-hint", Static).update(hint)
        fields = self.query_one("#step-fields")
        criteria = self.query_one("#step-criteria")
        next_btn = self.query_one("#wizard-next", Button)
        create_btn = self.query_one("#wizard-create", Button)
        back_btn = self.query_one("#wizard-back", Button)
        back_btn.disabled = self._step == 0
        if key == "criteria":
            fields.display = False
            criteria.display = True
            next_btn.display = False
            create_btn.display = True
            self._render_criteria()
            self._load_criterion_form()
            return
        fields.display = True
        criteria.display = False
        next_btn.display = True
        create_btn.display = False
        short = self.query_one("#field-text", Input)
        long = self.query_one("#field-long", TextArea)
        label = self.query_one("#field-label", Label)
        label.update(title)
        if key in {"description", "success"}:
            short.display = False
            long.display = True
            long.load_text(self._values[key])
            long.focus()
        else:
            short.display = True
            long.display = False
            short.placeholder = title
            short.value = self._values[key]
            short.focus()

    def _save_step(self) -> None:
        key = _STEPS[self._step][0]
        if key == "criteria":
            self._save_criterion_form()
            return
        if key in {"description", "success"}:
            self._values[key] = self.query_one("#field-long", TextArea).text
        else:
            self._values[key] = self.query_one("#field-text", Input).value.strip()

    def _validate_current(self) -> bool:
        key = _STEPS[self._step][0]
        if key == "title" and not self._values["title"].strip():
            self.notify("Title is required.", severity="error")
            return False
        if key == "topic" and not self._values["topic"].strip():
            self.notify("Topic is required.", severity="error")
            return False
        return True

    @on(Button.Pressed, "#wizard-next")
    def _next(self) -> None:
        self._save_step()
        if not self._validate_current():
            return
        if self._step < len(_STEPS) - 1:
            self._step += 1
            self._show_step()

    @on(Button.Pressed, "#wizard-back")
    def _back(self) -> None:
        self._save_step()
        if self._step > 0:
            self._step -= 1
            self._show_step()

    @on(Button.Pressed, "#wizard-cancel")
    def _cancel_clicked(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#wizard-create")
    def _create(self) -> None:
        self._save_step()
        self._commit_lesson()

    def _commit_lesson(self) -> None:
        drafts: list[CriterionDraft] = []
        for form in self._criteria:
            statement = form.statement.strip()
            if not statement:
                if form.required:
                    self.notify("Required criteria need a statement.", severity="error")
                    return
                continue
            try:
                drafts.append(
                    CriterionDraft(
                        kind=form.kind,
                        statement=statement,
                        required=form.required,
                        min_evidence_chars=max(1, form.min_evidence_chars),
                        keywords=list(form.keywords),
                    )
                )
            except ValidationError as exc:
                self.notify(str(exc), severity="error")
                return
        if not any(item.required for item in drafts):
            self.notify("Need at least one required criterion to create.", severity="error")
            return
        try:
            spec = NewLessonSpec(
                title=self._values["title"].strip(),
                topic=self._values["topic"].strip(),
                description=self._values["description"].strip(),
                success_description=self._values["success"].strip(),
                tags=split_csv(self._values["tags"]),
                criteria=drafts,
            )
        except ValidationError as exc:
            self.notify(str(exc), severity="error")
            return
        try:
            lesson = self.app.repository.create_lesson(spec)
        except Exception as exc:
            self.notify(f"Could not create lesson: {exc}", severity="error")
            return
        if lesson.status != LessonStatus.ACTIVE:
            lesson.status = LessonStatus.ACTIVE
            try:
                lesson = self.app.repository.save_lesson(lesson)
            except Exception:
                pass
        self.dismiss(lesson)

    def _render_criteria(self) -> None:
        widget = self.query_one("#crit-list", OptionList)
        options: list[Option] = []
        for index, form in enumerate(self._criteria):
            req = "req" if form.required else "opt"
            preview = form.statement.strip() or "(empty)"
            options.append(
                Option(f"{index + 1}. [{form.kind}/{req}] {preview}", id=f"c{index}")
            )
        if not options:
            options.append(Option("[dim]No criteria[/]", id="cempty", disabled=True))
        widget.set_options(options)
        if self._criteria:
            try:
                widget.highlighted = min(self._crit_index, len(self._criteria) - 1)
            except Exception:
                pass

    def _save_criterion_form(self) -> None:
        if not self._criteria:
            return
        index = max(0, min(self._crit_index, len(self._criteria) - 1))
        form = self._criteria[index]
        kind_value = self.query_one("#crit-kind", Select).value
        if isinstance(kind_value, str):
            try:
                form.kind = CriterionKind(kind_value)
            except ValueError:
                form.kind = CriterionKind.CUSTOM
        form.statement = self.query_one("#crit-statement", TextArea).text
        form.required = bool(self.query_one("#crit-required", Switch).value)
        raw_min = self.query_one("#crit-min", Input).value.strip()
        try:
            form.min_evidence_chars = max(1, int(raw_min or DEFAULT_MIN_EVIDENCE_CHARS))
        except ValueError:
            form.min_evidence_chars = DEFAULT_MIN_EVIDENCE_CHARS
        form.keywords = split_csv(self.query_one("#crit-keywords", Input).value)

    def _load_criterion_form(self) -> None:
        if not self._criteria:
            return
        index = max(0, min(self._crit_index, len(self._criteria) - 1))
        form = self._criteria[index]
        kind = self.query_one("#crit-kind", Select)
        try:
            kind.value = form.kind.value
        except Exception:
            pass
        self.query_one("#crit-statement", TextArea).load_text(form.statement)
        self.query_one("#crit-required", Switch).value = form.required
        self.query_one("#crit-min", Input).value = str(form.min_evidence_chars)
        self.query_one("#crit-keywords", Input).value = ", ".join(form.keywords)
        self.query_one("#crit-statement", TextArea).focus()

    def _select_criterion(self, index: int) -> None:
        if not self._criteria:
            return
        self._save_criterion_form()
        self._crit_index = max(0, min(index, len(self._criteria) - 1))
        self._render_criteria()
        self._load_criterion_form()

    @on(OptionList.OptionSelected, "#crit-list")
    @on(OptionList.OptionHighlighted, "#crit-list")
    def _crit_highlighted(self, event: OptionList.OptionMessage) -> None:
        option_id = event.option_id or ""
        if not option_id.startswith("c") or option_id == "cempty":
            return
        try:
            index = int(option_id[1:])
        except ValueError:
            return
        if index == self._crit_index:
            return
        self._save_criterion_form()
        self._crit_index = index
        self._load_criterion_form()

    @on(Button.Pressed, "#crit-add")
    def _add_criterion(self) -> None:
        self._save_criterion_form()
        self._criteria.append(_CriterionForm())
        self._crit_index = len(self._criteria) - 1
        self._render_criteria()
        self._load_criterion_form()

    @on(Button.Pressed, "#crit-remove")
    def _remove_criterion(self) -> None:
        self._save_criterion_form()
        if len(self._criteria) <= 1:
            self._criteria = [_CriterionForm()]
            self._crit_index = 0
        else:
            self._criteria.pop(self._crit_index)
            self._crit_index = min(self._crit_index, len(self._criteria) - 1)
        self._render_criteria()
        self._load_criterion_form()

    @on(Button.Pressed, "#crit-up")
    def _move_up(self) -> None:
        self._save_criterion_form()
        index = self._crit_index
        if index <= 0:
            return
        self._criteria[index - 1], self._criteria[index] = (
            self._criteria[index],
            self._criteria[index - 1],
        )
        self._crit_index = index - 1
        self._render_criteria()
        self._load_criterion_form()

    @on(Button.Pressed, "#crit-down")
    def _move_down(self) -> None:
        self._save_criterion_form()
        index = self._crit_index
        if index >= len(self._criteria) - 1:
            return
        self._criteria[index + 1], self._criteria[index] = (
            self._criteria[index],
            self._criteria[index + 1],
        )
        self._crit_index = index + 1
        self._render_criteria()
        self._load_criterion_form()
