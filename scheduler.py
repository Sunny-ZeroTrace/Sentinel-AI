"""
Sentinel AI background scheduler.

Runs as its own process (started by run.py alongside the FastAPI server).
Handles
anything time-based that must keep working whether or not the UI is open:

- Checking each awaiting-reply email thread for new messages.
- Firing follow-up drafts once the configured interval has passed with no
  reply (real: hours, demo: seconds — same code path, one config number).
- Periodically re-scanning the global face index for new cross-case links.

Every send action still requires a human click in the UI (drafts are
written to the case's drafts/ folder and flagged in the DB as
'pending_approval' — the scheduler NEVER sends on its own).
"""
import json
import time
import uuid
from pathlib import Path

import db
import config
from modules import gmail_client
from modules.update_log import log_event


def get_followup_interval_seconds() -> int:
    demo_mode = db.get_setting("demo_mode", default=False)
    return (
        config.DEMO_FOLLOWUP_INTERVAL_SECONDS
        if demo_mode
        else config.REAL_FOLLOWUP_INTERVAL_SECONDS
    )


def check_gmail_threads():
    if not gmail_client.is_configured():
        return  # Gmail not set up yet — nothing to do, no crash

    threads = db.list_awaiting_threads()
    for thread in threads:
        known_ids = set(
            json.loads(db.get_setting(f"known_msg_ids_{thread['id']}", default="[]"))
        )
        try:
            new_messages = gmail_client.list_new_messages_in_thread(
                thread["gmail_thread_id"], known_ids
            )
        except Exception as e:
            log_event(thread["case_id"], f"Gmail check failed for thread {thread['id']}: {e}")
            continue

        if new_messages:
            case_dir = config.resolve_case_dir(thread["case_id"])
            received_dir = case_dir / "emails" / "received"
            received_dir.mkdir(parents=True, exist_ok=True)

            for msg in new_messages:
                text = gmail_client.extract_plain_text(msg)
                (received_dir / f"{msg['id']}.txt").write_text(text, encoding="utf-8")
                attachments = gmail_client.extract_attachments_routed(msg, case_dir)
                _process_received_attachments(thread["case_id"], attachments)

                known_ids.add(msg["id"])
                log_event(
                    thread["case_id"],
                    f"Reply received in thread with {thread['department_label']} "
                    f"({len(attachments)} attachment(s) saved and processed).",
                )

            db.set_setting(f"known_msg_ids_{thread['id']}", json.dumps(list(known_ids)))
            db.mark_thread_replied(thread["id"])


def _process_received_attachments(case_id: str, attachment_paths: list) -> None:
    """Runs incoming evidence through the same pipeline manual uploads get:
    face detection, PDF text extraction, image captioning, RAG indexing —
    so evidence that arrives via Gmail isn't second-class to what's
    uploaded through the UI."""
    from modules import faces as faces_mod
    from modules import pdf_reader
    from modules import image_caption
    from modules import rag_search
    from pathlib import Path

    for path_str in attachment_paths:
        path = Path(path_str)
        suffix = path.suffix.lower()

        if suffix in config.IMAGE_EXTENSIONS:
            if faces_mod.is_available():
                results = faces_mod.process_evidence_photo(str(path), case_id)
                log_event(case_id, f"Received evidence photo processed: {path.name} ({len(results)} face(s)).")
            caption = image_caption.describe_image(str(path))
            rag_search.add_document(case_id, f"{case_id}_{path.name}_caption", caption, f"{path.name} (received, photo description)")
            log_event(case_id, f"Received photo description ({path.name}): {caption}")

        elif suffix == ".pdf":
            text = pdf_reader.extract_text(str(path))
            if text:
                rag_search.add_document(case_id, f"{case_id}_{path.name}", text, f"{path.name} (received)")
                log_event(case_id, f"Received PDF indexed: {path.name} ({len(text)} chars).")

        elif suffix == ".txt":
            text = path.read_text(encoding="utf-8", errors="ignore")
            rag_search.add_document(case_id, f"{case_id}_{path.name}", text, f"{path.name} (received)")
            log_event(case_id, f"Received text file indexed: {path.name}.")


def check_followups():
    interval = get_followup_interval_seconds()
    threads = db.list_awaiting_threads()
    for thread in threads:
        elapsed = time.time() - (thread["last_sent_at"] or 0)
        if elapsed >= interval:
            _draft_followup(thread)


def _draft_followup(thread: dict):
    """Writes a follow-up draft for human approval. Does NOT send it."""
    case_dir = config.resolve_case_dir(thread["case_id"])
    drafts_dir = case_dir / "drafts"
    drafts_dir.mkdir(parents=True, exist_ok=True)

    draft_text = (
        f"Follow-up — Case {thread['case_id']}\n"
        f"To: {thread['department_email']} ({thread['department_label']})\n"
        f"Re: {thread['subject']}\n\n"
        "Following up on our earlier request — we have not yet received a "
        "response. Could you please provide an update at your earliest "
        "convenience? Thank you for your assistance.\n"
    )
    draft_path = drafts_dir / f"followup_{thread['id']}_{int(time.time())}.txt"
    draft_path.write_text(draft_text, encoding="utf-8")

    db.touch_thread_sent(thread["id"])  # reset the timer so it doesn't spam drafts
    log_event(
        thread["case_id"],
        f"Follow-up draft prepared for {thread['department_label']} "
        f"(awaiting officer approval to send) — {draft_path.name}",
    )


def rescan_face_correlations():
    """Cheap periodic pass to catch any cross-case face links that weren't
    caught at upload time (e.g. if faces were added out of order)."""
    from modules.faces import cases_for_face

    for face in db.all_faces():
        cases = cases_for_face(face["id"])
        if len(cases) < 2:
            continue
        existing_edges = db.all_correlation_edges()
        for i in range(len(cases)):
            for j in range(i + 1, len(cases)):
                a, b = cases[i], cases[j]
                already_linked = any(
                    {e["case_id_a"], e["case_id_b"]} == {a, b} and e["entity_type"] == "face"
                    for e in existing_edges
                )
                if not already_linked:
                    db.add_correlation_edge(a, b, "face", face["id"])


SUMMARY_REFRESH_INTERVAL_SECONDS = 180  # don't regenerate more often than this per case


def refresh_stale_summaries():
    """Periodically regenerates AI summaries for cases with new log
    activity — but throttled per case, so this never becomes another
    source of per-action slowness. Runs in the background scheduler,
    never blocking anything the user is doing in the UI."""
    from modules.update_log import regenerate_ai_summary

    for case in db.list_cases(status="active"):
        case_id = case["id"]
        last_regen_key = f"last_summary_regen_{case_id}"
        last_regen = db.get_setting(last_regen_key, default=0)
        if time.time() - last_regen < SUMMARY_REFRESH_INTERVAL_SECONDS:
            continue
        log_rows = db.update_log_for_case(case_id)
        if not log_rows:
            continue
        most_recent_entry_time = log_rows[-1]["created_at"]
        if most_recent_entry_time <= last_regen:
            continue  # nothing new since the last summary was generated
        regenerate_ai_summary(case_id)
        db.set_setting(last_regen_key, time.time())


def run_forever():
    db.init_db()
    print("Sentinel AI scheduler started. Polling every", config.SCHEDULER_TICK_SECONDS, "seconds.")
    while True:
        try:
            check_gmail_threads()
            check_followups()
            rescan_face_correlations()
            refresh_stale_summaries()
        except Exception as e:
            print("Scheduler tick error (continuing):", e)
        time.sleep(config.SCHEDULER_TICK_SECONDS)


if __name__ == "__main__":
    run_forever()
