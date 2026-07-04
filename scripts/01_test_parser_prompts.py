"""
01_test_parser_prompts.py
--------------------------
Tests utils/parser.py IN ISOLATION — no AI API calls, no audio, nothing
external. This file just builds strings, so it's the safest, fastest, free
place to start: you can read exactly what gets sent to the AI later.

Run:
    python3 scripts/01_test_parser_prompts.py
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.parser import build_extraction_prompt, build_narrative_prompt

SAMPLE_TRANSCRIPT = (
    "Good morning Mr. Marks today 20 tables, 3 dafara, 4 hadara, 2 hadaq. "
    "table 1 king fish, table 2 shaari and safi, table 3 hammour"
)

print("############################################")
print("# 1) EXTRACTION PROMPT (transcript -> JSON) #")
print("############################################\n")
system_prompt, user_prompt = build_extraction_prompt(SAMPLE_TRANSCRIPT)
print("--- SYSTEM PROMPT ---\n")
print(system_prompt)
print("\n--- USER PROMPT ---\n")
print(user_prompt)

print("\n\n###################################################")
print("# 2) NARRATIVE PROMPT (JSON + transcript -> prose) #")
print("###################################################\n")

# A hand-typed example of what step 1 would eventually produce — this lets us
# test the narrative prompt without needing the LLM to have run yet.
FAKE_STRUCTURED_DATA = {
    "supervisor_name": "Mr. Marks",
    "report_date": None,
    "total_tables_declared": 20,
    "vessel_summary": [
        {"vessel_type": "dafara", "vessel_count": 3},
        {"vessel_type": "hadara", "vessel_count": 4},
        {"vessel_type": "hadaq", "vessel_count": 2},
    ],
    "table_details": [
        {"table_number": 1, "fish_names": ["king fish"]},
        {"table_number": 2, "fish_names": ["shaari", "safi"]},
        {"table_number": 3, "fish_names": ["hammour"]},
    ],
    "notes": "",
}
system_prompt2, user_prompt2 = build_narrative_prompt(FAKE_STRUCTURED_DATA, SAMPLE_TRANSCRIPT)
print("--- SYSTEM PROMPT ---\n")
print(system_prompt2)
print("\n--- USER PROMPT ---\n")
print(user_prompt2)

print("\n\n✅ If both prompts above look sensible, move on to scripts/02_test_speech_to_text.py")
