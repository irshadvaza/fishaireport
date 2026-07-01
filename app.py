"""
app.py
------
Fisheries Market Voice Report App
==================================
Captures a supervisor's spoken daily report (live mic, or uploaded audio/video),
transcribes it, extracts structured data with an LLM, and renders a clean
tabular report together with photo evidence of the market tables.

Run with:  streamlit run app.py
"""

import os
import hashlib

import streamlit as st
from dotenv import load_dotenv

from providers.stt_provider import get_stt_provider
from providers.llm_provider import get_llm_provider
from utils.audio_utils import save_uploaded_bytes, extract_audio_from_video
from utils.auth import require_login, logout_button
from utils.report import (
    build_summary_header_df,
    build_gear_summary_df,
    build_table_details_df,
    reconciliation_check,
    export_to_excel,
)

load_dotenv()

st.set_page_config(page_title="Fisheries Market Voice Report", page_icon="🐟", layout="wide")

if not require_login():
    st.stop()

logout_button()

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
        "captured_images", "image_hashes", "transcript", "structured_data",
        "uploaded_video_bytes", "uploaded_video_suffix", "video_audio_path",
    ]:
        st.session_state.pop(key, None)
    st.session_state.captured_images = []
    st.session_state.image_hashes = set()
    st.session_state.transcript = ""
    st.session_state.structured_data = None
    st.session_state.form_epoch += 1  # forces camera/file/audio widgets below to reset to empty


st.sidebar.button("🔄 Clear & Start New Entry", on_click=reset_session, use_container_width=True)


st.title("🐟 Fisheries Market — Voice Daily Report")
st.caption(
    "Speak (or upload) the daily gear/table report and get a clean, structured, "
    "tabular report automatically. Powered today by Groq (free) — swappable to Azure later."
)

# ---------------------------------------------------------------------------
# STEP 1 — Evidence capture: live camera (multi-snap) / uploaded photos / uploaded video
# ---------------------------------------------------------------------------
st.header("1️⃣ Capture / Upload Market Evidence (optional)")

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
# STEP 2 — Voice input: live mic / uploaded audio / audio-from-uploaded-video
# ---------------------------------------------------------------------------
st.header("2️⃣ Provide the Spoken Report")

audio_tabs = st.tabs(["🎙️ Record Live", "📁 Upload Audio File", "🎞️ Use Audio From Uploaded Video"])

audio_source_path = None

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

st.divider()

# ---------------------------------------------------------------------------
# STEP 3 — Process: transcribe + extract + report
# ---------------------------------------------------------------------------
st.header("3️⃣ Generate the Report")

process_clicked = st.button("🚀 Generate Report", type="primary", disabled=(audio_source_path is None))
if audio_source_path is None:
    st.caption("Record or upload audio above to enable this button.")

if process_clicked and audio_source_path is not None:
    try:
        with st.spinner("Transcribing speech..."):
            stt = get_stt_provider()
            transcript = stt.transcribe(audio_source_path)
            st.session_state.transcript = transcript

        with st.spinner("Extracting structured data with LLM..."):
            llm = get_llm_provider()
            data = llm.extract_structured_data(transcript)
            st.session_state.structured_data = data

    except Exception as e:
        st.error(f"Processing failed: {e}")

# ---------------------------------------------------------------------------
# STEP 4 — Consolidated report: transcript + tables + photo evidence together
# ---------------------------------------------------------------------------
if st.session_state.structured_data:
    data = st.session_state.structured_data
    st.header("4️⃣ Daily Report")

    st.subheader("Report Summary")
    st.dataframe(build_summary_header_df(data), use_container_width=True, hide_index=True)

    warnings = reconciliation_check(data)
    for w in warnings:
        st.warning(w)

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Gear-wise Table Count")
        st.dataframe(build_gear_summary_df(data), use_container_width=True, hide_index=True)
    with col2:
        st.subheader("Table-wise Fish Details")
        st.dataframe(build_table_details_df(data), use_container_width=True, hide_index=True)

    if st.session_state.transcript:
        with st.expander("📝 Raw transcript", expanded=False):
            st.write(st.session_state.transcript)

    if st.session_state.captured_images:
        st.subheader(f"📷 Photo Evidence ({len(st.session_state.captured_images)})")
        photo_cols = st.columns(min(4, len(st.session_state.captured_images)))
        for i, img_bytes in enumerate(st.session_state.captured_images):
            photo_cols[i % len(photo_cols)].image(img_bytes, use_container_width=True)
    else:
        st.caption("No photo evidence attached — add snapshots in Step 1 before generating the report.")

    excel_bytes = export_to_excel(data, images=st.session_state.captured_images)
    st.download_button(
        "⬇️ Download Full Report as Excel (tables + photos)",
        data=excel_bytes,
        file_name="fisheries_daily_report.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    with st.expander("🔧 Raw JSON (for debugging / integration)"):
        st.json(data)

st.divider()
st.caption(
    "Provider config: set STT_PROVIDER / LLM_PROVIDER to 'groq' (default, free) or 'azure' "
    "in your .env file. See README.md for the Azure migration steps."
)
