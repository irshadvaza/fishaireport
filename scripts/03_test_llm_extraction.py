"""
03_test_llm_extraction.py
---------------------------
Tests providers/llm_provider.py's extract_structured_data() IN ISOLATION —
takes text in, gets structured JSON back. No audio, no UI.

NEEDS: a real GROQ_API_KEY in .env (this makes one real API call).

By default reads dev_output/transcript.txt (written by script 02). You can
also just hardcode a transcript string below to test without re-running STT.

Run:
    python3 scripts/03_test_llm_extraction.py
"""

import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()

from providers.llm_provider import get_llm_provider

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "dev_output")
TRANSCRIPT_PATH = os.path.join(OUTPUT_DIR, "transcript.txt")

# Fallback if you haven't run script 02 yet / don't have a mic handy —
# uncomment and edit this instead of reading transcript.txt:
# HARDCODED_TRANSCRIPT = "Good morning Mr. Marks today 20 tables, 3 dafara, 4 hadara, 2 hadaq. table 1 king fish, table 2 shaari and safi, table 3 hammour"


def extract(transcript: str) -> dict:
    """This is literally the one function app.py calls right after transcribing."""
    llm = get_llm_provider()
    return llm.extract_structured_data(transcript)


if __name__ == "__main__":
    if os.path.exists(TRANSCRIPT_PATH):
        with open(TRANSCRIPT_PATH) as f:
            transcript = f.read().strip()
        print(f"Using transcript from {TRANSCRIPT_PATH}:\n{transcript}\n")
    else:
        print(f"❌ {TRANSCRIPT_PATH} not found. Either run script 02 first, or edit this "
              "file to set a HARDCODED_TRANSCRIPT and use that instead.")
        sys.exit(1)

    print("Calling the LLM to extract structured data...")
    data = extract(transcript)

    print("\n--- STRUCTURED DATA ---\n")
    print(json.dumps(data, indent=2))

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out_path = os.path.join(OUTPUT_DIR, "structured.json")
    with open(out_path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"\n✅ Saved to {out_path} — script 04 and 05 will read this file next.")

    # A quick sanity print, so you immediately see if vessel counts vs table
    # count were extracted as two SEPARATE things (the fix from this session):
    print(f"\nTotal tables declared: {data.get('total_tables_declared')}")
    print(f"Vessel summary (boats, independent of tables): {data.get('vessel_summary')}")
