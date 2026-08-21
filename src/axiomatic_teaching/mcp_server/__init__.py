"""MCP server exposing the success gate and read-only lesson tools."""

from axiomatic_teaching.mcp_server.server import (
    get_connections,
    get_lesson_criteria,
    list_banked_lessons,
    main,
    present_lesson_html,
    record_lesson_success,
    reset_repository_cache,
)

__all__ = [
    "get_connections",
    "get_lesson_criteria",
    "list_banked_lessons",
    "main",
    "present_lesson_html",
    "record_lesson_success",
    "reset_repository_cache",
]
