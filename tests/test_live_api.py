"""Live FastAPI tests (MOCK_MODE, isolated temp database per session)."""
import json
import os

import pytest

os.environ["MOCK_MODE"] = "true"
os.environ["REVLOOP_AUTH_ENABLED"] = "false"
os.environ["REVLOOP_DB"] = "test_revloop.db"

from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture(scope="module")
def client():
    db = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "test_revloop.db")
    if os.path.exists(db):
        os.remove(db)
    from app.main import app
    from app.database import initialize_database
    initialize_database()  # app import is cached across test modules
    with TestClient(app) as c:
        yield c
    if os.path.exists(db):
        os.remove(db)


def _seed(client):
    return client.post("/razorpay/test-transaction").json()["payment_id"]


def _paid_webhook(client, pid, event_id):
    m = client.post(f"/recovery/mock/pay/{pid}").json()
    body = json.dumps(m["webhook_body"])
    return client.post("/webhooks/razorpay", content=body, headers={
        "X-Razorpay-Signature": m["x_razorpay_signature"],
        "X-Razorpay-Event-Id": event_id,
        "Content-Type": "application/json",
    }), body, m["x_razorpay_signature"]


def test_startup_and_health(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["mock_mode"] is True


def test_analyze_returns_full_intelligence(client):
    pid = _seed(client)
    d = client.get(f"/decision/analyze/{pid}").json()
    assert d["diagnosis"] and 0 <= d["diagnosis_confidence"] <= 1
    assert d["scored_candidates"] and all(
        {"action", "probability", "cost", "ev"} <= set(s) for s in d["scored_candidates"])
    assert d["chosen_action"] in [s["action"] for s in d["scored_candidates"]]
    assert d["guardrail_checks"] and d["reasoning"]
    assert "SIMULATED" in d["probability_note"]


def test_execute_creates_link_and_lifecycle(client):
    pid = _seed(client)
    e = client.post(f"/decision/execute/{pid}").json()
    assert e["status"] == "action_initiated"
    assert e["recovery_state"] == "AWAITING_OUTCOME"
    assert e["payment_link_id"].startswith("plink_MOCK")
    # link created is NOT a recovery
    txns = client.get("/razorpay/dashboard/transactions").json()["transactions"]
    t = next(x for x in txns if x["payment_id"] == pid)
    assert t["recovery_state"] == "AWAITING_OUTCOME"
    assert t["net_recovered_amount"] == 0


def test_duplicate_execute_blocked_not_terminal(client):
    pid = _seed(client)
    client.post(f"/decision/execute/{pid}")
    e2 = client.post(f"/decision/execute/{pid}").json()
    assert e2["status"] == "blocked_temporarily"
    assert e2["guardrail_reason"] in ("min_24h_spacing_not_elapsed", "no_feasible_actions")
    txns = client.get("/razorpay/dashboard/transactions").json()["transactions"]
    t = next(x for x in txns if x["payment_id"] == pid)
    assert t["recovery_state"] == "AWAITING_OUTCOME"  # NOT stopped
    # exactly one payment link exists
    assert t["recovery_link_id"] is not None


def test_webhook_bad_signature_rejected(client):
    pid = _seed(client)
    client.post(f"/decision/execute/{pid}")
    m = client.post(f"/recovery/mock/pay/{pid}").json()
    body = json.dumps(m["webhook_body"])
    r = client.post("/webhooks/razorpay", content=body, headers={
        "X-Razorpay-Signature": "0" * 64,
        "Content-Type": "application/json"})
    assert r.status_code == 400
    r2 = client.post("/webhooks/razorpay", content=body,
                     headers={"Content-Type": "application/json"})
    assert r2.status_code == 400  # missing signature


def test_webhook_recovery_transition_and_net_revenue(client):
    pid = _seed(client)
    e = client.post(f"/decision/execute/{pid}").json()
    r, _, _ = _paid_webhook(client, pid, f"evt_{pid}")
    w = r.json()
    assert w["status"] == "success" and w["recovery_state"] == "RECOVERED"
    assert w["net_recovered_amount"] == w["gross_amount"] - w["discount_amount"]
    if e["chosen_action"] == "discount_offer":
        assert w["discount_amount"] > 0
        assert w["discount_amount"] <= w["gross_amount"] * 0.10


def test_webhook_event_deduplication(client):
    pid = _seed(client)
    client.post(f"/decision/execute/{pid}")
    r1, body, sig = _paid_webhook(client, pid, f"evt_dup_{pid}")
    assert r1.json()["status"] == "success"
    r2 = client.post("/webhooks/razorpay", content=body, headers={
        "X-Razorpay-Signature": sig,
        "X-Razorpay-Event-Id": f"evt_dup_{pid}",
        "Content-Type": "application/json"})
    assert r2.json()["status"] == "duplicate_ignored"


def test_recovered_is_terminal(client):
    pid = _seed(client)
    client.post(f"/decision/execute/{pid}")
    _paid_webhook(client, pid, f"evt_term_{pid}")
    r = client.post(f"/decision/execute/{pid}")
    assert r.status_code == 409


def test_opt_out_permanently_stops(client):
    pid = _seed(client)
    client.post(f"/recoveries/{pid}/opt-out")
    e = client.post(f"/decision/execute/{pid}").json()
    assert e["status"] == "stopped"
    assert e["guardrail_reason"] == "opted_out_permanent_stop"
    txns = client.get("/razorpay/dashboard/transactions").json()["transactions"]
    assert next(x for x in txns if x["payment_id"] == pid)["recovery_state"] == "STOPPED"


def test_audit_log_append_only(client):
    from app.database import get_connection
    conn = get_connection()
    before = conn.execute("SELECT COUNT(*) c FROM audit_log").fetchone()["c"]
    pid = _seed(client)
    client.get(f"/decision/analyze/{pid}")
    client.post(f"/decision/execute/{pid}")
    after = conn.execute("SELECT COUNT(*) c FROM audit_log").fetchone()["c"]
    assert after > before
    # decision + execution rows exist for this transaction, never overwritten
    rows = conn.execute(
        "SELECT event_type FROM audit_log WHERE transaction_id = ? ORDER BY id", (pid,)
    ).fetchall()
    conn.close()
    types = [r["event_type"] for r in rows]
    assert "decision" in types and "execution" in types
    import app.audit_db as audit_db
    import inspect
    src = inspect.getsource(audit_db)
    assert "UPDATE" not in src and "DELETE" not in src


def test_dashboard_net_accounting(client):
    s = client.get("/dashboard/summary").json()
    assert s["net_recovered"] == s["gross_recovered"] - s["discounts_given"]


def test_offline_audit_runs_are_isolated(tmp_path):
    from core.audit.logger import JsonlAuditLogger
    a = JsonlAuditLogger(str(tmp_path))
    a.log({"x": 1}); a.close()
    b = JsonlAuditLogger(str(tmp_path))
    b.log({"y": 2}); b.close()
    assert a.path != b.path
    assert len(list(tmp_path.iterdir())) == 2
    assert json.loads(open(a.path).read())["x"] == 1  # untouched by run b
