"""Smoke test that the tmp_vortis_home fixture works."""

from __future__ import annotations

from pathlib import Path

from vortis.core import config as config_mod


def test_fixture_redirects_default_config_dir(tmp_vortis_home: Path) -> None:
    assert config_mod.DEFAULT_CONFIG_DIR == tmp_vortis_home
    assert tmp_vortis_home.exists()
    assert (tmp_vortis_home / ".state").exists()
    assert (tmp_vortis_home / ".state" / "models").exists()


def test_fixture_redirects_config_path(tmp_vortis_home: Path) -> None:
    assert config_mod.DEFAULT_CONFIG_PATH == tmp_vortis_home / "config.toml"
