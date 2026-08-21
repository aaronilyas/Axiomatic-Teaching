"""Success gate: the only path that can bank a lesson."""

from axiomatic_teaching.gate.criteria import (
    build_auto_criterion,
    extract_keywords,
    resolve_criteria,
)
from axiomatic_teaching.gate.success import evaluate

__all__ = [
    "build_auto_criterion",
    "evaluate",
    "extract_keywords",
    "resolve_criteria",
]
