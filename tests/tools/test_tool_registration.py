"""Verify that importing vortis.tools registers all built-in tools."""

from __future__ import annotations

import importlib
import subprocess
import sys

from vortis.core.registry import ToolRegistry

EXPECTED_TOOLS = {
    "calculator",
    "think",
    "retrieval",
    "llm",
    "file_read",
    "file_write",
    "web_search",
    "get_weather",
    "fx_macro_data",
    "code_interpreter",
    "code_interpreter_docker",
    "repl",
    "memory_store",
    "memory_retrieve",
    "memory_search",
    "memory_index",
    "channel_send",
    "channel_list",
    "channel_status",
    "http_request",
    "docker_shell_exec",
    "shell_exec",
    "memory_manage",
    "user_profile_manage",
    "skill_manage",
    "apply_patch",
    "git_status",
    "git_diff",
    "git_commit",
    "git_log",
    "db_query",
    "pdf_extract",
    "image_generate",
    "audio_transcribe",
    "text_to_speech",
    "digest_collect",
    "kg_add_entity",
    "kg_add_relation",
    "kg_query",
    "kg_neighbors",
    "knowledge_sql",
    "scan_chunks",
    "calendar_upcoming",
    "calendar_search",
    "knowledge_search",
    "browser_navigate",
    "browser_click",
    "browser_type",
    "browser_screenshot",
    "browser_extract",
    "browser_axtree",
    "check_permission",
    "queue_action",
    "get_pending_actions",
    "record_decision",
    "execute_pending_actions",
}


def _reload_tool_modules() -> None:
    """Reload all vortis.tools.* submodules to re-trigger @register decorators.

    The autouse ``_clean_registries`` fixture clears all registries before each
    test.  A plain ``import vortis.tools`` won't re-register because the
    submodules are already cached in ``sys.modules``.  We ensure the package is
    imported, then reload the individual submodules so their class-level
    ``@ToolRegistry.register`` decorators execute again.
    """
    import vortis.tools  # noqa: F401

    for mod_name in list(sys.modules):
        if (
            mod_name.startswith("vortis.tools.")
            and not mod_name.endswith("_stubs")
            and not mod_name.endswith("agent_tools")
        ):
            try:
                importlib.reload(sys.modules[mod_name])
            except Exception:
                pass


def test_all_builtin_tools_registered():
    _reload_tool_modules()

    registered = set(ToolRegistry.keys())
    missing = EXPECTED_TOOLS - registered
    assert not missing, (
        f"Tools not registered (missing import in __init__.py?): {sorted(missing)}"
    )


def test_package_import_registers_deep_research_tools():
    """Registration must not depend on another module being imported first."""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import vortis.tools; "
                "from vortis.core.registry import ToolRegistry; "
                "expected = {'knowledge_sql', 'scan_chunks'}; "
                "missing = expected - set(ToolRegistry.keys()); "
                "assert not missing, f'Missing tools: {sorted(missing)}'"
            ),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_calendar_tools_register_when_connector_is_imported_first():
    """Connector imports must not suppress calendar tool registration."""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import vortis.connectors.apple_calendar; "
                "from vortis.core.registry import ToolRegistry; "
                "expected = {'calendar_upcoming', 'calendar_search'}; "
                "missing = expected - set(ToolRegistry.keys()); "
                "assert not missing, f'Missing tools: {sorted(missing)}'"
            ),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_package_import_registers_knowledge_browser_and_proactive_tools():
    """Package import registers knowledge_search, browser, and proactive tools."""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import vortis.tools; "
                "from vortis.core.registry import ToolRegistry; "
                "expected = {"
                "'knowledge_search', 'browser_navigate', 'browser_axtree', "
                "'check_permission', 'queue_action'"
                "}; "
                "missing = expected - set(ToolRegistry.keys()); "
                "assert not missing, f'Missing tools: {sorted(missing)}'"
            ),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
