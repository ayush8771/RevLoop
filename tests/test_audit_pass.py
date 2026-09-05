"""Tests added in the final audit pass: webhook amount verification,
persisted customer context, live run IDs, negative-EV stop, baseline
definition consistency, docs/simulator sync."""
import json
import os
from datetime import datetime, timezone

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


def _signed(client, pid):
    m = client.post(f"/recovery/mock/pay/{pid}").json()
    return m["webhook_body"], m["x_razorpay_signature"]


# ---------------- P0.1 webhook amount verification ----------------

def test_webhook_amount_mismatch_rejected(client):
    from app.razorpay_gateway import compute_webhook_signature
    pid = _seed(client)
    client.post(f"/decision/execute/{pid}")
    body, _sig = _signed(client, pid)
    # Tamper: claim a smaller paid amount, then RE-SIGN (models a partial
    # payment / stale payload delivered with a valid signature).
    body["payload"]["payment_link"]["entity"]["amount_paid"] -= 100
    raw = json.dumps(body)
    sig = compute_webhook_signature(raw.encode())
    r = client.post("/webhooks/razorpay", content=raw, headers={
        "X-Razorpay-Signature": sig,
        "X-Razorpay-Event-Id": f"evt_bad_amt_{pid}",
        "Content-Type": "application/json"}).json()
    assert r["status"] == "amount_mismatch"
    txns = client.get("/razorpay/dashboard/transactions").json()["transactions"]
    t = next(x for x in txns if x["payment_id"] == pid)
    assert t["recovery_state"] == "AWAITING_OUTCOME"  # NOT recovered
    assert t["net_recovered_amount"] == 0


def test_webhook_verified_amount_recorded(client):
    pid = _seed(client)
    e = client.post(f"/decision/execute/{pid}").json()
    body, sig = _signed(client, pid)
    entity = body["payload"]["payment_link"]["entity"]
    r = client.post("/webhooks/razorpay", content=json.dumps(body), headers={
        "X-Razorpay-Signature": sig,
        "X-Razorpay-Event-Id": f"evt_amt_{pid}",
        "Content-Type": "application/json"}).json()
    assert r["status"] == "success"
    # net recovered == the ACTUAL paid amount from the payload,
    # which equals gross − discount (link was created for the net).
    assert r["net_recovered_amount"] == entity["amount_paid"]
    assert r["net_recovered_amount"] == r["gross_amount"] - r["discount_amount"]


# ---------------- P0.2 customer context ----------------

def test_demo_profiles_persisted_with_provenance(client):
    seen = set()
    for _ in range(4):
        t = client.post("/razorpay/test-transaction").json()
        assert t["context_provenance"].startswith("TEST_PROFILE:")
        seen.add(t["customer_context"]["prior_success_count"])
    assert len(seen) >= 3  # profiles actually differ


def test_context_changes_recovery_probability(client):
    """Same amount/error, different history => different P(recovery)."""
    from app.database import get_connection
    conn = get_connection()
    for pid, prior, tenure in [("pay_ctx_loyal", 14, 730), ("pay_ctx_new", 1, 30)]:
        conn.execute(
            """INSERT INTO transactions (payment_id, order_id, amount, currency,
               status, method, error_code, error_description, recovery_state,
               prior_success_count, customer_tenure_days, recent_failure_count,
               context_provenance)
               VALUES (?, ?, 129900, 'INR', 'failed', 'card', 'INSUFFICIENT_FUNDS',
                       'x', 'AT_RISK', ?, ?, 0, 'TEST_PROFILE:x')""",
            (pid, "o_" + pid, prior, tenure))
    conn.commit(); conn.close()
    a = client.get("/decision/analyze/pay_ctx_loyal").json()
    b = client.get("/decision/analyze/pay_ctx_new").json()
    pa = {s["action"]: s["probability"] for s in a["scored_candidates"]}
    pb = {s["action"]: s["probability"] for s in b["scored_candidates"]}
    assert a["customer_context"]["prior_success_count"] == 14
    assert b["customer_context"]["prior_success_count"] == 1
    # the loyal customer's P(recovery) is strictly higher for the same action
    for action in pa:
        assert pa[action] > pb[action]


# ---------------- P0.5 live run IDs ----------------

def test_live_run_id_format_and_consistency(client):
    from app.audit_db import LIVE_RUN_ID
    assert LIVE_RUN_ID.startswith("live_") and len(LIVE_RUN_ID.split("_")) == 4
    datetime.strptime("_".join(LIVE_RUN_ID.split("_")[1:3]), "%Y%m%d_%H%M%S")
    pid = _seed(client)
    client.get(f"/decision/analyze/{pid}")
    client.post(f"/decision/execute/{pid}")
    from app.database import get_connection
    conn = get_connection()
    run_ids = {r["run_id"] for r in conn.execute(
        "SELECT DISTINCT run_id FROM audit_log WHERE transaction_id = ?", (pid,))}
    conn.close()
    assert run_ids == {LIVE_RUN_ID}


# ---------------- P1.9 negative-EV stop ----------------

def test_all_negative_ev_leads_to_stop():
    from core.decision.decision_engine import decide
    from core.guardrails.validator import GuardrailContext

    class _Pessimist:
        def predict_one(self, context, reason, action, attempt_number):
            return 0.001  # every action loses money after costs

    d = decide({"amount_inr": 100.0, "prior_success_count": 1,
                "customer_tenure_days": 100, "hours_since_failure": 12},
               GuardrailContext(record_id="r", amount=100.0), _Pessimist(),
               ("insufficient_funds", 0.9, "rule"),
               datetime(2026, 9, 1, tzinfo=timezone.utc),
               ["reminder_message", "escalate_call"])
    assert d.action == "stop"
    assert d.guardrail_reason == "no_positive_ev_action"
    assert all(s["ev"] <= 0 for s in d.scored_candidates)


# ---------------- P0.3/P0.4 docs & baseline sync ----------------

def test_assumptions_doc_matches_simulator():
    from offline.potential_outcomes import BASE_RATES
    doc = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "docs", "recovery_assumptions.md")).read()
    assert "payment_link_recovery" in doc and "| retry |" not in doc
    for reason, actions in BASE_RATES.items():
        assert reason in doc
        row = next(l for l in doc.splitlines() if l.startswith(f"| {reason}"))
        for action, p in actions.items():
            assert f"{p:.2f}" in row, f"{reason}/{action}={p} missing from doc row"
    assert "additively" in doc and "simulation assumptions" in doc


def test_baseline_name_consistent():
    from offline.policies import BASELINE_NAME, BASELINE_DEFINITION
    assert BASELINE_NAME == "Deterministic Default-Action Baseline"
    assert "invoice_overdue" in BASELINE_DEFINITION  # covers every event type
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    readme = open(os.path.join(root, "README.md"), encoding="utf-8").read()
    assert "Deterministic Default-Action Baseline" in readme
    assert "always-send-a-link" not in readme


def test_webhook_entity_status_must_be_paid(client):
    """A payment_link.paid event whose entity status is not 'paid'
    (e.g. stale/created) must not transition the record."""
    from app.razorpay_gateway import compute_webhook_signature
    pid = _seed(client)
    client.post(f"/decision/execute/{pid}")
    body, _ = _signed(client, pid)
    body["payload"]["payment_link"]["entity"]["status"] = "created"
    raw = json.dumps(body)
    r = client.post("/webhooks/razorpay", content=raw, headers={
        "X-Razorpay-Signature": compute_webhook_signature(raw.encode()),
        "X-Razorpay-Event-Id": f"evt_status_{pid}",
        "Content-Type": "application/json"}).json()
    assert r["status"] == "ignored" and "not 'paid'" in r["reason"]
    txns = client.get("/razorpay/dashboard/transactions").json()["transactions"]
    assert next(x for x in txns if x["payment_id"] == pid)["recovery_state"] == "AWAITING_OUTCOME"
