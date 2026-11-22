from unittest.mock import patch

from vortis.cli.init_cmd import _next_steps_text, _ollama_install_text


def test_windows_hint_uses_winget():
    with patch("vortis.cli.init_cmd.platform.system", return_value="Windows"):
        text = _ollama_install_text()
    assert "winget install Ollama.Ollama" in text
    assert "curl" not in text


def test_linux_hint_uses_install_script():
    with patch("vortis.cli.init_cmd.platform.system", return_value="Linux"):
        assert "ollama.com/install.sh" in _ollama_install_text()


def test_next_steps_include_platform_hint_and_model():
    with patch("vortis.cli.init_cmd.platform.system", return_value="Windows"):
        text = _next_steps_text("ollama", "qwen3.5:2b")
    assert "winget install Ollama.Ollama" in text
    assert "ollama pull qwen3.5:2b" in text
