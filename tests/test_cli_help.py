"""Smoke tests for the axiomatic-teach CLI (no TUI, no Grok)."""

from __future__ import annotations

import pytest

from axiomatic_teaching.cli import build_parser, main


def test_cli_help(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exited:
        main(["--help"])
    assert exited.value.code == 0
    out = capsys.readouterr().out
    assert "axiomatic-teach" in out
    assert "--demo" in out
    assert "--agent" in out
    assert "--grok-bin" in out
    assert "verify" in out


def test_verify_help(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exited:
        main(["verify", "--help"])
    assert exited.value.code == 0
    out = capsys.readouterr().out
    assert "verify" in out.lower() or "--db" in out


def test_parser_demo_and_agent() -> None:
    args = build_parser().parse_args(["--demo", "--agent", "echo"])
    assert args.demo is True
    assert args.agent == "echo"
    assert args.command is None


def test_parser_verify_db() -> None:
    args = build_parser().parse_args(["verify", "--db", "C:\\tmp\\axiomatic.db"])
    assert args.command == "verify"
    assert args.db == "C:\\tmp\\axiomatic.db"
