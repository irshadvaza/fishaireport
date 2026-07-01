"""
parser.py
---------
Holds the JSON schema definition and the prompt engineering used to convert
a raw fish-market supervisor transcript into structured data.

Domain notes (fisheries market / auction context):
- "gear" = fishing gear / net type used to catch the fish, e.g. hadara, dafara, hadaq,
  lampara, etc. These are counted at the start of the report
  ("total 20 tables, hadara 10, dafara 4, hadaq 6" -> gear-wise table counts).
- "table" = a numbered display/auction table in the market where a batch of fish is laid
  out. Each table is then assigned one or more fish species names
  ("table 1 king fish, table 2 shaari and safi, table 3 hammour").
- Fish/gear names are often local Arabic-Gulf market terms (hadara, dafara, hadaq,
  hammour, shaari, safi, kingfish, etc.) — do not translate or "correct" them,
  keep them exactly as spoken/transcribed.
"""

SCHEMA_EXAMPLE = {
    "supervisor_name": "Mr. Mark",
    "report_date": None,
    "total_tables_declared": 20,
    "gear_summary": [
        {"gear_name": "hadara", "table_count": 10},
        {"gear_name": "dafara", "table_count": 4},
        {"gear_name": "hadaq", "table_count": 6},
    ],
    "table_details": [
        {"table_number": 1, "fish_names": ["king fish"]},
        {"table_number": 2, "fish_names": ["shaari", "safi"]},
        {"table_number": 3, "fish_names": ["hammour"]},
    ],
    "notes": "",
}

SYSTEM_PROMPT = """You are an expert data-extraction assistant working for a fish market / auction
operations team. You convert a spoken (speech-to-text transcribed) daily report from a market
supervisor into strict structured JSON.

Domain vocabulary you must recognize and NEVER auto-correct or translate:
- Gear/net type names (examples): hadara, dafara, hadaq, lampara, etc.
- Fish species names (examples): hammour, shaari, safi, kingfish/king fish, sheri, etc.
- "table" refers to a numbered auction/display table.

Extraction rules:
1. Extract the supervisor's name if greeted/addressed (e.g. "Good morning Mr. Mark" -> supervisor_name "Mr. Mark"). If not present, use null.
2. Extract report_date only if explicitly spoken; otherwise null.
3. Extract total_tables_declared: the total number of tables mentioned up front (e.g. "today total 20 tables").
4. Extract gear_summary: a list of {gear_name, table_count} for every gear name and count spoken
   in the opening summary (e.g. "hadara 10, dafara 4 and hadaq 6").
5. Extract table_details: a list of {table_number, fish_names[]} for every "table N <fish>" statement.
   A table can have multiple fish names (e.g. "table 2 shaari and safi").
6. If the sum of gear_summary counts or the count of table_details entries does not match
   total_tables_declared, do NOT fix the numbers yourself — just extract what was said and put a short
   observation in "notes" (e.g. "gear counts sum to 20 but only 3 tables were individually detailed").
7. Keep all gear and fish names in lowercase, exactly as spoken (minor stammer/filler word cleanup is fine).
8. Output ONLY a single valid JSON object. No markdown, no code fences, no commentary, matching this schema:

{
  "supervisor_name": string or null,
  "report_date": string or null,
  "total_tables_declared": integer or null,
  "gear_summary": [ {"gear_name": string, "table_count": integer} ],
  "table_details": [ {"table_number": integer, "fish_names": [string, ...]} ],
  "notes": string
}
"""

USER_PROMPT_TEMPLATE = """Here is an example input/output pair:

EXAMPLE TRANSCRIPT:
"Good morning Mr. Mark today total 20 tables hadara 10, dafara 4 and hadaq 6. table 1 king fish, table 2 shaari and safi, table 3 hammour"

EXAMPLE OUTPUT JSON:
{example_json}

Now extract the structured JSON for this NEW transcript. Output JSON only:

TRANSCRIPT:
\"\"\"{transcript}\"\"\"
"""


def build_extraction_prompt(transcript: str):
    import json
    example_json = json.dumps(SCHEMA_EXAMPLE, indent=2)
    user_prompt = USER_PROMPT_TEMPLATE.format(example_json=example_json, transcript=transcript.strip())
    return SYSTEM_PROMPT, user_prompt
