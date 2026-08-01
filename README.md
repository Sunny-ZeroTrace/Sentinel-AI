# Sentinel AI — Agentic Child Protection Investigation Assistant
### Intelligence for Faster Child Protection Investigations

A fully local investigation-support platform: case management, evidence
correlation, face matching across cases, an explainable risk score, a
per-case chat (RAG search over evidence), and a Gmail-based evidence-
request workflow — all running on your own machine through a **local
LLM (Ollama)**. No cloud, no API keys, no quotas.

## Quick start

See **AGENT_SETUP.md** for full step-by-step setup. Short version:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
ollama pull llama3.2:3b
ollama pull moondream
python3 tests/manual_verify.py   # confirms core logic works
python3 run.py                   # launches the app at 127.0.0.1:8000
```

## What's real vs. illustrative

- **Real and fully functional**: case management with an elaborated
  physical folder structure per case, timeline reconstruction, explainable
  risk scoring, face detection/matching (`face_recognition`) with cropped
  thumbnails and a cross-case global face index, PDF/text evidence reading
  (`pypdf`), local vision photo descriptions (`moondream` via Ollama),
  dependency-free case search/chat, draft report generation, Gmail send/
  receive/follow-up logic.
- **Illustrative/demo-only**: `modules/hash_match.py` simulates
  known-content hash matching against a small local dummy list. Real
  CSAM hash-matching (PhotoDNA, NCMEC/INTERPOL) requires accredited
  agency access that isn't available as a public API — this module shows
  where it would plug in.
- **Synthetic-only case**: `modules/synthetic_data.py` generates one
  fictional demo case so you always have something safe to show.

## Important before any live demo

- Point the Gmail directory at test mailboxes you control, not real
  department addresses, until this is an actual authorized deployment.
- Toggle "Demo mode" in Settings to shrink the 2-hour follow-up interval
  down to 30 seconds — same code path, just a faster timer.
- Click "Load sample demo case" on the Dashboard as a safety net.
- Make sure `ollama serve` is running before you start the demo — the
  sidebar shows a live connection status.

## Project layout

```
sentinel_ai/
  server.py               FastAPI backend — REST API + serves the frontend
  frontend/                Plain HTML/CSS/JS UI (no framework, no build step)
    index.html
    style.css
    app.js
  modules/                All core logic (faces, graph, timeline, risk,
                          nlp flags, rag search, reports, gmail, hash match,
                          pdf_reader, image_caption)
  scheduler.py             Background process: Gmail polling + follow-ups
  run.py                   Launches scheduler + server.py together
  db.py                    SQLite layer (single source of truth)
  config.py                Paths, folder structure, tunable constants
  llm_client.py             Ollama client (local LLM, no cloud)
  tests/                   pytest suite + a stdlib-only offline smoke test
  sentinel_data/               Created on first run:
    sentinel.db                database
    rag_store.json          per-case search index (plain JSON, no vector DB)
    persons/<face_id>/      cross-case thumbnails of tagged individuals
    cases/<case_id>/
      evidence/images/      photos
      evidence/documents/   PDFs, text docs
      evidence/other/       anything else
      faces/                cropped face thumbnails from this case
      emails/sent, received/
      drafts/                unsent email drafts (follow-ups, etc.)
      reports/               generated draft reports
      chat_logs/
      notes/
      update.md              living case summary + log
```

## Models used

- **Text**: `llama3.2:3b` by default (fits comfortably on 6GB VRAM). Swap
  to `llama3.1` in Settings for higher quality if your hardware allows.
- **Vision**: `moondream`, used to describe evidence photos factually
  (setting, objects, readable text) — separate from face matching, which
  uses `face_recognition`/dlib and doesn't need an LLM at all.
