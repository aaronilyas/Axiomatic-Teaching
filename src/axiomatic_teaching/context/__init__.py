"""Session context assembly: pedagogy rules plus a budgeted lesson graph."""

from axiomatic_teaching.context.assembler import assemble, kickoff_prompt
from axiomatic_teaching.context.pedagogy import PEDAGOGY_RULES

__all__ = ["PEDAGOGY_RULES", "assemble", "kickoff_prompt"]
