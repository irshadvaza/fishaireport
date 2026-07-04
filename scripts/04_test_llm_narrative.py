"""
04_test_llm_narrative.py
--------------------------
Tests providers/llm_provider.py's generate_narrative_report() IN ISOLATION —
takes the structured JSON (+ transcript) and gets back the four prose
sections that go into the PDF.

NEEDS: a real GROQ_API_KEY in .env (this makes one real API call).

Reads dev_output/structured.json and dev_output/transcript.txt (written by
scripts 02 and 03).

Run:
    python3 scripts/04_test_llm_narrative.py
"""

import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()

from providers.llm_provider import get_llm_provider

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "dev_output")
STRUCTURED_PATH = os.path.join(OUTPUT_DIR, "structured.json")
TRANSCRIPT_PATH = os.path.join(OUTPUT_DIR, "transcript.txt")


def write_narrative(data: dict, transcript: str) -> dict:
    """This is literally the one function app.py calls right after extraction."""
    llm = get_llm_provider()
    return llm.generate_narrative_report(data, transcript)


if __name__ == "__main__":
    for p in (STRUCTURED_PATH, TRANSCRIPT_PATH):
        if not os.path.exists(p):
            print(f"❌ {p} not found. Run scripts 02 and 03 first.")
            sys.exit(1)

    with open(STRUCTURED_PATH) as f:
        data = json.load(f)
    with open(TRANSCRIPT_PATH) as f:
        transcript = f.read().strip()

    print("Calling the LLM to write the narrative report sections...")
    narrative = write_narrative(data, transcript)

    print("\n--- NARRATIVE ---\n")
    print(json.dumps(narrative, indent=2))

    out_path = os.path.join(OUTPUT_DIR, "narrative.json")
    with open(out_path, "w") as f:
        json.dump(narrative, f, indent=2)
    print(f"\n✅ Saved to {out_path} — script 06 (PDF) will read this file next.")
    print("\n⚠️ Read the 'observations' and 'remarks' text carefully — confirm the model "
          "didn't add any detail (species sizes, scientific names, claims) that wasn't "
          "actually in your transcript. This is a compliance-style document; see the "
          "'STRICT ACCURACY RULES' comment in utils/parser.py for why this matters.")
