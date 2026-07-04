"""
pages/2_Admin_Ops.py
---------------------
Observability/monitoring dashboard for admins: recent events (STT/LLM calls,
report saves, email sends, login attempts, security flags), rollup stats
(volumes, average latency, error rates), and a quick config/health snapshot.

This reads from utils/db.py's app_events + login_attempts tables, which are
populated by utils/observability.log_event() calls sprinkled through app.py.
For a real production deployment, forward the same structured events to a
proper observability backend (Azure Application Insights, Datadog, ELK, etc.)
instead of/alongside SQLite — see README.md "Observability" section.
"""

import sys
import os
import json
import datetime

import pandas as pd
import streamlit as st

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.auth import require_login, logout_button
from utils.db import init_db, get_recent_events, get_event_stats

st.set_page_config(page_title="Admin / Ops", page_icon="🛠️", layout="wide")
init_db()

if not require_login(role="admin"):
    st.stop()
logout_button(role="admin")

st.title("🛠️ Admin / Ops Dashboard")
st.caption("Observability, monitoring, and security event log for this app.")

# ---------------------------------------------------------------------------
# Config / health snapshot — quick visual check that the important switches
# are set the way you think they are, without needing shell access to .env.
# ---------------------------------------------------------------------------
st.subheader("⚙️ Configuration Snapshot")
cfg_cols = st.columns(4)
cfg_cols[0].metric("STT Provider", os.getenv("STT_PROVIDER", "groq"))
cfg_cols[1].metric("LLM Provider", os.getenv("LLM_PROVIDER", "groq"))
cfg_cols[2].metric("File Uploads", "Enabled" if os.getenv("ENABLE_FILE_UPLOADS", "false").lower() == "true" else "Disabled (Phase 1)")
cfg_cols[3].metric("Auto-Email PDF", "On" if os.getenv("AUTO_EMAIL_PDF", "true").lower() == "true" else "Off")

cfg_cols2 = st.columns(4)
cfg_cols2[0].metric("Groq API Key Set", "Yes" if os.getenv("GROQ_API_KEY", "").strip() not in ("", "your_groq_api_key_here") else "⚠️ No")
cfg_cols2[1].metric("SMTP Configured", "Yes" if os.getenv("SMTP_HOST", "").strip() else "⚠️ No")
cfg_cols2[2].metric("Max Reports/hr/user", os.getenv("MAX_REPORTS_PER_HOUR_PER_USER", "20"))
cfg_cols2[3].metric("Login Lockout", f"{os.getenv('MAX_FAILED_LOGIN_ATTEMPTS','5')} tries / {os.getenv('LOGIN_LOCKOUT_MINUTES','15')}min")

st.divider()

# ---------------------------------------------------------------------------
# Token usage — summed from the llm_token_usage events (see providers/llm_provider.py).
# get_event_stats() only counts/averages duration_ms per event_type, so token totals are
# summed here directly from the raw events instead of a SQL aggregate.
# ---------------------------------------------------------------------------
st.subheader("🔢 LLM Token Usage (last 24 hours)")
token_events = get_recent_events(limit=1000, event_type="llm_token_usage")
if not token_events:
    st.info("No LLM calls recorded yet.")
else:
    cutoff = (datetime.datetime.now() - datetime.timedelta(hours=24)).isoformat(timespec="seconds")
    rows = []
    for e in token_events:
        if e["timestamp"] < cutoff:
            continue
        meta = json.loads(e["meta_json"]) if e.get("meta_json") else {}
        rows.append({
            "Job": meta.get("job"), "Model": meta.get("model"),
            "Prompt Tokens": meta.get("prompt_tokens"),
            "Completion Tokens": meta.get("completion_tokens"),
            "Total Tokens": meta.get("total_tokens"),
        })
    if not rows:
        st.info("No LLM calls in the last 24 hours.")
    else:
        tdf = pd.DataFrame(rows)
        totals = tdf.groupby("Job")[["Prompt Tokens", "Completion Tokens", "Total Tokens"]].sum().reset_index()
        st.dataframe(totals, use_container_width=True, hide_index=True)
        t1, t2 = st.columns(2)
        t1.metric("Total calls (24h)", len(tdf))
        t2.metric("Total tokens (24h)", int(tdf["Total Tokens"].sum()))
        st.caption(
            "Cross-check against Groq's own console (console.groq.com → Dashboard → Usage) "
            "for billing — this table is per-request detail specific to this app, not a billing source of truth."
        )

st.divider()

# ---------------------------------------------------------------------------
# Rollup stats
# ---------------------------------------------------------------------------
st.subheader("📊 Activity (last 24 hours)")
stats = get_event_stats(since_minutes=1440)
if not stats:
    st.info("No events recorded yet in the last 24 hours.")
else:
    df = pd.DataFrame(stats)
    df["avg_ms"] = df["avg_ms"].round(1)
    df = df.rename(columns={"event_type": "Event Type", "status": "Status", "n": "Count", "avg_ms": "Avg Duration (ms)"})
    st.dataframe(df, use_container_width=True, hide_index=True)

    total_errors = int(df.loc[df["Status"] == "error", "Count"].sum())
    total_events = int(df["Count"].sum())
    m1, m2, m3 = st.columns(3)
    m1.metric("Total events (24h)", total_events)
    m2.metric("Errors (24h)", total_errors)
    security_flags = int(df.loc[df["Event Type"] == "prompt_injection_suspected", "Count"].sum()) if "Event Type" in df else 0
    m3.metric("Prompt-injection flags (24h)", security_flags)

st.divider()

# ---------------------------------------------------------------------------
# Recent event log — filterable
# ---------------------------------------------------------------------------
st.subheader("🔍 Recent Events")
f1, f2, f3 = st.columns(3)
with f1:
    event_type_filter = st.text_input("Filter by event_type (exact match, optional)")
with f2:
    status_filter = st.selectbox("Status", ["(any)", "ok", "error"])
with f3:
    limit = st.number_input("Max rows", min_value=10, max_value=1000, value=100, step=10)

events = get_recent_events(
    limit=int(limit),
    event_type=event_type_filter or None,
    status=None if status_filter == "(any)" else status_filter,
)

if not events:
    st.info("No matching events.")
else:
    edf = pd.DataFrame(events)
    edf = edf.rename(columns={
        "timestamp": "Time", "event_type": "Event", "status": "Status",
        "username": "User", "role": "Role", "duration_ms": "Duration (ms)", "meta_json": "Details",
    })
    st.dataframe(edf, use_container_width=True, hide_index=True)

    with st.expander("🔎 Inspect one event's full details"):
        ids = [e["id"] for e in events]
        selected = st.selectbox("Event ID", ids)
        chosen = next(e for e in events if e["id"] == selected)
        meta = json.loads(chosen["meta_json"]) if chosen.get("meta_json") else {}
        st.json({**{k: v for k, v in chosen.items() if k != "meta_json"}, "meta": meta})

st.caption(
    "Security note: failed logins and prompt-injection flags are logged here specifically so "
    "repeated attempts are visible — check this page periodically, especially the 'error' status "
    "rows for event_type 'login_attempt' and 'prompt_injection_suspected'."
)
