"""
security.py
------------
Three defensive layers around the two LLM calls in this app (transcript ->
structured JSON, structured JSON -> narrative prose):

1. sanitize_transcript()      — clean/limit whatever came out of speech-to-text
                                 before it ever reaches a prompt.
2. detect_prompt_injection()  — heuristic screen for text that looks like an
                                 attempt to manipulate the model's instructions,
                                 so a human can review before the pipeline
                                 continues (defense in depth, not a silent block).
3. validate_extracted_data()  — the LLM's JSON reply is still untrusted input.
                                 Even in JSON mode a model can return unexpected
                                 shapes/sizes; this enforces the real schema
                                 before anything downstream (Excel/PDF/DB/email)
                                 ever touches it.

None of this replaces good prompt design (see utils/parser.py) — it's the layer
that assumes the prompt design will occasionally be bypassed anyway, by an
adversarial speaker or a model mistake, and makes sure that doesn't propagate.
"""

import os
import re
import hmac
import unicodedata

MAX_TRANSCRIPT_LENGTH = int(os.getenv("MAX_TRANSCRIPT_LENGTH", "4000"))
MAX_STRING_FIELD_LENGTH = 500       # any single extracted string field (fish name, notes, ...)
MAX_LIST_ITEMS = 100                # any single extracted list (vessel_summary, table_details, ...)


def sanitize_transcript(text: str) -> str:
    """Strips control/invisible characters that don't belong in normal speech
    (a legitimate transcript is plain spoken words), collapses whitespace, and
    hard-truncates length. This runs BEFORE the text is ever put in a prompt,
    on every transcript, regardless of whether anything suspicious is found."""
    if not text:
        return ""
    # Drop control characters (category "C*") except normal whitespace, which strips
    # things like embedded escape sequences or non-printing Unicode tricks.
    cleaned = "".join(
        ch for ch in text
        if ch in ("\n", "\t", " ") or unicodedata.category(ch)[0] != "C"
    )
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:MAX_TRANSCRIPT_LENGTH]


# Heuristic, not exhaustive — catches common jailbreak/prompt-injection phrasing.
# Intentionally conservative: false positives just mean "ask a human to confirm",
# not "block outright", so a slightly-too-broad pattern here is a low-cost mistake.
_PROMPT_INJECTION_PATTERNS = [
    r"\bignore (all|any|the) (previous|prior|above)\b",
    r"\bdisregard (all|any|the) (previous|prior|above)\b",
    r"\byou are now\b",
    r"\bact as (a|an)\b",
    r"\bpretend (you are|to be)\b",
    r"\bsystem\s*prompt\b",
    r"\breveal (your|the) (instructions|system prompt|prompt)\b",
    r"\bnew instructions?\b",
    r"\boverride\b.*\binstructions?\b",
    r"\bjailbreak\b",
    r"\bdo anything now\b",
    r"\bdan mode\b",
    r"</?(system|assistant|user)>",     # fake chat-role tags
    r"```",                              # code fences have no business in a spoken transcript
]
_COMPILED_PATTERNS = [re.compile(p, re.IGNORECASE) for p in _PROMPT_INJECTION_PATTERNS]


def detect_prompt_injection(text: str) -> list:
    """Returns a list of matched pattern strings (empty list = nothing flagged).
    Called on the transcript AFTER sanitization, BEFORE it's sent to the
    extraction/narrative LLM calls. A non-empty result should pause the
    pipeline for human confirmation — see app.py's flagged-transcript flow."""
    if not text:
        return []
    matches = []
    for pattern in _COMPILED_PATTERNS:
        if pattern.search(text):
            matches.append(pattern.pattern)
    return matches


def _clip_str(value, max_len=MAX_STRING_FIELD_LENGTH) -> str:
    return str(value)[:max_len] if value is not None else value


def validate_extracted_data(data: dict) -> tuple:
    """
    Validates + sanitizes the LLM's structured-extraction output against the
    real schema (see utils/parser.py SCHEMA_EXAMPLE). Returns (is_valid, errors).
    On success, `data` is also cleaned in place (strings clipped, lists capped)
    so oversized/malformed content never reaches the DB, Excel, or PDF.
    This matters even with response_format={"type": "json_object"} (JSON mode
    only guarantees syntactically valid JSON, not a JSON object matching OUR
    schema, sane field types, or sane field sizes).
    """
    errors = []
    if not isinstance(data, dict):
        return False, ["Top-level response was not a JSON object."]

    if "total_tables_declared" in data and data["total_tables_declared"] is not None:
        if not isinstance(data["total_tables_declared"], (int, float)):
            errors.append("total_tables_declared must be a number or null.")
        elif not (0 <= data["total_tables_declared"] <= 100000):
            errors.append("total_tables_declared out of plausible range.")

    vessel_summary = data.get("vessel_summary")
    if vessel_summary is not None:
        if not isinstance(vessel_summary, list):
            errors.append("vessel_summary must be a list.")
        elif len(vessel_summary) > MAX_LIST_ITEMS:
            errors.append("vessel_summary has an implausible number of entries.")
        else:
            for item in vessel_summary:
                if not isinstance(item, dict) or "vessel_type" not in item or "vessel_count" not in item:
                    errors.append("Each vessel_summary entry needs vessel_type and vessel_count.")
                    break
                item["vessel_type"] = _clip_str(item.get("vessel_type"))
                if not isinstance(item.get("vessel_count"), (int, float)):
                    errors.append("vessel_count must be a number.")
                    break

    table_details = data.get("table_details")
    if table_details is not None:
        if not isinstance(table_details, list):
            errors.append("table_details must be a list.")
        elif len(table_details) > MAX_LIST_ITEMS:
            errors.append("table_details has an implausible number of entries.")
        else:
            for item in table_details:
                if not isinstance(item, dict) or "table_number" not in item:
                    errors.append("Each table_details entry needs a table_number.")
                    break
                fish_names = item.get("fish_names") or []
                if not isinstance(fish_names, list) or len(fish_names) > MAX_LIST_ITEMS:
                    errors.append("fish_names must be a reasonably-sized list.")
                    break
                item["fish_names"] = [_clip_str(f) for f in fish_names]

    for str_field in ("supervisor_name", "report_date", "notes"):
        if data.get(str_field) is not None:
            data[str_field] = _clip_str(data[str_field])

    return (len(errors) == 0), errors


def constant_time_compare(a: str, b: str) -> bool:
    """Timing-safe string comparison for password checks — a plain `==` leaks
    timing information proportional to how many leading characters match,
    which is a known (if minor, for a small internal tool) side channel."""
    return hmac.compare_digest((a or "").encode("utf-8"), (b or "").encode("utf-8"))
