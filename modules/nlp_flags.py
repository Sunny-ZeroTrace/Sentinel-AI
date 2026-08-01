"""
NLP risk-pattern flagging for chat/text evidence.

Deliberately scoped: the model is asked to identify which broad behavioral
CATEGORIES appear (e.g. secrecy requests, isolation tactics, escalation,
gift/flattery patterns) and cite which lines triggered each category — it
does not compile a reusable phrase library, and the categories themselves
are the standard, publicly-documented ones used in child-protection
training material.
"""
import json

import db
import llm_client
from modules.update_log import log_event

CATEGORIES = [
    "secrecy_or_isolation_request",
    "escalation_toward_in_person_contact",
    "gift_or_flattery_pattern",
    "boundary_testing",
    "other_concern",
]

_PROMPT_TEMPLATE = """You are assisting an authorized child-protection investigator
by triaging chat text for review — you are not making any final determination.

Read the conversation excerpt below. For each category in this fixed list,
say whether it is present (true/false) and, if true, give ONE short
paraphrased reason (not a verbatim quote) referencing which part of the
excerpt suggests it.

Categories: {categories}

Respond ONLY as JSON in this exact shape, nothing else:
{{"flags": [{{"category": "...", "present": true/false, "reason": "..."}}]}}

Conversation excerpt:
---
{text}
---
"""


def flag_text(case_id: str, text: str, source_label: str = "chat evidence") -> dict:
    prompt = _PROMPT_TEMPLATE.format(categories=", ".join(CATEGORIES), text=text[:8000])
    try:
        result = llm_client.call_llm(prompt, json_mode=True)
        parsed = json.loads(result.text)
    except Exception as e:
        parsed = {"flags": [], "error": str(e)}

    present_flags = [f for f in parsed.get("flags", []) if f.get("present")]
    if present_flags:
        cat_list = ", ".join(f["category"] for f in present_flags)
        log_event(
            case_id,
            f"risk-flag: NLP scan of {source_label} raised categories: {cat_list}",
        )

    return parsed
