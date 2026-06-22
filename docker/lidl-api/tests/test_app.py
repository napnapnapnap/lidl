import json
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def data_dir(tmp_path):
    return tmp_path


@pytest.fixture
def client(data_dir, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("SCRIPTS_DIR", "/scripts")
    monkeypatch.setenv("LIDL_COUNTRY", "FR")
    import importlib
    import app as app_module
    importlib.reload(app_module)
    from app import app
    return TestClient(app)


# /health
def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


# /status
def test_status_no_data(client):
    r = client.get("/status")
    assert r.status_code == 200
    body = r.json()
    assert body["auth_valid"] is False
    assert body["last_sync"] is None
    assert body["receipt_count"] == 0


def test_status_with_data(client, data_dir):
    (data_dir / "receipts_summaries.json").write_text(json.dumps({
        "fetched_at": "2026-06-20T10:00:00Z",
        "items": []
    }))
    (data_dir / "receipts_detail.json").write_text(json.dumps({
        "total_receipts": 42,
        "receipts": []
    }))
    (data_dir / "lidl_auth_state.json").write_text("{}")
    r = client.get("/status")
    assert r.status_code == 200
    body = r.json()
    assert body["auth_valid"] is True
    assert body["last_sync"] == "2026-06-20T10:00:00Z"
    assert body["receipt_count"] == 42


# /jobs
def test_jobs_not_found(client):
    r = client.get("/jobs/doesnotexist")
    assert r.status_code == 404


# /update
def test_update_returns_job_id(client, data_dir):
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
        r = client.post("/update")
    assert r.status_code == 200
    assert "job_id" in r.json()


def test_update_first_run_uses_all_command(client, data_dir):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch("subprocess.run", side_effect=fake_run):
        client.post("/update")

    time.sleep(0.2)
    assert "all" in captured.get("cmd", [])


def test_update_subsequent_run_uses_update_command(client, data_dir):
    (data_dir / "receipts_summaries.json").write_text(json.dumps({
        "fetched_at": "2026-06-20T10:00:00Z",
        "items": []
    }))
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch("subprocess.run", side_effect=fake_run):
        client.post("/update")

    time.sleep(0.2)
    assert "update" in captured.get("cmd", [])


def test_reauth_returns_job_id(client):
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        r = client.post("/reauth")
    assert r.status_code == 200
    assert "job_id" in r.json()


# /query
def test_query_returns_parsed_output(client):
    fake_output = json.dumps({
        "start": None, "end": None, "receipt_count": 3,
        "total_spent": 42.50, "receipts": []
    })
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=fake_output, stderr="")
        r = client.get("/query?days=30")
    assert r.status_code == 200
    assert r.json()["receipt_count"] == 3


def test_query_passes_days_param(client):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return MagicMock(returncode=0, stdout='{"receipts":[]}', stderr="")

    with patch("subprocess.run", side_effect=fake_run):
        client.get("/query?days=7")
    assert "--days" in captured["cmd"]
    assert "7" in captured["cmd"]


def test_query_raises_401_on_unauthorized(client):
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=1, stdout="",
            stderr="HTTP 401: Lidl session cookie is expired or unauthorized"
        )
        r = client.get("/query")
    assert r.status_code == 401


# /top
def _write_receipts(data_dir, receipts):
    (data_dir / "receipts_detail.json").write_text(json.dumps({
        "total_receipts": len(receipts),
        "receipts": receipts
    }))


def test_top_no_data_returns_404(client):
    r = client.get("/top")
    assert r.status_code == 404


def test_top_counts_items(client, data_dir):
    _write_receipts(data_dir, [{
        "date": "2026-06-20T10:00:00Z",
        "articles": [
            {"description": "Banane vrac", "quantity": 1},
            {"description": "Banane Bio", "quantity": 1},
            {"description": "Yaourt nature", "quantity": 1},
        ]
    }])
    r = client.get("/top?days=30")
    assert r.status_code == 200
    body = r.json()
    assert body["days"] == 30
    assert len(body["items"]) >= 1


def test_top_groups_similar_items(client, data_dir):
    _write_receipts(data_dir, [{
        "date": "2026-06-20T10:00:00Z",
        "articles": [
            {"description": "Banane", "quantity": 1},
            {"description": "Banane vrac", "quantity": 1},
            {"description": "Banane Bio fairtrade", "quantity": 1},
            {"description": "Café Espresso", "quantity": 1},
        ]
    }])
    r = client.get("/top?days=30")
    assert r.status_code == 200
    items = {item["name"]: item["count"] for item in r.json()["items"]}
    banane_count = next((v for k, v in items.items() if "banane" in k.lower()), None)
    assert banane_count == 3


def test_top_respects_days_filter(client, data_dir):
    _write_receipts(data_dir, [{
        "date": "2020-01-01T00:00:00Z",
        "articles": [{"description": "Pain", "quantity": 1}]
    }])
    r = client.get("/top?days=30")
    assert r.status_code == 200
    assert r.json()["items"] == []


def test_top_saves_groups_file(client, data_dir):
    _write_receipts(data_dir, [{
        "date": "2026-06-20T10:00:00Z",
        "articles": [{"description": "Poulet rôti", "quantity": 1}]
    }])
    client.get("/top")
    groups_file = data_dir / "item_groups.json"
    assert groups_file.exists()
    groups = json.loads(groups_file.read_text())
    assert "poulet" in groups


def test_top_uses_existing_groups_file(client, data_dir):
    (data_dir / "item_groups.json").write_text(json.dumps({
        "carte noire": "Café",
        "espresso": "Café",
    }))
    _write_receipts(data_dir, [{
        "date": "2026-06-20T10:00:00Z",
        "articles": [
            {"description": "Carte Noire café", "quantity": 1},
            {"description": "Café Espresso", "quantity": 1},
        ]
    }])
    r = client.get("/top")
    items = {item["name"]: item["count"] for item in r.json()["items"]}
    assert items.get("Café") == 2
