"""Kokoro TTS backend — fully open-source, runs locally.

Requires the kokoro package: pip install kokoro
Falls back gracefully if not installed.

Kokoro v1.x supports multiple languages. Each language has its own
``KPipeline`` (the model loads language-specific G2P resources at init).
This backend lazily creates one pipeline per language code, derived from
the voice ID prefix per Kokoro's naming convention
``{lang_prefix}{gender}_{name}`` — e.g. ``zf_xiaoxiao`` is Mandarin
female (prefix ``z`` → ``lang_code="z"``).
"""

from __future__ import annotations

import builtins
import io
import logging
import sys
import threading
import types
from collections import OrderedDict
from typing import Any, Dict, List

from vortis.core.registry import TTSRegistry
from vortis.speech.tts import TTSBackend, TTSResult

logger = logging.getLogger(__name__)

_VOICE_PREFIX_TO_LANG: Dict[str, str] = {
    "a": "a",
    "b": "b",
    "z": "z",
    "j": "j",
    "f": "f",
    "i": "i",
    "p": "p",
    "h": "h",
    "e": "e",
}

_DEFAULT_LANG_CODE = "a"
_DEFAULT_VOICE_ID = "af_heart"
_KOKORO_REPO_ID = "hexgrad/Kokoro-82M"
_IMPORT_LOCK = threading.RLock()


def _import_kokoro() -> Any:
    """Import ``kokoro``, tolerating a spaCy install that cannot be loaded.

    ``kokoro.pipeline`` imports ``misaki.en`` -- and with it spaCy -- for every
    language, but only the English G2P (voices ``a*``/``b*``) uses spaCy.
    Windows Smart App Control, for one, can refuse to load spaCy's unsigned
    extension DLLs, which would otherwise take every Kokoro voice down with
    it. When spaCy is the culprit, stub it so espeak-based voices (e.g.
    ``pf_dora``) keep working; English pipelines then fail on first use.
    """
    with _IMPORT_LOCK:
        try:
            import kokoro
        except ImportError as exc:
            if exc.name == "kokoro" or sys.modules.get("spacy") is not None:
                raise
            try:
                import spacy  # noqa: F401
            except ImportError as spacy_exc:
                spacy_error = spacy_exc
            else:
                raise exc from None
            shim = types.ModuleType("spacy")
            owner = threading.get_ident()
            original_import = builtins.__import__
            active = True

            def fallback_import(name, globals=None, locals=None, fromlist=(), level=0):
                if (
                    active
                    and threading.get_ident() == owner
                    and name == "spacy"
                    and level == 0
                ):
                    return shim
                return original_import(name, globals, locals, fromlist, level)

            builtins.__import__ = fallback_import
            try:
                import kokoro
            finally:
                active = False
                if builtins.__import__ is fallback_import:
                    builtins.__import__ = original_import
            kokoro._vortis_spacy_error = str(spacy_error)
            logger.warning(
                "spaCy unavailable (%s); English Kokoro voices disabled, "
                "other languages still work",
                spacy_error,
            )
        return kokoro


@TTSRegistry.register("kokoro")
class KokoroTTSBackend(TTSBackend):
    """Kokoro TTS — local open-source voice synthesis, multilingual."""

    backend_id = "kokoro"

    def __init__(
        self,
        *,
        model_path: str = "",
        device: str = "auto",
        max_cached_pipelines: int = 4,
    ) -> None:
        if max_cached_pipelines < 1:
            raise ValueError("max_cached_pipelines must be at least 1")
        self._model_path = model_path
        self._device = device
        self._max_cached_pipelines = max_cached_pipelines
        self._model: Any | None = None
        self._pipelines: OrderedDict[str, Any] = OrderedDict()
        self._pipeline_lock = threading.RLock()

    @staticmethod
    def _lang_for_voice(voice_id: str) -> str:
        """Return the Kokoro ``lang_code`` for a voice ID.

        Voice IDs follow the convention ``{lang}{gender}_{name}`` where
        ``lang`` is a single letter prefix (e.g. ``z`` for Mandarin in
        ``zf_xiaoxiao``). Falls back to American English if the prefix is
        unknown.
        """
        if not voice_id:
            return _DEFAULT_LANG_CODE
        return _VOICE_PREFIX_TO_LANG.get(voice_id[:1], _DEFAULT_LANG_CODE)

    def _ensure_pipeline(self, lang_code: str) -> Any:
        """Lazily create and retain a bounded LRU of language pipelines."""
        with self._pipeline_lock:
            pipeline = self._pipelines.get(lang_code)
            if pipeline is not None:
                self._pipelines.move_to_end(lang_code)
                return pipeline
            try:
                kokoro = _import_kokoro()
                KPipeline = kokoro.KPipeline
            except ImportError as exc:
                raise RuntimeError(
                    "kokoro package not installed. Install with: pip install kokoro"
                ) from exc
            if lang_code in {"a", "b"} and getattr(
                kokoro, "_vortis_spacy_error", None
            ):
                raise RuntimeError(
                    "English Kokoro voices require a working spaCy installation: "
                    f"{kokoro._vortis_spacy_error}"
                )
            try:
                pipeline = KPipeline(
                    lang_code=lang_code,
                    repo_id=_KOKORO_REPO_ID,
                    model=self._ensure_model(),
                )
            except ImportError as exc:
                hints = {
                    "z": 'pip install "misaki[zh]"',
                    "j": 'pip install "misaki[ja]"',
                }
                hint = hints.get(
                    lang_code,
                    f'extra phoneme deps for lang_code="{lang_code}" (see Kokoro docs)',
                )
                raise RuntimeError(
                    f"Kokoro lang_code={lang_code!r} requires extra dependencies. "
                    f"Try: {hint}. Original error: {exc}"
                ) from exc

            self._pipelines[lang_code] = pipeline
            if len(self._pipelines) > self._max_cached_pipelines:
                _, evicted = self._pipelines.popitem(last=False)
                self._cleanup_pipeline(evicted)
            return pipeline

    def _ensure_model(self) -> Any:
        """Load the configured Kokoro model once and move it to the device."""
        if self._model is not None:
            return self._model

        try:
            KModel = _import_kokoro().KModel
        except ImportError as exc:
            raise RuntimeError(
                "kokoro package not installed. Install with: pip install kokoro"
            ) from exc

        device = self._device
        if device == "auto":
            try:
                import torch
            except ImportError:
                device = "cpu"
            else:
                if torch.cuda.is_available():
                    device = "cuda"
                elif getattr(torch.backends, "mps", None) is not None and (
                    torch.backends.mps.is_available()
                ):
                    device = "mps"
                else:
                    device = "cpu"

        model_kwargs: Dict[str, Any] = {"repo_id": _KOKORO_REPO_ID}
        if self._model_path:
            model_kwargs["model"] = self._model_path
        try:
            self._model = KModel(**model_kwargs).to(device).eval()
        except RuntimeError as exc:
            raise RuntimeError(
                f"Failed to initialize Kokoro on device {device!r}: {exc}"
            ) from exc
        return self._model

    @staticmethod
    def _cleanup_pipeline(pipeline: Any) -> None:
        """Release resources exposed by a pipeline implementation, if any."""
        close = getattr(pipeline, "close", None)
        if callable(close):
            try:
                close()
            except Exception:  # pragma: no cover - third-party cleanup is best effort
                pass

    def close(self) -> None:
        """Release every cached pipeline and clear the cache."""
        with self._pipeline_lock:
            pipelines = list(self._pipelines.values())
            self._pipelines.clear()
            for pipeline in pipelines:
                self._cleanup_pipeline(pipeline)
            self._model = None

    def synthesize(
        self,
        text: str,
        *,
        voice_id: str = _DEFAULT_VOICE_ID,
        speed: float = 1.0,
        output_format: str = "wav",
    ) -> TTSResult:
        import numpy as np
        import soundfile as sf

        lang_code = self._lang_for_voice(voice_id)
        with self._pipeline_lock:
            pipeline = self._ensure_pipeline(lang_code)
            samples = []
            for _, _, audio in pipeline(text, voice=voice_id, speed=speed):
                samples.append(audio)

        if not samples:
            return TTSResult(
                audio=b"",
                format=output_format,
                voice_id=voice_id,
                metadata={"backend": "kokoro", "lang_code": lang_code},
            )

        combined = np.concatenate(samples)
        buf = io.BytesIO()
        sf.write(buf, combined, 24000, format=output_format.upper())
        buf.seek(0)

        return TTSResult(
            audio=buf.read(),
            format=output_format,
            voice_id=voice_id,
            sample_rate=24000,
            duration_seconds=len(combined) / 24000,
            metadata={"backend": "kokoro", "lang_code": lang_code},
        )

    def available_voices(self) -> List[str]:
        return [
            "af_heart",
            "af_bella",
            "af_nicole",
            "af_sarah",
            "af_sky",
            "am_adam",
            "am_michael",
            "bf_emma",
            "bf_isabella",
            "bm_george",
            "bm_lewis",
            "zf_xiaobei",
            "zf_xiaoni",
            "zf_xiaoxiao",
            "zf_xiaoyi",
            "zm_yunjian",
            "zm_yunxi",
            "zm_yunxia",
            "zm_yunyang",
            "jf_alpha",
            "jf_gongitsune",
            "jm_kumo",
        ]

    def health(self) -> bool:
        with self._pipeline_lock:
            try:
                self._ensure_model()
                return True
            except RuntimeError:
                return False
