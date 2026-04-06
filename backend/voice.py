import os
import tempfile
from pathlib import Path
from openai import OpenAI

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    return _client


def transcribe_audio(audio_bytes: bytes, filename: str = "audio.webm") -> str:
    """Send audio bytes to OpenAI Whisper and return the transcript."""
    client = _get_client()

    # Write to a temp file — Whisper SDK needs a file-like object with a name
    suffix = Path(filename).suffix or ".webm"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(audio_bytes)
        tmp_path = tmp.name

    try:
        with open(tmp_path, "rb") as f:
            result = client.audio.transcriptions.create(
                model="whisper-1",
                file=f,
            )
        return result.text
    finally:
        os.unlink(tmp_path)


def text_to_speech(text: str) -> bytes:
    """Convert text to MP3 audio bytes using OpenAI TTS."""
    client = _get_client()
    response = client.audio.speech.create(
        model="tts-1",
        voice="nova",
        input=text,
        response_format="mp3",
    )
    return response.content
