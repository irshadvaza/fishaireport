"""
stt_provider.py
----------------
Abstraction layer for Speech-to-Text.

Today  -> GroqSTTProvider  (free, uses Groq's hosted Whisper endpoint)
Future -> AzureSTTProvider (uses Azure Cognitive Services Speech SDK)

To migrate later you only need to:
1. Implement the body of AzureSTTProvider.transcribe()
2. Set STT_PROVIDER=azure in your .env file
Nothing in app.py needs to change because both providers share the same interface.
"""

import os
from abc import ABC, abstractmethod


class BaseSTTProvider(ABC):
    @abstractmethod
    def transcribe(self, audio_file_path: str) -> str:
        """Return plain text transcript for the given local audio file (wav/mp3/m4a)."""
        raise NotImplementedError


class GroqSTTProvider(BaseSTTProvider):
    def __init__(self):
        from groq import Groq
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key or api_key == "your_groq_api_key_here":
            raise RuntimeError(
                "GROQ_API_KEY is missing. Get a free key at https://console.groq.com/keys "
                "and add it to your .env file."
            )
        self.client = Groq(api_key=api_key)
        self.model = os.getenv("GROQ_STT_MODEL", "whisper-large-v3-turbo")

    def transcribe(self, audio_file_path: str) -> str:
        with open(audio_file_path, "rb") as f:
            result = self.client.audio.transcriptions.create(
                file=(os.path.basename(audio_file_path), f.read()),
                model=self.model,
                response_format="text",
                # language="en"  # uncomment / set if you want to force a language
            )
        # groq returns either a str or an object with .text depending on SDK version
        return result if isinstance(result, str) else getattr(result, "text", str(result))


class AzureSTTProvider(BaseSTTProvider):
    """
    Placeholder for the Azure migration.
    Recommended implementation: Azure AI Speech "Batch/Fast transcription" REST API
    or the Speech SDK's SpeechRecognizer with AudioConfig.filename(audio_file_path).
    """

    def __init__(self):
        self.key = os.getenv("AZURE_SPEECH_KEY")
        self.region = os.getenv("AZURE_SPEECH_REGION")
        if not self.key or not self.region:
            raise RuntimeError("AZURE_SPEECH_KEY / AZURE_SPEECH_REGION not set in .env")

    def transcribe(self, audio_file_path: str) -> str:
        raise NotImplementedError(
            "Implement Azure Speech-to-Text here using azure-cognitiveservices-speech SDK."
        )


def get_stt_provider() -> BaseSTTProvider:
    provider = os.getenv("STT_PROVIDER", "groq").lower()
    if provider == "groq":
        return GroqSTTProvider()
    elif provider == "azure":
        return AzureSTTProvider()
    raise ValueError(f"Unknown STT_PROVIDER '{provider}'")
