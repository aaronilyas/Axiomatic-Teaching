"""CLI entry: ``axiomatic-teach`` and ``axiomatic-teach verify``."""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
import traceback
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from axiomatic_teaching.config import Settings
from axiomatic_teaching.models import (
    CriterionDraft,
    CriterionKind,
    EvidenceItem,
    LessonStatus,
    NewLessonSpec,
    RecordSuccessRequest,
)

__all__ = ["build_parser", "main", "verify"]


class VerifyFailure(Exception):
    """A checked assertion failed in the critical-path verifier."""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="axiomatic-teach",
        description=(
            "Terminal tutor that intermediates a learner and Grok Build over ACP, "
            "banking knowledge only through a success-gated tool."
        ),
    )
    parser.add_argument(
        "--db",
        metavar="PATH",
        default=None,
        help=(
            "SQLite database path. Defaults to AXIOMATIC_DB or the per-user "
            "app data directory."
        ),
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Run without Grok (sets demo mode and agent=echo).",
    )
    parser.add_argument(
        "--agent",
        choices=("grok", "echo"),
        default=None,
        help="ACP agent implementation (default: AXIOMATIC_AGENT or grok).",
    )
    parser.add_argument(
        "--grok-bin",
        metavar="PATH",
        default=None,
        help="Grok executable path (default: AXIOMATIC_GROK_BIN or grok on PATH).",
    )
    subparsers = parser.add_subparsers(dest="command")
    verify_parser = subparsers.add_parser(
        "verify",
        help="Run the headless critical-path verifier (no TUI, no Grok).",
        description=(
            "Create a lesson, reject insufficient evidence, bank sufficient "
            "evidence, and assert already-banked idempotency."
        ),
    )
    # SUPPRESS so `axiomatic-teach --db PATH verify` is not overwritten by the
    # subparser default when --db is omitted after the subcommand.
    verify_parser.add_argument(
        "--db",
        metavar="PATH",
        default=argparse.SUPPRESS,
        help="SQLite path (default: a temporary database).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    settings = Settings.from_cli(
        db=args.db,
        demo=args.demo,
        agent=args.agent,
        grok_bin=args.grok_bin,
    )

    if args.command == "verify":
        db = Path(args.db) if args.db else None
        return verify(db)

    return _run_app(settings)


def verify(db_path: str | Path | None = None) -> int:
    """Headless critical path: reject bad evidence, bank good evidence, idempotent.

    Returns 0 on PASS, 1 on FAIL. No TUI, no Grok.
    """
    tmp: tempfile.TemporaryDirectory[str] | None = None
    engine: Any = None
    path = Path(db_path) if db_path is not None else None
    try:
        if path is None:
            tmp = tempfile.TemporaryDirectory(
                prefix="axiomatic_verify_",
                ignore_cleanup_errors=True,
            )
            path = Path(tmp.name) / "axiomatic.db"
        else:
            path.parent.mkdir(parents=True, exist_ok=True)

        try:
            from axiomatic_teaching.db.repository import create_repository
        except ImportError as exc:
            raise VerifyFailure(
                "cannot import create_repository from axiomatic_teaching.db.repository "
                f"({exc}). The SQLite repository is not available."
            ) from exc

        try:
            from axiomatic_teaching.db.engine import init_engine
        except ImportError:
            init_engine = None
        if init_engine is not None:
            engine = init_engine(path)

        repository = create_repository(path)
        _run_critical_path(repository)
        print("PASS: critical path (reject insufficient evidence, bank sufficient, already_banked)")
        return 0
    except VerifyFailure as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 — verifier must always exit 0/1
        print(f"FAIL: unexpected error: {exc}", file=sys.stderr)
        traceback.print_exc()
        return 1
    finally:
        if engine is not None:
            dispose = getattr(engine, "dispose", None)
            if callable(dispose):
                try:
                    dispose()
                except Exception:
                    pass
        if tmp is not None:
            try:
                tmp.cleanup()
            except OSError:
                pass


def _check(condition: object, message: str) -> None:
    if not condition:
        raise VerifyFailure(message)


def _run_critical_path(repository: Any) -> None:
    spec = NewLessonSpec(
        title="Recursion fundamentals",
        topic="algorithms",
        description="Critical-path verifier lesson.",
        success_description="Explain recursion and trace a recursive call to a base case.",
        tags=["verify", "recursion"],
        criteria=[
            CriterionDraft(
                kind=CriterionKind.EXPLAIN,
                statement="Explain recursion in your own words, including the base case.",
                required=True,
                min_evidence_chars=40,
                keywords=["recursion"],
            ),
            CriterionDraft(
                kind=CriterionKind.APPLY,
                statement="Trace a small recursive function down to its base case.",
                required=True,
                min_evidence_chars=40,
                keywords=[],
            ),
        ],
    )
    lesson = repository.create_lesson(spec)
    criteria = list(getattr(lesson, "criteria", None) or [])
    if len(criteria) < 2:
        listed = repository.list_criteria(lesson.id)
        criteria = list(listed)
    _check(len(criteria) >= 2, "create_lesson did not persist two success criteria")

    keyword_criterion = next(
        (c for c in criteria if any(k.lower() == "recursion" for k in (c.keywords or []))),
        criteria[0],
    )
    other_criterion = next(c for c in criteria if c.id != keyword_criterion.id)

    bad = RecordSuccessRequest(
        lesson_id=lesson.id,
        evidence=[
            EvidenceItem(
                criterion_id=keyword_criterion.id,
                text="too short",
                met=True,
            ),
            EvidenceItem(
                criterion_id=other_criterion.id,
                text="The learner did not demonstrate this criterion.",
                met=False,
            ),
        ],
        notes="insufficient evidence",
        style_note="should not be persisted on a rejected attempt",
    )
    rejected = repository.record_success(bad)
    _check(rejected.accepted is False, f"insufficient evidence was accepted: {rejected}")
    _check(
        not rejected.already_banked,
        "insufficient evidence reported already_banked",
    )
    _check(
        repository.get_completion(lesson.id) is None,
        "completion row written on rejected evidence",
    )
    style_notes = repository.list_style_notes()
    _check(not style_notes, f"style notes written on fail: {style_notes}")
    after_fail = repository.get_lesson(lesson.id)
    _check(after_fail is not None, "lesson disappeared after rejected record_success")
    _check(
        after_fail.status == LessonStatus.ACTIVE,
        f"lesson status after reject is {after_fail.status!r}, expected active",
    )

    good_explain = (
        "Recursion is a function calling itself on a smaller input until a base "
        "case stops the chain. Without a base case the calls would not terminate."
    )
    good_apply = (
        "factorial(3) expands to 3 * factorial(2), then 3 * 2 * factorial(1), "
        "and the base case n == 1 returns 1 so the product is 6."
    )
    _check(len(good_explain.strip()) >= 40, "verifier fixture explain text is too short")
    _check("recursion" in good_explain.lower(), "verifier fixture missing keyword")
    _check(len(good_apply.strip()) >= 40, "verifier fixture apply text is too short")

    good = RecordSuccessRequest(
        lesson_id=lesson.id,
        evidence=[
            EvidenceItem(criterion_id=keyword_criterion.id, text=good_explain, met=True),
            EvidenceItem(criterion_id=other_criterion.id, text=good_apply, met=True),
        ],
        notes="learner explained recursion and traced factorial",
        style_note="prefers tracing a concrete call tree",
    )
    accepted = repository.record_success(good)
    _check(accepted.accepted is True, f"sufficient evidence was rejected: {accepted}")
    _check(not accepted.already_banked, "first successful bank reported already_banked")
    completion = repository.get_completion(lesson.id)
    _check(completion is not None, "no completion after accepted evidence")
    completed = repository.get_lesson(lesson.id)
    _check(completed is not None, "lesson missing after accepted evidence")
    _check(
        completed.status == LessonStatus.COMPLETED,
        f"lesson status after pass is {completed.status!r}, expected completed",
    )

    card = repository.get_fsrs_card(lesson.id)
    if card is not None:
        _check(card.lesson_id == lesson.id, "FSRS card lesson_id mismatch")

    third = repository.record_success(good)
    _check(third.already_banked is True, f"third call was not already_banked: {third}")
    completions = repository.list_completions()
    matching = [row for row in completions if row.lesson_id == lesson.id]
    _check(
        len(matching) == 1,
        f"expected one completion, found {len(matching)}",
    )


def _run_app(settings: Settings) -> int:
    _warn_if_grok_missing(settings)

    try:
        from axiomatic_teaching.db.repository import create_repository
    except ImportError as exc:
        print(
            "error: cannot import create_repository from axiomatic_teaching.db.repository.\n"
            f"  {exc}\n"
            "The SQLite repository is not available. Try: pip install -e \".[dev]\"",
            file=sys.stderr,
        )
        return 1

    try:
        from axiomatic_teaching.db.engine import init_engine
    except ImportError:
        init_engine = None
    if init_engine is not None:
        init_engine(settings.db_path)

    repository = create_repository(settings.db_path)
    session_factory = _build_session_factory(settings)

    try:
        from axiomatic_teaching.app import AxiomaticApp
    except ImportError as exc:
        print(
            "error: cannot import AxiomaticApp from axiomatic_teaching.app.\n"
            f"  {exc}\n"
            "The TUI is not available. Try: pip install -e \".[dev]\"",
            file=sys.stderr,
        )
        return 1

    app = AxiomaticApp(settings, repository, session_factory=session_factory)
    app.run()
    return 0


def _build_session_factory(settings: Settings) -> Callable[..., Any] | None:
    try:
        from axiomatic_teaching.acp_client.grok import GrokSession
    except ImportError:
        return None

    def session_factory(lesson_id: str, on_event: Callable[[Any], None]) -> Any:
        return GrokSession(settings=settings, on_event=on_event, lesson_id=lesson_id)

    return session_factory


def _warn_if_grok_missing(settings: Settings) -> None:
    if settings.demo or settings.agent == "echo":
        return
    binary = settings.grok_bin
    resolved = shutil.which(binary)
    if resolved is None and not Path(binary).is_file():
        print(
            f"warning: grok executable not found ({binary!r}). "
            "Install grok, authenticate, and put it on PATH, or run with --demo.",
            file=sys.stderr,
        )


if __name__ == "__main__":
    raise SystemExit(main())
