# Luna — Local-First AI Desktop Assistant

Luna is a privacy-first desktop AI assistant that runs almost entirely on your own machine. Chat, task automation, scheduling, and voice all run locally through an open-source LLM served by [Ollama](https://ollama.com) — the only thing that ever leaves your computer is an optional live web search.

Built as a hackathon MVP and since extended with scheduling, email reminders, LLM-generated plans, and a local voice interface.

---

## Table of Contents

- [Why Luna](#why-luna)
- [Features](#features)
- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Setup](#setup)
- [Usage](#usage)
- [Configuration](#configuration)
- [Design Decisions](#design-decisions)
- [Known Limitations](#known-limitations)
- [Roadmap](#roadmap)
- [Troubleshooting](#troubleshooting)

---

## Why Luna

Most AI assistants are cloud-first: your conversations, your schedule, your files all pass through someone else's servers. Luna inverts that — the LLM runs locally via Ollama, all personal data lives in a local SQLite file, and every action that touches your system (opening an app, reading files) requires explicit, per-action confirmation. The one deliberate exception is live web search, since no local model can know today's information — and even that goes through the same confirmation gate as everything else.

## Features

**Chat**
- Streaming conversation with a local LLM (Phi-3-mini via Ollama)
- Per-conversation history, stored locally in SQLite
- Optional voice input/output — fully local speech-to-text and text-to-speech

**Task Automation** (rule-based intent detection, confirmed before executing)
- Open applications
- Search local files
- Create notes
- Schedule reminders — absolute ("at 5pm") or relative ("in 10 minutes")
- Mark schedule items done, by voice or text, with fuzzy title matching
- Ask what's on the schedule, or what's already been completed — answered from the real database, never guessed by the LLM
- Ask the current time, anywhere — computed locally, never hallucinated
- Web search — the one action that reaches the internet, clearly labeled as such

**Automated Reminders**
- A background job checks the schedule every 60 seconds and emails a reminder 5 minutes before anything is due, via SMTP
- A "Send Test Email" button in Settings gives immediate config feedback instead of waiting on the background cycle

**AI-Generated Plans**
- "Create a plan for learning FastAPI and add it to my schedule" — the LLM is constrained to return structured JSON, which the backend parses and inserts as real schedule rows (not just a wall of text)

**Memory & Privacy**
- All preferences and history stored locally in SQLite
- Memory dashboard: view and delete individual stored items
- Privacy dashboard: full activity log, plus one-click "Delete All My Data"

**Voice**
- Push-to-talk microphone input, transcribed locally (faster-whisper)
- Optional spoken replies (pyttsx3 / Windows SAPI5)

## Architecture

```
┌─────────────────────┐        HTTP (localhost:8000)        ┌──────────────────────┐
│   Electron Frontend  │ ───────────────────────────────────▶│   FastAPI Backend     │
│  (chat, schedule,    │◀─────────────────────────────────── │  (intent detection,   │
│   memory, settings)  │        streamed / JSON responses     │   task execution)     │
└─────────────────────┘                                      └──────────┬────────────┘
                                                                          │
                                   ┌──────────────────────────────────────┼───────────────────────┐
                                   ▼                                     ▼                        ▼
                          ┌────────────────┐                  ┌──────────────────┐      ┌──────────────────┐
                          │  Ollama (LLM)   │                  │  SQLite (memory,  │      │  DuckDuckGo /     │
                          │  localhost:11434│                  │  schedule, log)   │      │  SMTP / Whisper   │
                          └────────────────┘                  └──────────────────┘      └──────────────────┘
```

Every user message is checked against a rule-based intent matcher *before* it reaches the LLM. Deterministic, factual requests (time, schedule contents, marking things done) are answered directly from real data — the LLM is only used for open-ended conversation and for generating structured plans, and even then its output is validated before anything is executed.

## Tech Stack

| Layer | Choice | Why |
|---|---|---|
| Desktop shell | Electron | Fastest path to a packaged Windows `.exe` |
| Backend | Python + FastAPI | Async support for streaming + background jobs |
| Local LLM | Phi-3-mini via Ollama | Runs on CPU-only, 8GB RAM hardware; no PyTorch/GPU dependency |
| Storage | SQLite | Zero-config, single-file, fully local |
| Scheduling | APScheduler | In-process background job, no external service |
| Speech-to-text | faster-whisper | CTranslate2-based, lighter than openai-whisper (no PyTorch) |
| Text-to-speech | pyttsx3 | Drives Windows' built-in SAPI5 voices, no model download |
| Web search | DuckDuckGo HTML/lite endpoints | No API key required |

## Project Structure

```
luna/
├── backend/
│   ├── app.py              # FastAPI routes: chat, tasks, memory, schedule, voice
│   ├── ai.py                # Ollama streaming + non-streaming completion wrapper
│   ├── tasks.py              # Intent detection (regex-based) + task execution
│   ├── schedule_store.py     # SQLite schedule table (add/list/mark done)
│   ├── memory.py             # SQLite: preferences, conversations, activity log
│   ├── mailer.py             # SMTP reminder emails
│   ├── reminder_job.py       # Background scheduler — checks due items every 60s
│   ├── web_search.py         # DuckDuckGo scraper with redirect-URL decoding
│   ├── plan_generator.py     # LLM → structured JSON → real schedule rows
│   ├── voice.py              # faster-whisper STT + pyttsx3 TTS
│   └── requirements.txt
└── frontend/
    ├── main.js                # Electron main process
    ├── preload.js
    └── renderer/
        ├── index.html          # Onboarding, chat, schedule, memory, privacy, settings
        ├── renderer.js          # All UI logic, including voice recording
        └── style.css
```

## Setup

### 1. Install and run Ollama
```bash
# https://ollama.com/download
ollama pull phi3:mini
ollama serve
```

### 2. Backend
```bash
cd backend
python -m venv venv
venv\Scripts\activate        # Windows
pip install -r requirements.txt
uvicorn app:app --reload --port 8000
```
Verify: open `http://127.0.0.1:8000/health` — should return `{"backend":"ok","ollama_running":true}`.

**Voice feature requires `ffmpeg` on your PATH** (not installed by pip):
```powershell
winget install ffmpeg
```

### 3. Frontend
```bash
cd frontend
npm install
npm start
```

### 4. Package as a Windows installer (optional)
```bash
npm run dist
```
Produces `frontend/dist/Luna Setup <version>.exe`. Note: this only packages the Electron shell — Ollama and the Python backend still need to be running separately.

## Usage

Example commands you can type or speak:
```
what time is it in UAE
open notepad
reminder in 10 minutes
lookup intel i7 price
mark reminder as done
what's on my schedule
create a plan for learning FastAPI and add it to my schedule
```

Every action that touches your system shows a confirmation dialog before running — nothing executes silently.

## Configuration

**Email reminders** (Settings tab): for Gmail, generate an [App Password](https://myaccount.google.com/apppasswords) — your normal password won't work with SMTP. Use the **Send Test Email** button to confirm setup immediately.

**Voice replies**: toggle "Speak Luna's responses aloud" in Settings.

## Design Decisions

- **Deterministic-first, LLM-second.** Anything with a factual, checkable answer (current time, schedule contents, completed items) is answered from real code/data, never from the LLM. Small local models will confidently fabricate plausible-sounding answers rather than admit uncertainty — routing factual queries away from the model entirely is more reliable than trying to prompt that behavior away.
- **Confirm before executing.** Every action that opens an app, touches a file, or reaches the internet requires explicit per-action approval — there's no "trust mode."
- **Structured output for plan generation.** When the LLM needs to produce something actionable (a multi-step study plan), it's constrained to strict JSON rather than left to describe a plan in prose that nothing then acts on.

## Known Limitations

- Compound commands ("open WhatsApp and text mom") only execute the first clear action — Luna can launch apps, not operate inside them.
- Plan generation only works as a single combined command; a follow-up like "now add those to my schedule" referring to an earlier message won't work, since the rule-based layer has no memory of prior turns.
- The SMTP app password is stored in plaintext in the local SQLite file — acceptable for a personal/demo setup, not something to harden further without moving to OS-level credential storage.
- File search does an unindexed filesystem walk, capped at 20 results — fine for a demo, slow on very large drives.
- The packaged `.exe` bundles only the Electron shell; Ollama and the Python backend must be started separately.
- Web search depends on scraping DuckDuckGo's HTML/lite endpoints (no official API), which can change or start blocking requests without notice.

## Troubleshooting

**`ModuleNotFoundError` after installing requirements** — you likely installed into a different Python environment than the one running uvicorn. Activate the same environment for both steps.

**UI hangs on launch** — almost always means the backend isn't running; check its terminal for a traceback. Luna's UI shows a banner with a Retry button when it can't reach the backend.

**`electron-builder` not recognized** — run `npm install --save-dev electron-builder` explicitly.
