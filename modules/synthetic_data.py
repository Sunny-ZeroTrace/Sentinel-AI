"""
Generates one fully synthetic sample case so the app has something
realistic to demo without ever touching real evidence. All names,
locations, and details below are fictional placeholders.
"""
import db
import config
from modules.update_log import log_event
from modules.rag_search import add_document


def create_sample_case() -> str:
    case_id = db.create_case(
        title="Sample Case — Demo Only (fictional)",
        victim_name="Jane Doe (fictional)",
        location="Fictional Riverside Park, Sampletown",
        incident_datetime="2026-07-20 18:00",
        description=(
            "DEMO DATA. A fictional report describing a child last seen near "
            "Fictional Riverside Park around 6 PM. This case exists only to "
            "demonstrate the platform's workflow end-to-end."
        ),
        assigned_officer="Demo Officer",
        priority="unassessed",
    )
    config.ensure_case_dirs(case_id)

    log_event(case_id, "Case created from synthetic demo data generator.")
    log_event(case_id, "Intake form completed with fictional placeholder details.")

    sample_chat = (
        "This is a fictional, synthetic chat sample created only for demo "
        "purposes — no real persons or events. [demo] User A: hey, are you "
        "free after school today? [demo] User B: maybe, why? [demo] User A: "
        "just wanted to hang out, don't tell your parents though, it'll be "
        "our secret."
    )
    add_document(case_id, f"{case_id}_chat_1", sample_chat, "sample chat log (synthetic)")
    log_event(case_id, "Synthetic sample chat log indexed for case chat search.")

    log_event(case_id, "Demo request drafted to 'Fictional Police Dept' for CCTV footage near reported location/time.")

    return case_id
