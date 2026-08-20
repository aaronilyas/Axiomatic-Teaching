"""Spawn and drive Grok Build (or the demo echo agent) over ACP stdio."""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, IO

from axiomatic_teaching import __version__
from axiomatic_teaching.acp_client.client_impl import AxiomaticClient
from axiomatic_teaching.acp_client.events import AgentStatus
from axiomatic_teaching.config import Settings

log = logging.getLogger(__name__)

_STDIO_LIMIT = 50 * 1024 * 1024
_SHUTDOWN_TIMEOUT = 5.0
_CLIENT_NAME = "axiomatic-teaching"
_CLIENT_TITLE = "Axiomatic Teaching"
_MCP_NAME = "axiomatic"
_MCP_ARGS = ["-m", "axiomatic_teaching.mcp_server.server"]
_STDERR_LOG_NAME = "grok-acp.log"


def _package_dir() -> Path:
    return Path(__file__).resolve().parent.parent


def _src_dir() -> Path:
    return _package_dir().parent


def _echo_agent_path() -> Path:
    return _package_dir() / "demo" / "echo_agent.py"


def _python_executable() -> str:
    return str(Path(sys.executable).resolve())


def _is_echo(settings: Settings) -> bool:
    return settings.demo or settings.agent == "echo"


def _resolve_grok_bin(settings: Settings) -> str:
    candidate = settings.grok_bin
    found = shutil.which(candidate)
    if found:
        return found
    path = Path(candidate).expanduser()
    if path.is_file():
        return str(path.resolve())
    raise FileNotFoundError(
        f"Grok binary not found: {candidate!r}. Set AXIOMATIC_GROK_BIN or install grok."
    )


def _agent_command(settings: Settings) -> tuple[str, list[str]]:
    if _is_echo(settings):
        echo = _echo_agent_path()
        if not echo.is_file():
            raise FileNotFoundError(f"Echo agent not found: {echo}")
        return _python_executable(), [str(echo)]
    grok = _resolve_grok_bin(settings)
    args = ["agent", "--always-approve", "stdio"]
    if os.name == "nt" and grok.lower().endswith((".cmd", ".bat")):
        comspec = os.environ.get("ComSpec") or "cmd.exe"
        return comspec, ["/c", grok, *args]
    return grok, args


def _wrap_kickoff(rules: str, kickoff_prompt: str) -> str:
    rules = rules.strip()
    if not rules:
        return kickoff_prompt
    return f"<axiomatic-context>\n{rules}\n</axiomatic-context>\n\n{kickoff_prompt}"


_MCP_ENV_PASSTHROUGH = (
    "PATH",
    "PATHEXT",
    "SYSTEMROOT",
    "SystemRoot",
    "WINDIR",
    "windir",
    "USERPROFILE",
    "HOMEDRIVE",
    "HOMEPATH",
    "HOME",
    "TEMP",
    "TMP",
    "TMPDIR",
    "LOCALAPPDATA",
    "APPDATA",
    "PROGRAMDATA",
    "COMSPEC",
    "ComSpec",
    "VIRTUAL_ENV",
    "PYTHONHOME",
    "PYTHONUTF8",
    "PYTHONIOENCODING",
    "SystemDrive",
    "NUMBER_OF_PROCESSORS",
)


def _mcp_env(settings: Settings, lesson_id: str) -> list[Any]:
    """Env for the MCP subprocess Grok spawns. Include a Windows-safe PATH subset."""
    from acp.schema import EnvVariable

    pythonpath = os.pathsep.join(p for p in (str(_src_dir()), os.environ.get("PYTHONPATH", "")) if p)
    seen: set[str] = set()
    variables: list[Any] = []
    for name in _MCP_ENV_PASSTHROUGH:
        value = os.environ.get(name)
        if value is None or name in seen:
            continue
        seen.add(name)
        variables.append(EnvVariable(name=name, value=value))
    for name, value in os.environ.items():
        if name.startswith("PYTHON") and name not in seen:
            seen.add(name)
            variables.append(EnvVariable(name=name, value=value))
    overrides = {
        "AXIOMATIC_DB": str(settings.db_path),
        "AXIOMATIC_LESSON_ID": lesson_id,
        "PYTHONPATH": pythonpath,
        "PYTHONUNBUFFERED": "1",
    }
    for name, value in overrides.items():
        if name in seen:
            variables = [item for item in variables if getattr(item, "name", None) != name]
        variables.append(EnvVariable(name=name, value=value))
    return variables


class GrokSession:
    """ACP session controller that owns the agent subprocess."""

    def __init__(
        self,
        settings: Settings,
        on_event: Callable[[Any], None],
        lesson_id: str | None = None,
    ) -> None:
        self._settings = settings
        self._on_event = on_event
        self._lesson_id = lesson_id
        self._busy = False
        self._session_id: str | None = None
        self._process: asyncio.subprocess.Process | None = None
        self._conn: Any | None = None
        self._stderr: IO[bytes] | None = None
        self._prompt_lock = asyncio.Lock()
        self._dead = False
        try:
            self._loop: asyncio.AbstractEventLoop | None = asyncio.get_running_loop()
        except RuntimeError:
            self._loop = None

    @property
    def busy(self) -> bool:
        return self._busy

    @property
    def session_id(self) -> str | None:
        return self._session_id

    def _emit(self, event: Any, *, force: bool = False) -> None:
        if self._dead and not force:
            return
        loop = self._loop
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None

        def _call() -> None:
            try:
                self._on_event(event)
            except Exception:
                log.exception("on_event callback failed")

        if loop is not None and loop.is_running() and running is not loop:
            loop.call_soon_threadsafe(_call)
            return
        _call()

    def _set_busy(self, busy: bool, message: str = "") -> None:
        self._busy = busy
        self._emit(
            AgentStatus(
                connected=self._conn is not None,
                message=message,
                session_id=self._session_id,
                busy=busy,
            )
        )

    async def start(self, lesson_id: str, rules: str, kickoff_prompt: str) -> None:
        async with self._prompt_lock:
            if self._process is not None or self._conn is not None:
                await self._shutdown_unlocked()
            self._dead = False
            try:
                await self._start_unlocked(lesson_id, rules, kickoff_prompt)
            except BaseException:
                await self._shutdown_unlocked()
                raise

    async def send(self, text: str) -> None:
        async with self._prompt_lock:
            if self._dead or self._conn is None or self._session_id is None:
                raise RuntimeError("ACP session is not started")
            from acp import text_block

            await self._prompt_unlocked([text_block(text)])

    async def cancel(self) -> None:
        conn, session_id = self._conn, self._session_id
        if conn is None or session_id is None or self._dead:
            return
        await conn.cancel(session_id=session_id)

    async def shutdown(self) -> None:
        async with self._prompt_lock:
            await self._shutdown_unlocked()

    async def _start_unlocked(self, lesson_id: str, rules: str, kickoff_prompt: str) -> None:
        from acp import PROTOCOL_VERSION, connect_to_agent, text_block
        from acp.schema import ClientCapabilities, Implementation, McpServerStdio

        self._loop = asyncio.get_running_loop()
        self._lesson_id = lesson_id
        workspace = self._settings.workspace_for(lesson_id).resolve()
        command, args = _agent_command(self._settings)
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        src = str(_src_dir())
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = os.pathsep.join(p for p in (src, existing) if p)

        log_path = self._settings.log_dir / _STDERR_LOG_NAME
        log_path.parent.mkdir(parents=True, exist_ok=True)
        rotate = log_path.exists() and log_path.stat().st_size > 2_000_000
        stderr = log_path.open("wb" if rotate else "ab")
        self._stderr = stderr

        spawn_kwargs: dict[str, Any] = {
            "stdin": asyncio.subprocess.PIPE,
            "stdout": asyncio.subprocess.PIPE,
            "stderr": stderr,
            "env": env,
            "limit": _STDIO_LIMIT,
        }
        if sys.platform == "win32":
            spawn_kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        try:
            self._process = await asyncio.create_subprocess_exec(command, *args, **spawn_kwargs)
        except Exception:
            self._close_stderr()
            raise

        if self._process.stdin is None or self._process.stdout is None:
            await self._shutdown_unlocked()
            raise RuntimeError("agent process does not expose stdio pipes")

        client = AxiomaticClient(self._emit)
        self._conn = connect_to_agent(client, self._process.stdin, self._process.stdout)
        self._emit(AgentStatus(connected=True, message="initializing", session_id=None, busy=True))

        try:
            await self._conn.initialize(
                protocol_version=PROTOCOL_VERSION,
                client_info=Implementation(
                    name=_CLIENT_NAME,
                    title=_CLIENT_TITLE,
                    version=__version__,
                ),
                client_capabilities=ClientCapabilities(),
            )
            mcp = McpServerStdio(
                name=_MCP_NAME,
                command=_python_executable(),
                args=list(_MCP_ARGS),
                env=_mcp_env(self._settings, lesson_id),
            )
            # Extra kwargs become NewSessionRequest._meta (field_meta).
            response = await self._conn.new_session(
                cwd=str(workspace),
                mcp_servers=[mcp],
                rules=rules,
                yoloMode=True,
            )
            self._session_id = response.session_id
            self._emit(
                AgentStatus(connected=True, message="session ready", session_id=self._session_id, busy=True)
            )
            await self._prompt_unlocked([text_block(_wrap_kickoff(rules, kickoff_prompt))])
        except Exception as exc:
            self._emit(
                AgentStatus(
                    connected=False,
                    message=f"start failed: {exc}",
                    session_id=self._session_id,
                    busy=False,
                )
            )
            raise

    async def _prompt_unlocked(self, prompt: list[Any]) -> None:
        conn, session_id = self._conn, self._session_id
        if conn is None or session_id is None:
            raise RuntimeError("ACP session is not started")
        self._set_busy(True, "prompting")
        try:
            await conn.prompt(session_id=session_id, prompt=prompt)
        except asyncio.CancelledError:
            self._set_busy(False, "cancelled")
            raise
        except Exception as exc:
            self._set_busy(False, str(exc))
            raise
        else:
            self._set_busy(False, "")

    async def _shutdown_unlocked(self) -> None:
        if self._dead and self._conn is None and self._process is None:
            return
        conn, session_id, busy = self._conn, self._session_id, self._busy
        self._dead = True
        if busy and conn is not None and session_id is not None:
            try:
                await conn.cancel(session_id=session_id)
            except Exception:
                log.debug("session/cancel during shutdown failed", exc_info=True)
        if conn is not None and session_id is not None:
            close_session = getattr(conn, "close_session", None)
            if callable(close_session):
                try:
                    await close_session(session_id=session_id)
                except Exception:
                    log.debug("session/close during shutdown failed", exc_info=True)

        if conn is not None:
            try:
                await conn.close()
            except Exception:
                log.debug("ACP connection close failed", exc_info=True)
            self._conn = None

        await self._stop_process()
        self._close_stderr()
        self._session_id = None
        self._busy = False
        self._emit(
            AgentStatus(connected=False, message="shutdown", session_id=None, busy=False),
            force=True,
        )

    async def _stop_process(self) -> None:
        proc = self._process
        self._process = None
        if proc is None or proc.returncode is not None:
            return
        if proc.stdin is not None:
            try:
                proc.stdin.close()
            except Exception:
                log.debug("agent stdin close failed", exc_info=True)
        if sys.platform == "win32":
            await self._taskkill_tree(proc.pid)
            try:
                await asyncio.wait_for(proc.wait(), timeout=_SHUTDOWN_TIMEOUT)
                return
            except (asyncio.TimeoutError, ProcessLookupError):
                pass
        try:
            proc.terminate()
        except ProcessLookupError:
            return
        try:
            await asyncio.wait_for(proc.wait(), timeout=_SHUTDOWN_TIMEOUT)
            return
        except asyncio.TimeoutError:
            pass
        except ProcessLookupError:
            return
        try:
            proc.kill()
        except ProcessLookupError:
            return
        try:
            await asyncio.wait_for(proc.wait(), timeout=_SHUTDOWN_TIMEOUT)
        except (asyncio.TimeoutError, ProcessLookupError):
            log.warning("agent process did not exit after kill")

    async def _taskkill_tree(self, pid: int) -> None:
        try:
            await asyncio.to_thread(
                subprocess.run,
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True,
                timeout=_SHUTDOWN_TIMEOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception:
            log.debug("taskkill /T failed for pid %s", pid, exc_info=True)

    def _close_stderr(self) -> None:
        handle = self._stderr
        self._stderr = None
        if handle is None:
            return
        try:
            handle.close()
        except Exception:
            log.debug("stderr log close failed", exc_info=True)
