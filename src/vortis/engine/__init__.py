"""Inference Engine primitive — LLM runtime management."""

from __future__ import annotations

import importlib
import logging

import vortis.engine.nim  # noqa: F401
import vortis.engine.ollama  # noqa: F401
import vortis.engine.openai_compat_engines  # noqa: F401
from vortis.engine._base import (
    EngineConnectionError,
    EngineContextLengthError,
    InferenceEngine,
    looks_like_context_length_error,
    messages_to_dicts,
)
from vortis.engine._discovery import discover_engines, discover_models, get_engine

logger = logging.getLogger(__name__)


def _register_optional_engines() -> None:
    """Register available optional engines and retain import diagnostics."""

    for optional in ("cloud", "litellm", "gemma_cpp", "apple_fm"):
        try:
            importlib.import_module(f".{optional}", __name__)
        except (ImportError, OSError) as exc:
            logger.debug("Optional engine %r unavailable: %s", optional, exc)


_register_optional_engines()

__all__ = [
    "EngineConnectionError",
    "EngineContextLengthError",
    "InferenceEngine",
    "discover_engines",
    "discover_models",
    "get_engine",
    "looks_like_context_length_error",
    "messages_to_dicts",
]
