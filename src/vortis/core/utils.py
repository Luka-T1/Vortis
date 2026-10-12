"""Small cross-platform utilities used by the CLI, OAuth flow, and evals.

Kept dependency-free so importing this module is cheap (the public re-export
from ``vortis.core`` must not pull in heavy modules at package init).
"""

from __future__ import annotations

import os
import platform
import shutil
import signal
import subprocess
import time
import webbrowser


def _windows_process_alive(pid: int) -> bool:
    """Query a Windows process handle without sending it a signal."""
    import ctypes
    from ctypes import wintypes

    error_invalid_parameter = 87
    synchronize = 0x00100000
    wait_object_0 = 0x00000000

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    handle = kernel32.OpenProcess(synchronize, False, pid)
    if not handle:
        return ctypes.get_last_error() != error_invalid_parameter

    try:
        return kernel32.WaitForSingleObject(handle, 0) != wait_object_0
    finally:
        kernel32.CloseHandle(handle)


def _posix_process_state(pid: int) -> str | None:
    """Return a POSIX process state letter, or ``None`` when unavailable."""
    proc_root = "/proc"
    try:
        with open(f"{proc_root}/{pid}/stat", encoding="utf-8") as stat_file:
            return stat_file.read().rsplit(") ", 1)[1][:1]
    except FileNotFoundError:
        if os.path.isdir(proc_root):
            return "X"
    except (IndexError, OSError):
        pass

    try:
        result = subprocess.run(
            ["ps", "-o", "stat=", "-p", str(pid)],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    state = result.stdout.strip()
    if result.returncode != 0 or not state:
        return "X"
    return state[:1]


def get_python_executable() -> str:
    """Return the best ``python`` interpreter name on PATH.

    Prefers ``python3`` (Linux/macOS convention); falls back to ``python``
    (Windows / some minimal Linux distros that ship only ``python``). Returns
    the literal string ``"python3"`` when neither is found, so callers still
    get a usable command that will fail with a clear "command not found"
    rather than an empty string.

    The result is a *command name or absolute path* that callers can hand to
    :mod:`subprocess` directly when ``shell=False``, and must be shell-quoted
    (:func:`shlex.quote`) before being interpolated into a ``shell=True``
    command string — paths on Windows often contain spaces.
    """
    return shutil.which("python3") or shutil.which("python") or "python3"


def open_browser(url: str) -> None:
    """Open *url* in the user's default browser, with a Windows fast-path.

    :func:`webbrowser.open` is the cross-platform default, but on Windows it
    sometimes blocks or fails inside a console host. :func:`os.startfile`
    hands the URL to the OS shell and returns immediately. We try that first
    on Windows and fall back to :func:`webbrowser.open` if it fails.
    """
    if platform.system() == "Windows":
        try:
            os.startfile(url)  # type: ignore[attr-defined]
            return
        except Exception:  # noqa: BLE001 - any launch failure -> fall back
            pass
    webbrowser.open(url)


def process_alive(pid: int | None) -> bool:
    """Return ``True`` if a process with *pid* is currently running.

    Cross-platform and *non-destructive*. The common POSIX idiom
    ``os.kill(pid, 0)`` must NOT be used on Windows: there ``os.kill`` maps any
    signal to ``TerminateProcess``, so a "liveness probe" would actually kill
    the process. On Windows we inspect a process handle instead.
    """
    if not pid or pid <= 0:
        return False
    if platform.system() == "Windows":
        return _windows_process_alive(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    except OSError:
        return False

    return _posix_process_state(pid) not in {"X", "Z"}


def terminate_process(pid: int | None, *, grace_seconds: float = 3.0) -> None:
    """Terminate *pid* gracefully, escalating to a forced kill (cross-platform).

    POSIX sends ``SIGTERM`` then, after *grace_seconds*, ``SIGKILL``. Windows
    has neither; it uses ``taskkill /T`` (graceful, whole tree) then
    ``taskkill /F /T`` (force). ``signal.SIGKILL`` does not exist on Windows,
    so it is only referenced inside the POSIX branch.
    """
    if not process_alive(pid):
        return
    is_windows = platform.system() == "Windows"

    if is_windows:
        subprocess.run(
            ["taskkill", "/T", "/PID", str(pid)],
            capture_output=True,
            check=False,
        )
    else:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            return

    deadline = time.monotonic() + max(0.0, grace_seconds)
    while time.monotonic() < deadline:
        if not process_alive(pid):
            return
        time.sleep(0.05)

    if is_windows:
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            capture_output=True,
            check=False,
        )
    else:
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass


__all__ = [
    "get_python_executable",
    "open_browser",
    "process_alive",
    "terminate_process",
]
