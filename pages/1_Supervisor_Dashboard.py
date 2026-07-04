"""
pages/1_Supervisor_Dashboard.py
--------------------------------
A separate page (Streamlit auto-detects anything in pages/ and adds it to the
sidebar navigation) where a supervisor logs in independently from field staff
and browses every submitted report, filtered by date. Also lets them download
the running "Master Log" Excel (Operator | Date | No. of tables | Hadaq |
Defara | Hadhra) across many reports at once — the format they asked for,
with no photos, ready to open directly.
"""

import sys
import os
import datetime

import pandas as pd
import streamlit as st

# allow importing from the project root (utils/, providers/) when Streamlit
# runs this file directly as a sub-page
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.auth import require_login, logout_button
from utils.db import init_db, list_reports, list_full_reports, get_report
from utils.report import (
    build_summary_header_df,
    build_vessel_summary_df,
    build_table_details_df,
    build_master_log_df_from_records,
    export_master_log_excel,
)

st.set_page_config(page_title="Supervisor Dashboard", page_icon="📊", layout="wide")
init_db()

if not require_login(role="supervisor"):
    st.stop()
logout_button(role="supervisor")

st.title("📊 Supervisor Dashboard")
st.caption(
    "Review daily fisheries reports submitted by your team — filter by date, open any report, "
    "and download the Master Log or an individual report's Excel/PDF."
)

col1, col2 = st.columns(2)
with col1:
    date_from = st.date_input("From date", value=datetime.date.today() - datetime.timedelta(days=7))
with col2:
    date_to = st.date_input("To date", value=datetime.date.today())

if date_from > date_to:
    st.error("'From date' must be before 'To date'.")
    st.stop()

# ---------------------------------------------------------------------------
# Master Log — the exact "Operator | Date | No. of tables | Hadaq | Defara |
# Hadhra" format, rebuilt fresh from the database for the selected date range
# so it's always in sync with every report ever submitted (see README.md
# "Master Log: why rebuild instead of append?" for the reasoning).
# ---------------------------------------------------------------------------
st.subheader("📑 Master Log (all reports in range)")
full_records = list_full_reports(date_from=date_from.isoformat(), date_to=date_to.isoformat())
master_df = build_master_log_df_from_records(full_records)

if master_df.empty:
    st.info("No reports found in this date range.")
else:
    st.dataframe(master_df, use_container_width=True, hide_index=True)
    st.download_button(
        "⬇️ Download Master Log as Excel",
        data=export_master_log_excel(master_df),
        file_name=f"master_log_{date_from.isoformat()}_to_{date_to.isoformat()}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

st.divider()

# ---------------------------------------------------------------------------
# Individual report browser
# ---------------------------------------------------------------------------
st.subheader("🔍 Browse Individual Reports")

reports = list_reports(date_from=date_from.isoformat(), date_to=date_to.isoformat())

if not reports:
    st.info("No reports found in this date range.")
    st.stop()

df = pd.DataFrame(reports)
df_display = df.rename(columns={
    "id": "ID",
    "report_date": "Date",
    "submitted_at": "Submitted At",
    "submitted_by": "Submitted By",
    "supervisor_name": "Supervisor (spoken)",
    "total_tables": "Total Tables",
})
st.dataframe(df_display, use_container_width=True, hide_index=True)

selected_id = st.selectbox(
    "Select a report to view in full",
    options=df["id"].tolist(),
    format_func=lambda rid: f"#{rid} — {df.loc[df['id'] == rid, 'report_date'].values[0]} "
                             f"({df.loc[df['id'] == rid, 'submitted_by'].values[0]})",
)

if selected_id:
    record = get_report(selected_id)
    data = record["data"]
    narrative = record.get("narrative") or {}

    st.subheader(f"Report #{record['id']} — {record['report_date']}")
    st.dataframe(build_summary_header_df(data), use_container_width=True, hide_index=True)

    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Vessel-wise Count (boats, not tables)")
        st.dataframe(build_vessel_summary_df(data), use_container_width=True, hide_index=True)
    with c2:
        st.subheader("Table-wise Fish Details")
        st.dataframe(build_table_details_df(data), use_container_width=True, hide_index=True)

    if record["transcript"]:
        with st.expander("📝 Transcript"):
            st.write(record["transcript"])

    if narrative:
        with st.expander("📄 Narrative report (as sent in the PDF)"):
            st.markdown(f"**Purpose of the Visit**\n\n{narrative.get('purpose_of_visit','')}")
            st.markdown(f"**Observations**\n\n{narrative.get('observations','')}")
            st.markdown("**Summary**")
            for b in narrative.get("summary_bullets", []) or []:
                st.markdown(f"- {b}")
            st.markdown(f"**Remarks**\n\n{narrative.get('remarks','')}")

    if record["images"]:
        st.subheader(f"📷 Photo Evidence ({len(record['images'])})")
        cols = st.columns(min(4, len(record["images"])))
        for i, img_bytes in enumerate(record["images"]):
            cols[i % len(cols)].image(img_bytes, use_container_width=True)

    dl_col1, dl_col2 = st.columns(2)
    with dl_col1:
        if record["excel_blob"]:
            st.download_button(
                "⬇️ Download This Report as Excel",
                data=record["excel_blob"],
                file_name=f"fisheries_report_{record['report_date']}_{record['id']}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key=f"xl_{record['id']}",
            )
    with dl_col2:
        if record.get("pdf_blob"):
            st.download_button(
                "⬇️ Download This Report as PDF",
                data=record["pdf_blob"],
                file_name=f"fish_market_visit_report_{record['report_date']}_{record['id']}.pdf",
                mime="application/pdf",
                key=f"pdf_{record['id']}",
            )
        else:
            st.caption("No PDF available for this report (submitted before the PDF feature was added).")
