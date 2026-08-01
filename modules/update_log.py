"""
Maintains each case's living memory file: cases/<id>/update.md

Two sections:
1. A "current state" summary at the top.
2. A timestamped running log below it, append-only.

IMPORTANT PERFORMANCE NOTE: log_event() is called by almost every action
in the app (uploading evidence, tagging a face, sending an email, etc.).
Earlier this called the LLM synchronously on every single one of those
events to regenerate the summary — which made every action in the app
wait on an LLM round-trip, even for actions that have nothing to do with
summaries. That was the main cause of the app feeling slow.

Now: log_event() only ever does fast, local work (DB write + rewriting
the log list). The AI-written summary is cached in the database and only
regenerated when explicitly requested — via the "Regenerate AI summary"
button in the Update Log tab, or periodically in the background by
scheduler.py. This keeps every button click in the app fast, and still
gets you an AI summary, just not synchronously blocking every action.
"""
import datetime
from pathlib import Path

import db
import llm_client
from config import resolve_case_dir


def _update_md_path(case_id: str) -> Path:
    return resolve_case_dir(case_id) / "update.md"


def _summary_setting_key(case_id: str) -> str:
    return f"case_summary_{case_id}"


def log_event(case_id: str, entry: str) -> None:
    """Append one event to DB and rewrite the markdown file. Fast — does
    NOT call the LLM. Use regenerate_ai_summary() separately for that."""
    db.append_update_log(case_id, entry)
    _rewrite_markdown(case_id)


def _rewrite_markdown(case_id: str) -> None:
    case = db.get_case(case_id)
    if not case:
        return
    log_rows = db.update_log_for_case(case_id)

    summary = db.get_setting(_summary_setting_key(case_id), default=None)
    if not summary:
        summary = _fallback_summary(case, log_rows)

    lines = [
        f"# Case {case_id} — {case.get('title', '')}",
        "",
        "## Current summary",
        summary,
        "",
        "## Running log",
        "",
    ]
    for row in log_rows:
        ts = datetime.datetime.fromtimestamp(row["created_at"]).strftime("%Y-%m-%d %H:%M:%S")
        lines.append(f"- **{ts}** — {row['entry']}")

    path = _update_md_path(case_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def _fallback_summary(case: dict, log_rows: list) -> str:
    """A fast, no-LLM factual recap — used until an AI summary has been
    generated at least once, or whenever the LLM isn't reachable."""
    return (
        f"Status: {case.get('status')}. Priority: {case.get('priority')}. "
        f"Location: {case.get('location')}. "
        f"{len(log_rows)} logged event(s) so far. "
        "(No AI summary generated yet — click \"Regenerate AI summary\" "
        "in the Update Log tab, or wait for the next automatic refresh.)"
    )


def regenerate_ai_summary(case_id: str) -> str:
    """The one place that actually calls the LLM for a case summary.
    Called explicitly (button click) or periodically by the scheduler —
    never from inside log_event(), so normal app actions stay fast."""
    case = db.get_case(case_id)
    if not case:
        return ""
    log_rows = db.update_log_for_case(case_id)
    recent_entries = "\n".join(f"- {r['entry']}" for r in log_rows[-25:])
    prompt = (
        "Summarize the current state of this child-protection case in 4-6 "
        "plain factual sentences, for an investigator resuming work on it. "
        "Do not speculate beyond what's stated. No headers, just prose.\n\n"
        f"Case title: {case.get('title')}\n"
        f"Status: {case.get('status')}\n"
        f"Priority: {case.get('priority')}\n"
        f"Location: {case.get('location')}\n"
        f"Incident time: {case.get('incident_datetime')}\n"
        f"Description: {case.get('description')}\n\n"
        f"Recent log entries:\n{recent_entries}"
    )
    try:
        result = llm_client.call_llm(prompt)
        summary = result.text.strip()
        db.set_setting(_summary_setting_key(case_id), summary)
        _rewrite_markdown(case_id)
        return summary
    except Exception as e:
        return f"(Summary generation failed: {e})"


def read_markdown(case_id: str) -> str:
    path = _update_md_path(case_id)
    if path.exists():
        return path.read_text(encoding="utf-8")
    return f"# Case {case_id}\n\nNo entries yet."
