# 🚀 Push This Project to GitHub — Step by Step

This assumes you've downloaded and unzipped `fisheries_report_app.zip` somewhere on your
computer (e.g. `~/Downloads/fisheries_report_app`). Do these steps **on your own machine**,
in a terminal — not inside this chat — since pushing code needs your personal GitHub login.

---

## Step 0 — One-time setup (skip if already done)

Check if Git is installed:
```bash
git --version
```
If not found, install it:
- **Windows**: download from https://git-scm.com/download/win
- **macOS**: `brew install git` (or it prompts to install via Xcode tools)
- **Ubuntu/Debian**: `sudo apt-get install git`

Tell Git who you are (only needed once per machine):
```bash
git config --global user.name "Your Name"
git config --global user.email "you@example.com"
```

---

## Step 1 — Create an empty repository on GitHub

1. Go to https://github.com/new
2. **Repository name**: e.g. `fisheries-voice-report`
3. Choose **Private** (recommended, since this is a business tool) or Public
4. **Do NOT** check "Add a README", "Add .gitignore", or "Choose a license" — leave the repo
   completely empty. You already have a `.gitignore` and `README.md` in the project folder,
   and starting from an empty repo avoids merge conflicts in step 4.
5. Click **Create repository**. GitHub will show you a page with setup commands — keep that
   page open, you'll need the repository URL from it.

---

## Step 2 — Make sure secrets aren't in the folder

Open the project folder and confirm:
- There is a `.gitignore` file (already included) that lists `.env` — this stops your real
  API key from ever being uploaded.
- If you created a real `.env` file while testing locally (copied from `.env.example` and
  filled in your Groq key), **do not delete it** — just make sure `.gitignore` is present so
  Git skips it automatically. You can double check with:
  ```bash
  cd fisheries_report_app
  git check-ignore -v .env
  ```
  If this prints a line pointing at `.gitignore`, you're safe — `.env` will not be committed.

---

## Step 3 — Initialize Git and make your first commit

From inside the project folder:
```bash
cd fisheries_report_app

git init
git add .
git status          # sanity check: .env should NOT appear in this list
git commit -m "Initial commit: fisheries market voice report app"
```

---

## Step 4 — Connect your local folder to the GitHub repo and push

Copy the URL GitHub showed you in Step 1 (it looks like
`https://github.com/<your-username>/fisheries-voice-report.git`), then:

```bash
git branch -M main
git remote add origin https://github.com/<your-username>/fisheries-voice-report.git
git push -u origin main
```

### Authenticating the push

GitHub no longer accepts your account password directly for `git push` over HTTPS. You have
two common options:

**Option A — Personal Access Token (simplest, no extra install)**
1. Go to https://github.com/settings/tokens → **Generate new token (classic)**
2. Give it `repo` scope, set an expiry, generate it, and **copy the token immediately**
   (GitHub only shows it once).
3. When `git push` asks for a username/password, enter your GitHub username as the username
   and **paste the token as the password**.
4. (Optional) So you don't have to paste it every time:
   ```bash
   git config --global credential.helper store
   ```
   This saves the token locally after the first successful push.

**Option B — GitHub CLI (easier, handles auth for you)**
```bash
# install from https://cli.github.com/ if not already installed
gh auth login
gh repo create fisheries-voice-report --private --source=. --remote=origin --push
```
This single `gh repo create ... --push` command replaces Steps 1 and 4 entirely — it creates
the GitHub repo *and* pushes in one go.

**Option C — SSH (if you already have an SSH key set up with GitHub)**
```bash
git remote set-url origin git@github.com:<your-username>/fisheries-voice-report.git
git push -u origin main
```

---

## Step 5 — Verify

Refresh the GitHub repo page in your browser — you should see all the project files:
`app.py`, `providers/`, `utils/`, `requirements.txt`, `README.md`, `CODE_WALKTHROUGH.md`,
`.env.example`, `.gitignore` — and **no `.env` file**.

---

## Step 6 — Future changes (the normal day-to-day workflow)

Every time you edit the code afterward:
```bash
git add .
git commit -m "Describe what you changed"
git push
```

---

## Quick troubleshooting

| Problem | Fix |
|---|---|
| `git push` asks for password and rejects it | You're using your GitHub password instead of a token — see Option A above. |
| `.env` shows up in `git status` | Make sure `.gitignore` is in the same folder as `.env` and that you ran `git add .` *after* creating `.gitignore`. |
| `remote origin already exists` | Run `git remote remove origin` then re-run the `git remote add origin ...` command. |
| `failed to push some refs` (non-fast-forward) | Your GitHub repo isn't actually empty (e.g. you checked "Add a README"). Run `git pull origin main --allow-unrelated-histories` once, resolve any conflicts, then push again. |

---

## Optional next step: keep secrets out of GitHub *and* deploy easily

If you later deploy this app (e.g. on Streamlit Community Cloud or Azure), you won't add
`.env` to GitHub at all — you'll paste your `GROQ_API_KEY` / `APP_PASSWORD` etc. into that
platform's own "Secrets" or "Environment Variables" settings screen instead. The app already
reads everything via `os.getenv(...)`, so this works with zero code changes.
