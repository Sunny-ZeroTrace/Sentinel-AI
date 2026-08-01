"""
Hash-matching module — ILLUSTRATIVE / ARCHITECTURE DEMO ONLY.

Real known-content identification (PhotoDNA, NCMEC/ICMEC hash lists,
INTERPOL ICSE) requires accredited access restricted to authorized
agencies — there is no free public API for it, and this project does not
attempt to reimplement that detection. This module exists purely to show
where such an accredited API would plug into the pipeline: it hashes files
with SHA-256 and checks them against a small local demo list of dummy
hashes (of your own synthetic test files), so the *architecture and UI
flow* work end-to-end. Swap `check_hash()` for a real accredited API call
in an actual authorized deployment.
"""
import hashlib
import json
from pathlib import Path

from config import get_data_root

DEMO_HASH_LIST_FILE = "demo_known_hashes.json"


def _hash_list_path() -> Path:
    return get_data_root() / DEMO_HASH_LIST_FILE


def sha256_of_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def load_demo_hash_list() -> dict:
    p = _hash_list_path()
    if not p.exists():
        return {}
    return json.loads(p.read_text())


def register_demo_hash(file_path: str, label: str) -> None:
    """Adds a file's hash to the local demo 'known' list — for demo/testing
    purposes only, e.g. marking one of your synthetic sample images as a
    stand-in 'known item' so the matching flow has something to find."""
    hashes = load_demo_hash_list()
    hashes[sha256_of_file(file_path)] = label
    _hash_list_path().write_text(json.dumps(hashes, indent=2))


def check_hash(file_path: str):
    """Returns (matched: bool, label_or_None). Illustrative only — see
    module docstring."""
    file_hash = sha256_of_file(file_path)
    hashes = load_demo_hash_list()
    if file_hash in hashes:
        return True, hashes[file_hash]
    return False, None
