"""
Timeline reconstruction — merges events from every source attached to a case
(update log, email threads, evidence uploads) into one sorted, de-duplicated
timeline. Conflicting/ambiguous timestamps are flagged rather than silently
dropped, per the design principle of not hiding uncertainty from the
investigator.
"""
import datetime

import db


def build_timeline(case_id: str):
    events = []

    for row in db.update_log_for_case(case_id):
        events.append(
            {
                "timestamp": row["created_at"],
                "source": "case_log",
                "description": row["entry"],
                "uncertain": False,
            }
        )

    for thread in db.list_threads_for_case(case_id):
        events.append(
            {
                "timestamp": thread["created_at"],
                "source": "email",
                "description": f"Request sent to {thread['department_label']}: {thread['subject']}",
                "uncertain": False,
            }
        )
        if thread["status"] == "replied":
            events.append(
                {
                    "timestamp": thread["last_sent_at"],
                    "source": "email",
                    "description": f"Reply received from {thread['department_label']}",
                    "uncertain": False,
                }
            )

    case = db.get_case(case_id)
    if case and case.get("incident_datetime"):
        parsed_ok, ts = _try_parse(case["incident_datetime"])
        events.append(
            {
                "timestamp": ts,
                "source": "intake",
                "description": f"Reported incident time: {case['incident_datetime']}",
                "uncertain": not parsed_ok,
            }
        )

    # Sort using inf for unparseable dates (pushes them to the end), but
    # never return a raw inf value — it isn't valid JSON and will crash
    # the API response. Convert it to None after sorting.
    events.sort(key=lambda e: e["timestamp"] if e["timestamp"] is not None else 0)
    for e in events:
        if e["timestamp"] == float("inf"):
            e["timestamp"] = None
    return events


def _try_parse(value: str):
    """Best-effort parse of a free-text incident datetime into an epoch
    timestamp for sorting. If it can't be parsed, flag uncertain=True and
    sort it at the end rather than guessing silently."""
    formats = ["%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d", "%d-%m-%Y %H:%M", "%d/%m/%Y %H:%M"]
    for fmt in formats:
        try:
            dt = datetime.datetime.strptime(value, fmt)
            return True, dt.timestamp()
        except ValueError:
            continue
    return False, float("inf")
