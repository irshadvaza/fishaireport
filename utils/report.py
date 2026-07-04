"""
report.py
---------
Turns the LLM's structured JSON into:
  - pandas DataFrames for on-screen display
  - a per-report Excel export (tables only — no photos; photos now live in the PDF, see pdf_report.py)
  - the "Master Log" — one row per submitted report, in the exact columns the
    supervisor asked for, aggregated across many reports for a running operational log
"""

import io
import difflib
import datetime
import pandas as pd


def build_summary_header_df(data: dict) -> pd.DataFrame:
    return pd.DataFrame([{
        "Supervisor": data.get("supervisor_name") or "-",
        "Report Date": data.get("report_date") or "-",
        "Total Tables Declared": data.get("total_tables_declared") if data.get("total_tables_declared") is not None else "-",
        "Notes": data.get("notes") or "-",
    }])


def build_vessel_summary_df(data: dict) -> pd.DataFrame:
    """Vessel/boat types and how many of each landed catch — independent of table count."""
    rows = data.get("vessel_summary", []) or []
    df = pd.DataFrame(rows)
    if df.empty:
        df = pd.DataFrame(columns=["vessel_type", "vessel_count"])
    df = df.rename(columns={"vessel_type": "Vessel / Boat Type", "vessel_count": "Number of Vessels"})
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


def reconciliation_check(data: dict) -> list:
    """
    Returns human-readable warning strings, empty if all good.
    NOTE: vessel counts are intentionally NOT compared against total_tables_declared —
    they measure two different things (boats landing catch vs. auction tables set up)
    and are not expected to add up to each other.
    """
    warnings = []
    total_declared = data.get("total_tables_declared")
    detailed_tables = len(data.get("table_details") or [])

    if total_declared is not None and detailed_tables and detailed_tables != total_declared:
        warnings.append(
            f"⚠️ Only {detailed_tables} table(s) had fish details spoken, but total tables declared was {total_declared}."
        )
    return warnings


def _autosize_columns(worksheet, df: pd.DataFrame):
    """openpyxl doesn't autosize columns to fit content by default — without this, a long
    value (e.g. in 'Other Vessel Types') just gets visually truncated by Excel's default
    column width even though the data itself is fine. Widths are capped so one very long
    cell can't blow out the whole sheet."""
    for i, col in enumerate(df.columns, start=1):
        max_len = max([len(str(col))] + [len(str(v)) for v in df[col].tolist()])
        worksheet.column_dimensions[worksheet.cell(row=1, column=i).column_letter].width = min(max_len + 2, 45)


def export_to_excel(data: dict) -> bytes:
    """Per-report Excel with 3 sheets: Summary, Vessel Summary, Table Details. No photos —
    photo evidence now lives in the PDF report (see pdf_report.build_pdf)."""
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        for sheet_name, df in [
            ("Summary", build_summary_header_df(data)),
            ("Vessel Summary", build_vessel_summary_df(data)),
            ("Table Details", build_table_details_df(data)),
        ]:
            df.to_excel(writer, sheet_name=sheet_name, index=False)
            _autosize_columns(writer.sheets[sheet_name], df)
    buffer.seek(0)
    return buffer.read()


# ---------------------------------------------------------------------------
# Master Log — the running operational sheet the supervisor asked for:
# Operator | Date | No. of tables | Hadaq | Defara | Hadhra
# ---------------------------------------------------------------------------

# Maps whatever the LLM extracted as vessel_type (lowercase, as spoken) to the
# supervisor's exact requested column spelling. Add more variants here as they show up in
# the field — this explicit list is checked before any fuzzy fallback, so it's always the
# safest and most predictable way to fix a new mis-transcription.
VESSEL_COLUMN_GROUPS = {
    "Hadaq":  ["hadaq", "hadhaq", "hadak", "haddaq", "hadagh", "hadaqh", "hadag"],
    "Defara": ["dafara", "defara", "daffara", "dafarah", "defarah", "daphara"],
    "Hadhra": ["hadara", "hadhra", "hadra", "hadhara", "haddara"],
}
MASTER_LOG_VESSEL_COLUMNS = list(VESSEL_COLUMN_GROUPS.keys())  # fixed order, matches the requested template

# Fuzzy fallback only kicks in for a spelling variant that isn't in the list above yet.
# It requires BOTH a high absolute similarity AND a clear lead over the next-best group,
# because these words are all short and share a "had-" prefix — a plain "closest match"
# (no margin check) was found to misfile e.g. "hadag" into Hadhra instead of Hadaq. When the
# match is ambiguous, it falls back to "Other Vessel Types" instead of guessing wrong.
_FUZZY_MATCH_CUTOFF = 0.72
_FUZZY_MATCH_MARGIN = 0.06


def _canonical_vessel_column(vtype_raw: str) -> str | None:
    key = (vtype_raw or "").strip().lower()
    if not key:
        return None
    for canon, aliases in VESSEL_COLUMN_GROUPS.items():
        if key in aliases:
            return canon
    scores = {
        canon: max(difflib.SequenceMatcher(None, key, alias).ratio() for alias in aliases)
        for canon, aliases in VESSEL_COLUMN_GROUPS.items()
    }
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    best_canon, best_score = ranked[0]
    runner_up_score = ranked[1][1] if len(ranked) > 1 else 0.0
    if best_score >= _FUZZY_MATCH_CUTOFF and (best_score - runner_up_score) >= _FUZZY_MATCH_MARGIN:
        return best_canon
    return None


def build_master_log_row(data: dict, submitted_by: str, submission_date: str) -> dict:
    """
    Builds exactly one row for the master log, in the requested column format.
    `submission_date` should already be formatted as DD.MM.YYYY.
    Any vessel type that doesn't match a known alias is preserved in an
    "Other Vessel Types" column instead of being silently dropped.
    """
    row = {
        "Operator": submitted_by or data.get("supervisor_name") or "-",
        "Date": submission_date,
        "No. of tables": data.get("total_tables_declared") if data.get("total_tables_declared") is not None else "",
    }
    counts = {col: "" for col in MASTER_LOG_VESSEL_COLUMNS}
    unmapped = []
    for v in data.get("vessel_summary", []) or []:
        vtype_raw = (v.get("vessel_type") or "").strip().lower()
        col = _canonical_vessel_column(vtype_raw)
        count = v.get("vessel_count") or 0
        if col:
            counts[col] = (counts[col] or 0) + count
        else:
            unmapped.append(f"{v.get('vessel_type')}: {count}")
    row.update(counts)
    if unmapped:
        row["Other Vessel Types"] = "; ".join(unmapped)
    return row


def build_master_log_df(rows: list) -> pd.DataFrame:
    base_cols = ["Operator", "Date", "No. of tables"] + MASTER_LOG_VESSEL_COLUMNS
    if not rows:
        return pd.DataFrame(columns=base_cols)
    df = pd.DataFrame(rows)
    extra_cols = [c for c in df.columns if c not in base_cols]
    ordered_cols = [c for c in base_cols if c in df.columns] + extra_cols
    return df[ordered_cols]


def build_master_log_df_from_records(records: list) -> pd.DataFrame:
    """
    Builds the master log across many stored reports (as returned by
    db.list_full_reports). Converts each report's stored YYYY-MM-DD
    report_date into the requested DD.MM.YYYY display format.
    """
    rows = []
    for rec in records:
        try:
            d = datetime.date.fromisoformat(rec["report_date"])
            date_str = d.strftime("%d.%m.%Y")
        except (ValueError, TypeError):
            date_str = rec.get("report_date") or "-"
        rows.append(build_master_log_row(rec["data"], submitted_by=rec.get("submitted_by"), submission_date=date_str))
    return build_master_log_df(rows)


def export_master_log_excel(df: pd.DataFrame) -> bytes:
    """Single-sheet Excel, exactly the format the supervisor asked for — no photos."""
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Master Log", index=False)
        _autosize_columns(writer.sheets["Master Log"], df)
    buffer.seek(0)
    return buffer.read()
