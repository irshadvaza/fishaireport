"""
app.py
------
Fisheries Market Voice Report App — staff-facing page
=======================================================
Captures a supervisor's spoken daily report (live mic + live camera only in
this phase — see ENABLE_FILE_UPLOADS), transcribes it, extracts structured
data with an LLM, writes an official narrative report, and:
  - shows a clean tabular report + photo evidence on screen
  - saves everything to the database (visible on the Supervisor Dashboard page)
  - builds a PDF "Visit Report" (narrative + photos) and automatically emails
    it to the supervisor
  - offers a per-report Excel download (tables only, no photos)

Security/observability layers (see utils/security.py, utils/observability.py):
  - the transcript is sanitized and screened for prompt-injection patterns
    before it's used in any LLM prompt; a flagged transcript pauses for human
    confirmation instead of being silently processed or silently blocked
  - the LLM's structured JSON reply is schema-validated before it's saved or
    put in a PDF/Excel/email
  - every key step (STT call, LLM calls, save, email) is timed and logged as
    a structured event, queryable on the Admin/Ops page
  - a simple per-user rate limit guards against runaway API cost from abuse

Run with:  streamlit run app.py
"""

import os
import hashlib
import datetime

import streamlit as st
from dotenv import load_dotenv

from providers.stt_provider import transcribe
from providers.llm_provider import extract_structured_data, generate_narrative_report
from utils.audio_utils import save_uploaded_bytes, extract_audio_from_video
from utils.auth import require_login, logout_button
from utils.db import init_db, save_report, count_recent_reports_by_user
from utils.email_utils import send_pdf_report_email
from utils.pdf_report import build_pdf
from utils.security import sanitize_transcript, detect_prompt_injection, validate_extracted_data
from utils.observability import log_event, timed_operation
from utils.report import (
    build_summary_header_df,
    build_vessel_summary_df,
    build_table_details_df,
    build_master_log_row,
    reconciliation_check,
    export_to_excel,
)

load_dotenv()

st.set_page_config(page_title="Fisheries Market Voice Report", page_icon="🐟", layout="wide")

init_db()

if not require_login(role="staff"):
    st.stop()

logout_button(role="staff")

staff_username = st.session_state.get("staff_username", "unknown")

# Phase 1 feature flag: file uploads (images/audio/video) are disabled by default.
# Only live camera capture + live mic recording are offered. Flip this back on in
# .env (ENABLE_FILE_UPLOADS=true) for a later phase — no code changes needed.
ENABLE_FILE_UPLOADS = os.getenv("ENABLE_FILE_UPLOADS", "false").lower() == "true"

MAX_REPORTS_PER_HOUR = int(os.getenv("MAX_REPORTS_PER_HOUR_PER_USER", "20"))

# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------
if "captured_images" not in st.session_state:
    st.session_state.captured_images = []          # list of raw image bytes
if "image_hashes" not in st.session_state:
    st.session_state.image_hashes = set()           # dedupe guard, see _add_image_if_new
if "transcript" not in st.session_state:
    st.session_state.transcript = ""
if "structured_data" not in st.session_state:
    st.session_state.structured_data = None
if "narrative" not in st.session_state:
    st.session_state.narrative = None
if "form_epoch" not in st.session_state:
    st.session_state.form_epoch = 0   # bumped on reset so widgets below get fresh keys and forget old values


def _add_image_if_new(img_bytes: bytes) -> bool:
    """
    Streamlit re-runs the whole script on every interaction, and both
    st.camera_input and st.file_uploader keep returning the SAME bytes on every
    re-run until the widget's value actually changes. Appending blindly would
    therefore add the same photo again and again. We dedupe by content hash so
    each distinct photo is added exactly once, no matter how many times the
    script re-runs, and taking/uploading a NEW photo always gets added.
    """
    h = hashlib.md5(img_bytes).hexdigest()
    if h in st.session_state.image_hashes:
        return False
    st.session_state.image_hashes.add(h)
    st.session_state.captured_images.append(img_bytes)
    return True


def reset_session():
    """Wipes the current report (images, transcript, extracted data, uploaded video/audio)
    so the user can start a brand new entry from a clean slate."""
    for key in [
        "captured_images", "image_hashes", "transcript", "structured_data", "narrative",
        "uploaded_video_bytes", "uploaded_video_suffix", "video_audio_path", "last_report_id",
        "auto_email_status", "pending_transcript", "injection_flag_count",
    ]:
        st.session_state.pop(key, None)
    st.session_state.captured_images = []
    st.session_state.image_hashes = set()
    st.session_state.transcript = ""
    st.session_state.structured_data = None
    st.session_state.narrative = None
    st.session_state.form_epoch += 1  # forces camera/file/audio widgets below to reset to empty


st.sidebar.button("🔄 Clear & Start New Entry", on_click=reset_session, use_container_width=True)


st.title("🐟 Fisheries Market — Voice Daily Report")
st.caption(
    "Speak your daily table/vessel report and get a clean, structured, tabular report and "
    "an official PDF automatically. Powered today by Groq (free) — swappable to Azure later."
)

# ---------------------------------------------------------------------------
# STEP 1 — Evidence capture: live camera (multi-snap). Uploads gated by ENABLE_FILE_UPLOADS.
# ---------------------------------------------------------------------------
st.header("1️⃣ Capture Market Evidence (optional)")

if ENABLE_FILE_UPLOADS:
    evidence_tabs = st.tabs(["📷 Live Camera Snapshot", "🖼️ Upload Image(s)", "🎞️ Upload Video"])

    with evidence_tabs[0]:
        st.write(
            "Take a photo, then click **Clear photo** and take another to add as many "
            "snapshots as you like — each one is added to the report below."
        )
        cam_image = st.camera_input("Take a snapshot of the tables", key=f"camera_{st.session_state.form_epoch}")
        if cam_image is not None:
            if _add_image_if_new(cam_image.getvalue()):
                st.success("Snapshot added. Click 'Clear photo' above to take another.")

    with evidence_tabs[1]:
        img_upload = st.file_uploader(
            "Upload one or more images", type=["jpg", "jpeg", "png"], accept_multiple_files=True,
            key=f"img_upload_{st.session_state.form_epoch}",
        )
        if img_upload:
            newly_added = sum(_add_image_if_new(f.getvalue()) for f in img_upload)
            if newly_added:
                st.success(f"{newly_added} new image(s) added.")

    with evidence_tabs[2]:
        video_upload = st.file_uploader(
            "Upload a recorded video (its audio can also be used for the report below)",
            type=["mp4", "mov", "m4v", "avi"],
            key=f"video_upload_{st.session_state.form_epoch}",
        )
        if video_upload is not None:
            st.video(video_upload)
            st.session_state["uploaded_video_bytes"] = video_upload.getvalue()
            st.session_state["uploaded_video_suffix"] = os.path.splitext(video_upload.name)[1] or ".mp4"
else:
    st.caption("📷 Live camera capture only in this phase — file uploads are disabled (`ENABLE_FILE_UPLOADS=false`).")
    st.write(
        "Take a photo, then click **Clear photo** and take another to add as many "
        "snapshots as you like — each one is added to the report below."
    )
    cam_image = st.camera_input("Take a snapshot of the tables", key=f"camera_{st.session_state.form_epoch}")
    if cam_image is not None:
        if _add_image_if_new(cam_image.getvalue()):
            st.success("Snapshot added. Click 'Clear photo' above to take another.")

if st.session_state.captured_images:
    st.write(f"**{len(st.session_state.captured_images)} image(s) attached to this report:**")
    cols = st.columns(min(4, len(st.session_state.captured_images)))
    for i, img_bytes in enumerate(st.session_state.captured_images):
        cols[i % len(cols)].image(img_bytes, use_container_width=True)
    if st.button("🗑️ Clear all attached images"):
        st.session_state.captured_images = []
        st.session_state.image_hashes = set()
        st.rerun()

st.divider()

# ---------------------------------------------------------------------------
# STEP 2 — Voice input: live mic. Uploads gated by ENABLE_FILE_UPLOADS.
# ---------------------------------------------------------------------------
st.header("2️⃣ Provide the Spoken Report")

audio_source_path = None

if ENABLE_FILE_UPLOADS:
    audio_tabs = st.tabs(["🎙️ Record Live", "📁 Upload Audio File", "🎞️ Use Audio From Uploaded Video"])

    with audio_tabs[0]:
        st.write("Click the mic, speak the report, then click stop.")
        live_audio = st.audio_input("Record your report", key=f"live_audio_{st.session_state.form_epoch}")
        if live_audio is not None:
            st.audio(live_audio)
            audio_source_path = save_uploaded_bytes(live_audio.getvalue(), ".wav")

    with audio_tabs[1]:
        audio_upload = st.file_uploader(
            "Upload a recorded audio file", type=["wav", "mp3", "m4a", "ogg", "flac"],
            key=f"audio_upload_{st.session_state.form_epoch}",
        )
        if audio_upload is not None:
            st.audio(audio_upload)
            suffix = os.path.splitext(audio_upload.name)[1] or ".wav"
            audio_source_path = save_uploaded_bytes(audio_upload.getvalue(), suffix)

    with audio_tabs[2]:
        if "uploaded_video_bytes" in st.session_state:
            st.write("A video was uploaded in Step 1 — its audio track will be extracted and transcribed.")
            if st.button("Use this video's audio for the report"):
                video_path = save_uploaded_bytes(
                    st.session_state["uploaded_video_bytes"], st.session_state["uploaded_video_suffix"]
                )
                with st.spinner("Extracting audio track from video..."):
                    extracted_path = extract_audio_from_video(video_path)
                st.session_state["video_audio_path"] = extracted_path
                st.success("Audio extracted. Click 'Generate Report' below.")
        else:
            st.info("Upload a video in Step 1 first.")
        if "video_audio_path" in st.session_state and audio_source_path is None:
            audio_source_path = st.session_state["video_audio_path"]
else:
    st.caption("🎙️ Live recording only in this phase — audio/video file uploads are disabled (`ENABLE_FILE_UPLOADS=false`).")
    st.write("Click the mic, speak the report, then click stop.")
    live_audio = st.audio_input("Record your report", key=f"live_audio_{st.session_state.form_epoch}")
    if live_audio is not None:
        st.audio(live_audio)
        audio_source_path = save_uploaded_bytes(live_audio.getvalue(), ".wav")

st.divider()

# ---------------------------------------------------------------------------
# STEP 3 — Process: transcribe + security screen + extract + validate + narrate
#          + build PDF/Excel + save + auto-email
# ---------------------------------------------------------------------------
st.header("3️⃣ Generate the Report")

recent_count = count_recent_reports_by_user(staff_username, minutes=60)
rate_limited = recent_count >= MAX_REPORTS_PER_HOUR
if rate_limited:
    st.error(
        f"You've submitted {recent_count} reports in the last hour, which hits this app's "
        f"abuse-prevention limit ({MAX_REPORTS_PER_HOUR}/hour). Please wait before submitting more, "
        "or ask an admin to raise MAX_REPORTS_PER_HOUR_PER_USER in .env."
    )

process_clicked = st.button("🚀 Generate Report", type="primary", disabled=(audio_source_path is None or rate_limited))
if audio_source_path is None:
    st.caption("Record audio above to enable this button.")


def _run_from_transcript(transcript: str):
    """Everything from LLM extraction onward — shared by the normal (unflagged) path
    and the 'proceed anyway after prompt-injection warning' confirmation path."""
    with st.spinner("Extracting structured data with LLM..."):
        with timed_operation("llm_extract", username=staff_username, role="staff"):
            data = extract_structured_data(transcript)

    is_valid, errors = validate_extracted_data(data)
    if not is_valid:
        log_event("llm_extract_invalid", status="error", username=staff_username, role="staff", errors=errors)
        st.error(
            "The AI's extracted data didn't pass validation, so nothing was saved. "
            "Please try again: " + "; ".join(errors)
        )
        return
    st.session_state.structured_data = data

    with st.spinner("Writing the official narrative report..."):
        with timed_operation("llm_narrative", username=staff_username, role="staff"):
            narrative = generate_narrative_report(data, transcript)
        st.session_state.narrative = narrative

    with st.spinner("Building Excel + PDF and saving..."):
        submission_date_str = datetime.date.today().strftime("%d.%m.%Y")
        master_row = build_master_log_row(data, submitted_by=staff_username, submission_date=submission_date_str)
        excel_bytes = export_to_excel(data)
        pdf_bytes = build_pdf(
            data, narrative, st.session_state.captured_images, master_row,
            location=os.getenv("MARKET_LOCATION", "Fish Auction Market"),
        )
        report_id = save_report(
            data=data, transcript=transcript, images=st.session_state.captured_images,
            excel_bytes=excel_bytes, submitted_by=staff_username, pdf_bytes=pdf_bytes, narrative=narrative,
        )
        st.session_state.last_report_id = report_id
        st.session_state["last_pdf_bytes"] = pdf_bytes
        st.session_state["last_excel_bytes"] = excel_bytes
        log_event("report_saved", username=staff_username, role="staff", report_id=report_id)

    auto_target = os.getenv("DEFAULT_SUPERVISOR_EMAIL", "")
    auto_enabled = os.getenv("AUTO_EMAIL_PDF", "true").lower() == "true"
    if auto_enabled and auto_target:
        try:
            with st.spinner(f"Emailing PDF report to {auto_target}..."):
                with timed_operation("email_send", username=staff_username, role="staff", to=auto_target):
                    send_pdf_report_email(
                        to_email=auto_target,
                        subject=f"Fish Auction Market Visit Report — {submission_date_str}",
                        body="Please find attached today's Fish Auction Market visit report.",
                        pdf_bytes=pdf_bytes,
                        pdf_filename=f"fish_market_visit_report_{submission_date_str}.pdf",
                    )
            st.session_state.auto_email_status = ("success", auto_target)
        except Exception as e:
            st.session_state.auto_email_status = ("error", str(e))
    else:
        st.session_state.auto_email_status = None

    st.session_state.pop("pending_transcript", None)
    st.session_state.pop("injection_flag_count", None)


if process_clicked and audio_source_path is not None:
    try:
        with st.spinner("Transcribing speech..."):
            with timed_operation("stt_transcribe", username=staff_username, role="staff"):
                raw_transcript = transcribe(audio_source_path)

        transcript = sanitize_transcript(raw_transcript)
        st.session_state.transcript = transcript

        flags = detect_prompt_injection(transcript)
        if flags:
            log_event(
                "prompt_injection_suspected", status="error", username=staff_username, role="staff",
                matched_pattern_count=len(flags), transcript_preview=transcript[:200],
            )
            st.session_state.pending_transcript = transcript
            st.session_state.injection_flag_count = len(flags)
        else:
            _run_from_transcript(transcript)

    except Exception as e:
        log_event("pipeline_error", status="error", username=staff_username, role="staff", error=str(e))
        st.error(f"Processing failed: {e}")

if st.session_state.get("pending_transcript"):
    st.warning(
        f"⚠️ This transcript contains phrasing ({st.session_state.injection_flag_count} pattern(s)) that's "
        "uncommon in a normal spoken report — this could be a false alarm, but it's also what a prompt-injection "
        "attempt can look like, so it's held here for a manual check instead of being processed automatically."
    )
    st.text_area("Transcript pending review", st.session_state.pending_transcript, height=100, disabled=True)
    confirm = st.checkbox("I have reviewed this transcript and confirm it's a legitimate report.")
    if st.button("✅ Proceed Anyway", disabled=not confirm):
        log_event("prompt_injection_override", username=staff_username, role="staff")
        _run_from_transcript(st.session_state.pending_transcript)

# ---------------------------------------------------------------------------
# STEP 4 — Consolidated report: transcript + tables + narrative + photo evidence together
# ---------------------------------------------------------------------------
if st.session_state.structured_data:
    data = st.session_state.structured_data
    narrative = st.session_state.narrative or {}
    st.header("4️⃣ Daily Report")

    if st.session_state.get("last_report_id"):
        st.success(
            f"✅ Saved as report #{st.session_state.last_report_id} — your supervisor can view it "
            "on the 📊 Supervisor Dashboard page (see sidebar) by selecting today's date."
        )

    email_status = st.session_state.get("auto_email_status")
    if email_status:
        status, detail = email_status
        if status == "success":
            st.success(f"📧 PDF report auto-emailed to {detail}.")
        else:
            st.warning(f"⚠️ Could not auto-email the PDF report: {detail}. You can retry below.")

    st.subheader("Report Summary")
    st.dataframe(build_summary_header_df(data), use_container_width=True, hide_index=True)

    warnings = reconciliation_check(data)
    for w in warnings:
        st.warning(w)

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Vessel-wise Count (boats, not tables)")
        st.dataframe(build_vessel_summary_df(data), use_container_width=True, hide_index=True)
    with col2:
        st.subheader("Table-wise Fish Details")
        st.dataframe(build_table_details_df(data), use_container_width=True, hide_index=True)

    if st.session_state.transcript:
        with st.expander("📝 Raw transcript", expanded=False):
            st.write(st.session_state.transcript)

    if narrative:
        with st.expander("📄 Narrative report preview (goes into the PDF)", expanded=False):
            st.markdown(f"**Purpose of the Visit**\n\n{narrative.get('purpose_of_visit','')}")
            st.markdown(f"**Observations**\n\n{narrative.get('observations','')}")
            st.markdown("**Summary**")
            for b in narrative.get("summary_bullets", []) or []:
                st.markdown(f"- {b}")
            st.markdown(f"**Remarks**\n\n{narrative.get('remarks','')}")
            st.caption(
                "⚠️ AI-generated from your spoken report — please review for accuracy before treating "
                "this as an official record, especially any biological or compliance claims."
            )

    if st.session_state.captured_images:
        st.subheader(f"📷 Photo Evidence ({len(st.session_state.captured_images)})")
        photo_cols = st.columns(min(4, len(st.session_state.captured_images)))
        for i, img_bytes in enumerate(st.session_state.captured_images):
            photo_cols[i % len(photo_cols)].image(img_bytes, use_container_width=True)
    else:
        st.caption("No photo evidence attached — add snapshots in Step 1 before generating the report.")

    dl_col1, dl_col2 = st.columns(2)
    with dl_col1:
        st.download_button(
            "⬇️ Download Excel (tables only)",
            data=st.session_state.get("last_excel_bytes", b""),
            file_name="fisheries_daily_report.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    with dl_col2:
        st.download_button(
            "⬇️ Download PDF (narrative + photos)",
            data=st.session_state.get("last_pdf_bytes", b""),
            file_name="fish_market_visit_report.pdf",
            mime="application/pdf",
        )

    st.subheader("📧 Resend the PDF Report")
    supervisor_email = st.text_input("Supervisor's email address", value=os.getenv("DEFAULT_SUPERVISOR_EMAIL", ""))
    if st.button("Send PDF Now"):
        if not supervisor_email:
            st.warning("Enter an email address first.")
        else:
            try:
                with timed_operation("email_send_manual", username=staff_username, role="staff", to=supervisor_email):
                    send_pdf_report_email(
                        to_email=supervisor_email,
                        subject=f"Fish Auction Market Visit Report — {datetime.date.today().strftime('%d.%m.%Y')}",
                        body="Please find attached the Fish Auction Market visit report.",
                        pdf_bytes=st.session_state.get("last_pdf_bytes", b""),
                        pdf_filename="fish_market_visit_report.pdf",
                    )
                st.success(f"Emailed to {supervisor_email}.")
            except Exception as e:
                st.error(str(e))

    with st.expander("🔧 Raw JSON (for debugging / integration)"):
        st.json(data)

st.divider()
st.caption(
    "Provider config: set STT_PROVIDER / LLM_PROVIDER to 'groq' (default, free) or 'azure' "
    "in your .env file. See README.md for the Azure migration steps."
)
