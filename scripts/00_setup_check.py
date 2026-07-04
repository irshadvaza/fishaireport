"""
00_setup_check.py
------------------
Run this FIRST. Checks that your environment is ready before you test
anything else: is .env loaded, is the Groq key present, are the required
packages installed. Doesn't call any AI API — completely free/instant to run.

Run:
    cd fisheries_report_app
    python3 scripts/00_setup_check.py
"""

import os
import sys

# Make the project root importable when running scripts/*.py directly
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()

print("=== 1. .env file ===")
if os.path.exists(".env"):
    print("✅ .env found in current directory")
else:
    print("❌ No .env file found. Run this script from the project root "
          "(the folder containing app.py), and copy .env.example to .env first.")

print("\n=== 2. Required environment variables ===")
required = ["GROQ_API_KEY", "STAFF_USERNAME", "STAFF_PASSWORD", "SUPERVISOR_USERNAME", "SUPERVISOR_PASSWORD"]
for key in required:
    val = os.getenv(key)
    if not val or val.startswith("your_") or val.startswith("change_this"):
        print(f"⚠️  {key} is missing or still has its placeholder value")
    else:
        shown = val if len(val) < 6 else val[:3] + "..." + val[-2:]
        print(f"✅ {key} = {shown}")

print("\n=== 3. Required packages ===")
packages = ["streamlit", "groq", "pandas", "openpyxl", "moviepy", "PIL", "fpdf"]
for pkg in packages:
    try:
        __import__(pkg)
        print(f"✅ {pkg} importable")
    except ImportError as e:
        print(f"❌ {pkg} NOT importable: {e}  (run: pip install -r requirements.txt)")

print("\n=== 4. Project files reachable ===")
for path in ["utils/parser.py", "providers/stt_provider.py", "providers/llm_provider.py",
             "utils/report.py", "utils/pdf_report.py", "utils/db.py"]:
    print(("✅ " if os.path.exists(path) else "❌ ") + path)

print("\nIf everything above is ✅, move on to scripts/01_test_parser_prompts.py")
