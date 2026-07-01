# 🐟 Fisheries Market — Voice Daily Report App

A simple Streamlit app for fish-market supervisors. They **speak or record** their daily
report — table counts, gear names, fish species per table — and the app turns it into a
clean **tabular report** automatically, using a **free LLM (Groq)** today, with a clear path
to swap to **Azure** later without rewriting the app.

Example of the kind of speech it understands:

> "Good morning Mr. Mark today total 20 tables hadara 10, dafara 4 and hadaq 6.
> table 1 king fish, table 2 shaari and safi, table 3 hammour"

It extracts:
- Supervisor name, date, total tables declared
- **Gear Summary table**: gear/net name → number of tables
- **Table Details table**: table number → fish name(s)
- Warnings if the numbers don't reconcile (e.g. gear counts don't add up to total tables)

---

## 1. How it works (architecture)

```
┌─────────────────┐      ┌──────────────────┐      ┌────────────────────┐      ┌───────────────┐
│  Voice / Video   │ ---> │  Speech-to-Text   │ ---> │   LLM Extraction    │ ---> │  Tabular       │
│  (mic / upload)  │      │  (Groq Whisper)   │      │  (Groq Llama 3.3,   │      │  Report +      │
│                  │      │                   │      │   JSON mode)        │      │  Excel export  │
└─────────────────┘      └──────────────────┘      └────────────────────┘      └───────────────┘
      +  camera snapshot / uploaded images / video are attached to the report as evidence
```

Both the STT and LLM steps sit behind a small **provider interface**
(`providers/stt_provider.py`, `providers/llm_provider.py`) so that later you can add an
`AzureSTTProvider` / `AzureLLMProvider` implementation and just flip an environment
variable — **`app.py` never has to change**.

### Project structure
```
fisheries_report_app/
├── app.py                     # Streamlit UI + orchestration
├── requirements.txt
├── .env.example                # copy to .env and fill in your Groq key
├── providers/
│   ├── stt_provider.py         # GroqSTTProvider (today) / AzureSTTProvider (later)
│   └── llm_provider.py         # GroqLLMProvider (today) / AzureLLMProvider (later)
└── utils/
    ├── parser.py                # prompt + JSON schema for extraction
    ├── report.py                 # builds pandas tables + Excel export (incl. embedded photos)
    ├── audio_utils.py            # save recordings / extract audio from video
    └── auth.py                   # simple login gate
```

---

## 2. Prerequisites

- Python 3.10+
- `ffmpeg` installed on your machine (needed to read video files / extract audio):
  - macOS: `brew install ffmpeg`
  - Ubuntu/Debian: `sudo apt-get install ffmpeg`
  - Windows: download from https://ffmpeg.org and add to PATH
- A **free Groq API key**: https://console.groq.com/keys (no credit card needed for the free tier)

---

## 3. Setup — step by step

```bash
# 1. Go into the project folder
cd fisheries_report_app

# 2. Create and activate a virtual environment
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure your API key
cp .env.example .env
# open .env and paste your key into GROQ_API_KEY=...

# 5. Run the app
streamlit run app.py
```

The app opens in your browser at `http://localhost:8501`.

---

## 4. Login

The app opens behind a simple login page (`utils/auth.py`). Credentials are read from
`.env`:
```
APP_USERNAME=admin
APP_PASSWORD=change_this_password
```
Change `APP_PASSWORD` before sharing the app with anyone. This is a single shared
username/password suitable for an internal tool — swap in Azure AD / SSO later if you need
per-user accounts; only `utils/auth.py` needs to change, `app.py` just calls
`require_login()`.

## 5. Using the app

A **"🔄 Clear & Start New Entry"** button sits in the sidebar at all times — click it to wipe
the current photos, transcript, and report and start a fresh entry (it also resets the
camera/upload widgets themselves, not just the data, so old photos can't silently reappear).

1. **Step 1 – Evidence (optional)**: take a live camera snapshot, then click **Clear photo**
   and take another — each distinct photo you capture is added to the report (duplicates
   from Streamlit re-running the script are automatically filtered out). You can also
   upload multiple images at once, or upload a video recording of the market floor.
2. **Step 2 – Voice**: either
   - record live through your mic, or
   - upload a pre-recorded audio file, or
   - reuse the audio track of a video you uploaded in Step 1.
3. **Step 3 – Generate Report**: click the button. The app transcribes the speech, then
   asks the LLM to extract structured fields.
4. **Step 4 – Report**: view the Summary, Gear Summary, and Table Details tables, the raw
   transcript, and the attached photo evidence all together on one screen, check any
   reconciliation warnings, and download the whole thing as an Excel file (Summary / Gear
   Summary / Table Details sheets, plus a Photo Evidence sheet with the images embedded
   directly in the workbook).

---

## 6. Why Groq for now

Groq offers a **free tier** covering both pieces you need:
- **Whisper (`whisper-large-v3-turbo`)** for fast, accurate speech-to-text
- **Llama 3.3 70B** with **JSON mode** for reliable structured extraction

This lets you prototype and validate the whole workflow with zero cost before committing to
Azure spend.

---

## 7. Migrating to Azure later

Because of the provider abstraction, migration is contained to two files:

1. **`providers/stt_provider.py`** — implement `AzureSTTProvider.transcribe()` using the
   Azure AI Speech SDK (`azure-cognitiveservices-speech`) or the Speech "Fast Transcription"
   REST API.
2. **`providers/llm_provider.py`** — implement `AzureLLMProvider.extract_structured_data()`
   using the `openai` SDK pointed at your Azure OpenAI deployment
   (`AzureOpenAI(azure_endpoint=..., api_key=..., api_version=...)`), reusing the exact same
   prompt from `utils/parser.build_extraction_prompt()` and `response_format={"type": "json_object"}`.
3. In `.env`, set:
   ```
   STT_PROVIDER=azure
   LLM_PROVIDER=azure
   AZURE_SPEECH_KEY=...
   AZURE_SPEECH_REGION=...
   AZURE_OPENAI_ENDPOINT=...
   AZURE_OPENAI_KEY=...
   AZURE_OPENAI_DEPLOYMENT=...
   ```

No changes are needed in `app.py`, `utils/parser.py`, or `utils/report.py`.

---

## 8. Customizing for your market's vocabulary

Gear and fish names are domain/dialect specific (e.g. hadara, dafara, hadaq, hammour, shaari,
safi). If the model mis-hears or mis-extracts a term:
- Add more example terms to the vocabulary list in `utils/parser.py` (`SYSTEM_PROMPT`).
- For STT accuracy on local terms, you can also pass a `prompt`/glossary hint to Whisper
  (Groq's transcription call supports a `prompt` parameter to bias recognition toward
  specific vocabulary — add your gear/fish name list there for best results).

---

## 9. Known simplifications (by design, for a "simple app")

- No database — each run is a single report; add persistence (SQLite/Azure SQL/Cosmos DB) if
  you need historical reporting across days.
- No user authentication.
- No automatic fish/gear species recognition from the photos/video (only stored as evidence);
  computer-vision-based species detection would be a separate future module.
- Table/gear number reconciliation is a simple sum-check warning, not auto-correction —
  the app never silently "fixes" what the supervisor said.
