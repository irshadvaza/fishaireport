"""
07_test_database.py
----------------------
Tests utils/db.py IN ISOLATION — pure SQLite code, no AI calls. Saves a
report (using whatever's in dev_output/ from earlier scripts, or a fake
sample), then reads it straight back to prove persistence actually works.

Uses a SEPARATE test database file (dev_output/test_reports.db) so this never
touches your real reports.db.

Run:
    python3 scripts/07_test_database.py
"""

import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "dev_output")
os.environ["DB_PATH"] = os.path.join(OUTPUT_DIR, "test_reports.db")  # must be set BEFORE importing utils.db

from utils.db import init_db, save_report, list_reports, list_full_reports, get_report
from utils.report import build_master_log_df_from_records, export_master_log_excel

FAKE_DATA = {
    "supervisor_name": "Mr. Marks", "report_date": None, "total_tables_declared": 20,
    "vessel_summary": [{"vessel_type": "dafara", "vessel_count": 3}, {"vessel_type": "hadara", "vessel_count": 4}],
    "table_details": [{"table_number": 1, "fish_names": ["king fish"]}],
    "notes": "",
}

if __name__ == "__main__":
    print(f"Using test database: {os.environ['DB_PATH']}")
    init_db()
    print("✅ init_db() ran (tables created if they didn't exist)")

    structured_path = os.path.join(OUTPUT_DIR, "structured.json")
    data = json.load(open(structured_path)) if os.path.exists(structured_path) else FAKE_DATA

    report_id = save_report(
        data=data,
        transcript="test transcript from script 07",
        images=[b"fake-image-bytes-for-testing"],
        excel_bytes=b"fake-excel-bytes-for-testing",
        submitted_by="dev_test_user",
        pdf_bytes=b"fake-pdf-bytes-for-testing",
        narrative={"purpose_of_visit": "test", "observations": "test", "summary_bullets": [], "remarks": "test"},
    )
    print(f"✅ save_report() -> new report id: {report_id}")

    print("\n--- list_reports() ---")
    for r in list_reports():
        print(r)

    print("\n--- get_report(report_id) ---")
    full = get_report(report_id)
    print({k: (v if k not in ("data_json", "excel_blob", "pdf_blob") else f"<{len(str(v))} bytes>") for k, v in full.items()})

    print("\n--- Master Log built from ALL stored reports ---")
    records = list_full_reports()
    df = build_master_log_df_from_records(records)
    print(df.to_string(index=False))

    excel_bytes = export_master_log_excel(df)
    out_path = os.path.join(OUTPUT_DIR, "master_log.xlsx")
    with open(out_path, "wb") as f:
        f.write(excel_bytes)
    print(f"\n✅ Saved {out_path} — this is what the Supervisor Dashboard's 'Download Master Log' button produces.")
