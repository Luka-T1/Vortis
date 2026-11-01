"""Speech subsystem — speech-to-text and text-to-speech backends."""

from __future__ import annotations

import importlib
import logging

logger = logging.getLogger(__name__)

for _mod in ("faster_whisper", "openai_whisper", "deepgram"):
    try:
        importlib.import_module(f".{_mod}", __name__)
    except ImportError as _exc:
        logger.debug("Optional STT backend %s not loaded: %s", _mod, _exc)

for _mod in ("cartesia_tts", "elevenlabs_tts", "kokoro_tts", "openai_tts"):
    try:
        importlib.import_module(f".{_mod}", __name__)
    except ImportError as _exc:
        logger.debug("Optional TTS backend %s not loaded: %s", _mod, _exc)
