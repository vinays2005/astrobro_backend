"""Speech-to-text via Groq Whisper. Used for voice questions."""
from __future__ import annotations

import structlog
from groq import APIStatusError, AsyncGroq

from app.config import get_settings
from app.services import languages

logger = structlog.get_logger()

MAX_AUDIO_BYTES = 10 * 1024 * 1024
ALLOWED_EXTENSIONS = {".mp3", ".mp4", ".mpeg", ".mpga", ".m4a", ".wav", ".webm", ".ogg", ".oga", ".flac", ".aac", ".amr"}


class SpeechError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


async def transcribe(data: bytes, filename: str, language: str | None = None) -> dict:
    settings = get_settings()
    if not settings.groq_api_key:
        raise SpeechError(503, "Speech input is not configured.")
    if not data:
        raise SpeechError(400, "The audio file is empty.")
    if len(data) > MAX_AUDIO_BYTES:
        raise SpeechError(413, f"Audio is too large (limit {MAX_AUDIO_BYTES // (1024 * 1024)} MB).")
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise SpeechError(415, "Unsupported audio type. Use mp3, m4a, wav, webm, ogg or flac.")

    kwargs: dict = {"model": settings.groq_stt_model, "response_format": "verbose_json", "temperature": 0.0}
    code = languages.whisper_code(language)
    if code:
        kwargs["language"] = code

    client = AsyncGroq(api_key=settings.groq_api_key, timeout=60.0)
    try:
        result = await client.audio.transcriptions.create(file=(filename, data), **kwargs)
    except APIStatusError as exc:
        logger.error("stt_provider_error", status=exc.status_code, error=str(exc))
        if exc.status_code == 429:
            raise SpeechError(503, "Speech service is busy. Please try again in a minute.") from exc
        raise SpeechError(502, "Could not transcribe the audio. Please try again.") from exc
    except Exception as exc:  # network or SDK failure
        logger.error("stt_failed", error=str(exc))
        raise SpeechError(502, "Could not transcribe the audio. Please try again.") from exc

    text = (getattr(result, "text", "") or "").strip()
    return {
        "text": text,
        "language": getattr(result, "language", None) or code,
        "duration_seconds": getattr(result, "duration", None),
        "empty": not text,
    }
