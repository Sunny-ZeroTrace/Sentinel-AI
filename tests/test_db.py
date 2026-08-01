import os
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


def test_case_crud(temp_data_root):
    db = temp_data_root
    case_id = db.create_case(title="Test case", location="Nowhere")
    case = db.get_case(case_id)
    assert case["title"] == "Test case"
    assert case["status"] == "active"

    db.update_case(case_id, status="closed", priority="high")
    updated = db.get_case(case_id)
    assert updated["status"] == "closed"
    assert updated["priority"] == "high"


def test_api_key_priority_ordering(temp_data_root):
    db = temp_data_root
    db.add_api_key("gemini", "key-b", label="b", priority=50)
    db.add_api_key("gemini", "key-a", label="a", priority=10)
    keys = db.list_api_keys(provider="gemini")
    assert keys[0]["label"] == "a"
    assert keys[1]["label"] == "b"


def test_settings_roundtrip(temp_data_root):
    db = temp_data_root
    db.set_setting("demo_mode", True)
    assert db.get_setting("demo_mode") is True
    db.set_setting("demo_mode", False)
    assert db.get_setting("demo_mode") is False


def test_update_log_and_correlation(temp_data_root):
    db = temp_data_root
    case_a = db.create_case(title="A")
    case_b = db.create_case(title="B")
    db.append_update_log(case_a, "test entry")
    log = db.update_log_for_case(case_a)
    assert len(log) == 1
    assert log[0]["entry"] == "test entry"

    db.add_correlation_edge(case_a, case_b, "face", "face123")
    edges = db.all_correlation_edges()
    assert len(edges) == 1
    assert edges[0]["entity_type"] == "face"
