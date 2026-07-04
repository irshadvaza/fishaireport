"""
pdf_report.py
-------------
Builds the full "Fish Auction Market Visit Report" PDF: fixed headings +
LLM-written narrative sections + the master-log-style summary table + numbered
photo annexes. Uses fpdf2 (pure Python, no external binaries needed).
"""

import io
import tempfile

from fpdf import FPDF
from fpdf.fonts import FontFace
from PIL import Image as PILImage


class _ReportPDF(FPDF):
    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(120, 120, 120)
        self.cell(0, 10, f"Page {self.page_no()}", align="C")


def _section_title(pdf: FPDF, text: str):
    pdf.ln(4)
    pdf.set_font("Helvetica", "B", 13)
    pdf.set_text_color(20, 20, 20)
    pdf.cell(0, 8, text, new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 11)


def _paragraph(pdf: FPDF, text: str):
    pdf.multi_cell(0, 6, text or "-")
    pdf.ln(1)


def _bullets(pdf: FPDF, items: list):
    if not items:
        pdf.multi_cell(0, 6, "-")
        return
    for item in items:
        pdf.set_x(pdf.l_margin + 4)
        pdf.multi_cell(0, 6, f"-  {item}")
    pdf.ln(1)


def _mini_table(pdf: FPDF, row: dict):
    """Renders the single-row 'General Overview' table (same columns as the master log).
    Uses fpdf2's Table API (not raw .cell() calls) specifically because it auto-wraps long
    cell text and grows the row height to fit — raw fixed-width .cell() calls do NOT wrap,
    so a long "Other Vessel Types" value would just print past the cell/table border."""
    headers = list(row.keys())
    values = [str(row[h]) if row[h] not in (None, "") else "-" for h in headers]

    # Give any long-text column (e.g. "Other Vessel Types") more relative width so it
    # wraps onto 2-3 lines instead of being squeezed as narrow as the short numeric columns.
    col_weights = [3 if len(str(v)) > 12 else 1 for v in values]

    pdf.set_font("Helvetica", "", 9)
    with pdf.table(
        col_widths=col_weights,
        text_align="CENTER",
        line_height=5,
        headings_style=FontFace(emphasis="BOLD", fill_color=(230, 230, 230)),
    ) as table:
        table.row(headers)
        table.row(values)
    pdf.ln(2)


def build_pdf(data: dict, narrative: dict, images: list, master_row: dict, location: str = "Fish Auction Market") -> bytes:
    """
    data:        the structured extraction JSON (supervisor_name, total_tables_declared, ...)
    narrative:   dict with purpose_of_visit / observations / summary_bullets / remarks
                 (from GroqLLMProvider.generate_narrative_report)
    images:      list of raw photo bytes, shown as numbered "Photo annexes"
    master_row:  dict from utils.report.build_master_log_row — reused as the
                 "General Overview" mini-table so the PDF and the Excel log always agree
    """
    narrative = narrative or {}
    pdf = _ReportPDF(format="A4", unit="mm")
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 18)
    pdf.multi_cell(0, 10, "Fish Auction Market Visit Report", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    pdf.set_font("Helvetica", "", 11)
    report_date = master_row.get("Date") or data.get("report_date") or "-"
    pdf.cell(0, 7, f"Date: {report_date}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 7, f"Location: {location}", new_x="LMARGIN", new_y="NEXT")

    _section_title(pdf, "Purpose of the Visit")
    _paragraph(pdf, narrative.get("purpose_of_visit"))

    _section_title(pdf, "General Overview")
    _mini_table(pdf, master_row)

    _section_title(pdf, "Observations")
    _paragraph(pdf, narrative.get("observations"))

    _section_title(pdf, "Summary")
    _bullets(pdf, narrative.get("summary_bullets") or [])

    _section_title(pdf, "Remarks")
    _paragraph(pdf, narrative.get("remarks"))

    if images:
        _section_title(pdf, "Photo Annexes")
        for i, img_bytes in enumerate(images, start=1):
            try:
                pil_img = PILImage.open(io.BytesIO(img_bytes)).convert("RGB")
            except Exception:
                continue  # skip anything that isn't a readable image

            tmp_path = tempfile.mktemp(suffix=".jpg")
            pil_img.save(tmp_path, format="JPEG", quality=85)

            # keep each photo + its caption together, start a new page if it won't fit
            if pdf.get_y() > pdf.h - 100:
                pdf.add_page()
            pdf.set_font("Helvetica", "B", 10)
            pdf.cell(0, 7, f"Photo {i}", new_x="LMARGIN", new_y="NEXT")
            pdf.image(tmp_path, w=110)
            pdf.ln(4)

    return bytes(pdf.output())
