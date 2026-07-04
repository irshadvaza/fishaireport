"""
parser.py
---------
Holds the JSON schema + prompts for two separate LLM jobs:

1. EXTRACTION — turn the spoken transcript into structured data
   (build_extraction_prompt)
2. NARRATIVE  — turn that structured data (+ transcript) into the prose
   sections of an official visit report (build_narrative_prompt)

Domain notes (fisheries market / auction context) — CORRECTED based on
supervisor feedback:
- "vessel type" (hadara / dafara / hadaq / etc.) = the TYPE OF FISHING BOAT
  that landed catch that day. A count next to it is a COUNT OF VESSELS/BOATS,
  e.g. "3 dafara, 4 hadara, 2 hadaq" = 3 dafara boats, 4 hadara boats, 2 hadaq
  boats landed catch. This is a completely separate figure from...
- "table" = a numbered display/auction table where a batch of fish is laid
  out for sale, e.g. "today 20 tables" = 20 auction tables were set up.
  Vessel counts and table counts do NOT need to add up to each other — they
  measure two different things. Never reconcile them against one another.
- Each table is then assigned one or more fish species names
  ("table 1 king fish, table 2 shaari and safi, table 3 hammour").
- Fish/vessel names are often local Arabic-Gulf market terms (hadara, dafara,
  hadaq, hammour, shaari, safi, kingfish, etc.) — do not translate or
  "correct" them, keep them exactly as spoken/transcribed.
"""

import json

# ---------------------------------------------------------------------------
# 1. EXTRACTION prompt (transcript -> structured JSON)
# ---------------------------------------------------------------------------

SCHEMA_EXAMPLE = {
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

SYSTEM_PROMPT = """You are an expert data-extraction assistant working for a fish market / auction
operations team. You convert a spoken (speech-to-text transcribed) daily report from a market
supervisor into strict structured JSON.

Domain vocabulary you must recognize and NEVER auto-correct or translate:
- Vessel/boat type names (examples): hadara, dafara, hadaq, lampara, etc. A number spoken next
  to one of these is a COUNT OF VESSELS/BOATS of that type that landed catch that day — it is
  NOT a count of tables.
- Fish species names (examples): hammour, shaari, safi, kingfish/king fish, sheri, etc.
- "table" refers to a numbered auction/display table — a completely separate figure from vessel
  counts. Never assume vessel counts should sum to the table total, and never "fix" either
  number to match the other.

Extraction rules:
1. Extract the supervisor's name if greeted/addressed (e.g. "Good morning Mr. Marks" -> supervisor_name "Mr. Marks"). If not present, use null.
2. Extract report_date only if explicitly spoken; otherwise null.
3. Extract total_tables_declared: the total number of auction tables mentioned up front (e.g. "today 20 tables").
4. Extract vessel_summary: a list of {vessel_type, vessel_count} for every vessel/boat type and
   count spoken (e.g. "3 dafara, 4 hadara, 2 hadaq" -> three entries). This is a count of BOATS,
   not tables.
5. Extract table_details: a list of {table_number, fish_names[]} for every "table N <fish>" statement.
   A table can have multiple fish names (e.g. "table 2 shaari and safi").
6. If the count of table_details entries doesn't match total_tables_declared, do NOT fix it
   yourself — just extract what was said and put a short observation in "notes"
   (e.g. "only 3 of 20 tables were individually detailed"). Do NOT compare or reconcile
   vessel_summary against total_tables_declared — they are unrelated figures.
7. Keep all vessel and fish names in lowercase, exactly as spoken (minor stammer/filler word cleanup is fine).
8. Output ONLY a single valid JSON object. No markdown, no code fences, no commentary, matching this schema:

{
  "supervisor_name": string or null,
  "report_date": string or null,
  "total_tables_declared": integer or null,
  "vessel_summary": [ {"vessel_type": string, "vessel_count": integer} ],
  "table_details": [ {"table_number": integer, "fish_names": [string, ...]} ],
  "notes": string
}
"""

USER_PROMPT_TEMPLATE = """Here is an example input/output pair:

EXAMPLE TRANSCRIPT:
"Good morning Mr. Marks today 20 tables, 3 dafara, 4 hadara, 2 hadaq. table 1 king fish, table 2 shaari and safi, table 3 hammour"

EXAMPLE OUTPUT JSON:
{example_json}

Now extract the structured JSON for this NEW transcript. Output JSON only:

TRANSCRIPT:
\"\"\"{transcript}\"\"\"
"""


def build_extraction_prompt(transcript: str):
    example_json = json.dumps(SCHEMA_EXAMPLE, indent=2)
    user_prompt = USER_PROMPT_TEMPLATE.format(example_json=example_json, transcript=transcript.strip())
    return SYSTEM_PROMPT, user_prompt


# ---------------------------------------------------------------------------
# 2. NARRATIVE prompt (structured data + transcript -> official report prose)
# ---------------------------------------------------------------------------
#
# IMPORTANT SAFETY NOTE: this is a compliance-adjacent document (fisheries
# market inspection). We deliberately instruct the model to NEVER invent
# biological claims, scientific species names, or observations that were not
# actually said — a real-world extraction/narrative pipeline like this must
# not fabricate specifics such as "small-sized fish were observed" unless the
# transcript actually said so. Getting this wrong could mislead a real
# regulatory or business decision. Always have a human review the generated
# PDF before it's treated as an official record — see README.md.

NARRATIVE_SYSTEM_PROMPT = """You are an experienced fisheries field officer writing the prose sections of
an official "Fish Auction Market Visit Report", based on a colleague's spoken field notes.

STRICT ACCURACY RULES (do not break these, even to make the report sound more complete):
- Only state facts that are directly supported by the structured data or the transcript given to you.
- NEVER invent scientific/biological species names (Latin binomials), size measurements, compliance
  conclusions, or observations (e.g. "small-sized fish were observed") that were not explicitly present
  in the transcript. If the transcript only names a fish informally (e.g. "kingfish"), use that name as-is
  — do not add a scientific name unless the transcript stated one.
- If information for a section genuinely isn't available, write one brief, neutral, honest sentence
  saying so (e.g. "No additional observations were recorded during this visit.") instead of fabricating
  detail to fill the section.
- Tone: formal, factual, third-person, suitable for an internal fisheries market inspection report.

Given the JSON data and transcript, write these four sections and return them as JSON:
{
  "purpose_of_visit": "1-2 sentences describing the general purpose of a routine fish market visit (observing landings, species composition, vessel types) — this can be a standard professional phrasing, since it describes the visit's purpose rather than specific findings.",
  "observations": "1-3 factual sentences/paragraphs describing what was recorded: number of tables, vessel types and counts, and fish species named on the tables. Stick strictly to the data given.",
  "summary_bullets": ["short bullet points restating the key figures: table count, vessel counts by type, species named"],
  "remarks": "1-2 closing sentences noting this is a snapshot of the visit and, only if relevant vessel/table data was recorded, that continued routine monitoring is useful — do not add unsupported compliance claims."
}
Output ONLY the JSON object, no markdown, no commentary.
"""

NARRATIVE_USER_TEMPLATE = """Structured data extracted from the supervisor's spoken report:
{data_json}

Original transcript:
\"\"\"{transcript}\"\"\"

Write the four report sections now, grounded strictly in the above. Output JSON only.
"""


def build_narrative_prompt(data: dict, transcript: str):
    data_json = json.dumps(data, indent=2)
    user_prompt = NARRATIVE_USER_TEMPLATE.format(data_json=data_json, transcript=(transcript or "").strip())
    return NARRATIVE_SYSTEM_PROMPT, user_prompt
