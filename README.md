# 🐟 Fisheries Market — Voice Daily Report App

A Streamlit app for fish-market field staff. They **speak or record** their daily
report — auction table count, fishing vessel counts by type, and fish species per table —
and the app turns it into:
- a clean on-screen **tabular report**
- a running **Master Log Excel** in the exact format the supervisor asked for
- an official **PDF "Visit Report"** with narrative sections and photo annexes, **emailed
  automatically** to the supervisor
- a searchable **Supervisor Dashboard** to browse everything by date

All powered today by a **free LLM (Groq)**, with a clear path to swap to **Azure** later
without rewriting the app.

Example of the kind of speech it understands:

> "Good morning Mr. Marks today 20 tables, 3 dafara, 4 hadara, 2 hadaq.
> table 1 king fish, table 2 shaari and safi, table 3 hammour"

---

## 1. The domain model (important — read this first)

Two numbers in the transcript are **completely independent** and must never be reconciled
against each other:

| | What it means | Example |
|---|---|---|
| **Tables** | Auction/display tables set up that day | "today 20 tables" → 20 |
| **Vessels** | Fishing boats, by type, that landed catch that day | "3 dafara, 4 hadara, 2 hadaq" → 3 boats of one type, 4 of another, 2 of a third |

`Dafara`, `Hadara`/`Hadhra`, and `Hadaq` are **vessel/boat types**, not gear assigned to a
table. A table can separately be assigned fish species ("table 1 king fish") — that's a third,
also-independent piece of data. The app extracts all three separately and never assumes one
should add up to another.

---

## 2. How it works (architecture)

```
 [Speak/Record] → [Speech-to-Text] → [Extract structured JSON] → [Write narrative prose] → ┐
   audio/video       Groq Whisper      Groq Llama 3.3, JSON        Groq Llama 3.3, JSON    │
                                        mode (tables, vessels,      mode (Purpose/           │
                                        fish — no invented facts)   Observations/Summary/     │
                                                                     Remarks — grounded only   │
                                                                     in the extracted data)    │
                                                                                                ▼
                              ┌─────────────────────────────────────────────────────────────────┐
                              │  Saved to SQLite (utils/db.py): data, transcript, narrative,      │
                              │  photos, per-report Excel, PDF                                    │
                              └─────────────────────────────────────────────────────────────────┘
                                         │                              │
                                         ▼                              ▼
                       Supervisor Dashboard page              PDF auto-emailed to supervisor
                       (browse by date, download Master        (utils/email_utils.py)
                       Log Excel or any report's PDF/Excel)
```

Both the STT and LLM steps are plain functions with a simple if/else dispatch inside
(`providers/stt_provider.py`, `providers/llm_provider.py`) — no classes — so that later you
can fill in the Azure branch and just flip an environment variable — `app.py` never has to
change.

### Project structure
```
fisheries_report_app/
├── app.py                          # Staff-facing page: record live, generate + auto-email report
├── pages/
│   ├── 1_Supervisor_Dashboard.py     # Supervisor-facing page: Master Log + browse by date
│   └── 2_Admin_Ops.py                # Admin-facing page: observability / monitoring / security log
├── requirements.txt
├── .env.example                       # copy to .env — Groq key, all 3 logins, SMTP, security, etc.
├── providers/
│   ├── stt_provider.py                # transcribe() -- Groq today, fill in the Azure branch later
│   └── llm_provider.py                # extract_structured_data()/generate_narrative_report() -- same idea
└── utils/
    ├── parser.py                      # prompts: 1) transcript→JSON extraction, 2) JSON→narrative prose
    ├── report.py                      # DataFrames, per-report Excel, Master Log Excel
    ├── pdf_report.py                  # builds the full PDF "Visit Report" (fpdf2)
    ├── audio_utils.py                 # save recordings / extract audio from video
    ├── auth.py                        # role-based login gate + lockout (staff/supervisor/admin)
    ├── security.py                    # input sanitization, prompt-injection screen, output validation
    ├── observability.py                # structured JSON logging + timed-operation instrumentation
    ├── db.py                          # SQLite persistence — reports, events, login attempts
    └── email_utils.py                 # SMTP sender — auto-emails the PDF, or resend on demand
```

See `CODE_WALKTHROUGH.md` for a full, beginner-friendly, file-by-file explanation of everything above.

---

## 3. Prerequisites

- Python 3.10+
- `ffmpeg` installed (needed to read uploaded video files / extract their audio):
  - macOS: `brew install ffmpeg`
  - Ubuntu/Debian: `sudo apt-get install ffmpeg`
  - Windows: download from https://ffmpeg.org and add to PATH
- A **free Groq API key**: https://console.groq.com/keys (no credit card needed)

---

## 4. Setup — step by step

```bash
cd fisheries_report_app
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# open .env and fill in: GROQ_API_KEY, STAFF_/SUPERVISOR_ passwords,
# and (optionally) SMTP_* + DEFAULT_SUPERVISOR_EMAIL for auto-email

streamlit run app.py
```
The app opens at `http://localhost:8501`. The Supervisor Dashboard is automatically listed
in the sidebar (Streamlit turns anything in `pages/` into a second page).

---

## 5. Login

Three separate logins, all read from `.env`:
```
STAFF_USERNAME=staff
STAFF_PASSWORD=change_this_password

SUPERVISOR_USERNAME=supervisor
SUPERVISOR_PASSWORD=change_this_too

ADMIN_USERNAME=admin
ADMIN_PASSWORD=change_this_admin_password
```
- **Staff** log into `app.py` to submit daily reports.
- **Supervisors** log into the Dashboard page to review them.
- **Admins** log into the Ops page to monitor system health and security events.

Change all three passwords before sharing the app. Passwords are compared with a timing-safe
comparison and accounts lock out temporarily after repeated failed attempts (see section 15).
This is still one shared username/password per role, suitable for an internal tool — swap in
Azure AD / SSO later if you need per-user accounts; only `utils/auth.py` needs to change.

---

## 6. Using the app (staff)

A **"🔄 Clear & Start New Entry"** button in the sidebar wipes photos/transcript/report and
resets every input widget, ready for the next submission.

> **Phase 1:** only live capture is offered — live camera snapshots and live mic recording.
> File uploads (images/audio/video) are disabled by default (`ENABLE_FILE_UPLOADS=false`).
> Flip that to `true` in `.env` for a later phase; no code changes needed, the upload tabs
> are already implemented and just hidden behind the flag.

1. **Step 1 – Evidence (optional)**: take live camera snapshots — click "Clear photo"
   between each to take more, each distinct one is added to the report.
2. **Step 2 – Voice**: record live through your mic.
3. **Step 3 – Generate Report**: this single click:
   - transcribes the speech, then sanitizes and screens the transcript for prompt-injection
     patterns (see section 15) — a flagged transcript pauses for your confirmation instead
     of being processed automatically
   - extracts structured data (tables, vessels, fish-per-table) — strictly no invented facts
     — and validates the AI's output against the real schema before trusting it
   - writes the narrative report sections (Purpose/Observations/Summary/Remarks), grounded
     only in the extracted data and transcript
   - builds the per-report Excel and the full PDF
   - **saves everything to the database**
   - **automatically emails the PDF to the supervisor**, if `DEFAULT_SUPERVISOR_EMAIL` and
     SMTP are configured (`AUTO_EMAIL_PDF=true`, the default)
   - a simple per-user rate limit (`MAX_REPORTS_PER_HOUR_PER_USER`, default 20) guards
     against runaway API cost if an account is compromised or misused
4. **Step 4 – Report**: view all the tables, transcript, narrative preview, and photos; download
   the Excel or PDF directly; or manually resend the PDF to a different address.

---

## 7. The Master Log (the Excel format the supervisor asked for)

On the **Supervisor Dashboard**, pick a date range and the app shows/downloads a single
Excel sheet in exactly this format, rebuilt fresh from every report submitted in that range:

| Operator | Date | No. of tables | Hadaq | Defara | Hadhra |
|---|---|---|---|---|---|
| User 1 | 07.01.2025 | 47 | 6 | 5 | |
| User 2 | 08.01.2025 | 51 | 8 | | 5 |

No photos in this file — it's meant to be opened and read directly. Spelling variants spoken
in the field (`hadara`/`hadhra`/`hadra`, `dafara`/`defara`) are automatically normalized to
the same column via `VESSEL_COLUMN_ALIASES` in `utils/report.py`; any genuinely new vessel
type not yet in that mapping lands in an extra "Other Vessel Types" column instead of being
silently dropped or crashing — add it to the alias map once you see it appear.

**Why rebuild the log instead of literally appending rows to a saved file?** Every report is
already stored in SQLite as structured data. Regenerating the log on demand from that data
(rather than mutating a shared `.xlsx` file in place) avoids file-corruption/locking issues
if two people download it at the same moment, and means the log is always 100% consistent
with the database — there's no separate file that could drift out of sync. The tradeoff is
it's generated per request rather than being a static file supervisors can point a network
drive at; if you need that instead, it's a small extension (see section 10).

---

## 8. The PDF Visit Report + auto-email

Every submission produces a PDF with this structure (matching the requested format):
**Title → Date/Location → Purpose of the Visit → General Overview (mini table, same columns
as the Master Log) → Observations → Summary (bullets) → Remarks → Photo Annexes**.

The **Purpose of the Visit** and **Remarks** sections use safe, generic professional
phrasing. The **Observations** and **Summary** sections are written by a second LLM call
(`generate_narrative_report` in `providers/llm_provider.py`) that is explicitly instructed,
in `utils/parser.py`, to **only state what's in the extracted data or transcript** — it must
not invent scientific species names, size measurements, or compliance conclusions. See
section 11 below for why this matters and what to do about it.

Configure email in `.env`:
```
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=you@gmail.com
SMTP_PASSWORD=your_gmail_app_password     # not your normal password — see below
SMTP_FROM=you@gmail.com
DEFAULT_SUPERVISOR_EMAIL=supervisor@example.com
AUTO_EMAIL_PDF=true                        # false = never auto-send, staff can still resend manually
```
For Gmail: turn on 2-Step Verification, then create an **App Password** at
https://myaccount.google.com/apppasswords. Any SMTP provider works the same way (Outlook,
SendGrid's free tier, Amazon SES, etc.) — just change `SMTP_HOST`/`SMTP_PORT`.

If SMTP isn't configured, auto-email is silently skipped (a warning is shown, not an error) —
the report still saves and the PDF is still downloadable/manually-emailable.

---

## 9. Persistence caveat

`reports.db` is a plain SQLite file on disk. Fine for local use or your own server. If you
deploy on a platform with an **ephemeral filesystem** (e.g. Streamlit Community Cloud's free
tier), it gets wiped on redeploy/restart. For production, point `DB_PATH` at a persistent
volume, or swap `utils/db.py`'s SQLite calls for Azure SQL / Postgres — keep the same function
signatures (`save_report`, `list_reports`, `list_full_reports`, `get_report`) and nothing else
needs to change.

---

## 10. Enterprise layers: observability, monitoring, security, prompt injection

Four layers were added on top of the core pipeline, all in `utils/security.py` and
`utils/observability.py`, wired into `app.py`:

### Observability & monitoring
Every key operation — STT call, both LLM calls, report save, email send, login attempt — is
timed and logged as one structured JSON event, via `observability.timed_operation(...)` /
`log_event(...)`. Each event is written to **both**:
- a rotating JSON-line log file (`logs/app.log`, `LOG_DIR`/`LOG_LEVEL` in `.env`)
- a SQLite table (`app_events`), queryable without grepping log files

The new **🛠️ Admin/Ops page** (`pages/2_Admin_Ops.py`, its own `ADMIN_USERNAME`/`ADMIN_PASSWORD`
login) reads that table and shows: a config/health snapshot (which provider, is the Groq key
set, is SMTP configured, is Phase 1 upload-lock on), 24-hour activity rollups (call counts,
average latency, error counts per event type), and a filterable recent-events log.

**This is the "roll your own" version appropriate for a small self-hosted app.** For a real
production deployment, the natural upgrade is to ship the same structured log lines to a real
backend — Azure Application Insights / OpenTelemetry, Datadog, ELK — instead of/alongside
SQLite. Because every event already goes through one function (`log_event`), that's a
one-file change in `utils/observability.py`, not a rewrite of `app.py`.

### Security
- **Timing-safe login comparison** (`security.constant_time_compare`, using `hmac.compare_digest`)
  instead of Python's `==`, which leaks timing information about how many leading characters matched.
- **Account lockout**: after `MAX_FAILED_LOGIN_ATTEMPTS` failures within `LOGIN_LOCKOUT_MINUTES`
  (per role+username, tracked in the `login_attempts` table), further attempts are rejected
  outright — even with the correct password — until the window passes. This defends against
  online password guessing, which a bare equality check does nothing to stop.
- **Rate limiting**: `MAX_REPORTS_PER_HOUR_PER_USER` caps how many reports one staff account
  can generate per hour — cheap insurance against a compromised or misbehaving account running
  up your Groq/SMTP usage.
- **Secrets stay in `.env`**, excluded from git (`.gitignore` covers `.env`, `*.db`, `logs/`).

### Prompt injection defense
The transcript is the one piece of this app's data that comes from an open microphone — text
an adversarial or careless speaker fully controls, and it flows straight into two LLM prompts
(`utils/parser.py`). Three layers guard that path, in order:

1. **`security.sanitize_transcript()`** — strips control/invisible Unicode characters and
   hard-truncates to `MAX_TRANSCRIPT_LENGTH`, on *every* transcript, before it's used anywhere.
2. **`security.detect_prompt_injection()`** — a heuristic regex screen for common jailbreak
   phrasing ("ignore previous instructions", "reveal your system prompt", fake `<system>` tags,
   code fences, etc.). This is deliberately **not a hard block**: a match pauses the pipeline
   in `app.py` and shows the transcript to the staff member with a confirmation checkbox
   ("I have reviewed this transcript...") before the LLM calls proceed. False positives just
   cost one extra click; a real injection attempt gets a human in the loop instead of quietly
   reaching the model — and either way, the flag is logged (`prompt_injection_suspected`) so
   it's visible on the Admin/Ops page.
3. **`security.validate_extracted_data()`** — even with the LLM's JSON mode and the strict
   system prompt (`utils/parser.py`), the reply is still untrusted input: it's schema-validated
   (right types, sane list/string sizes) and clipped before it's ever saved to the database or
   put in a PDF/Excel/email. A reply that fails validation is discarded with an error, not saved.

**What this doesn't cover, and what real "enterprise" hardening would add:** this heuristic
denylist catches known phrasing patterns, not novel ones — it's a speed bump, not a guarantee.
For higher assurance you'd add a dedicated classifier model or moderation API in front of the
transcript, rate-limit/alert on repeated flags from the same account, and treat the narrative
LLM call's output with the same suspicion as the transcript (e.g. checking it doesn't echo
system-prompt content back). The system prompt itself (in `utils/parser.py`) is also a layer
here — it explicitly tells the model its role and schema and to ignore instructions embedded
in the transcript — but a system prompt alone is not a security boundary, which is exactly why
these extra layers exist around it.

---

## 11. My recommendations / what I'd tighten up next

A few things worth knowing as the "expert" pass on this build:

1. **Have a human skim the PDF before it's treated as an official record**, at least at
   first. The narrative sections are grounded strictly in what was extracted/spoken (that's
   enforced in the prompt, not just a hope), but LLMs can still occasionally misphrase or
   drop a fact. The in-app narrative preview (Step 4, staff page) is there for exactly this —
   don't disable it.
2. **The example report you shared includes biological commentary** (fish size structure,
   stock-sustainability implications) **that a voice transcript of table/vessel counts simply
   can't support.** I deliberately did *not* have the AI fabricate that kind of finding. If
   your supervisor wants that content included, the honest way to get it is to give staff a
   way to *say it out loud* (e.g. "note: many small kingfish today") — I'd add an explicit
   "additional_notes" extraction field for exactly this, captured only when actually spoken,
   never invented. Happy to add that if useful.
3. **Master Log as a live shared file** (instead of "download fresh each time"): if your
   supervisor specifically wants a network-drive Excel file that updates itself, that's
   doable — `utils/report.py` would gain a function that opens the existing file with
   `openpyxl.load_workbook()` and appends one row per new submission. I chose the
   regenerate-on-demand approach here because it's more robust against concurrent access and
   partial writes; let me know if the live-file version is worth the tradeoff for your setup.
4. **Vessel type list will need occasional maintenance.** As new spellings or genuinely
   new vessel types show up in the field, add them to `VESSEL_COLUMN_GROUPS` in
   `utils/report.py` — there's also a safe fuzzy-match fallback for close spelling variants,
   but it's deliberately conservative (won't guess between two similar-looking vessel types),
   so genuinely new ones land in "Other Vessel Types" rather than silently vanishing OR being
   silently miscategorized — worth tidying up when you see one appear there.
5. **Single shared password per role** is fine for a small team but doesn't tell you *which*
   staff member submitted a report beyond the login username typed in. If that matters for
   accountability, move to per-user accounts (Azure AD/SSO) sooner rather than later.
6. **The Admin/Ops page is pull-based** (someone has to go look at it) — for real monitoring,
   the next step is push-based alerting: e.g. a scheduled check that emails/Slacks an admin
   when `prompt_injection_suspected` or `login_locked_out` events spike, rather than relying
   on someone remembering to check the dashboard.

---

## 12. Known simplifications (by design, for a "simple app")

- Single shared username/password per role (staff / supervisor), not per-user accounts.
- SQLite is a single file — great for one small team on one server, not built for many
  concurrent writers or multi-region deployments (see section 9).
- No automatic fish/vessel recognition from photos/video — they're stored as evidence only;
  computer-vision species detection would be a separate future module.
- The table-count-vs-tables-detailed reconciliation warning is a simple mismatch check, never
  an auto-correction — the app never silently "fixes" what staff said.
- The prompt-injection screen is a heuristic regex denylist, not a trained classifier — see
  section 10 for exactly what that does and doesn't catch.
- File uploads (images/audio/video) are fully implemented but disabled by default for Phase 1
  (`ENABLE_FILE_UPLOADS=false`) — flip the flag when you're ready, no code changes needed.

---

## 13. Why Groq for now

Groq offers a **free tier** covering everything this app needs:
- **Whisper (`whisper-large-v3-turbo`)** for fast, accurate speech-to-text
- **Llama 3.3 70B** with **JSON mode** for both structured extraction and narrative writing

This lets you prototype and validate the whole workflow with zero cost before committing to
Azure spend.

---

## 14. Migrating to Azure later

Because of the provider abstraction, migration is contained to two files:

1. **`providers/stt_provider.py`** — implement `_transcribe_azure()` using the
   Azure AI Speech SDK or the Speech "Fast Transcription" REST API.
2. **`providers/llm_provider.py`** — implement `_json_chat_azure()` using the `openai` SDK's
   `AzureOpenAI` client pointed at your Azure OpenAI deployment. Both `extract_structured_data()`
   and `generate_narrative_report()` already call this one shared function, so implementing it
   once covers both — reusing the exact same prompts from `utils/parser.py` and
   `response_format={"type": "json_object"}`.
3. In `.env`, set `STT_PROVIDER=azure`, `LLM_PROVIDER=azure`, and fill in the
   `AZURE_*` variables.

No changes are needed in `app.py`, the dashboard page, `utils/parser.py`, `utils/report.py`,
or `utils/pdf_report.py`.

Two more files worth swapping out at the same time, for the same "same interface, new
backend" reason (see section 10):
- **`utils/db.py`** — swap SQLite for Azure SQL/Postgres, keeping the same function signatures.
- **`utils/observability.py`** — point `log_event()` at Azure Application Insights /
  OpenTelemetry instead of (or in addition to) the local log file + SQLite `app_events` table.

---

## 15. Customizing for your market's vocabulary

If a vessel type or fish name is mis-heard or mis-extracted:
- Add more example terms to `SYSTEM_PROMPT` in `utils/parser.py`.
- Add spelling variants to `VESSEL_COLUMN_ALIASES` in `utils/report.py` so they land in the
  right Master Log column.
- For STT accuracy, Groq's transcription call supports a `prompt` parameter to bias
  recognition toward specific vocabulary — worth adding your gear/fish name list there too.
