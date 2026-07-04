"""
llm_provider.py
----------------
The two LLM jobs in this app, as plain functions (no classes):
  1. extract_structured_data()   -- transcript -> structured JSON (tables, vessels, fish)
  2. generate_narrative_report() -- structured JSON + transcript -> report prose

Today: Groq (Llama 3.3, JSON mode).
Later: fill in the two _azure functions below and set LLM_PROVIDER=azure in .env.
Nothing else in the app needs to change -- everything calls these two functions by name.
"""

import os
import json

from utils.parser import build_extraction_prompt, build_narrative_prompt
from utils.observability import log_event


def extract_structured_data(transcript: str) -> dict:
    system_prompt, user_prompt = build_extraction_prompt(transcript)
    return _run_json_chat(system_prompt, user_prompt, job_name="extract_structured_data")


def generate_narrative_report(data: dict, transcript: str) -> dict:
    system_prompt, user_prompt = build_narrative_prompt(data, transcript)
    return _run_json_chat(system_prompt, user_prompt, job_name="generate_narrative_report")


def _run_json_chat(system_prompt: str, user_prompt: str, job_name: str) -> dict:
    """Sends one system+user prompt pair to whichever LLM provider is configured,
    and parses the JSON reply into a Python dict."""
    provider = os.getenv("LLM_PROVIDER", "groq").lower()
    if provider == "groq":
        return _json_chat_groq(system_prompt, user_prompt, job_name)
    elif provider == "azure":
        return _json_chat_azure(system_prompt, user_prompt, job_name)
    raise ValueError(f"Unknown LLM_PROVIDER: {provider}")


def _json_chat_groq(system_prompt: str, user_prompt: str, job_name: str) -> dict:
    from groq import Groq

    api_key = os.getenv("GROQ_API_KEY")
    if not api_key or api_key == "your_groq_api_key_here":
        raise RuntimeError(
            "GROQ_API_KEY is missing. Get a free key at https://console.groq.com/keys "
            "and add it to your .env file."
        )
    client = Groq(api_key=api_key)
    model = os.getenv("GROQ_LLM_MODEL", "llama-3.3-70b-versatile")

    response = client.chat.completions.create(
        model=model,
        temperature=0,
        response_format={"type": "json_object"},   # forces a clean JSON reply, no extra chatter
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )

    # Groq's response includes token usage — log it so it shows up on the Admin/Ops page,
    # right next to the timing events already logged around this call in app.py.
    # Defensive: don't let a missing/changed `usage` shape ever break the actual request.
    usage = getattr(response, "usage", None)
    if usage is not None:
        try:
            log_event(
                "llm_token_usage", status="ok", job=job_name, model=model,
                prompt_tokens=usage.prompt_tokens,
                completion_tokens=usage.completion_tokens,
                total_tokens=usage.total_tokens,
            )
        except Exception:
            pass  # observability must never be the reason a real request fails

    content = response.choices[0].message.content
    try:
        return json.loads(content)
    except json.JSONDecodeError as e:
        raise ValueError(f"LLM did not return valid JSON:\n{content}") from e


def _json_chat_azure(system_prompt: str, user_prompt: str, job_name: str) -> dict:
    raise NotImplementedError(
        "Implement Azure OpenAI chat completion here (openai SDK, AzureOpenAI client) "
        "when you're ready to migrate. See README.md section 14. Azure OpenAI responses "
        "include the same kind of `usage` object -- log it the same way as the Groq version above."
    )
