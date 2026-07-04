# 🐟 Fisheries Market Voice Report App — Full Code Walkthrough

This document explains **every file, in the order you should read them**, plus the
**end-to-end workflow** of what happens when staff, a supervisor, and an admin each use the
app. It's written so a beginner can follow it, but goes deep enough to be a real technical
reference — including the enterprise layers (observability, security, prompt-injection
defense) added on top of the core AI pipeline.

---

## 1. The big picture (read this first)

Three **pages** (three separate logins), sharing one **pipeline** and one **database**:

```
 STAFF PAGE (app.py)                    SUPERVISOR PAGE                  ADMIN PAGE
 ────────────────────                   (1_Supervisor_Dashboard.py)      (2_Admin_Ops.py)
 record live -> sanitize/screen             browse reports by date        config snapshot
   -> transcribe -> validate                download Master Log           24h activity rollup
   -> extract JSON -> narrate                download any PDF/Excel        filterable event log
   -> build Excel/PDF -> save
   -> auto-email PDF
        |
        v
 +-----------------------------------------------------------+
 |  SQLite (utils/db.py): reports, report_images,             |
 |  app_events, login_attempts                                |
 +-----------------------------------------------------------+
        ^
        | every key step logs here via utils/observability.py
        | every input is screened via utils/security.py first
```

| Concern | File(s) |
|---|---|
| UI shell / orchestration (staff) | `app.py` |
| Supervisor browsing | `pages/1_Supervisor_Dashboard.py` |
| Admin monitoring | `pages/2_Admin_Ops.py` |
| Login (3 roles) + lockout | `utils/auth.py` |
| Input sanitization / prompt-injection screen / output validation | `utils/security.py` |
| Structured logging + timing | `utils/observability.py` |
| Audio file handling | `utils/audio_utils.py` |
| Speech -> text | `providers/stt_provider.py` |
| Text -> structured JSON, then JSON -> narrative prose | `providers/llm_provider.py` + `utils/parser.py` |
| JSON -> tables/Excel/Master Log | `utils/report.py` |
| JSON+narrative+photos -> PDF | `utils/pdf_report.py` |
| Persistence | `utils/db.py` |
| Email | `utils/email_utils.py` |

**Recommended reading order** (this is the order the rest of this document follows):

1. `utils/parser.py` — what data we extract, and how we ask the AI for it.
2. `providers/stt_provider.py`, `providers/llm_provider.py` — the two AI calls.
3. `utils/security.py` — the three defensive layers around those AI calls.
4. `utils/observability.py` — how every step gets timed and logged.
5. `utils/audio_utils.py`, `utils/report.py`, `utils/pdf_report.py` — the non-AI plumbing.
6. `utils/db.py` — persistence for reports, events, and login attempts.
7. `utils/auth.py` — login + lockout, built on top of `security.py` and `db.py`.
8. `app.py` — the conductor. Read last; every function it calls is now familiar.
9. `pages/1_Supervisor_Dashboard.py`, `pages/2_Admin_Ops.py` — thin read-only views over the same `db.py`/`report.py` functions.

---

## 2. `utils/parser.py` — the domain "brain"

Two prompts live here, used by the two LLM calls in `llm_provider.py`:

1. **Extraction prompt** — turns a transcript into structured JSON. The schema separates
   **tables** (`total_tables_declared`) from **vessels** (`vessel_summary`, boat types like
   Hadaq/Defara/Hadhra) — these are independent counts and the prompt is explicit that they
   must never be reconciled against each other (see README section 1). `table_details` maps
   table numbers to fish species, a third independent piece of data.
2. **Narrative prompt** — turns that JSON (plus the transcript) into the PDF's prose sections
   (Purpose/Observations/Summary/Remarks). This prompt's most important rule: **only state
   what's in the extracted data or transcript** — no invented species biology, no fabricated
   size-structure or compliance conclusions. This is a direct, deliberate response to the risk
   that an LLM asked to "write a professional report" will pad it with plausible-sounding but
   unsupported claims.

Both prompts use **JSON mode** (`response_format={"type": "json_object"}`, set in
`llm_provider.py`) and a one-shot worked example, for the same reasons explained in the
earlier design (see section 3 below on `llm_provider.py` for what JSON mode actually
guarantees — and doesn't).

---

## 3. `providers/stt_provider.py` and `providers/llm_provider.py`

Both are **plain functions with a simple if/else dispatch inside** — no classes, no abstract
base class. This was a deliberate simplification: an earlier version used an
abstract-base-class-plus-factory pattern (common in larger codebases), but for a
two-person, single-deployment app that was more ceremony than it was worth. The if/else
version gives the exact same "swap providers via one `.env` line" benefit with far less to
read:

```python
def transcribe(audio_filepath: str) -> str:
    provider = os.getenv("STT_PROVIDER", "groq").lower()
    if provider == "groq":
        return _transcribe_groq(audio_filepath)
    elif provider == "azure":
        return _transcribe_azure(audio_filepath)     # <-- stub today, fill in when you migrate
    raise ValueError(f"Unknown STT_PROVIDER: {provider}")
```

`app.py` just calls `transcribe(audio_path)` directly — no factory call, no `.method()` on an
object, no class to look up. `llm_provider.py` follows the identical shape for its two jobs
(`extract_structured_data()` and `generate_narrative_report()`), both funneling through one
shared `_run_json_chat()` helper that does the actual dispatch, so implementing the Azure
branch once (`_json_chat_azure()`) covers both jobs.

**Migrating to Azure later** means: write the body of `_transcribe_azure()` and
`_json_chat_azure()`, set `STT_PROVIDER=azure` / `LLM_PROVIDER=azure` in `.env`. `app.py`
doesn't change at all, because it never knew which provider it was calling in the first place
— it just calls `transcribe(...)` / `extract_structured_data(...)` by name.

Both use **JSON mode** (`response_format={"type": "json_object"}`, set inside
`_json_chat_groq()`) and a one-shot worked example in the prompt (see `utils/parser.py`).

**What JSON mode does and doesn't guarantee:** it forces the reply to be *syntactically*
valid JSON — no stray prose, no markdown fences. It does **not** guarantee the JSON matches
your schema, has sane field types, or has a sane size. That gap is exactly what
`security.validate_extracted_data()` closes — see the next section.

---

## 4. `utils/security.py` — three defensive layers

This file assumes the prompt design in `parser.py` will occasionally be bypassed anyway —
by an adversarial speaker, a transcription quirk, or a model mistake — and makes sure that
never silently propagates into a saved report, a PDF, or an email.

### Layer 1 — `sanitize_transcript(text)`
Runs on **every** transcript, unconditionally, before it's used in any prompt:
```python
cleaned = "".join(
    ch for ch in text
    if ch in ("\n", "\t", " ") or unicodedata.category(ch)[0] != "C"
)
```
`unicodedata.category(ch)[0] != "C"` drops any Unicode "Control" category character — normal
spoken words never contain these; their presence in a transcript is itself a signal something
unusual is in the audio (e.g. embedded control sequences). The result is also hard-truncated
to `MAX_TRANSCRIPT_LENGTH` (env-configurable, default 4000 chars) — a normal daily report is a
few sentences; anything wildly longer is capped rather than trusted wholesale.

### Layer 2 — `detect_prompt_injection(text)`
A regex denylist for common jailbreak phrasing:
```python
_PROMPT_INJECTION_PATTERNS = [
    r"\bignore (all|any|the) (previous|prior|above)\b",
    r"\byou are now\b",
    r"\bsystem\s*prompt\b",
    r"</?(system|assistant|user)>",     # fake chat-role tags
    r"```",                              # code fences have no business in spoken text
    # ...
]
```
Returns the list of matched patterns (empty = clean). **This deliberately does not block
anything by itself** — see the `app.py` section below for how a match pauses the pipeline for
a human to confirm, rather than either silently proceeding or silently refusing. A regex
denylist is a heuristic, not a guarantee — see README section 10 for what a more robust
version would add (a trained classifier, alerting on repeat flags from one account, etc).

### Layer 3 — `validate_extracted_data(data)`
Schema-validates and sanitizes the LLM's JSON reply *after* extraction, *before* it's saved
anywhere:
```python
if not isinstance(vessel_summary, list):
    errors.append("vessel_summary must be a list.")
elif len(vessel_summary) > MAX_LIST_ITEMS:
    errors.append("vessel_summary has an implausible number of entries.")
```
Checks every field's type, caps list lengths and string lengths, and — importantly — mutates
`data` in place to clip oversized strings, so even a *passing* result is safe to use
downstream. Returns `(is_valid, errors)`; `app.py` discards the whole report (doesn't save,
doesn't email) if `is_valid` is `False`, rather than trying to partially salvage it.

### Bonus: `constant_time_compare(a, b)`
```python
return hmac.compare_digest((a or "").encode("utf-8"), (b or "").encode("utf-8"))
```
Used by `auth.py` for password checks instead of Python's `==`. A plain `==` on strings
compares character-by-character and returns as soon as it finds a mismatch — in principle an
attacker measuring response time could infer how many leading characters they got right.
`hmac.compare_digest` takes the same amount of time regardless of where the mismatch is.

---

## 5. `utils/observability.py` — structured logging + timing

**The core idea:** wrap any operation you care about in `timed_operation(...)`, and it's
automatically timed, logged (success or failure), and queryable later — without littering
`app.py` with manual `time.time()` calls and `try/except/finally` blocks everywhere.

```python
@contextmanager
def timed_operation(event_type, username=None, role=None, **meta):
    start = time.perf_counter()
    try:
        yield
    except Exception as e:
        duration_ms = (time.perf_counter() - start) * 1000
        log_event(event_type, status="error", duration_ms=duration_ms, error=str(e), **meta)
        raise                              # <-- re-raised, so the caller still sees the failure
    else:
        duration_ms = (time.perf_counter() - start) * 1000
        log_event(event_type, status="ok", duration_ms=duration_ms, **meta)
```
Used in `app.py` as:
```python
with timed_operation("stt_transcribe", username=staff_username, role="staff"):
    raw_transcript = stt.transcribe(audio_source_path)
```
Whether the block succeeds or raises, a structured event is logged with accurate timing — and
if it raised, the exception still propagates normally to `app.py`'s own `try/except`, so error
handling behavior is unchanged; the logging is purely additive.

`log_event()` writes to **two places** every time:
1. A **rotating JSON-line log file** (`logs/app.log`), via a custom `_JsonFormatter` — each
   line is one JSON object, easy to pipe into any log aggregator later.
2. The **`app_events` SQLite table** (`db.log_event_db`), so the Admin/Ops page can query
   without touching the filesystem.

**A subtle but important bug this file avoids:** Streamlit re-executes the whole script on
every interaction. A naive `logging.basicConfig(...)` call at the top of `app.py` would
therefore re-add log handlers on every single click, duplicating every future log line more
and more over a session. `get_logger()` guards against this explicitly:
```python
def get_logger():
    logger = logging.getLogger(_LOGGER_NAME)
    if logger.handlers:
        return logger    # already configured earlier in this process -- don't add handlers again
    ...
```

---

## 6. `utils/audio_utils.py`, `utils/report.py`, `utils/pdf_report.py`

These three are pure data-transformation — no AI calls, no security concerns beyond what
already arrived validated from `security.py`.

- **`audio_utils.py`**: `save_uploaded_bytes()` writes in-memory audio bytes to a real temp
  file (the Groq SDK wants a file, not bytes-in-memory); `extract_audio_from_video()` uses
  `moviepy`/`ffmpeg` to pull the audio track out of an uploaded video (used when
  `ENABLE_FILE_UPLOADS=true`).
- **`report.py`**: builds pandas DataFrames for on-screen tables, the per-report Excel
  (`export_to_excel`), and the **Master Log** — the exact "Operator | Date | No. of tables |
  Hadaq | Defara | Hadhra" format. `VESSEL_COLUMN_GROUPS` + `_canonical_vessel_column()`
  normalize spelling variants ("hadara"/"hadhra"/"hadra" -> the same "Hadhra" column) using a
  **grouped, margin-checked fuzzy match** — not a plain closest-match, because plain fuzzy
  matching was found (by testing) to occasionally misfile e.g. "hadag" into the wrong column
  entirely; the margin check means an ambiguous match falls safely into "Other Vessel Types"
  instead of guessing wrong. `_autosize_columns()` makes sure Excel columns aren't visually
  truncated when opened.
- **`pdf_report.py`**: builds the full PDF using `fpdf2`'s `Table` API (not manual
  fixed-width `.cell()` calls, which don't wrap long text and can overflow the page — this was
  a real bug, fixed by switching to `pdf.table(...)`). Narrative paragraphs are rendered with
  `multi_cell()` (which does wrap); photos are resized and embedded per-image in a "Photo
  Annexes" section.

---

## 7. `utils/db.py` — persistence for everything

Four tables, all in one SQLite file (`reports.db`):

| Table | Written by | Read by |
|---|---|---|
| `reports` | `save_report()` in `app.py` Step 3 | Dashboard, Admin page (indirectly) |
| `report_images` | `save_report()` (one row per photo) | Dashboard's photo gallery |
| `app_events` | `observability.log_event()` on every timed operation | Admin/Ops page |
| `login_attempts` | `auth.require_login()` on every attempt | `auth.py`'s own lockout check |

`init_db()` is safe to call on every page load (it's called at the top of `app.py` and both
`pages/*.py` files) — `CREATE TABLE IF NOT EXISTS` plus a small `_ensure_columns()` migration
helper that adds any newly-introduced column to an already-existing table, so an older
`reports.db` from before a feature existed still works without manual migration.

`count_recent_reports_by_user()` and `count_recent_failed_logins()` are the two functions that
back rate limiting and login lockout respectively — both are just `SELECT COUNT(*) ... WHERE
timestamp >= ?` queries against a rolling time window.

---

## 8. `utils/auth.py` — login, built on `security.py` + `db.py`

```python
def require_login(role="staff") -> bool:
    if st.session_state.get(f"authenticated_{role}"):
        return True
    # ...draw form...
    if submitted:
        recent_failures = count_recent_failed_logins(role, username, LOGIN_LOCKOUT_MINUTES)
        if recent_failures >= MAX_FAILED_LOGIN_ATTEMPTS:
            st.error("Too many failed login attempts...")
            return False                      # <-- rejected even before checking the password

        is_valid = constant_time_compare(username, valid_user) and constant_time_compare(password, valid_pass)
        record_login_attempt(role, username, success=is_valid)
        log_event("login_attempt", status="ok" if is_valid else "error", username=username, role=role)
        ...
```
Notice the **lockout check happens before the password is even compared** — once an account
has too many recent failures, further attempts are rejected outright, so even the *correct*
password won't work until the lockout window passes. This is intentional and was specifically
tested (a 3-failure lockout still rejected the 4th attempt even with the right password).

Every attempt — success or failure — is both recorded in `login_attempts` (for the lockout
math) and logged as a structured event (for the Admin/Ops page), via two separate function
calls that do two different jobs: one is the security control, the other is the audit trail.

`role="admin"` works with **zero new code** — `require_login`/`logout_button` already read
`f"{role.upper()}_USERNAME"` / `f"{role.upper()}_PASSWORD"` generically, so adding the Admin
Ops page's login was just adding `ADMIN_USERNAME`/`ADMIN_PASSWORD` to `.env` and calling
`require_login(role="admin")`.

---

## 9. `app.py` — the conductor (read this last)

### The Phase 1 feature flag
```python
ENABLE_FILE_UPLOADS = os.getenv("ENABLE_FILE_UPLOADS", "false").lower() == "true"

if ENABLE_FILE_UPLOADS:
    evidence_tabs = st.tabs(["Live Camera Snapshot", "Upload Image(s)", "Upload Video"])
    ...
else:
    # just the live camera widget, no tabs
    cam_image = st.camera_input(...)
```
The upload code paths are **fully implemented, not deleted** — just gated behind one boolean.
Flipping `ENABLE_FILE_UPLOADS=true` in `.env` re-enables them with no code changes, which is
the point of a feature flag: the "Phase 2" functionality already exists and is tested, it's
just switched off by default for the current rollout phase.

### The prompt-injection pause/confirm flow
This is the one place the control flow got meaningfully more complex, because "screen the
transcript, and pause for confirmation if flagged" doesn't fit neatly inside a single button
click. The solution: pull everything from LLM extraction onward into its own function,
callable from two different places:

```python
def _run_from_transcript(transcript: str):
    # LLM extract -> validate -> narrate -> build Excel/PDF -> save -> auto-email
    ...

if process_clicked:
    raw_transcript = stt.transcribe(audio_source_path)
    transcript = sanitize_transcript(raw_transcript)
    flags = detect_prompt_injection(transcript)
    if flags:
        st.session_state.pending_transcript = transcript   # <-- pause here
        st.session_state.injection_flag_count = len(flags)
    else:
        _run_from_transcript(transcript)                    # <-- clean case, proceeds immediately

if st.session_state.get("pending_transcript"):
    st.warning("This transcript contains unusual phrasing...")
    st.text_area("Transcript pending review", st.session_state.pending_transcript, disabled=True)
    confirm = st.checkbox("I have reviewed this transcript and confirm it's a legitimate report.")
    if st.button("Proceed Anyway", disabled=not confirm):
        _run_from_transcript(st.session_state.pending_transcript)
```
`_run_from_transcript` doesn't care which path called it — it's the same function either way,
so there's no risk of the "confirmed" path skipping a step the "clean" path does (a common bug
pattern when duplicating logic across two branches instead of sharing one function).

### Rate limiting, before any API calls happen
```python
recent_count = count_recent_reports_by_user(staff_username, minutes=60)
rate_limited = recent_count >= MAX_REPORTS_PER_HOUR
...
process_clicked = st.button("Generate Report", disabled=(audio_source_path is None or rate_limited))
```
The check is a cheap SQLite query, done *before* the button is even clickable — so a
rate-limited account can't burn any Groq API calls at all, not even the transcription one.

### Everything else (Steps 1/2/4, the DB save, auto-email) is unchanged from the core pipeline
described in earlier sections — `_run_from_transcript` is just the old Step 3 body, wrapped
in a function and instrumented with `timed_operation(...)` around each sub-step.

---

## 10. `pages/1_Supervisor_Dashboard.py` and `pages/2_Admin_Ops.py`

Both are intentionally thin — they call `require_login(role=...)`, then read-only functions
already covered above (`db.list_reports`, `db.get_report`, `report.build_master_log_df_from_records`
for the Dashboard; `db.get_recent_events`, `db.get_event_stats` for Admin/Ops). Neither page
writes to the database except indirectly through login attempts. If you understand
`utils/db.py` and `utils/report.py`, both pages should read as "just wiring a form to a query
and a query to a table."

---

## 11. Full end-to-end workflow (tracing three real sessions)

### A. Normal staff submission (no security flags)
1. `app.py` loads -> `require_login(role="staff")` -> login form -> `constant_time_compare` check
   -> `record_login_attempt(..., success=True)` + `log_event("login_attempt", status="ok")`.
2. Staff takes 2 camera snapshots (`ENABLE_FILE_UPLOADS=false`, so only the live widget shows)
   -> `_add_image_if_new()` hash-dedupes -> 2 photos in `st.session_state.captured_images`.
3. Staff records their voice -> `save_uploaded_bytes()` writes a temp `.wav`.
4. Staff clicks **Generate Report**. Rate limit check passes (few reports this hour).
   - `timed_operation("stt_transcribe")` wraps the Groq Whisper call -> transcript.
   - `sanitize_transcript()` cleans it -> `detect_prompt_injection()` finds nothing.
   - `_run_from_transcript(transcript)` runs immediately:
     - `timed_operation("llm_extract")` wraps the extraction call -> JSON dict.
     - `validate_extracted_data()` passes -> data is safe to use.
     - `timed_operation("llm_narrative")` wraps the narrative call -> narrative dict.
     - `export_to_excel()`, `build_pdf()` build the two files.
     - `save_report()` writes everything to `reports`/`report_images`.
     - `log_event("report_saved", ...)`.
     - `timed_operation("email_send")` wraps the SMTP send -> supervisor gets the PDF.
5. Step 4 renders: tables, transcript, narrative preview (with its AI-generated-content
   caution note), photos, download buttons.

### B. A flagged transcript
Same as above through step 4, except `detect_prompt_injection()` returns matches (e.g. the
transcript contains "ignore previous instructions"). Instead of calling `_run_from_transcript`
immediately:
- `log_event("prompt_injection_suspected", status="error", ...)` — visible on Admin/Ops.
- `st.session_state.pending_transcript` is set; the script reruns (Streamlit does this after
  every widget interaction) and renders the warning + transcript + checkbox + "Proceed Anyway"
  button instead of a report.
- Staff reviews, ticks the checkbox, clicks "Proceed Anyway" -> `log_event("prompt_injection_override", ...)`
  -> `_run_from_transcript(...)` now runs, exactly as in path A.

### C. Admin checks the Ops page
1. `require_login(role="admin")`.
2. `get_event_stats(since_minutes=1440)` groups `app_events` by `(event_type, status)` over
   the last 24h -> the activity rollup table, including the `prompt_injection_suspected` count
   from session B above.
3. `get_recent_events(limit=100)` -> the filterable raw event log; admin can filter to
   `event_type="login_attempt", status="error"` to see failed logins, or expand any single
   event's full `meta_json` for details like the flagged transcript preview.

---

## 12. Key concepts glossary (new since the last version of this doc)

| Term | Meaning in this app |
|---|---|
| **Feature flag** | A boolean config value (`ENABLE_FILE_UPLOADS`) that turns already-written code on/off without deploying new code — used here to restrict the app to Phase 1 functionality. |
| **Provider dispatch** | A plain function with an if/else on a `.env` setting (`STT_PROVIDER`), calling a private per-vendor function — the simple alternative to a class hierarchy, giving the same "swap vendors via config" benefit for a fraction of the code. |
| **Timing-safe comparison** | A string comparison (`hmac.compare_digest`) that takes the same time regardless of where a mismatch occurs, preventing timing-based side-channel attacks on password checks. |
| **Account lockout** | Temporarily rejecting login attempts (even correct ones) after too many recent failures, to slow down password-guessing attacks. |
| **Prompt injection** | An attempt to manipulate an LLM's behavior by embedding fake instructions in the data it's asked to process (here: the spoken transcript) rather than in the system prompt the developer controls. |
| **Heuristic denylist** | A pattern-matching approach (here: regex) that catches *known* bad patterns but not novel ones — a speed bump, not a guarantee, hence pairing it with human confirmation rather than a silent block. |
| **Structured logging** | Logging events as machine-parseable data (here: one JSON object per line) instead of free-text messages, so logs can be queried/aggregated later. |
| **Context manager** (`with ... :`) | A Python construct (`@contextmanager`) that runs setup code, yields control to a block, then runs cleanup code afterward — used here (`timed_operation`) to guarantee timing/logging happens whether the wrapped code succeeds or raises. |
| **Rate limiting** | Capping how many times an action can happen in a time window (here: reports per staff account per hour) to bound cost/abuse. |
| **Idempotent setup** | Code safe to run multiple times without duplicating effects (`get_logger()` only adds handlers once, `init_db()` only creates tables if missing) — necessary here because Streamlit re-runs the whole script on every interaction. |

---

## 13. Suggested learning path if you're new to this stack

1. Read `utils/parser.py`'s two system prompts — get comfortable with "programming an AI"
   meaning precise English instructions, including instructions about what *not* to invent.
2. Read `utils/security.py` top to bottom — it's short, self-contained, and demonstrates the
   "assume the AI call will occasionally misbehave, and don't let that reach anything
   important" mindset that the rest of the security/observability work follows.
3. Run the app locally, submit one normal report, then deliberately speak/type a transcript
   containing "ignore previous instructions" (turn `ENABLE_FILE_UPLOADS=true` temporarily to
   use the Upload Audio tab with a test file) to see the confirmation flow trigger.
4. Open the Admin/Ops page and find both events from step 3 in the log.
5. Re-read `app.py` section by section, now that every function it calls is familiar.
