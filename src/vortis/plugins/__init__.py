"""Single-file plugins: drop a ``.py`` into a plugins folder and it is a tool.

Format (compatible with FatihMakes/Mark-LVII ``plugins/_template.py``, so most
plugins written for Mark 57 / Torvis load unchanged)::

    PLUGIN = {
        "name": "inventor_export",            # unique, snake_case
        "description": "When the model should call this tool.",
        "parameters": {                        # JSON schema; Gemini-style
            "type": "object",                  # "OBJECT"/"STRING" also accepted
            "properties": {"part": {"type": "string"}},
            "required": ["part"],
        },
        "confirm": False,     # True → the HUD confirmation button gates it
        "timeout": 30,        # seconds
    }

    def run(parameters, player=None, session_memory=None):
        return "status=done action=inventor_export file=C:/parts/wing.stp"

``run`` may return a string, or a dict ``{"content": ..., "outcome":
"done"|"unverified"|"failed"}`` (see ``vortis.tools.outcome``).

Folders scanned, in order: ``$VORTIS_PLUGIN_DIRS`` (os.pathsep separated),
``./plugins`` in the working directory, and ``~/.vortis/plugins``. Files
starting with ``_`` are skipped. A plugin is ordinary Python running with your
user's rights: only install plugins you have read.
"""

from __future__ import annotations

import importlib.util
import logging
import os
import re
import sys
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from vortis.core.paths import get_config_dir
from vortis.core.types import ToolResult
from vortis.tools._stubs import BaseTool, ToolSpec

logger = logging.getLogger(__name__)

_NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,63}$")
_lock = threading.Lock()
_loaded: Dict[str, Dict[str, Any]] = {}
_errors: Dict[str, str] = {}
_scanned = False


def plugin_dirs() -> List[Path]:
    dirs: List[Path] = []
    env = os.environ.get("VORTIS_PLUGIN_DIRS", "")
    dirs += [Path(p).expanduser() for p in env.split(os.pathsep) if p.strip()]
    dirs.append(Path.cwd() / "plugins")
    dirs.append(get_config_dir() / "plugins")
    seen: List[Path] = []
    for d in dirs:
        try:
            resolved = d.resolve()
        except OSError:
            continue
        if resolved not in seen:
            seen.append(resolved)
    return seen


def _normalise_schema(schema: Any) -> Dict[str, Any]:
    """Gemini-style upper-case types → JSON schema lower-case."""
    if isinstance(schema, dict):
        out: Dict[str, Any] = {}
        for key, value in schema.items():
            if key == "type" and isinstance(value, str):
                out[key] = value.lower()
            else:
                out[key] = _normalise_schema(value)
        return out
    if isinstance(schema, list):
        return [_normalise_schema(v) for v in schema]  # type: ignore[return-value]
    return schema


class PluginTool(BaseTool):
    """Adapter from a ``PLUGIN`` dict + ``run`` function to ``BaseTool``."""

    is_local = True

    def __init__(self, meta: Dict[str, Any], run: Any, source: str) -> None:
        self._meta = meta
        self._run = run
        self._source = source
        self.tool_id = meta["name"]

    @property
    def spec(self) -> ToolSpec:
        params = _normalise_schema(
            self._meta.get("parameters") or {"type": "object", "properties": {}}
        )
        params.setdefault("type", "object")
        params.setdefault("properties", {})
        return ToolSpec(
            name=self._meta["name"],
            description=str(self._meta.get("description", "")),
            parameters=params,
            category="plugin",
            requires_confirmation=bool(self._meta.get("confirm", False)),
            timeout_seconds=float(self._meta.get("timeout", 30)),
            metadata={"plugin_source": self._source},
        )

    def execute(self, **params: Any) -> ToolResult:
        name = self._meta["name"]
        try:
            try:
                value = self._run(params, None, None)
            except TypeError:
                value = self._run(params)
        except Exception as exc:
            logger.warning("Plugin %s raised: %s", name, exc)
            return ToolResult(
                tool_name=name,
                content=f"Plugin '{name}' failed: {exc}",
                success=False,
                metadata={"outcome": "failed"},
            )
        if isinstance(value, dict):
            outcome = str(value.get("outcome", "done")).lower()
            return ToolResult(
                tool_name=name,
                content=str(value.get("content", "")),
                success=outcome != "failed",
                metadata={"outcome": outcome},
            )
        text = "" if value is None else str(value)
        status = re.match(r"\s*status=(done|unverified|failed)\b", text)
        outcome = status.group(1) if status else "done"
        return ToolResult(
            tool_name=name,
            content=text,
            success=outcome != "failed",
            metadata={"outcome": outcome},
        )


def _load_file(path: Path) -> Optional[Dict[str, Any]]:
    module_name = f"vortis_plugin_{path.stem}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError("cannot create module spec")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(module_name, None)
        raise
    meta = getattr(module, "PLUGIN", None)
    run = getattr(module, "run", None)
    if not isinstance(meta, dict) or not callable(run):
        raise ValueError("needs a PLUGIN dict and a run() function")
    name = str(meta.get("name", ""))
    if not _NAME_RE.match(name):
        raise ValueError(f"invalid plugin name {name!r}")
    return {"meta": dict(meta), "run": run}


def load_plugins(
    dirs: Optional[List[Path]] = None, *, force: bool = False
) -> List[str]:
    """Discover plugins and register them in ``ToolRegistry``. Idempotent."""
    global _scanned
    from vortis.core.registry import ToolRegistry

    with _lock:
        registry_intact = all(ToolRegistry.contains(n) for n in _loaded)
        if _scanned and not force and dirs is None and registry_intact:
            return sorted(_loaded)
        if not registry_intact or force:
            _loaded.clear()
            _errors.clear()
        _scanned = True
        for folder in dirs if dirs is not None else plugin_dirs():
            if not folder.is_dir():
                continue
            for path in sorted(folder.glob("*.py")):
                if path.name.startswith("_"):
                    continue
                try:
                    loaded = _load_file(path)
                except BaseException as exc:  # noqa: BLE001 - isolate plugins
                    if isinstance(exc, KeyboardInterrupt):
                        raise
                    _errors[str(path)] = str(exc)
                    logger.warning("Plugin %s not loaded: %s", path, exc)
                    continue
                assert loaded is not None
                meta, run = loaded["meta"], loaded["run"]
                name = meta["name"]
                if name in _loaded or ToolRegistry.contains(name):
                    _errors[str(path)] = f"name '{name}' already taken"
                    logger.warning("Plugin %s skipped: name taken", path)
                    continue

                def _factory(_m=meta, _r=run, _s=str(path), **_kw: Any) -> PluginTool:
                    return PluginTool(_m, _r, _s)

                ToolRegistry.register_value(name, _factory)
                _loaded[name] = {
                    "name": name,
                    "description": str(meta.get("description", ""))[:300],
                    "source": str(path),
                    "confirm": bool(meta.get("confirm", False)),
                }
                logger.info("Loaded plugin %s from %s", name, path)
        return sorted(_loaded)


def plugin_names() -> List[str]:
    return sorted(_loaded)


def loaded_plugins() -> List[Dict[str, Any]]:
    out = [dict(v, loaded=True) for v in _loaded.values()]
    out += [
        {"source": src, "loaded": False, "error": err} for src, err in _errors.items()
    ]
    return out


def _reset_for_tests() -> None:
    global _scanned
    from vortis.core.registry import ToolRegistry

    with _lock:
        for name in list(_loaded):
            try:
                ToolRegistry._entries().pop(name, None)
            except Exception:
                pass
        _loaded.clear()
        _errors.clear()
        _scanned = False


__all__ = [
    "PluginTool",
    "load_plugins",
    "loaded_plugins",
    "plugin_dirs",
    "plugin_names",
]
