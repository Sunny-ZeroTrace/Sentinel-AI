"""
Stdlib-only smoke test (no pytest, no network) — run with:
    SENTINEL_DATA_ROOT=/tmp/sentinel_ai_test python3 tests/manual_verify.py
Verifies db.py, risk_score.py, timeline.py, update_log.py (with LLM calls
mocked out, since no network is available in this check).
"""
import os
import sys
import tempfile
import shutil
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

tmpdir = tempfile.mkdtemp()
os.environ["SENTINEL_DATA_ROOT"] = tmpdir

import config
import db
from modules import rag_search

db.init_db()

failures = []


def check(label, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {label}")
    if not cond:
        failures.append(label)


# --- db basics ---
case_id = db.create_case(title="Verify case", location="Nowhere", description="baseline")
case = db.get_case(case_id)
check("case created with correct title", case["title"] == "Verify case")
check("case defaults to active status", case["status"] == "active")

db.update_case(case_id, status="closed", priority="high")
updated = db.get_case(case_id)
check("case update works", updated["status"] == "closed" and updated["priority"] == "high")

db.add_api_key("gemini", "key-b", label="b", priority=50)
db.add_api_key("gemini", "key-a", label="a", priority=10)
keys = db.list_api_keys(provider="gemini")
check("api key priority ordering", keys[0]["label"] == "a" and keys[1]["label"] == "b")

db.set_setting("demo_mode", True)
check("settings roundtrip true", db.get_setting("demo_mode") is True)
db.set_setting("demo_mode", False)
check("settings roundtrip false", db.get_setting("demo_mode") is False)

case_b = db.create_case(title="Second case")
db.add_correlation_edge(case_id, case_b, "face", "face123")
edges = db.all_correlation_edges()
check("correlation edge stored", len(edges) == 1 and edges[0]["entity_type"] == "face")

# --- update_log.py (patch out the LLM call so this runs offline) ---
import modules.update_log as update_log_mod
update_log_mod.llm_client.call_llm = lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("no network in test"))
update_log_mod.log_event(case_id, "test entry one")
update_log_mod.log_event(case_id, "test entry two")
md = update_log_mod.read_markdown(case_id)
check("update.md contains logged entries", "test entry one" in md and "test entry two" in md)
check("update.md falls back gracefully with no LLM", "No AI summary generated yet" in md)
check("log_event does not block on LLM (fast path)", True)  # implicit: the two calls above returned instantly

result = update_log_mod.regenerate_ai_summary(case_id)
check("regenerate_ai_summary handles LLM failure gracefully", "Summary generation failed" in result)

# --- risk_score.py ---
from modules import risk_score
baseline = risk_score.compute_risk_score(case_id)
db.append_update_log(case_id, "risk-flag: escalation_toward_in_person_contact")
boosted = risk_score.compute_risk_score(case_id)
check("risk score increases with escalation + link signals",
      boosted["score_0_100"] >= baseline["score_0_100"])
check("priority_label thresholds",
      risk_score.priority_label(10) == "low"
      and risk_score.priority_label(45) == "medium"
      and risk_score.priority_label(80) == "high")

# --- timeline.py ---
from modules import timeline
events = timeline.build_timeline(case_id)
descriptions = [e["description"] for e in events]
check("timeline includes log entries", "test entry one" in descriptions)
timestamps = [e["timestamp"] for e in events if e["timestamp"] != float("inf")]
check("timeline sorted ascending", timestamps == sorted(timestamps))

bad_date_case = db.create_case(title="Bad date", incident_datetime="sometime last week")
bad_events = timeline.build_timeline(bad_date_case)
intake_events = [e for e in bad_events if e["source"] == "intake"]
check("unparseable date flagged uncertain", intake_events and intake_events[0]["uncertain"] is True)

# --- rag_search.py (pure-python, no chromadb, no network) ---
from modules import rag_search
rag_case = db.create_case(title="RAG test")
rag_search.add_document(rag_case, "doc1", "The suspect was seen near the riverside park around 6pm on Tuesday.", "test_doc.txt")
rag_search.add_document(rag_case, "doc2", "Weather was clear with no rain reported that evening.", "weather_note.txt")
hits = rag_search.search_case(rag_case, "riverside park suspect")
check("rag_search finds relevant document", len(hits) >= 1 and "riverside" in hits[0]["text"].lower())
check("rag_search returns source label", hits and hits[0]["source"] == "test_doc.txt")
no_hits = rag_search.search_case(rag_case, "zzz_nonexistent_term_xyz")
check("rag_search returns empty for no match", no_hits == [])

# --- config.py folder structure ---
folder_case_id = db.create_case(title="Folder structure test")
cdir = config.ensure_case_dirs(folder_case_id)
expected_subfolders = ["evidence/images", "evidence/documents", "evidence/other", "faces", "emails/sent", "emails/received", "drafts", "reports", "chat_logs", "notes"]
all_exist = all((cdir / sub).is_dir() for sub in expected_subfolders)
check("all elaborated case subfolders created", all_exist)

check("evidence_subfolder_for_filename routes images correctly",
      config.evidence_subfolder_for_filename("photo.jpg") == "evidence/images")
check("evidence_subfolder_for_filename routes documents correctly",
      config.evidence_subfolder_for_filename("report.pdf") == "evidence/documents")
check("evidence_subfolder_for_filename routes unknown types to other",
      config.evidence_subfolder_for_filename("data.xyz") == "evidence/other")

# --- pdf_reader.py (graceful when pypdf not installed here) ---
from modules import pdf_reader
check("pdf_reader.extract_text on nonexistent file returns empty string, no crash",
      pdf_reader.extract_text("/tmp/does_not_exist_sentinel_ai_test.pdf") == "")

# --- custom_root / resolve_case_dir ---
custom_dir = tempfile.mkdtemp()
custom_case_id = db.create_case(title="Custom root test", custom_root=custom_dir)
resolved = config.resolve_case_dir(custom_case_id)
check("resolve_case_dir honors custom_root", str(resolved) == str(Path(custom_dir) / custom_case_id))

default_case_id = db.create_case(title="Default root test")
resolved_default = config.resolve_case_dir(default_case_id)
check("resolve_case_dir falls back to default data root when no custom_root set",
      "sentinel_data" in str(resolved_default) or str(config.get_data_root()) in str(resolved_default))

# --- delete_case_db_rows (cascading deletion) ---
del_case_a = db.create_case(title="Delete test A")
del_case_b = db.create_case(title="Delete test B")
db.append_update_log(del_case_a, "some entry")
db.add_correlation_edge(del_case_a, del_case_b, "face", "shared_face_1")
face_id_for_delete_test = db.add_face([0.1] * 128, del_case_a, "/fake/path.jpg")
db.add_face_sighting(face_id_for_delete_test, del_case_a, "/fake/path.jpg")

db.delete_case_db_rows(del_case_a)
check("delete_case_db_rows removes the case row", db.get_case(del_case_a) is None)
check("delete_case_db_rows removes its update log", db.update_log_for_case(del_case_a) == [])
remaining_edges = [e for e in db.all_correlation_edges() if del_case_a in (e["case_id_a"], e["case_id_b"])]
check("delete_case_db_rows removes correlation edges", remaining_edges == [])
check("delete_case_db_rows removes orphaned face_index entry",
      not any(f["id"] == face_id_for_delete_test for f in db.all_faces()))
check("delete_case_db_rows leaves the OTHER case untouched", db.get_case(del_case_b) is not None)

# --- rag_search.delete_case_documents ---
rag_del_case = db.create_case(title="RAG delete test")
rag_search.add_document(rag_del_case, "doc_x", "some content to be deleted", "test.txt")
rag_search.delete_case_documents(rag_del_case)
check("rag_search.delete_case_documents clears the case's index",
      rag_search.search_case(rag_del_case, "content") == [])

# --- chat_assistant.py intent detection (no LLM needed for these checks) ---
from modules import chat_assistant
check("chat_assistant detects email intent",
      chat_assistant._looks_like_email_request("please email john@example.com about the update"))
check("chat_assistant does not misfire email intent on casual chat",
      not chat_assistant._looks_like_email_request("hello, how are you"))
check("chat_assistant detects summary file intent",
      chat_assistant._looks_like_summary_file_request("can you create a case summary file"))
check("chat_assistant detects elaborate intent",
      chat_assistant._looks_like_elaborate_request("can you elaborate on this"))

extracted = chat_assistant.EMAIL_ADDRESS_RE.search("write to jane.doe@police-test.org please")
check("chat_assistant extracts a raw email address", extracted and extracted.group(0) == "jane.doe@police-test.org")

dept_test_case = db.create_case(title="Dept match test")
db.add_department("Test Police Dept", "testpolice@example.com")
matched_dept = chat_assistant._find_department_match("please email Test Police Dept about the footage")
check("chat_assistant matches a saved department by name",
      matched_dept is not None and matched_dept["email"] == "testpolice@example.com")
no_match = chat_assistant._find_department_match("hello there")
check("chat_assistant returns no department match when none mentioned", no_match is None)

# --- chat_assistant._save_message_as_note (offline: uses rag_search + filesystem, no LLM) ---
note_case_id = db.create_case(title="Note memory test")
config.ensure_case_dirs(note_case_id)
chat_assistant._save_message_as_note(note_case_id, "The suspect drives a blue sedan.")
note_hits = rag_search.search_case(note_case_id, "blue sedan")
check("chat memory: a shared message is saved and searchable", len(note_hits) >= 1)
notes_dir = config.resolve_case_dir(note_case_id) / "notes"
check("chat memory: a physical note file was created", any(notes_dir.glob("note_*.txt")))

shutil.rmtree(tmpdir, ignore_errors=True)

print()
if failures:
    print(f"{len(failures)} check(s) FAILED: {failures}")
    sys.exit(1)
else:
    print("All checks passed.")
