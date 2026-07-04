"""
stt_provider.py
----------------
Speech-to-text as plain functions (no classes) — simple on purpose.

Today: Groq's hosted Whisper (free).
Later: fill in _transcribe_azure() below and set STT_PROVIDER=azure in .env.
Nothing else in the app needs to change — everything calls transcribe().
"""

import os


def transcribe(audio_filepath: str) -> str:
    """Transcribes an audio file to text using whichever provider is set in .env."""
    provider = os.getenv("STT_PROVIDER", "groq").lower()
    if provider == "groq":
        return _transcribe_groq(audio_filepath)
    elif provider == "azure":
        return _transcribe_azure(audio_filepath)
    raise ValueError(f"Unknown STT_PROVIDER: {provider}")


def _transcribe_groq(audio_filepath: str) -> str:
    from groq import Groq

    api_key = os.getenv("GROQ_API_KEY")
    if not api_key or api_key == "your_groq_api_key_here":
        raise RuntimeError(
            "GROQ_API_KEY is missing. Get a free key at https://console.groq.com/keys "
            "and add it to your .env file."
        )
    client = Groq(api_key=api_key)
    model = os.getenv("GROQ_STT_MODEL", "whisper-large-v3-turbo")

    with open(audio_filepath, "rb") as audio_file:
        transcription = client.audio.transcriptions.create(
            model=model,
            file=audio_file,
            language="en",
        )
    return transcription.text


def _transcribe_azure(audio_filepath: str) -> str:
    raise NotImplementedError(
        "Implement Azure Speech-to-Text here (azure-cognitiveservices-speech SDK) "
        "when you're ready to migrate. See README.md section 14."
    )
