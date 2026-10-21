"""Tools primitive — tool system with ABC interface and built-in tools."""

from __future__ import annotations

import importlib
import logging

from vortis.tools._stubs import BaseTool, ToolExecutor, ToolSpec

logger = logging.getLogger(__name__)

_BUILTIN_TOOL_MODULES = (
    "calculator",
    "think",
    "retrieval",
    "llm_tool",
    "file_read",
    "web_search",
    "weather",
    "fx_macro",
    "code_interpreter",
    "code_interpreter_docker",
    "repl",
    "storage_tools",
    "mcp_adapter",
    "channel_tools",
    "http_request",
    "docker_shell_exec",
    "shell_exec",
    "memory_manage",
    "user_profile_manage",
    "skill_manage",
    "file_write",
    "apply_patch",
    "git_tool",
    "db_query",
    "pdf_tool",
    "image_tool",
    "audio_tool",
    "knowledge_tools",
    "text_to_speech",
    "digest_collect",
    "scan_chunks",
    "knowledge_sql",
    "apple_calendar",
    "knowledge_search",
    "browser",
    "browser_axtree",
    "proactive_tools",
    "show_on_screen",
)

for _name in _BUILTIN_TOOL_MODULES:
    try:
        importlib.import_module(f"vortis.tools.{_name}")
    except ImportError as _exc:
        logger.debug("Optional tool %s not loaded: %s", _name, _exc)

__all__ = ["BaseTool", "ToolExecutor", "ToolSpec"]
