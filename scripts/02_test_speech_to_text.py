"""
02_test_speech_to_text.py
---------------------------
Tests providers/stt_provider.py IN ISOLATION — this is the same shape as the
"speech() -> save to folder -> speech_to_text(path)" pattern you described:
we point at an audio FILE PATH on disk and get text back. No Streamlit, no
UI, just a function call.

NEEDS: a real GROQ_API_KEY in .env (this makes one real API call).

Before running this, put a short audio file (wav/mp3/m4a) at:
    sample_data/sample_report.wav
The easiest way to get one: record yourself on your phone saying something
like the SAMPLE_TRANSCRIPT text in scripts/01_test_parser_prompts.py, then
copy the file into sample_data/ under that name (or pass a path as an
argument, see below).

Run:
    python3 scripts/02_test_speech_to_text.py
    python3 scripts/02_test_speech_to_text.py path/to/your_audio.mp3
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()

from providers.stt_provider import get_stt_provider

DEFAULT_AUDIO_PATH = os.path.join(os.path.dirname(__file__), "..", "sample_data", "sample_report.wav")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "dev_output")


def speech_to_text(audio_path: str) -> str:
    """This is literally the one function app.py calls in Step 3 — same call,
    same provider, just invoked directly instead of from a button click."""
    stt = get_stt_provider()
    return stt.transcribe(audio_path)


if __name__ == "__main__":
    audio_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_AUDIO_PATH

    if not os.path.exists(audio_path):
        print(f"❌ No audio file found at: {audio_path}")
        print("   Record a short clip and save it there (see the docstring above), "
              "or pass a path: python3 scripts/02_test_speech_to_text.py your_file.wav")
        sys.exit(1)

    print(f"Transcribing: {audio_path}")
    transcript = speech_to_text(audio_path)

    print("\n--- TRANSCRIPT ---\n")
    print(transcript)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out_path = os.path.join(OUTPUT_DIR, "transcript.txt")
    with open(out_path, "w") as f:
        f.write(transcript)
    print(f"\n✅ Saved to {out_path} — script 03 will read this file next.")
