"""``vortis start|stop|restart|status`` — daemon management commands."""

from __future__ import annotations

import json
import os
import re
import secrets
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import click
from rich.console import Console

from vortis.core.config import DEFAULT_CONFIG_DIR, load_config
from vortis.core.utils import process_alive, terminate_process
from vortis.security.file_utils import secure_write_json, secure_write_text

_PID_FILE = DEFAULT_CONFIG_DIR / "server.pid"
_LOG_FILE = DEFAULT_CONFIG_DIR / "server.log"
_STATE_FILE = DEFAULT_CONFIG_DIR / "server.json"
_LAUNCH_TOKEN_ENV = "VORTIS_DAEMON_LAUNCH_TOKEN"


def _pid_alive(pid: int) -> bool:
    """Return whether *pid* identifies a running process without signaling it."""
    return process_alive(pid)


def _linux_process_identity(pid: int) -> dict | None:
    """Read a process identity unaffected by wall-clock adjustments.

    Linux's boot epoch changes when the clock is set; boot_id and start ticks
    do not. Both are needed because PIDs and start ticks can repeat after boot.
    """
    if sys.platform != "linux":
        return None
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
        start_ticks = int(stat.rsplit(")", 1)[1].split()[19])
        boot_id = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        if start_ticks < 0 or not boot_id:
            return None
        return {"pid": pid, "boot_id": boot_id, "start_ticks": start_ticks}
    except (OSError, ValueError, IndexError):
        return None


def _read_pid_identity() -> dict:
    """Read the optional Linux identity sidecar, preserving legacy PID files."""
    try:
        identity = json.loads(_PID_FILE.with_suffix(".identity.json").read_text())
    except (OSError, ValueError):
        return {}
    if (
        not isinstance(identity, dict)
        or type(identity.get("pid")) is not int
        or identity["pid"] <= 0
        or type(identity.get("start_ticks")) is not int
        or identity["start_ticks"] < 0
        or not isinstance(identity.get("boot_id"), str)
        or not identity["boot_id"]
    ):
        return {}
    return identity


def _legacy_cli_args(argv: list[str]) -> list[str] | None:
    """Find CLI arguments without treating script arguments as Python options."""
    entry_points = {"vortis", "vortis.exe"}
    if not argv:
        return None
    executable = Path(argv[0]).name
    if executable in entry_points:
        return argv[1:]
    if not re.fullmatch(
        r"(?:python|pypy)(?:\d+(?:\.\d+)*)?[tdm]?(?:\.exe)?", executable
    ):
        return None

    index = 1
    while index < len(argv):
        arg = argv[index]
        if arg == "--":
            index += 1
            break
        if not arg.startswith("-") or arg == "-":
            break
        if arg == "--check-hash-based-pycs":
            index += 2
            continue
        if arg.startswith("--check-hash-based-pycs="):
            index += 1
            continue
        options = arg[1:]
        while options:
            option, options = options[0], options[1:]
            if option == "c":
                return None
            if option in "mWX":
                if not options:
                    index += 1
                    if index >= len(argv):
                        return None
                    options = argv[index]
                if option == "m":
                    return argv[index + 1 :] if options == "vortis.cli" else None
                break
            if option not in "bBdEiIOPqRsSuvx":
                return None
        index += 1
    if index < len(argv) and Path(argv[index]).name in entry_points:
        return argv[index + 1 :]
    return None


def _legacy_linux_daemon(pid: int) -> bool | None:
    """Recognize an old registration before it has a saved process identity."""
    try:
        arguments = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
    except OSError:
        return None
    if arguments and arguments[-1] == b"":
        arguments.pop()
    argv = [os.fsdecode(arg) for arg in arguments]
    command = _legacy_cli_args(argv)
    if command is None:
        return False
    while command and command[0] in {"--verbose", "--quiet", "--pick-model"}:
        command = command[1:]
    if command and command[0] == "--":
        command = command[1:]
    return bool(command) and command[0] == "serve"


def _registered_pid_alive(pid: int) -> bool:
    """Reject reused Linux PIDs without comparing mutable wall-clock times."""
    if not _pid_alive(pid):
        return False
    if sys.platform != "linux":
        return True
    current = _linux_process_identity(pid)
    if current is None:
        return True
    recorded = _read_pid_identity()
    if recorded.get("pid") == pid:
        return current == recorded
    is_daemon = _legacy_linux_daemon(pid)
    if is_daemon is False:
        return False
    if is_daemon:
        confirmed = _linux_process_identity(pid)
        if confirmed is not None and confirmed != current:
            return False
        if confirmed is not None:
            try:
                secure_write_json(_PID_FILE.with_suffix(".identity.json"), confirmed)
            except OSError:
                pass
    return True


@contextmanager
def _state_lock(state_file: Path | None = None) -> Iterator[None]:
    """Serialize daemon bookkeeping across launching and supervised processes."""
    path = _PID_FILE if state_file is None else state_file
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(".lock").open("a+b") as lock:
        if os.name == "nt":
            import msvcrt

            if lock.tell() == 0:
                lock.write(b"\0")
                lock.flush()
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == "nt":
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _read_pid_file() -> int | None:
    try:
        pid = int(_PID_FILE.read_text().strip())
    except (OSError, ValueError):
        return None
    return pid if pid > 0 else None


def _clear_state_unlocked(pid: int) -> None:
    if _read_pid_file() == pid:
        _PID_FILE.unlink(missing_ok=True)
    if _read_state().get("pid") == pid:
        _STATE_FILE.unlink(missing_ok=True)
    if _read_pid_identity().get("pid") == pid:
        _PID_FILE.with_suffix(".identity.json").unlink(missing_ok=True)


def _read_pid_unlocked() -> int | None:
    """Read and clean up daemon state while the state lock is held."""
    pid = _read_pid_file()
    if pid is None:
        _PID_FILE.unlink(missing_ok=True)
        return None
    if not _registered_pid_alive(pid):
        _clear_state_unlocked(pid)
        return None
    return pid


def _read_pid() -> int | None:
    """Read PID from pid file, return None if not found or stale."""
    with _state_lock():
        return _read_pid_unlocked()


def _write_pid(
    pid: int,
    host: str = "",
    port: int | None = None,
    *,
    ready: bool = True,
    launch_token: str | None = None,
) -> None:
    """Write PID, plus the address the daemon actually bound to."""
    with _state_lock():
        _write_pid_unlocked(pid, host, port, ready=ready, launch_token=launch_token)


def _write_pid_unlocked(
    pid: int,
    host: str = "",
    port: int | None = None,
    *,
    ready: bool = True,
    launch_token: str | None = None,
) -> None:
    """Update the state while holding the lock, allowing one launch to promote."""
    existing = _read_pid_file()
    current = _read_state()
    same_launch = (
        launch_token is not None
        and current.get("launch_token") == launch_token
        and current.get("pid") == existing
    )
    if (
        not ready
        and current.get("ready", True)
        and (current.get("pid") == pid or same_launch)
    ):
        return
    if existing is not None and existing != pid and _registered_pid_alive(existing):
        if not (ready and same_launch and current.get("ready") is False):
            raise RuntimeError(f"Another server is already registered (PID {existing})")
    identity = _linux_process_identity(pid)
    if identity is not None:
        secure_write_json(_PID_FILE.with_suffix(".identity.json"), identity)
    else:
        _PID_FILE.with_suffix(".identity.json").unlink(missing_ok=True)
    secure_write_text(_PID_FILE, str(pid))
    if host or port is not None:
        state = {"pid": pid, "host": host, "port": port}
        if not ready:
            state["ready"] = False
        if launch_token is not None:
            state["launch_token"] = launch_token
        secure_write_json(_STATE_FILE, state)
    else:
        _STATE_FILE.unlink(missing_ok=True)


def _read_state() -> dict:
    """Return the recorded daemon address, or {} when it is unavailable."""
    try:
        state = json.loads(_STATE_FILE.read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(state, dict):
        return {}
    if (
        type(state.get("pid")) is not int
        or state["pid"] <= 0
        or not isinstance(state.get("host"), str)
        or not state["host"].strip()
        or type(state.get("port")) is not int
        or not 0 <= state["port"] <= 65535
        or type(state.get("ready", True)) is not bool
        or (
            "launch_token" in state
            and (
                not isinstance(state["launch_token"], str) or not state["launch_token"]
            )
        )
    ):
        return {}
    return state


def _bound_address(pid: int | None = None) -> tuple[str, int]:
    """Resolve the daemon's address, preferring what `start` recorded."""
    state = _read_state()
    if (
        state.get("pid") == (pid if pid is not None else _read_pid_file())
        and state.get("ready", True)
        and state
    ):
        return state["host"], state["port"]
    config = load_config()
    return config.server.host, int(config.server.port)


def _server_url(host: str, port: int) -> str:
    return f"http://[{host}]:{port}" if ":" in host else f"http://{host}:{port}"


def record_server_state(pid: int, host: str, port: int) -> None:
    """Register a running server so `vortis status` can find it.

    Called by `vortis serve` itself, so a server supervised by launchd/systemd
    (which never goes through `vortis start`) is still reported as running.
    """
    _write_pid(pid, host, port, launch_token=os.environ.get(_LAUNCH_TOKEN_ENV))


def clear_server_state(pid: int) -> None:
    """Deregister a server on shutdown, but only if it still owns the files."""
    with _state_lock():
        _clear_state_unlocked(pid)


@click.group()
def daemon() -> None:
    """Manage the Vortis server daemon."""


@daemon.command()
@click.option("--host", default=None, help="Bind address.")
@click.option("--port", default=None, type=int, help="Port number.")
@click.option("-e", "--engine", "engine_key", default=None, help="Engine backend.")
@click.option("-m", "--model", "model_name", default=None, help="Default model.")
@click.option("-a", "--agent", "agent_name", default=None, help="Agent type.")
def start(
    host: str | None,
    port: int | None,
    engine_key: str | None,
    model_name: str | None,
    agent_name: str | None,
) -> None:
    """Start the Vortis server as a background daemon."""
    console = Console(stderr=True)

    existing = _read_pid()
    if existing is not None:
        console.print(f"[yellow]Server already running (PID {existing}).[/yellow]")
        console.print("Use 'vortis stop' to stop it first, or 'vortis restart'.")
        sys.exit(1)

    config = load_config()
    bind_host = host or config.server.host
    bind_port = port if port is not None else config.server.port

    cmd = [sys.executable, "-m", "vortis.cli", "serve"]
    if host:
        cmd.extend(["--host", host])
    if port is not None:
        cmd.extend(["--port", str(port)])
    if engine_key:
        cmd.extend(["--engine", engine_key])
    if model_name:
        cmd.extend(["--model", model_name])
    if agent_name:
        cmd.extend(["--agent", agent_name])

    DEFAULT_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    spawn_kwargs: dict = {}
    if sys.platform == "win32":
        spawn_kwargs["creationflags"] = (
            subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        )
    else:
        spawn_kwargs["start_new_session"] = True
    launch_token = secrets.token_hex(16)
    proc = None
    registration_error = None
    with _state_lock():
        existing = _read_pid_unlocked()
        if existing is None:
            with open(_LOG_FILE, "a") as log_fh:
                proc = subprocess.Popen(
                    cmd,
                    stdout=log_fh,
                    stderr=log_fh,
                    env={**os.environ, _LAUNCH_TOKEN_ENV: launch_token},
                    **spawn_kwargs,
                )
            try:
                _write_pid_unlocked(
                    proc.pid,
                    bind_host,
                    bind_port,
                    ready=False,
                    launch_token=launch_token,
                )
            except (OSError, RuntimeError) as exc:
                registration_error = exc

    if existing is not None:
        console.print(f"[yellow]Server already running (PID {existing}).[/yellow]")
        console.print("Use 'vortis stop' to stop it first, or 'vortis restart'.")
        sys.exit(1)
    assert proc is not None
    if registration_error is not None:
        terminate_process(proc.pid, grace_seconds=10.0)
        clear_server_state(proc.pid)
        raise click.ClickException(str(registration_error)) from registration_error

    console.print(
        f"[green]Vortis server starting[/green] (launch PID {proc.pid})\n"
        f"  Requested URL: {_server_url(bind_host, bind_port)}\n"
        f"  Log: {_LOG_FILE}"
    )


@daemon.command()
def stop() -> None:
    """Stop the running Vortis server daemon."""
    console = Console(stderr=True)
    from vortis.cli.gui_cmd import stop_frontend

    frontend_pid = stop_frontend()
    if frontend_pid is not None:
        console.print(f"[green]Frontend stopped[/green] (PID {frontend_pid}).")

    pid = _read_pid()
    if pid is None:
        console.print("[yellow]No running server found.[/yellow]")
        sys.exit(0 if frontend_pid is not None else 1)

    terminate_process(pid, grace_seconds=10.0)

    clear_server_state(pid)
    console.print(f"[green]Server stopped[/green] (PID {pid}).")


@daemon.command()
@click.pass_context
def restart(ctx: click.Context) -> None:
    """Restart the Vortis server daemon."""
    console = Console(stderr=True)
    pid = _read_pid()
    previous = _read_state() if pid is not None else {}
    if previous.get("pid") != pid:
        previous = {}
    if pid is not None:
        console.print(f"Stopping server (PID {pid})...")
        ctx.invoke(stop)
    ctx.invoke(
        start,
        host=previous.get("host") or None,
        port=previous.get("port"),
    )


@daemon.command()
def status() -> None:
    """Show status of the Vortis server daemon."""
    console = Console(stderr=True)
    pid = _read_pid()
    if pid is None:
        console.print("[yellow]Server is not running.[/yellow]")
        return

    state = _read_state()
    if state.get("pid") == pid and state.get("ready") is False:
        console.print(f"[yellow]Server is starting[/yellow] (PID {pid}).")
        console.print(f"  Log: {_LOG_FILE}")
        return

    uptime_info = ""
    try:
        import psutil

        proc = psutil.Process(pid)
        uptime = time.time() - proc.create_time()
        hours, remainder = divmod(int(uptime), 3600)
        minutes, seconds = divmod(remainder, 60)
        uptime_info = f"\n  Uptime: {hours}h {minutes}m {seconds}s"
    except (ImportError, Exception):
        pass

    host, port = _bound_address(pid)
    console.print(
        f"[green]Server is running[/green] (PID {pid}){uptime_info}\n"
        f"  URL: {_server_url(host, port)}\n"
        f"  Log: {_LOG_FILE}"
    )


__all__ = ["daemon", "start", "stop", "restart", "status"]
