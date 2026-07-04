"""
06_test_pdf_report.py
------------------------
Tests utils/pdf_report.py IN ISOLATION — pure PDF layout code, no AI calls.
Reads dev_output/structured.json + dev_output/narrative.json if present
(from scripts 03/04), else falls back to a built-in fake sample so this file
is fully testable on its own, right now.

Optional: put a few .jpg/.png files in sample_data/photos/ to see them appear
as numbered "Photo annexes" in the output PDF.

Run:
    python3 scripts/06_test_pdf_report.py
"""

import sys, os, json, glob
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.pdf_report import build_pdf
from utils.report import build_master_log_row

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "dev_output")
PHOTOS_DIR = os.path.join(os.path.dirname(__file__), "..", "sample_data", "photos")

FAKE_DATA = {
    "supervisor_name": "Mr. Marks", "report_date": None, "total_tables_declared": 25,
    "vessel_summary": [{"vessel_type": "hadaq", "vessel_count": 5}, {"vessel_type": "hadara", "vessel_count": 5}],
    "table_details": [{"table_number": 1, "fish_names": ["king fish"]}, {"table_number": 2, "fish_names": ["hammour"]}],
    "notes": "",
}
FAKE_NARRATIVE = {
    "purpose_of_visit": "The purpose of the visit was to observe fish landings at the auction market, "
                         "assess species composition, and record vessel types delivering fish.",
    "observations": "A total of 25 auction tables were observed. Ten fishing vessels landed catch, "
                     "comprising 5 Hadaq and 5 Hadhra units. Kingfish and hammour were named on the tables.",
    "summary_bullets": ["Auction tables observed: 25", "Fishing vessels landed: 10 (Hadaq: 5, Hadhra: 5)",
                         "Species named: kingfish, hammour"],
    "remarks": "This observation provides a snapshot of landings at the auction market on this date.",
}

if __name__ == "__main__":
    structured_path = os.path.join(OUTPUT_DIR, "structured.json")
    narrative_path = os.path.join(OUTPUT_DIR, "narrative.json")

    data = json.load(open(structured_path)) if os.path.exists(structured_path) else FAKE_DATA
    narrative = json.load(open(narrative_path)) if os.path.exists(narrative_path) else FAKE_NARRATIVE
    print(f"Using {'real' if os.path.exists(structured_path) else 'fake'} structured data "
          f"and {'real' if os.path.exists(narrative_path) else 'fake'} narrative.\n")

    images = []
    if os.path.isdir(PHOTOS_DIR):
        for path in sorted(glob.glob(os.path.join(PHOTOS_DIR, "*"))):
            with open(path, "rb") as f:
                images.append(f.read())
    print(f"Found {len(images)} photo(s) in {PHOTOS_DIR}")

    master_row = build_master_log_row(data, submitted_by="dev_test_user", submission_date="02.07.2026")
    print(f"Master log row used for 'General Overview': {master_row}\n")

    pdf_bytes = build_pdf(data, narrative, images, master_row, location="Fish Auction Market")

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out_path = os.path.join(OUTPUT_DIR, "visit_report.pdf")
    with open(out_path, "wb") as f:
        f.write(pdf_bytes)
    print(f"✅ Saved {out_path} ({len(pdf_bytes)} bytes) — open it and check it matches the requested template.")
