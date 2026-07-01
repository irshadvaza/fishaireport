"""
report.py
---------
Turns the LLM's structured JSON into pandas DataFrames for on-screen display,
plus an Excel export with one sheet per table (and a sheet with photo evidence).
"""

import io
import tempfile
import pandas as pd


def build_gear_summary_df(data: dict) -> pd.DataFrame:
    rows = data.get("gear_summary", []) or []
    df = pd.DataFrame(rows)
    if df.empty:
        df = pd.DataFrame(columns=["gear_name", "table_count"])
    df = df.rename(columns={"gear_name": "Gear / Net Name", "table_count": "Tables Count"})
    return df


def build_table_details_df(data: dict) -> pd.DataFrame:
    rows = data.get("table_details", []) or []
    flat = []
    for r in rows:
        flat.append({
            "Table No.": r.get("table_number"),
            "Fish Name(s)": ", ".join(r.get("fish_names", []) or []),
        })
    df = pd.DataFrame(flat)
    if df.empty:
        df = pd.DataFrame(columns=["Table No.", "Fish Name(s)"])
    else:
        df = df.sort_values("Table No.").reset_index(drop=True)
    return df


def build_summary_header_df(data: dict) -> pd.DataFrame:
    return pd.DataFrame([{
        "Supervisor": data.get("supervisor_name") or "-",
        "Report Date": data.get("report_date") or "-",
        "Total Tables Declared": data.get("total_tables_declared") if data.get("total_tables_declared") is not None else "-",
        "Notes": data.get("notes") or "-",
    }])


def reconciliation_check(data: dict) -> list:
    """Returns a list of human-readable warning strings, empty if all good."""
    warnings = []
    total_declared = data.get("total_tables_declared")
    gear_sum = sum((g.get("table_count") or 0) for g in (data.get("gear_summary") or []))
    detailed_tables = len(data.get("table_details") or [])

    if total_declared is not None and gear_sum and total_declared != gear_sum:
        warnings.append(
            f"⚠️ Gear summary counts add up to {gear_sum}, but total tables declared was {total_declared}."
        )
    if total_declared is not None and detailed_tables and detailed_tables != total_declared:
        warnings.append(
            f"⚠️ Only {detailed_tables} table(s) had fish details spoken, but total tables declared was {total_declared}."
        )
    return warnings


def export_to_excel(data: dict, images: list | None = None) -> bytes:
    """
    Returns Excel file bytes with sheets: Summary, Gear Summary, Table Details,
    and (if any photos were captured) a Photo Evidence sheet with the images
    embedded directly in the sheet.
    """
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        build_summary_header_df(data).to_excel(writer, sheet_name="Summary", index=False)
        build_gear_summary_df(data).to_excel(writer, sheet_name="Gear Summary", index=False)
        build_table_details_df(data).to_excel(writer, sheet_name="Table Details", index=False)

        if images:
            # Create an empty "Photo Evidence" sheet, then drop each image into it.
            pd.DataFrame({"Photo Evidence": [f"Photo {i+1}" for i in range(len(images))]}).to_excel(
                writer, sheet_name="Photo Evidence", index=False
            )
            worksheet = writer.sheets["Photo Evidence"]
            _embed_images(worksheet, images)

    buffer.seek(0)
    return buffer.read()


def _embed_images(worksheet, images: list, max_width_px: int = 320, row_height_px: int = 240):
    """Embeds each image (raw bytes, any common format) into the given openpyxl worksheet."""
    from openpyxl.drawing.image import Image as XLImage
    from PIL import Image as PILImage

    row_cursor = 2  # leave row 1 for the header written by pandas
    for idx, img_bytes in enumerate(images):
        try:
            pil_img = PILImage.open(io.BytesIO(img_bytes)).convert("RGB")
        except Exception:
            continue  # skip anything that isn't a readable image

        # scale down large photos so the workbook doesn't balloon in size
        w, h = pil_img.size
        if w > max_width_px:
            scale = max_width_px / w
            pil_img = pil_img.resize((max_width_px, int(h * scale)))

        tmp_path = tempfile.mktemp(suffix=".png")
        pil_img.save(tmp_path, format="PNG")

        xl_img = XLImage(tmp_path)
        anchor_cell = f"B{row_cursor}"
        worksheet.add_image(xl_img, anchor_cell)
        worksheet.row_dimensions[row_cursor].height = row_height_px * 0.75  # px -> points approx
        row_cursor += max(15, int(row_height_px / 15))  # leave enough rows before next image
