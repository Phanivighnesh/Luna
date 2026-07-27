# Luna — Local AI Desktop Assistant

A working prototype: Electron chat UI + Python (FastAPI) backend + local LLM via Ollama.
Everything runs on your machine; no cloud calls anywhere in this code.

## What's included

```
luna/
├── backend/
│   ├── app.py           # FastAPI server (chat, memory, tasks, activity log)
│   ├── ai.py            # Ollama streaming wrapper
│   ├── memory.py        # SQLite: preferences, conversations, activity log
│   ├── tasks.py         # Intent detection + safe task execution
│   └── requirements.txt
└── frontend/
    ├── main.js           # Electron main process
    ├── preload.js
    ├── package.json
    └── renderer/
        ├── index.html    # Onboarding, chat, memory, privacy, settings views
        ├── style.css
        └── renderer.js
```

## 1. Install & run the local model (Ollama)

```bash
# Install from https://ollama.com/download
ollama pull phi3:mini
ollama serve
```
Leave this running in a terminal. Default endpoint: `http://localhost:11434`.

Not certain of exact speed on your specific CPU — test with `ollama run phi3:mini` first.
If it's too slow, swap to a smaller model (e.g. `ollama pull gemma:2b`) and change
`DEFAULT_MODEL` in `backend/ai.py`.

## 2. Run the backend

```bash
cd backend
python -m venv venv
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate

pip install -r requirements.txt
uvicorn app:app --reload --port 8000
```

Check it's alive: open `http://localhost:8000/health` in a browser —
you should see `{"backend":"ok","ollama_running":true}`.

## 3. Run the frontend (development mode)

```bash
cd frontend
npm install
npm start
```

This opens the Electron window. Both the backend (port 8000) and Ollama
(port 11434) must already be running.

## 4. Package as a Windows .exe

```bash
cd frontend
npm run dist
```

This uses `electron-builder` (config already in `package.json`) to produce
an installer under `frontend/dist/`. The Python backend is NOT bundled into
the .exe in this version — for the hackathon demo, run the backend
separately alongside the packaged app (or note in your demo that this is a
known next step, not yet automated).

## Troubleshooting

**`ModuleNotFoundError` for a package (e.g. `apscheduler`) even though you
installed requirements.txt before:** you likely installed it into a
different Python environment than the one uvicorn is running in. If you're
using Anaconda, make sure you `pip install -r requirements.txt` **inside the
same activated environment** you use to run `uvicorn` — e.g.:
```bash
conda activate Luna
cd backend
pip install -r requirements.txt
uvicorn app:app --reload --port 8000
```

**The Electron window looks stuck / onboarding never progresses:** this
almost always means the backend isn't actually running (crashed on
startup, wrong port, etc.), so the UI's fetch calls to `localhost:8000` are
failing silently. Check the backend terminal for a traceback first. The UI
now shows a red banner at the top with a "Retry" button when it can't reach
the backend, instead of hanging silently.

**`'electron-builder' is not recognized`:** it didn't actually get
installed even though it's in `package.json`. Run:
```bash
npm install --save-dev electron-builder
```
then `npm run dist` again.

**`The system cannot find the file <app name>`:** this is `open_app`
correctly reporting that Windows doesn't recognize that name — not a bug.
Use the exact executable name (e.g. `brave.exe`) or however the app is
registered with `start`.

## What works end-to-end right now

- Onboarding (name, assistant name, theme) → saved to SQLite
- Streaming chat with a local model through Ollama
- **Time queries**: "what time is it" / "what time is it in UAE" answer
  instantly from Python's `datetime`/`zoneinfo` (stdlib, no dependency) —
  deliberately bypassing the LLM entirely. Small local models can hallucinate
  odd non-answers (e.g. inventing a "privacy restriction" that doesn't exist
  in this codebase) when asked something factual they have no way to know;
  anything with a deterministic answer should be intercepted before it
  reaches the model, not prompted around.
- **Plan generation → real schedule items**: "create a plan for learning
  FastAPI and add it to my schedule" now actually works — the LLM is asked
  for strict JSON (title + time offset per item), which the backend parses
  and inserts as real rows via the same schedule system as everything else.
  Verified with a mocked model response, including one that added markdown
  code fences around the JSON (small models often do this despite being told
  not to) — the fence-stripping logic handles it correctly.
  **Known limitation:** this only works as a single combined command. A
  separate follow-up like "now add those to my schedule" referring to an
  earlier chat message won't work — the rule-based system has no memory of
  "those," since it doesn't re-read prior turns. If you want that follow-up
  pattern to work, phrase the whole request in one message.
- **Fuzzy "mark X as done" matching**: now strips filler words ("the", "a",
  "my") before matching, so "mark the reminder as done" correctly finds an
  item titled just "Reminder".
- **"What's been marked done" queries** now answer from the real schedule
  database instead of the LLM — previously the model fabricated a
  plausible-sounding but entirely fictional history of "completed" items.
  Any question about the user's own stored data should never reach the LLM;
  it has no access to that data and will confabulate rather than say so.
- Relative-time reminders now accept more phrasings ("in 5 minutes",
  "remind me to X in 5 minutes", "set a reminder in 5 minutes", bare
  "reminder in 5 minutes") — parsed deterministically, no LLM involved.
- **Compound "open X and Y" commands**: `open_app` now stops at "and" (e.g.
  "open whatsapp and text mom" opens WhatsApp only). Luna can launch apps but
  can't yet operate inside them — the confirmation message says so explicitly
  rather than silently dropping the second half of the request.
- **Web search reliability**: switched to GET with realistic browser headers
  and a `lite.duckduckgo.com` fallback if the main endpoint 403s. Failures now
  return the actual status code + a snippet of the response body instead of
  a bare error, to make future debugging faster. Not verified end-to-end from
  this environment (DuckDuckGo isn't reachable from the sandbox used to build
  this) — test on your machine and report back what the diagnostic shows if
  it still fails.
- Rule-based task detection for: opening apps, searching files, creating
  notes/reminders — each gated behind an explicit Allow/Deny modal
- **Schedule + email reminders**: say "schedule team meeting at 5:00 PM" (or
  add it from the Schedule tab). A background job checks every 60 seconds
  and emails you 5 minutes before it's due, via SMTP (configure in Settings).
- **Mark as done**: say "mark team meeting as done" in chat, or click
  "Mark Done" in the Schedule tab. Runs immediately — no confirmation modal,
  since it's a non-destructive, explicitly user-issued update to your own data.
- **Web search**: say "search the web for X" or "look up X" — the one
  feature that intentionally leaves your machine, since no local model has
  live internet data. Uses DuckDuckGo's HTML endpoint, no API key needed.
- Memory dashboard: view and delete individual stored preferences
- Privacy dashboard: activity log + "Delete All My Data"
- Settings: assistant name, theme, response length preference, email/SMTP config

## Setting up email reminders

1. If using Gmail: turn on 2-Step Verification, then generate an **App
   Password** at https://myaccount.google.com/apppasswords (your normal
   Gmail password will NOT work here — Google blocks that for SMTP apps).
2. In Luna's Settings tab, enter your email and the app password, and
   optionally a different "send reminders to" address.
3. Schedule something with a due time in the next few minutes to test it,
   and watch the Privacy tab's activity log for `reminder_emailed` or
   `reminder_email_failed` entries.

**Known limitation:** the app password is stored in plaintext in the local
SQLite file (`backend/db/luna.db`). Acceptable for a hackathon demo on your
own machine — flag it in your demo video rather than let it look like an
oversight. If you want to harden this later, look into the OS keychain
(`keytar` on the Electron side, or Windows Credential Manager) instead of
storing it in SQLite.

## Known gaps to fill before a polished demo

- `search_file` does a bounded filesystem walk — fine for a demo, but slow
  on very large drives; consider indexing (e.g. `es`/Everything CLI on
  Windows) if you have time.
- Response-length setting is stored but not yet wired into the prompt sent
  to Ollama — pass it into `SYSTEM_PROMPT` in `ai.py` if you want it to
  actually change output length.
- Time parsing for scheduling uses `dateutil`'s fuzzy parser — it handles
  "5:00 PM", "tomorrow 9am", etc. reasonably well but isn't perfect. If a
  scheduled time comes out wrong, rephrase more explicitly.
- No true voice input yet — "mark X as done" works as a typed/chat command,
  not spoken. Adding speech-to-text (e.g. a local Whisper.cpp build) would
  be a reasonable next step and was intentionally left out to keep this
  version's dependencies lightweight for an 8GB/i3 target.
- No packaging story yet for bundling Python + Ollama inside the .exe —
  today it's three processes (Ollama, backend, Electron) run separately.
