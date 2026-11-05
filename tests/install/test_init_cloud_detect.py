"""Tests for init's cloud auto-detect and from-bare-vortis flag."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from vortis.cli.init_cmd import init


def _clear_keys(monkeypatch) -> None:
    for k in (
        "OPENROUTER_API_KEY",
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "GOOGLE_API_KEY",
        "GEMINI_API_KEY",
    ):
        monkeypatch.delenv(k, raising=False)


def test_init_accepts_from_bare_vortis_flag(
    tmp_vortis_home: Path, monkeypatch
) -> None:
    """The --from-bare-vortis flag exists and suppresses the launch-chat prompt."""
    _clear_keys(monkeypatch)
    runner = CliRunner()
    result = runner.invoke(
        init,
        ["--from-bare-vortis", "--engine", "ollama", "--no-download", "--no-scan"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
    assert "Launch chat" not in result.output


def test_init_proposes_cloud_when_key_in_env(
    tmp_vortis_home: Path, monkeypatch
) -> None:
    """When ANTHROPIC_API_KEY is set, init mentions cloud / anthropic."""
    _clear_keys(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    runner = CliRunner()
    result = runner.invoke(
        init,
        ["--from-bare-vortis", "--engine", "ollama", "--no-download", "--no-scan"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
    assert "anthropic" in result.output.lower() or "cloud" in result.output.lower()


def test_init_from_bare_vortis_skips_engine_prompt(
    tmp_vortis_home: Path, monkeypatch
) -> None:
    """--from-bare-vortis must not hang on the engine-selection prompt
    even when --engine is not provided."""
    _clear_keys(monkeypatch)
    runner = CliRunner()
    result = runner.invoke(
        init,
        ["--from-bare-vortis", "--no-download", "--no-scan"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
