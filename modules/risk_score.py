"""
Risk scoring — transparent, weighted, explainable. This is deliberately NOT
a black-box ML model: every score decomposes into named factors an
investigator can see and challenge. Weights live in config.RISK_WEIGHTS.
"""
import time

import db
import config


def compute_risk_score(case_id: str) -> dict:
    case = db.get_case(case_id)
    if not case:
        return {"score": 0.0, "factors": {}}

    factors = {}

    # Recency: more recent activity -> higher urgency contribution
    days_since_update = (time.time() - (case.get("updated_at") or time.time())) / 86400
    recency_signal = max(0.0, 1.0 - min(days_since_update / 14, 1.0))
    factors["recency"] = round(recency_signal, 3)

    # Escalation language: was a grooming/escalation flag raised anywhere
    # in this case's chat/nlp flags? (looked up via update log text search,
    # since flags get logged there when nlp_flags.py runs)
    log_rows = db.update_log_for_case(case_id)
    escalation_hit = any("risk-flag" in r["entry"].lower() for r in log_rows)
    factors["escalation_language"] = 1.0 if escalation_hit else 0.0

    # Cross-case link: does this case share any correlation edge with another?
    edges = db.all_correlation_edges()
    has_link = any(e["case_id_a"] == case_id or e["case_id_b"] == case_id for e in edges)
    factors["cross_case_link"] = 1.0 if has_link else 0.0

    # Known-hash match: any evidence in this case matched the (demo) known list?
    hash_hit = any("known-hash match" in r["entry"].lower() for r in log_rows)
    factors["known_hash_match"] = 1.0 if hash_hit else 0.0

    # Imminent contact signal: simple keyword presence in description/log,
    # as a stand-in for a more advanced NLP pass (nlp_flags.py handles the
    # richer version; this is a fast structural check).
    imminent_terms = ("meet", "come alone", "pick you up", "today", "tonight")
    text_blob = (case.get("description") or "").lower() + " " + " ".join(
        r["entry"].lower() for r in log_rows
    )
    imminent_hit = any(term in text_blob for term in imminent_terms)
    factors["imminent_contact_signal"] = 1.0 if imminent_hit else 0.0

    weighted_sum = sum(factors[k] * config.RISK_WEIGHTS[k] for k in factors)
    max_possible = sum(config.RISK_WEIGHTS.values())
    normalized_score = round((weighted_sum / max_possible) * 100, 1) if max_possible else 0.0

    breakdown = {
        "score_0_100": normalized_score,
        "factors": factors,
        "weights": config.RISK_WEIGHTS,
    }

    db.update_case(case_id, risk_score=normalized_score, risk_breakdown=str(breakdown))
    return breakdown


def priority_label(score: float) -> str:
    if score >= 60:
        return "high"
    if score >= 30:
        return "medium"
    return "low"
