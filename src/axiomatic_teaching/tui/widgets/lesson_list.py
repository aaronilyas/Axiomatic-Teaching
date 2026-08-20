"""Scrollable lesson list, optionally grouped by status."""

from __future__ import annotations

from collections.abc import Sequence

from textual.message import Message
from textual.widgets import OptionList
from textual.widgets.option_list import Option

from axiomatic_teaching.models import Lesson, LessonStatus

_STATUS_ORDER = (
    LessonStatus.ACTIVE,
    LessonStatus.DRAFT,
    LessonStatus.COMPLETED,
    LessonStatus.ARCHIVED,
)

_STATUS_LABELS = {
    LessonStatus.ACTIVE: "ACTIVE",
    LessonStatus.DRAFT: "DRAFT",
    LessonStatus.COMPLETED: "COMPLETED",
    LessonStatus.ARCHIVED: "ARCHIVED",
}


def _prompt_for(lesson: Lesson, *, grouped: bool) -> str:
    title = lesson.title.strip() or lesson.id
    topic = lesson.topic.strip()
    extra = f"  [dim]{topic}[/]" if topic else ""
    if lesson.status == LessonStatus.DRAFT:
        return f"[dim]{title} (draft)[/]{extra}"
    if lesson.status == LessonStatus.COMPLETED:
        return f"[green]✓[/] {title}{extra}"
    if grouped:
        return f"{title}{extra}"
    return f"{title}{extra}  [italic dim]{lesson.status}[/]"


class LessonList(OptionList):
    """OptionList of lessons. Enter posts ``LessonChosen``."""

    DEFAULT_CSS = """
    LessonList {
        height: 1fr;
        width: 1fr;
        border: tall #1e2a36;
        background: #0c1117;
        padding: 0 0;
    }
    """

    class LessonChosen(Message):
        def __init__(self, lesson_list: LessonList, lesson: Lesson) -> None:
            super().__init__()
            self.lesson_list = lesson_list
            self.lesson = lesson

        @property
        def control(self) -> LessonList:
            return self.lesson_list

    def __init__(self, **kwargs: object) -> None:
        super().__init__(compact=True, **kwargs)  # type: ignore[arg-type]
        self._lessons: dict[str, Lesson] = {}
        self._grouped = True

    def set_lessons(
        self,
        lessons: Sequence[Lesson],
        *,
        group: bool = True,
        selected_id: str | None = None,
    ) -> None:
        self._grouped = group
        self._lessons = {lesson.id: lesson for lesson in lessons}
        previous = selected_id or self.selected_id
        options: list[Option | None] = []
        if not lessons:
            options.append(Option("[dim]No lessons[/]", id="__empty__", disabled=True))
        elif group:
            buckets: dict[LessonStatus, list[Lesson]] = {status: [] for status in _STATUS_ORDER}
            unknown: list[Lesson] = []
            for lesson in lessons:
                try:
                    buckets[LessonStatus(lesson.status)].append(lesson)
                except Exception:
                    unknown.append(lesson)
            first_section = True
            for status in _STATUS_ORDER:
                group_lessons = buckets[status]
                if not group_lessons:
                    continue
                if not first_section:
                    options.append(None)
                first_section = False
                options.append(
                    Option(
                        f"[bold]{_STATUS_LABELS[status]}[/]",
                        id=f"__hdr_{status.value}__",
                        disabled=True,
                    )
                )
                for lesson in group_lessons:
                    options.append(
                        Option(_prompt_for(lesson, grouped=True), id=lesson.id)
                    )
            if unknown:
                if not first_section:
                    options.append(None)
                options.append(Option("[bold]OTHER[/]", id="__hdr_other__", disabled=True))
                for lesson in unknown:
                    options.append(Option(_prompt_for(lesson, grouped=True), id=lesson.id))
        else:
            for lesson in lessons:
                options.append(Option(_prompt_for(lesson, grouped=False), id=lesson.id))
        self.set_options(options)
        self._restore_selection(previous)

    def _restore_selection(self, lesson_id: str | None) -> None:
        if lesson_id and lesson_id in self._lessons:
            try:
                self.highlighted = self.get_option_index(lesson_id)
                return
            except Exception:
                pass
        for index, option in enumerate(self.options):
            if option.id and option.id in self._lessons and not option.disabled:
                self.highlighted = index
                return

    @property
    def selected_id(self) -> str | None:
        option = self.highlighted_option
        if option is None or option.disabled:
            return None
        if option.id and option.id in self._lessons:
            return option.id
        return None

    def selected_lesson(self) -> Lesson | None:
        lesson_id = self.selected_id
        if lesson_id is None:
            return None
        return self._lessons.get(lesson_id)

    def highlight_lesson(self, lesson_id: str) -> None:
        if lesson_id not in self._lessons:
            return
        try:
            self.highlighted = self.get_option_index(lesson_id)
        except Exception:
            return

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        lesson_id = event.option_id
        if not lesson_id or lesson_id not in self._lessons:
            return
        event.stop()
        self.post_message(self.LessonChosen(self, self._lessons[lesson_id]))
