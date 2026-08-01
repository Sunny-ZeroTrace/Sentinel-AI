"""
Unified case chat assistant.

Fixes a real bug from the previous version: the chat used to ONLY answer
using search-matched evidence, and gave a canned refusal ("no indexed
documents...") for anything else — including a plain "hello". That made
it feel broken for casual conversation. Now it always responds naturally
like a helpful assistant, and additionally uses evidence context when
something relevant was found — it never refuses to engage just because
nothing matched a search.

This module also handles:
- Email intent: drafts (never auto-sends) an email when asked.
- Memory: every message you send is automatically saved into the case's
  notes/ folder and indexed for search — so anything you tell it about
  the case becomes permanent, searchable case memory, not just a one-off
  chat reply. If you ask it to "elaborate" or "expand" on something, it
  writes a fuller structured note instead of just a short save.
- Summary-file requests: "give me a full summary" / "create a case
  summary file" triggers generation of a real CaseSummary.docx via
  modules/case_export.py.
"""
import re
import time

import db
import config
import llm_client
from modules import rag_search

EMAIL_ADDRESS_RE = re.compile(r"[\w.\-]+@[\w.\-]+\.\w+")
EMAIL_INTENT_KEYWORDS = (
    "email", "e-mail", "mail to", "send a message to", "write to",
    "draft a message", "draft an email", "compose",
)
ELABORATE_KEYWORDS = ("elaborate", "expand on", "go through that", "write it up", "elaborate on this")
SUMMARY_FILE_KEYWORDS = (
    "summary file", "case summary file", "full summary", "full context",
    "generate a report file", "create a summary", "casesummary",
)


def _looks_like_email_request(text: str) -> bool:
    lower = text.lower()
    return any(k in lower for k in EMAIL_INTENT_KEYWORDS)


def _looks_like_summary_file_request(text: str) -> bool:
    lower = text.lower()
    return any(k in lower for k in SUMMARY_FILE_KEYWORDS)


def _looks_like_elaborate_request(text: str) -> bool:
    lower = text.lower()
    return any(k in lower for k in ELABORATE_KEYWORDS)


def _find_department_match(text: str):
    """Fuzzy-ish match: if any saved department's label appears in the
    message, use that as the recipient. This is how the assistant tells
    apart the different departments/Gmail recipients you've saved in
    Settings — by name, from what you type."""
    lower = text.lower()
    for dept in db.list_departments():
        if dept["label"].lower() in lower:
            return dept
    return None


def _save_message_as_note(case_id: str, message: str, elaborated_text: str = None) -> None:
    """Always-on memory: whatever you tell the chat gets saved into the
    case's notes/ folder and indexed for search, so it's remembered and
    answerable later — this is what makes the chat able to 'do anything'
    with information you share, not just respond once and forget it."""
    cdir = config.resolve_case_dir(case_id)
    notes_dir = cdir / "notes"
    notes_dir.mkdir(parents=True, exist_ok=True)

    content_to_save = elaborated_text or message
    note_id = f"note_{int(time.time() * 1000)}"
    note_path = notes_dir / f"{note_id}.txt"
    note_path.write_text(content_to_save, encoding="utf-8")

    rag_search.add_document(case_id, f"{case_id}_{note_id}", content_to_save, "chat note")

    from modules.update_log import log_event
    log_event(case_id, f"Note saved from chat: {content_to_save[:80]}{'...' if len(content_to_save) > 80 else ''}")


def handle_message(case_id: str, message: str) -> dict:
    """Returns {"answer": str, "sources": [...], "email_draft": dict|None,
    "summary_file_path": str|None}"""

    if _looks_like_summary_file_request(message):
        return _handle_summary_file_request(case_id)

    if _looks_like_email_request(message):
        draft = _try_build_email_draft(case_id, message)
        if draft:
            return {
                "answer": (
                    f"I've drafted an email to {draft['to_label']} ({draft['to']}) "
                    "— review it below and click Send when you're ready. Nothing "
                    "is sent automatically."
                ),
                "sources": [], "email_draft": draft, "summary_file_path": None,
            }
        # Looked like an email request but no recipient could be identified —
        # fall through to a normal conversational reply.

    if _looks_like_elaborate_request(message):
        elaborated = _elaborate(case_id, message)
        _save_message_as_note(case_id, message, elaborated_text=elaborated)
        return {
            "answer": f"Here's the elaborated write-up — I've saved this to the case notes:\n\n{elaborated}",
            "sources": [], "email_draft": None, "summary_file_path": None,
        }

    # Default: save whatever was shared as case memory, then respond
    # conversationally (using it as context immediately, not just later).
    _save_message_as_note(case_id, message)
    result = _conversational_answer(case_id, message)
    result["email_draft"] = None
    result["summary_file_path"] = None
    return result


def _handle_summary_file_request(case_id: str) -> dict:
    from modules import case_export
    try:
        path = case_export.generate_docx(case_id)
        answer = (
            "I've put together a full CaseSummary.docx with the case details, "
            f"timeline, log, and evidence photos — saved to the case's "
            f"summary/ folder ({path.split('/')[-1] if '/' in path else path.split(chr(92))[-1]})."
        )
    except Exception as e:
        answer = f"Couldn't generate the summary file automatically: {e}"
        path = None
    return {"answer": answer, "sources": [], "email_draft": None, "summary_file_path": path}


def _elaborate(case_id: str, message: str) -> str:
    case = db.get_case(case_id)
    prompt = (
        "The investigator shared the following about this case and asked "
        "you to elaborate/expand on it into a clear, structured written "
        "note (a few sentences to a short paragraph, factual, no "
        "speculation beyond what's given).\n\n"
        f"Case: {case.get('title') if case else case_id}\n\n"
        f"Investigator's message: {message}"
    )
    try:
        result = llm_client.call_llm(prompt)
        return result.text.strip()
    except Exception as e:
        return f"(Could not elaborate automatically: {e}) Original message saved as-is: {message}"


def _try_build_email_draft(case_id: str, message: str):
    case = db.get_case(case_id)
    address_match = EMAIL_ADDRESS_RE.search(message)
    department = _find_department_match(message)

    if address_match:
        to_address = address_match.group(0)
        to_label = department["label"] if department else to_address
    elif department:
        to_address = department["email"]
        to_label = department["label"]
    else:
        return None  # no identifiable recipient

    case_title = case.get("title") if case else case_id
    prompt = (
        "Draft a professional, factual email body based on this instruction "
        f"from an investigator working case '{case_title}'. Instruction: "
        f"{message}\n\nReply with the email body only — no subject line, "
        "no preamble, no signature placeholder text beyond a simple closing."
    )
    try:
        result = llm_client.call_llm(prompt)
        body = result.text.strip()
    except Exception as e:
        body = f"(Could not auto-draft the body: {e}) Please write it manually below."

    return {
        "to": to_address,
        "to_label": to_label,
        "subject": f"Regarding case {case_id}",
        "body": body,
    }


def _conversational_answer(case_id: str, message: str) -> dict:
    hits = rag_search.search_case(case_id, message)
    case = db.get_case(case_id)

    context_block = ""
    if hits:
        context_block = "\n\nRelevant case evidence found:\n" + "\n\n".join(
            f"[Source: {h['source']}]\n{h['text']}" for h in hits
        )

    prompt = (
        "You are chatting with an investigator about a specific case — be "
        "warm, direct, and genuinely conversational. Respond naturally to "
        "greetings and general questions; never refuse to engage just "
        "because there's no matching evidence for a casual message. When "
        "evidence context is provided below and it's relevant to the "
        "question, use it and mention the source; otherwise just have a "
        "normal, helpful conversation.\n\n"
        f"Case: {case.get('title') if case else case_id}\n"
        f"Status: {case.get('status') if case else ''}\n"
        f"Description: {case.get('description') if case else ''}"
        f"{context_block}\n\n"
        f"Investigator: {message}"
    )
    try:
        result = llm_client.call_llm(prompt)
        answer = result.text.strip()
    except Exception as e:
        answer = f"(Local LLM unavailable right now: {e}. Make sure `ollama serve` is running.)"

    return {"answer": answer, "sources": [h["source"] for h in hits], "email_draft": None}
