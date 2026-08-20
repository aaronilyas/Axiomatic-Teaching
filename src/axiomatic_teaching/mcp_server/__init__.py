"""MCP server exposing the success gate and read-only lesson tools."""

from axiomatic_teaching.mcp_server.server import (
    get_connections,
    get_lesson_criteria,
    list_banked_lessons,
    main,
    record_lesson_success,
)

__all__ = [
    "get_connections",
    "get_lesson_criteria",
    "list_banked_lessons",
    "main",
    "record_lesson_success",
]
