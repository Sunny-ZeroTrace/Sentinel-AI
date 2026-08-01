import tempfile

import pytest


@pytest.fixture(autouse=True)
def temp_data_root(monkeypatch):
    tmpdir = tempfile.mkdtemp()
    monkeypatch.setenv("SENTINEL_DATA_ROOT", tmpdir)
    import importlib
    import config as config_mod
    import db as db_mod
    importlib.reload(config_mod)
    importlib.reload(db_mod)
    db_mod.init_db()
    yield db_mod


def test_risk_score_increases_with_signals(temp_data_root):
    db = temp_data_root
    from modules import risk_score

    case_id = db.create_case(title="Risk test", description="normal case, nothing unusual")
    baseline = risk_score.compute_risk_score(case_id)

    db.append_update_log(case_id, "risk-flag: escalation_toward_in_person_contact")
    case_b = db.create_case(title="linked case")
    db.add_correlation_edge(case_id, case_b, "face", "abc")

    boosted = risk_score.compute_risk_score(case_id)
    assert boosted["score_0_100"] >= baseline["score_0_100"]
    assert boosted["factors"]["escalation_language"] == 1.0
    assert boosted["factors"]["cross_case_link"] == 1.0


def test_priority_label_thresholds(temp_data_root):
    from modules import risk_score
    assert risk_score.priority_label(10) == "low"
    assert risk_score.priority_label(45) == "medium"
    assert risk_score.priority_label(80) == "high"


def test_timeline_merges_and_sorts(temp_data_root):
    db = temp_data_root
    from modules import timeline
    import time

    case_id = db.create_case(title="Timeline test", incident_datetime="2026-07-20 18:00")
    db.append_update_log(case_id, "first event")
    time.sleep(0.01)
    db.append_update_log(case_id, "second event")

    events = timeline.build_timeline(case_id)
    descriptions = [e["description"] for e in events]
    assert "first event" in descriptions
    assert "second event" in descriptions
    # sorted ascending by timestamp
    timestamps = [e["timestamp"] for e in events if e["timestamp"] != float("inf")]
    assert timestamps == sorted(timestamps)


def test_timeline_flags_unparseable_incident_time(temp_data_root):
    db = temp_data_root
    from modules import timeline

    case_id = db.create_case(title="Bad date test", incident_datetime="sometime last week")
    events = timeline.build_timeline(case_id)
    intake_events = [e for e in events if e["source"] == "intake"]
    assert len(intake_events) == 1
    assert intake_events[0]["uncertain"] is True
