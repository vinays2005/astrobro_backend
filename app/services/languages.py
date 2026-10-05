"""Supported languages for AI answers and speech input."""
from __future__ import annotations

# code, English name, native name, script, Whisper code (None if unsupported by speech-to-text)
_LANGS = [
    ("en", "English", "English", "Latin", "en"),
    ("hi", "Hindi", "हिन्दी", "Devanagari", "hi"),
    ("mr", "Marathi", "मराठी", "Devanagari", "mr"),
    ("gu", "Gujarati", "ગુજરાતી", "Gujarati", "gu"),
    ("bn", "Bengali", "বাংলা", "Bengali", "bn"),
    ("ta", "Tamil", "தமிழ்", "Tamil", "ta"),
    ("te", "Telugu", "తెలుగు", "Telugu", "te"),
    ("kn", "Kannada", "ಕನ್ನಡ", "Kannada", "kn"),
    ("ml", "Malayalam", "മലയാളം", "Malayalam", "ml"),
    ("pa", "Punjabi", "ਪੰਜਾਬੀ", "Gurmukhi", "pa"),
    ("or", "Odia", "ଓଡ଼ିଆ", "Odia", None),
    ("as", "Assamese", "অসমীয়া", "Bengali-Assamese", "as"),
    ("ur", "Urdu", "اردو", "Perso-Arabic", "ur"),
]
LANGUAGES = [
    {"code": c, "name": n, "native_name": nat, "script": s, "speech_input": w is not None}
    for c, n, nat, s, w in _LANGS
]
_BY_KEY: dict[str, tuple] = {}
for _t in _LANGS:
    _BY_KEY[_t[0]] = _t
    _BY_KEY[_t[1].lower()] = _t
    _BY_KEY[_t[2].lower()] = _t


def resolve(value: str | None) -> tuple | None:
    if not value:
        return None
    return _BY_KEY.get(value.strip().lower())


def is_english(value: str | None) -> bool:
    t = resolve(value)
    return t is None or t[0] == "en"


def language_directive(value: str | None, json_output: bool) -> str:
    """Instruction appended to the system prompt; empty for English."""
    t = resolve(value)
    if t is None or t[0] == "en":
        return ""
    _, name, native, script, _w = t
    base = (f"8. LANGUAGE: Write every human-readable sentence in {name} ({native}) using the {script} script, in simple, "
            "natural wording. Keep Sanskrit names of planets, signs and nakshatras as commonly written in that language.")
    if json_output:
        base += " Keep all JSON keys and enumerated values (such as supportive, challenging, mixed, neutral) in English."
    return base


def whisper_code(value: str | None) -> str | None:
    t = resolve(value)
    return t[4] if t else None
