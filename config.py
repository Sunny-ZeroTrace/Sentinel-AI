"""
Sentinel AI — central configuration.
Everything here is local. No cloud paths, no hardcoded secrets.
"""
import os
from pathlib import Path

# Root of the whole app (this file's directory)
APP_ROOT = Path(__file__).resolve().parent

# Where case folders + db + vector store live. Overridable from Settings page.
DEFAULT_DATA_ROOT = APP_ROOT / "sentinel_data"

DB_FILENAME = "sentinel.db"
CASES_DIRNAME = "cases"
GLOBAL_PERSONS_DIRNAME = "persons"   # tagged/identified individuals, cross-case
GMAIL_TOKEN_FILENAME = "gmail_token.json"
GMAIL_CLIENT_SECRET_FILENAME = "gmail_client_secret.json"

# ---------------------------------------------------------------- local LLM
# No cloud, no API keys. Talks to a locally running Ollama server.
# Change these defaults, or override per-install from the Settings page.
OLLAMA_DEFAULT_BASE_URL = "http://localhost:11434"
OLLAMA_DEFAULT_TEXT_MODEL = "llama3.2:3b"   # fast, fits comfortably on 6GB VRAM
OLLAMA_DEFAULT_VISION_MODEL = "moondream"    # for describing evidence photos

# Follow-up interval defaults, in seconds
REAL_FOLLOWUP_INTERVAL_SECONDS = 2 * 60 * 60   # 2 hours
DEMO_FOLLOWUP_INTERVAL_SECONDS = 30            # 30 seconds

# Scheduler tick — how often the background process checks things
SCHEDULER_TICK_SECONDS = 15

# Risk score weights (explainable, editable — not a black box)
RISK_WEIGHTS = {
    "recency": 0.25,
    "escalation_language": 0.30,
    "cross_case_link": 0.20,
    "known_hash_match": 0.35,
    "imminent_contact_signal": 0.40,
}

# Face matching threshold (lower = stricter). face_recognition uses distance,
# not similarity — 0.6 is the commonly used default cutoff.
FACE_MATCH_DISTANCE_THRESHOLD = 0.6


def get_data_root() -> Path:
    env_override = os.environ.get("SENTINEL_DATA_ROOT")
    return Path(env_override) if env_override else DEFAULT_DATA_ROOT


def ensure_dirs(data_root: Path) -> None:
    data_root.mkdir(parents=True, exist_ok=True)
    (data_root / CASES_DIRNAME).mkdir(parents=True, exist_ok=True)
    (data_root / GLOBAL_PERSONS_DIRNAME).mkdir(parents=True, exist_ok=True)


def case_dir(data_root: Path, case_id: str) -> Path:
    return data_root / CASES_DIRNAME / case_id


def resolve_case_dir(case_id: str) -> Path:
    """Returns the actual folder for a case, honoring a custom root the
    user picked at creation time (via the native folder-picker) if one
    was set — otherwise falls back to the default data root's cases/
    subfolder. This is what every module should call, not case_dir()
    directly, so custom-location cases work everywhere automatically."""
    import db  # local import: avoids a circular import (db.py imports config)

    case = db.get_case(case_id)
    custom_root = case.get("custom_root") if case else None
    if custom_root:
        return Path(custom_root) / case_id
    return case_dir(get_data_root(), case_id)


def person_dir(data_root: Path, face_id: str) -> Path:
    return data_root / GLOBAL_PERSONS_DIRNAME / face_id


# Physical folder layout created for every new case. Elaborated so an
# investigator (or anyone browsing the raw files outside the app) can
# immediately see what's inside without opening the UI.
CASE_SUBFOLDERS = [
    "evidence/images",
    "evidence/documents",
    "evidence/other",
    "faces",              # cropped face thumbnails detected in this case
    "emails/sent",
    "emails/received",
    "drafts",
    "reports",             # AI-drafted case reports (markdown)
    "summary",             # generated CaseSummary.docx / .pdf files
    "chat_logs",
    "notes",               # anything shared with / saved by the case chat
]

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}
DOCUMENT_EXTENSIONS = {".pdf", ".doc", ".docx", ".txt", ".rtf"}


def evidence_subfolder_for_filename(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext in IMAGE_EXTENSIONS:
        return "evidence/images"
    if ext in DOCUMENT_EXTENSIONS:
        return "evidence/documents"
    return "evidence/other"


def ensure_case_dirs(case_id: str, custom_root: str = None) -> Path:
    """Creates every subfolder for a case. If custom_root is given (the
    folder the user picked in the native dialog when creating the case),
    the case folder is created there instead of the default data root."""
    if custom_root:
        cdir = Path(custom_root) / case_id
    else:
        cdir = case_dir(get_data_root(), case_id)
    for sub in CASE_SUBFOLDERS:
        (cdir / sub).mkdir(parents=True, exist_ok=True)
    return cdir
