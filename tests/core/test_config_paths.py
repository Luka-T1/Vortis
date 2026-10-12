"""Tests for the env-aware Vortis home-directory resolver (issue #462).

Covers the single-root consolidation: ``$VORTIS_HOME`` >
``$XDG_DATA_HOME/vortis`` > ``~/.vortis``, backward compatibility
(no env => exactly ``~/.vortis``), and the source-tree rejection guard.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from vortis.core import paths


def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove every env var that influences home resolution."""
    for var in (
        "VORTIS_HOME",
        "XDG_DATA_HOME",
        "XDG_CONFIG_HOME",
        "XDG_CACHE_HOME",
    ):
        monkeypatch.delenv(var, raising=False)


class TestGetConfigDir:
    """Precedence and backward compatibility of get_config_dir()."""

    def test_default_when_unset_is_legacy_dir(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _clear_env(monkeypatch)
        assert paths.get_config_dir() == (Path.home() / ".vortis").resolve()

    def test_respects_vortis_home(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _clear_env(monkeypatch)
        custom = tmp_path / "oj"
        monkeypatch.setenv("VORTIS_HOME", str(custom))
        assert paths.get_config_dir() == custom.resolve()

    def test_respects_xdg_data_home(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _clear_env(monkeypatch)
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        assert paths.get_config_dir() == (tmp_path / "vortis").resolve()

    def test_vortis_home_wins_over_xdg(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _clear_env(monkeypatch)
        oj = tmp_path / "vt_wins"
        monkeypatch.setenv("VORTIS_HOME", str(oj))
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg_loses"))
        assert paths.get_config_dir() == oj.resolve()

    def test_expands_user_in_vortis_home(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _clear_env(monkeypatch)
        monkeypatch.setenv("VORTIS_HOME", "~/relocated-oj")
        assert paths.get_config_dir() == (Path.home() / "relocated-oj").resolve()

    def test_returns_absolute_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _clear_env(monkeypatch)
        monkeypatch.setenv("VORTIS_HOME", str(tmp_path / "rel"))
        assert paths.get_config_dir().is_absolute()


class TestDerivedDirs:
    """config_path / data_dir / cache_dir all hang off the single root."""

    def test_config_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _clear_env(monkeypatch)
        monkeypatch.setenv("VORTIS_HOME", str(tmp_path / "oj"))
        assert paths.get_config_path() == (tmp_path / "oj" / "config.toml").resolve()

    def test_data_dir_equals_config_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _clear_env(monkeypatch)
        monkeypatch.setenv("VORTIS_HOME", str(tmp_path / "oj"))
        assert paths.get_data_dir() == paths.get_config_dir()

    def test_cache_dir_is_nested_cache(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _clear_env(monkeypatch)
        monkeypatch.setenv("VORTIS_HOME", str(tmp_path / "oj"))
        assert paths.get_cache_dir() == (tmp_path / "oj" / "cache").resolve()

    def test_cache_dir_under_xdg(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _clear_env(monkeypatch)
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        assert paths.get_cache_dir() == (tmp_path / "vortis" / "cache").resolve()


class TestSourceTreeRejection:
    """A home pointing inside the repo must fail loudly (REVIEW.md)."""

    def test_rejects_path_inside_source_tree(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _clear_env(monkeypatch)
        source_root = paths._find_source_root()
        assert source_root is not None
        monkeypatch.setenv("VORTIS_HOME", str(source_root / "junk_dir"))
        with pytest.raises(paths.ConfigurationError, match="inside the source tree"):
            paths.get_config_dir()


class TestLegacyConstantsHonorEnv:
    """The legacy DEFAULT_CONFIG_* names route through the env-aware resolver.

    This is the exact split-brain bug from #462: the constant used to ignore
    VORTIS_HOME entirely. The constant is resolved once at import (the
    install-script model, where the env is set before the process starts), and
    every instance-level default goes through ``get_config_dir()`` so it honors
    the override. ``DEFAULT_CONFIG_DIR`` stays a real attribute so existing
    tests can ``monkeypatch.setattr`` it.
    """

    def test_constant_matches_resolver_at_import(self) -> None:
        from vortis.core import config

        assert config.DEFAULT_CONFIG_DIR == paths.get_config_dir()
        assert config.DEFAULT_CONFIG_PATH == paths.get_config_path()

    def test_constant_is_a_real_settable_attribute(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from vortis.core import config

        monkeypatch.setattr(config, "DEFAULT_CONFIG_DIR", tmp_path / "patched")
        assert config.DEFAULT_CONFIG_DIR == tmp_path / "patched"

    def test_dataclass_defaults_reflect_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _clear_env(monkeypatch)
        from vortis.core.config import SessionConfig, StorageConfig

        monkeypatch.setenv("VORTIS_HOME", str(tmp_path / "oj"))
        root = (tmp_path / "oj").resolve()
        assert StorageConfig().db_path == str(root / "memory.db")
        assert SessionConfig().db_path == str(root / "sessions.db")

    def test_downstream_consumer_honors_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _clear_env(monkeypatch)
        from vortis.core import credentials

        monkeypatch.setenv("VORTIS_HOME", str(tmp_path / "oj"))
        assert (
            credentials._default_path()
            == (tmp_path / "oj" / "credentials.toml").resolve()
        )

    def test_constant_never_resolves_to_the_real_developer_home(self) -> None:
        """Regression for #787: DEFAULT_CONFIG_DIR is resolved once, at the
        first import of vortis.core.config anywhere in the test
        session -- which happens via tests/conftest.py, before any test
        body runs. If conftest.py doesn't set VORTIS_HOME before that
        import, this constant (and the ~45 modules that reference it)
        permanently binds to the developer's real ~/.vortis for the
        rest of the run, so tests touching e.g. AgentConfigEvolver or
        LearningOrchestrator read/write real files there.

        No monkeypatching here on purpose: this checks the *actual*
        session-wide value tests/conftest.py's import-time setup already
        produced, not a value manufactured by this test.
        """
        from vortis.core.config import DEFAULT_CONFIG_DIR

        real_home = (Path.home() / ".vortis").resolve()
        assert DEFAULT_CONFIG_DIR != real_home
        assert "VORTIS_CONFIG" not in os.environ
