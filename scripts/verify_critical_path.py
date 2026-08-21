"""Headless critical-path verifier (no TUI, no Grok).

Product acceptance test:

1. tempfile sqlite
2. create_repository
3. create_lesson from title/topic plus a short success description; one
   auto-derived required criterion with keywords including \"recursion\"
   and min_evidence_chars=50
4. insufficient evidence (too short / missing keyword) → rejected,
   no completion, no style notes, lesson still active
5. sufficient evidence covering the auto-derived criterion → accepted,
   completion exists, lesson completed, FSRS card if the repository creates one
6. third call → already_banked, still one completion
7. print PASS/FAIL and exit 0/1

Usage::

    python scripts/verify_critical_path.py
    python scripts/verify_critical_path.py --db PATH
    axiomatic-teach verify [--db PATH]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from axiomatic_teaching.cli import verify  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Headless critical-path verifier for Axiomatic Teaching.",
    )
    parser.add_argument(
        "--db",
        metavar="PATH",
        default=None,
        help="SQLite path (default: a temporary database).",
    )
    args = parser.parse_args(argv)
    db_path = Path(args.db) if args.db else None
    return verify(db_path)


if __name__ == "__main__":
    raise SystemExit(main())
