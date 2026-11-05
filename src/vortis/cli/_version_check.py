"""Check for newer releases published as tags on the project repository."""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path

from vortis.core.paths import get_config_dir

logger = logging.getLogger(__name__)

_CACHE_PATH = get_config_dir() / "version-check.json"
_CACHE_TTL = 86400
_TAGS_API = "https://api.github.com/repos/Luka-T1/Vortis/tags?per_page=100"


def _config_path() -> Path:
    """Resolve the config path, honoring ``VORTIS_CONFIG`` like core.config."""
    override = os.environ.get("VORTIS_CONFIG")
    if override:
        return Path(override).expanduser()
    return get_config_dir() / "config.toml"


_CHECK_COMMANDS = {
    "ask",
    "chat",
    "serve",
    "doctor",
    "init",
    "quickstart",
    "model",
    "agents",
    "skill",
    "memory",
    "telemetry",
    "config",
}

_OPT_OUT_ENV_VARS = ("VORTIS_NO_UPDATE_CHECK",)


def _check_disabled() -> bool:
    """Return True when the user has opted out of update checks."""
    for name in _OPT_OUT_ENV_VARS:
        raw = os.environ.get(name, "")
        if raw and raw.strip().lower() not in ("", "0", "false", "no", "off"):
            return True
    if os.environ.get("CI", "").strip().lower() in ("1", "true", "yes", "on"):
        return True
    return _config_disabled()


def _config_disabled() -> bool:
    """Return True if config.toml has ``[updates] auto_update = false``.

    On a malformed config we conservatively return ``True`` — if the user
    tried to express an opt-out and the file has a typo, we should not
    silently flip back to auto-checking against their intent.
    """
    path = _config_path()
    if not path.exists():
        return False
    try:
        import tomllib
    except ImportError:
        try:
            import tomli as tomllib  # type: ignore[no-redef]
        except ImportError:
            logger.debug("tomli not available, skipping config opt-out check")
            return False
    try:
        with open(path, "rb") as f:
            config = tomllib.load(f)
    except OSError as exc:
        logger.debug("config read failed: %s", exc)
        return False
    except tomllib.TOMLDecodeError as exc:
        logger.debug("config malformed at %s: %s — treating as opt-out", path, exc)
        return True
    return not config.get("updates", {}).get("auto_update", True)


def check_for_updates(command_name: str) -> None:
    """Print a message if a newer version is available. Best-effort, never raises.

    Honors ``VORTIS_NO_UPDATE_CHECK=1`` and ``CI=true`` — any
    truthy value (``1``, ``true``, ``yes``, ``on``) disables both the
    PyPI poll and the banner. See ``_check_disabled`` for the full list.
    """
    if command_name not in _CHECK_COMMANDS:
        return
    if _check_disabled():
        return
    try:
        _do_check()
    except Exception:
        pass


def _do_check() -> None:
    import vortis

    current = vortis.__version__
    if "unknown" in current.lower():
        return
    latest = _get_latest_version(current)
    if latest is None:
        return

    from packaging.version import InvalidVersion, Version

    try:
        if Version(latest) > Version(current):
            from vortis.cli._install_detect import detect_install

            cmd = detect_install().upgrade_command
            alternative = (
                "" if cmd == "vortis self-update" else "Or run: vortis self-update\n"
            )
            sys.stderr.write(
                f"\033[33mA new version of Vortis is available "
                f"(v{current} → v{latest})\n"
                f"Update: {cmd}\n"
                f"{alternative}\033[0m\n"
            )
    except InvalidVersion:
        pass


def _get_latest_version(current: str) -> str | None:
    """Return the latest non-prerelease version string from cache or PyPI.

    Returns ``None`` on network/parse failures rather than caching a stale
    or empty result. Dev/pre-release versions (``.devN``, ``aN``, ``bN``,
    ``rcN``) are filtered out so users on a stable release are not nudged
    to a rolling autotag build — they can still opt in via ``--pre``.
    """
    try:
        if _CACHE_PATH.exists():
            data = json.loads(_CACHE_PATH.read_text())
            last_check = data.get("last_check", 0)
            if time.time() - last_check < _CACHE_TTL:
                cached = data.get("latest_version")
                return cached or None
    except Exception:
        pass

    latest = _fetch_latest_stable()
    if not latest:
        return None

    try:
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_PATH.write_text(
            json.dumps(
                {
                    "last_check": time.time(),
                    "latest_version": latest,
                    "current_version": current,
                }
            )
        )
    except Exception:
        pass

    return latest


def _fetch_latest_stable() -> str | None:
    """Return the highest non-prerelease tagged version, or ``None``."""
    try:
        import urllib.request

        req = urllib.request.Request(
            _TAGS_API, headers={"Accept": "application/vnd.github+json"}
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            tags = json.loads(resp.read())
    except Exception as exc:
        logger.debug("Release poll failed: %s", exc)
        return None
    if not isinstance(tags, list):
        return None

    from packaging.version import InvalidVersion, Version

    stable: list[Version] = []
    for tag in tags:
        name = str(tag.get("name", "")) if isinstance(tag, dict) else ""
        try:
            v = Version(name.lstrip("vV"))
        except InvalidVersion:
            continue
        if not (v.is_prerelease or v.is_devrelease):
            stable.append(v)
    return str(max(stable)) if stable else None
