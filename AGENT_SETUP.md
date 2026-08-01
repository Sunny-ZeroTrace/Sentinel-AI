# Sentinel AI — automated setup instructions for a CLI coding agent

Give this whole file to your CLI agent and ask it to execute every step
in order. Each step is a copy-pasteable shell command. The agent should
stop and report back if any step fails, rather than skipping ahead.

Assumes: Windows/macOS/Linux desktop, Python 3.10+, this `sentinel_ai/` project
folder already placed somewhere on disk, and (if reusing a prior venv)
`dlib`/`face_recognition` already working in it.

---

## Step 1 — System dependencies for face recognition (skip if already working)

`face_recognition` depends on `dlib`, which needs a C++ build toolchain.

**Windows:** install Visual Studio Build Tools with the "Desktop
development with C++" workload, OR use the precompiled route:
```powershell
pip install dlib-bin
```

**Ubuntu/Debian/WSL:**
```bash
sudo apt-get update
sudo apt-get install -y build-essential cmake libopenblas-dev liblapack-dev
```

**macOS:**
```bash
brew install cmake
```

## Step 2 — Create and activate a virtual environment (skip if reusing one)

```bash
cd sentinel_ai
python3 -m venv .venv
source .venv/bin/activate    # on Windows: .venv\Scripts\activate
python3 -m pip install --upgrade pip
```

## Step 3 — Install Python dependencies

```bash
pip install -r requirements.txt
```

## Step 4 — Install and start Ollama (the local LLM runtime)

Sentinel AI uses **Ollama** for all AI features — no cloud, no API keys, no
quotas, everything runs on this machine.

1. Install Ollama from `https://ollama.com` (Windows/macOS/Linux installers
   available; on Linux: `curl -fsSL https://ollama.com/install.sh | sh`).
2. Ollama usually starts automatically after install. If not, run:
   ```bash
   ollama serve
   ```
   (leave this running in its own terminal/background).
3. Pull the two models this app uses:
   ```bash
   ollama pull llama3.2:3b
   ollama pull moondream
   ```
   `llama3.2:3b` handles text (chat, drafting, flagging) and comfortably
   fits on a 6GB-VRAM GPU. `moondream` is a small vision model used to
   describe evidence photos. If the machine has more VRAM/RAM headroom,
   `llama3.1` can be used instead for higher-quality text — swap it in
   later from the app's Settings page, no code change needed.
4. Verify:
   ```bash
   ollama list
   ```
   Should show both models.

## Step 5 — Verify the core logic offline (no Ollama needed for this step)

```bash
python3 tests/manual_verify.py
```
Expected output: a list of `[PASS]` lines ending in `All checks passed.`
This step doesn't call Ollama at all (LLM calls are mocked), so it passes
even before Step 4 is done — it's just proving the database, risk
scoring, timeline, and search logic work. If anything fails here, stop
and report the failing check.

## Step 6 — Run the pytest suite (same checks, standard test runner)

```bash
pytest tests/ -v
```

## Step 7 — First launch

```bash
python3 run.py
```
This starts two processes: the background scheduler and the FastAPI/
uvicorn server (which also serves the frontend). Opens
`http://127.0.0.1:8000` automatically. On first launch it checks Ollama's
connection — if Step 4 is done correctly, it goes straight to the
Dashboard. If not, it shows a clear status screen with the exact command
to fix it, and a "Continue anyway" button to explore the rest of the app
(everything except AI-dependent features still works without Ollama).

Stop with `Ctrl+C` — cleanly shuts down both processes.

## Step 8 — (Important: needed for chat-based email drafting/sending too) Gmail authorization

See **GMAIL_SETUP.md** (in the docs bundle) for full step-by-step
instructions. **This step matters more than it used to**: the case chat
can now draft and send emails directly from natural-language requests
("email jane@example.com about the footage request") — that feature is
inert without Gmail authorized. This step requires a one-time interactive
browser login and cannot be automated silently. Short version:

```bash
python3 -m modules.gmail_client --authorize
```

## Step 9 — Load the sample demo case (recommended before any pitch)

Once running, click **"Load sample demo case"** on the Dashboard — a
fully synthetic case for safe demoing even if live typing/upload goes
wrong mid-pitch.

## Step 10 — Report status to the user

Summarize: whether Step 5/6 (offline tests) passed, whether Step 7 (app
launch) succeeded and Ollama shows connected in the sidebar, and whether
Step 8 (Gmail) was completed or skipped.

---

## Troubleshooting quick reference

| Symptom | Likely cause | Fix |
|---|---|---|
| Sidebar shows "Ollama not reachable" | Ollama not running | Run `ollama serve` in a terminal, refresh the page |
| Chat/reports say "Ollama isn't reachable" | Model not pulled, or Ollama just started | `ollama pull llama3.2:3b`, wait a few seconds after `ollama serve` starts |
| Photo upload has no description text | Vision model missing | `ollama pull moondream` |
| PDF uploads say "no text extracted" | Scanned/image-only PDF | Expected — pypdf can't OCR; file is still saved |
| Case chat says "no indexed documents" | Nothing uploaded/indexed yet for that case | Upload an evidence photo or .txt/.pdf document first |
| "Choose folder" button does nothing / errors | `tkinter` not installed (some Linux distros ship Python without it) | Linux: `sudo apt-get install python3-tk`. Windows/macOS: tkinter ships with standard Python already |
| CaseSummary download fails with an import error | `python-docx` or `reportlab` missing | Re-run `pip install -r requirements.txt` |
| `dlib` fails to build | Missing build tools | See Step 1; try `pip install dlib-bin` as a fast alternative |
| Gmail tab shows "not authorized" | Step 8 not completed | See GMAIL_SETUP.md |

