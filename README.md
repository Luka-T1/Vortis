# Vortis

Vortis is a personal assistant that runs on your own computer. You talk to it, point at it, or type, and it answers on whatever screen is closest: the PC, a paired phone, or the TV.

It is local-first. A small model on the PC handles quick commands and keeps working offline; harder questions go to a cloud model of your choice. Camera frames and microphone audio stay on the device that captured them.

## What it does

- **Voice.** Wake word, speech recognition and spoken replies, in Serbian and English.
- **Hand gestures.** In-browser hand tracking with remappable gestures: open palm, fist, thumbs up/down, V sign, pinch, swipes, grab, repulsor push, two-hand spread and collapse. Short voice commands trigger exactly the same actions.
- **HUD.** A full-screen command centre with live tool activity, paired devices and gesture settings.
- **Any screen.** Pair a phone or TV with a QR code or a six-digit code. The assistant can push text, tables and charts (line, bar, area, scatter, pie) to the TV.
- **Safe by default.** Anything that changes files, sends messages or controls a device waits for a human confirmation that the model cannot forge. Tool results are reported as done, unverified or failed.
- **Extensible.** Single-file plugins, skills, MCP servers and a large tool set (files, shell, git, browser, web search, calendar and mail connectors, memory).
- **Hybrid models.** Ollama, llama.cpp, vLLM and other local engines, plus OpenAI, Anthropic, Google and OpenRouter in the cloud, with routing between them.

## Requirements

- Windows 10/11, macOS or Linux
- Python 3.11 to 3.13 and [uv](https://docs.astral.sh/uv/)
- Rust toolchain (the native extension is built from source)
- Node.js 22+ for the web interface
- [Ollama](https://ollama.com) for local models

## Install

Windows (PowerShell):

```powershell
irm https://raw.githubusercontent.com/Luka-T1/Vortis/main/deploy/windows/install.ps1 | iex
```

macOS and Linux:

```bash
curl -fsSL https://raw.githubusercontent.com/Luka-T1/Vortis/main/scripts/install/install.sh | bash
```

From source:

```bash
git clone https://github.com/Luka-T1/Vortis.git
cd Vortis
uv sync --extra server --extra desktop --group desktop-native
cd frontend && npm ci && npm run build && cd ..
uv run vortis init
uv run vortis serve
```

Open `http://localhost:8000`. The HUD is the start page.

## Everyday commands

```bash
vortis                 # chat in the terminal
vortis ask "..."       # one question
vortis serve           # API server and web interface
vortis doctor          # check engines, models and extensions
vortis model list      # local and cloud models
vortis memory list     # what the assistant remembers
```

## Using the TV

1. Start the server on the LAN: `vortis serve --host 0.0.0.0` with `VORTIS_API_KEY` set.
2. HUD, Uređaji, QR kod. On the TV open the shown address, type the code and tick "Ovo je TV".
3. The TV now shows `/display`. Say "pošalji na TV", swipe up, or let the assistant use its `show_on_screen` tool.

The TV is output only. Its camera and microphone are never used.

More detail: [docs/hud.md](docs/hud.md).

## Development

```bash
uv sync --extra dev --extra server
uv run maturin develop -m rust/crates/vortis-python/Cargo.toml
uv run pytest -n auto
uv run ruff check src tests
cd frontend && npx vitest run && npx tsc -b --noEmit
```

## License

Apache License 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
