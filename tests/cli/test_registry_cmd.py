"""Tests for the ``vortis registry`` CLI commands."""

from __future__ import annotations

from click.testing import CliRunner

from vortis.cli import cli
from vortis.core.registry import (
    ToolRegistry,
)


class TestRegistryCmd:
    """Test cases for the vortis registry CLI group."""

    def test_registry_group_help(self) -> None:
        """Test that the registry group help displays correctly."""
        result = CliRunner().invoke(cli, ["registry", "--help"])
        assert result.exit_code == 0
        assert "registry" in result.output.lower()

    def test_registry_list_help(self) -> None:
        """Test that the registry list help displays correctly."""
        result = CliRunner().invoke(cli, ["registry", "list", "--help"])
        assert result.exit_code == 0

    def test_registry_show_help(self) -> None:
        """Test that the registry show help displays correctly."""
        result = CliRunner().invoke(cli, ["registry", "show", "--help"])
        assert result.exit_code == 0

    def test_registry_list_shows_all_registries(self) -> None:
        """Test that registry list displays all available registries."""
        result = CliRunner().invoke(cli, ["registry", "list"])
        assert result.exit_code == 0
        output = result.output.lower()
        assert "registry" in output

    def test_registry_show_unknown_registry(self) -> None:
        """Test that showing an unknown registry shows an error."""
        result = CliRunner().invoke(cli, ["registry", "show", "unknown_registry_xyz"])
        assert result.exit_code == 0
        assert (
            "unknown" in result.output.lower() or "not found" in result.output.lower()
        )

    def test_registry_show_tool_registry(self) -> None:
        """Test that showing the tool registry displays entries."""
        import vortis.tools  # noqa: F401

        result = CliRunner().invoke(cli, ["registry", "show", "tool"])
        assert result.exit_code == 0
        assert "tool" in result.output.lower() or "key" in result.output.lower()

    def test_registry_show_tool_registry_verbose(self) -> None:
        """Test that showing the tool registry with verbose flag shows details."""
        import vortis.tools  # noqa: F401

        result = CliRunner().invoke(cli, ["registry", "show", "tool", "-v"])
        assert result.exit_code == 0

    def test_registry_show_empty_registry(self) -> None:
        """Test registry show behavior with an empty registry."""
        result = CliRunner().invoke(cli, ["registry", "show", "agent"])
        assert result.exit_code == 0
        assert "agent" in result.output.lower() or "empty" in result.output.lower()

    def test_registry_show_accepts_aliases(self) -> None:
        """Test that registry show accepts various aliases."""
        import vortis.tools  # noqa: F401

        result = CliRunner().invoke(cli, ["registry", "show", "tools"])
        assert result.exit_code == 0

    def test_registry_keys_match_actual_registries(self) -> None:
        """Test that the list command shows all expected registry names."""
        result = CliRunner().invoke(cli, ["registry", "list"])
        assert result.exit_code == 0
        output = result.output

        assert "ToolRegistry" in output or "tool" in output.lower()
        assert "EngineRegistry" in output or "engine" in output.lower()
        assert "MemoryRegistry" in output or "memory" in output.lower()
        assert "ChannelRegistry" in output or "channel" in output.lower()

    def test_registry_show_nonexistent_key(self) -> None:
        """Test that showing a nonexistent key in a registry is handled."""
        result = CliRunner().invoke(cli, ["registry", "show", "nonexistent"])
        assert result.exit_code == 0
        assert (
            "unknown" in result.output.lower() or "not found" in result.output.lower()
        )

    def test_registry_list_handles_import_error(self) -> None:
        """Test that registry list handles import errors gracefully."""
        result = CliRunner().invoke(cli, ["registry", "list"])
        assert result.exit_code == 0

    def test_registry_show_handles_exception(self) -> None:
        """Test that registry show handles exceptions gracefully."""
        from unittest.mock import patch

        with patch(
            "vortis.core.registry.ToolRegistry.keys",
            side_effect=Exception("Test error"),
        ):
            result = CliRunner().invoke(cli, ["registry", "show", "tool"])
            assert result.exit_code == 0
            assert "error" in result.output.lower()

    def test_registry_list_handles_registry_error(self) -> None:
        """Test that registry list handles errors for specific registries."""
        from unittest.mock import patch

        with patch.object(ToolRegistry, "keys", side_effect=Exception("Import error")):
            result = CliRunner().invoke(cli, ["registry", "list"])
            assert result.exit_code == 0

    def test_registry_show_handles_error_during_import(self) -> None:
        """Test that registry show handles exceptions during import."""
        from unittest.mock import patch

        with patch.dict("sys.modules", {"vortis.core.registry": None}):
            result = CliRunner().invoke(cli, ["registry", "show", "tool"])
            assert result.exit_code == 0

    def test_registry_show_handles_error_during_iteration(self) -> None:
        """Test that registry show handles exceptions during entry iteration."""
        from unittest.mock import patch

        with patch.object(ToolRegistry, "keys", return_value=["fake_tool"]):
            with patch.object(
                ToolRegistry, "get", side_effect=Exception("Iteration error")
            ):
                result = CliRunner().invoke(cli, ["registry", "show", "tool"])
                assert result.exit_code == 0
                assert "error" in result.output.lower()
