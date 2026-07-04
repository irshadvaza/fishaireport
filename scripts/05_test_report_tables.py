"""
05_test_report_tables.py
--------------------------
Tests utils/report.py IN ISOLATION — pure data transformation, no AI calls,
no audio. Turns dev_output/structured.json into the same pandas tables and
Excel file app.py shows on screen / offers for download.

If you haven't run scripts 02-03 yet, this uses a built-in FAKE_DATA sample
so you can test this file completely on its own, right now.

Run:
    python3 scripts/05_test_report_tables.py
"""

import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.report import (
    build_summary_header_df, build_vessel_summary_df, build_table_details_df,
    build_master_log_row, reconciliation_check, export_to_excel,
)

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "dev_output")
STRUCTURED_PATH = os.path.join(OUTPUT_DIR, "structured.json")

FAKE_DATA = {
    "supervisor_name": "Mr. Marks", "report_date": None, "total_tables_declared": 20,
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

if __name__ == "__main__":
    if os.path.exists(STRUCTURED_PATH):
        with open(STRUCTURED_PATH) as f:
            data = json.load(f)
        print(f"Using real data from {STRUCTURED_PATH}\n")
    else:
        data = FAKE_DATA
        print("No dev_output/structured.json found yet — using a built-in FAKE_DATA sample.\n")

    print("--- Summary ---")
    print(build_summary_header_df(data).to_string(index=False))

    print("\n--- Vessel Summary (boats, NOT tables) ---")
    print(build_vessel_summary_df(data).to_string(index=False))

    print("\n--- Table Details ---")
    print(build_table_details_df(data).to_string(index=False))

    print("\n--- Reconciliation warnings ---")
    warnings = reconciliation_check(data)
    print(warnings if warnings else "(none)")

    print("\n--- Master Log row (the format the supervisor asked for) ---")
    row = build_master_log_row(data, submitted_by="dev_test_user", submission_date="02.07.2026")
    print(row)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    excel_bytes = export_to_excel(data)
    out_path = os.path.join(OUTPUT_DIR, "report.xlsx")
    with open(out_path, "wb") as f:
        f.write(excel_bytes)
    print(f"\n✅ Saved {out_path} — open it to check the 3 sheets (Summary / Vessel Summary / Table Details).")
