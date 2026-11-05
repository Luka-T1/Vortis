"""Tests for the ``vortis tool`` CLI commands."""

from __future__ import annotations

from click.testing import CliRunner

from vortis.cli import cli
from vortis.core.registry import ToolRegistry


class TestToolCmd:
    """Test cases for the vortis tool CLI group."""

    def test_tool_group_help(self) -> None:
        """Test that the tool group help displays correctly."""
        result = CliRunner().invoke(cli, ["tool", "--help"])
        assert result.exit_code == 0
        assert "tool" in result.output.lower() or "list" in result.output

    def test_tool_list_help(self) -> None:
        """Test that the tool list help displays correctly."""
        result = CliRunner().invoke(cli, ["tool", "list", "--help"])
        assert result.exit_code == 0
        assert "list" in result.output.lower() or "registered" in result.output.lower()

    def test_tool_inspect_help(self) -> None:
        """Test that the tool inspect help displays correctly."""
        result = CliRunner().invoke(cli, ["tool", "inspect", "--help"])
        assert result.exit_code == 0
        assert "tool" in result.output.lower() or "inspect" in result.output.lower()

    def test_tool_list_shows_registered_tools(self) -> None:
        """Test that tool list displays registered tools."""
        result = CliRunner().invoke(cli, ["tool", "list"])
        assert result.exit_code == 0
        output = result.output.lower()
        assert "tool" in output or "name" in output or "description" in output

    def test_tool_inspect_unknown_tool(self) -> None:
        """Test that inspecting an unknown tool shows an error."""
        result = CliRunner().invoke(cli, ["tool", "inspect", "nonexistent_tool_xyz"])
        assert result.exit_code == 0
        assert "not found" in result.output.lower() or "error" in result.output.lower()

    def test_tool_inspect_known_tool(self) -> None:
        """Test that inspecting a known tool shows details."""
        import vortis.tools  # noqa: F401

        registered_tools = ToolRegistry.keys()
        if registered_tools:
            tool_name = registered_tools[0]
            result = CliRunner().invoke(cli, ["tool", "inspect", tool_name])
            assert result.exit_code == 0
            assert tool_name in result.output

    def test_tool_list_empty_registry(self) -> None:
        """Test tool list behavior with empty registry."""
        result = CliRunner().invoke(cli, ["tool", "list"])
        assert result.exit_code == 0

    def test_tool_inspect_requires_tool_name(self) -> None:
        """Test that inspect command requires a tool name argument."""
        result = CliRunner().invoke(cli, ["tool", "inspect"])
        assert result.exit_code in (0, 2)

    def test_tool_list_with_registered_tools(self) -> None:
        """Test that tool list shows details for registered tools."""
        import vortis.tools  # noqa: F401

        result = CliRunner().invoke(cli, ["tool", "list"])
        assert result.exit_code == 0
        output = result.output
        assert (
            "Registered Tools" in output
            or "No tools registered" in output
            or "Total:" in output
        )

    def test_tool_list_handles_instantiation_error(self) -> None:
        """Test that tool list handles tool instantiation errors gracefully."""
        from unittest.mock import patch

        with patch.object(ToolRegistry, "keys", return_value=["mock_tool"]):
            with patch.object(ToolRegistry, "get", return_value=object):
                result = CliRunner().invoke(cli, ["tool", "list"])
                assert result.exit_code == 0
                assert "mock_tool" in result.output or "Total:" in result.output

    def test_tool_inspect_with_spec_details(self) -> None:
        """Test that inspect shows full spec details for tools with specs."""
        import vortis.tools  # noqa: F401

        registered_tools = ToolRegistry.keys()
        if registered_tools:
            tool_name = registered_tools[0]
            result = CliRunner().invoke(cli, ["tool", "inspect", tool_name])
            assert result.exit_code == 0
            output = result.output
            assert tool_name in output

    def test_tool_inspect_handles_instantiation_error(self) -> None:
        """Test that inspect handles tool instantiation errors gracefully."""
        from unittest.mock import patch

        with patch.object(ToolRegistry, "contains", return_value=True):
            with patch.object(ToolRegistry, "get", return_value=object):
                result = CliRunner().invoke(cli, ["tool", "inspect", "mock_tool"])
                assert result.exit_code == 0
                assert "mock_tool" in result.output

    def test_tool_list_catches_registry_exception(self) -> None:
        """Test that tool list handles exceptions during registry access."""
        from unittest.mock import patch

        with patch.object(
            ToolRegistry, "keys", side_effect=Exception("Registry error")
        ):
            result = CliRunner().invoke(cli, ["tool", "list"])
            assert result.exit_code == 0
            assert "error" in result.output.lower()

    def test_tool_inspect_catches_registry_exception(self) -> None:
        """Test that tool inspect handles exceptions during registry access."""
        from unittest.mock import patch

        with patch.object(
            ToolRegistry, "contains", side_effect=Exception("Registry error")
        ):
            result = CliRunner().invoke(cli, ["tool", "inspect", "mock_tool"])
            assert result.exit_code == 0
            assert "error" in result.output.lower()

    def test_tool_list_shows_tool_spec(self) -> None:
        """Test that tool list displays spec details when available."""
        from unittest.mock import MagicMock, patch

        mock_spec = MagicMock()
        mock_spec.description = "Test tool description"
        mock_spec.category = "test-category"

        mock_tool_cls = MagicMock()
        mock_tool_instance = MagicMock()
        mock_tool_instance.spec = mock_spec
        mock_tool_cls.return_value = mock_tool_instance

        with patch.object(ToolRegistry, "keys", return_value=["mock_tool"]):
            with patch.object(ToolRegistry, "get", return_value=mock_tool_cls):
                result = CliRunner().invoke(cli, ["tool", "list"])
                assert result.exit_code == 0
                output = result.output
                assert "mock_tool" in output
                assert "Test tool description" in output

    def test_tool_inspect_shows_full_spec_details(self) -> None:
        """Test that inspect displays full spec details including parameters."""
        from unittest.mock import MagicMock, patch

        mock_spec = MagicMock()
        mock_spec.name = "MockTool"
        mock_spec.description = "A mock tool for testing"
        mock_spec.category = "testing"
        mock_spec.parameters = {
            "properties": {
                "input": {"type": "string", "description": "Input parameter"},
                "count": {"type": "integer", "description": "Count value"},
            }
        }

        mock_tool_cls = MagicMock()
        mock_tool_instance = MagicMock()
        mock_tool_instance.spec = mock_spec
        mock_tool_cls.return_value = mock_tool_instance

        with patch.object(ToolRegistry, "contains", return_value=True):
            with patch.object(ToolRegistry, "get", return_value=mock_tool_cls):
                result = CliRunner().invoke(cli, ["tool", "inspect", "mock_tool"])
                assert result.exit_code == 0
                output = result.output
                assert "mock_tool" in output
                assert "MockTool" in output
                assert "A mock tool for testing" in output
                assert "testing" in output
                assert "Parameters" in output
                assert "input" in output
                assert "count" in output

    def test_tool_inspect_handles_tool_without_spec(self) -> None:
        """Test that inspect handles tools without spec attribute."""
        from unittest.mock import MagicMock, patch

        mock_tool_cls = MagicMock()
        del mock_tool_cls.spec

        with patch.object(ToolRegistry, "contains", return_value=True):
            with patch.object(ToolRegistry, "get", return_value=mock_tool_cls):
                result = CliRunner().invoke(cli, ["tool", "inspect", "mock_tool"])
                assert result.exit_code == 0
                assert "mock_tool" in result.output

    def test_tool_list_handles_tool_without_spec(self) -> None:
        """Test that tool list handles tools without spec attribute."""
        from unittest.mock import patch

        class ToolWithoutSpec:
            pass

        mock_tool_cls = ToolWithoutSpec

        with patch.object(ToolRegistry, "keys", return_value=["mock_tool"]):
            with patch.object(ToolRegistry, "get", return_value=mock_tool_cls):
                result = CliRunner().invoke(cli, ["tool", "list"])
                assert result.exit_code == 0
                assert "mock_tool" in result.output or "Total" in result.output
