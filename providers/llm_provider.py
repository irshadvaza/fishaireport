"""
llm_provider.py
----------------
Abstraction layer for the LLM that turns a raw transcript into structured JSON.

Today  -> GroqLLMProvider   (free, Llama-3.3-70b on Groq, JSON mode)
Future -> AzureLLMProvider  (Azure OpenAI GPT-4o / GPT-4.1, same JSON contract)
"""

import os
import json
from abc import ABC, abstractmethod

from utils.parser import build_extraction_prompt, SCHEMA_EXAMPLE


class BaseLLMProvider(ABC):
    @abstractmethod
    def extract_structured_data(self, transcript: str) -> dict:
        raise NotImplementedError


class GroqLLMProvider(BaseLLMProvider):
    def __init__(self):
        from groq import Groq
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key or api_key == "your_groq_api_key_here":
            raise RuntimeError(
                "GROQ_API_KEY is missing. Get a free key at https://console.groq.com/keys "
                "and add it to your .env file."
            )
        self.client = Groq(api_key=api_key)
        self.model = os.getenv("GROQ_LLM_MODEL", "llama-3.3-70b-versatile")

    def extract_structured_data(self, transcript: str) -> dict:
        system_prompt, user_prompt = build_extraction_prompt(transcript)
        response = self.client.chat.completions.create(
            model=self.model,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        content = response.choices[0].message.content
        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            raise ValueError(f"LLM did not return valid JSON:\n{content}") from e


class AzureLLMProvider(BaseLLMProvider):
    """
    Placeholder for the Azure migration.
    Recommended implementation: Azure OpenAI Chat Completions API
    (openai python SDK, azure_endpoint + api_key + deployment name),
    using the same system/user prompts from utils.parser.build_extraction_prompt
    and response_format={"type": "json_object"}.
    """

    def __init__(self):
        self.endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
        self.key = os.getenv("AZURE_OPENAI_KEY")
        self.deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")
        if not (self.endpoint and self.key and self.deployment):
            raise RuntimeError(
                "AZURE_OPENAI_ENDPOINT / AZURE_OPENAI_KEY / AZURE_OPENAI_DEPLOYMENT not set in .env"
            )

    def extract_structured_data(self, transcript: str) -> dict:
        raise NotImplementedError(
            "Implement Azure OpenAI chat completion call here, reusing build_extraction_prompt()."
        )


def get_llm_provider() -> BaseLLMProvider:
    provider = os.getenv("LLM_PROVIDER", "groq").lower()
    if provider == "groq":
        return GroqLLMProvider()
    elif provider == "azure":
        return AzureLLMProvider()
    raise ValueError(f"Unknown LLM_PROVIDER '{provider}'")
