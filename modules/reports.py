"""
Draft report generation. Every output here is a DRAFT — the UI must always
show it for investigator review/edit before it's treated as final or sent
anywhere. Nothing in this module sends or finalizes a report on its own.
"""
import datetime

import db
import llm_client
from config import resolve_case_dir


def draft_case_report(case_id: str) -> str:
    case = db.get_case(case_id)
    log_rows = db.update_log_for_case(case_id)
    threads = db.list_threads_for_case(case_id)

    log_text = "\n".join(f"- {r['entry']}" for r in log_rows)
    thread_text = "\n".join(
        f"- {t['department_label']}: {t['status']}" for t in threads
    )

    prompt = (
        "Draft a factual, neutral case summary report for a child-protection "
        "investigation, for internal review by a supervisor. Use only the "
        "information given below. Include: case overview, key timeline "
        "points, evidence gathered, correlations found, current risk "
        "assessment, and outstanding requests. Mark this clearly as a DRAFT "
        "requiring officer review before distribution.\n\n"
        f"Case: {case.get('title')}\n"
        f"Status: {case.get('status')}\nPriority: {case.get('priority')}\n"
        f"Risk score: {case.get('risk_score')}\n"
        f"Location: {case.get('location')}\nIncident time: {case.get('incident_datetime')}\n"
        f"Description: {case.get('description')}\n\n"
        f"Log:\n{log_text}\n\nEmail requests:\n{thread_text}"
    )

    try:
        result = llm_client.call_llm(prompt)
        body = result.text
    except Exception as e:
        body = (
            f"(Auto-draft unavailable: {e})\n\n"
            f"Manual fallback summary:\nCase: {case.get('title')}\n"
            f"Status: {case.get('status')}, Priority: {case.get('priority')}\n"
            f"Log entries: {len(log_rows)}\nEmail threads: {len(threads)}"
        )

    header = (
        f"# DRAFT REPORT — Case {case_id}\n"
        f"Generated: {datetime.datetime.now().isoformat()}\n"
        "**This is an AI-drafted summary. It must be reviewed and approved "
        "by an authorized officer before use or distribution.**\n\n"
    )
    full_text = header + body

    reports_dir = resolve_case_dir(case_id) / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    out_path = reports_dir / f"draft_report_{int(datetime.datetime.now().timestamp())}.md"
    out_path.write_text(full_text, encoding="utf-8")

    return str(out_path)
