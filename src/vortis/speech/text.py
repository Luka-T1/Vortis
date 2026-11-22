"""Post-processing for speech-to-text output."""

from __future__ import annotations

import re
import unicodedata

_CYRILLIC_TO_LATIN = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "ђ": "đ", "е": "e",
    "ж": "ž", "з": "z", "и": "i", "ј": "j", "к": "k", "л": "l", "љ": "lj",
    "м": "m", "н": "n", "њ": "nj", "о": "o", "п": "p", "р": "r", "с": "s",
    "т": "t", "ћ": "ć", "у": "u", "ф": "f", "х": "h", "ц": "c", "ч": "č",
    "џ": "dž", "ш": "š",
}

_HALLUCINATIONS = (
    "hvala na gledanju",
    "hvala sto ste gledali",
    "hvala vam na paznji",
    "titlovi",
    "prevod i obrada",
    "pretplatite se",
    "thank you for watching",
    "thanks for watching",
    "subtitles by",
    "please subscribe",
    "like and subscribe",
)

_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)


def to_latin(text: str) -> str:
    """Transliterate Serbian Cyrillic to Latin script, preserving case."""
    if not any("Ѐ" <= ch <= "ӿ" for ch in text):
        return text
    out = []
    for ch in text:
        low = ch.lower()
        latin = _CYRILLIC_TO_LATIN.get(low)
        if latin is None:
            out.append(ch)
        elif ch != low:
            out.append(latin[0].upper() + latin[1:])
        else:
            out.append(latin)
    return "".join(out)


def fold(text: str) -> str:
    """Lowercase, strip diacritics and punctuation for loose comparison."""
    text = to_latin(text).lower().replace("đ", "dj")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(_PUNCT.sub(" ", text).split())


def is_hallucination(text: str) -> bool:
    """True for the stock phrases Whisper invents on silence or noise."""
    folded = fold(text)
    if not folded:
        return True
    return any(folded.startswith(p) or folded == p for p in _HALLUCINATIONS)
