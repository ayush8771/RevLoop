"""
Razorpay webhook handling.

Order of operations (deliberate):
  1. Read the RAW request body (bytes) -- signature verification MUST
     run on the raw body, never on re-serialized JSON.
  2. Verify X-Razorpay-Signature = HMAC-SHA256(raw_body, webhook secret).
  3. Deduplicate by event id (X-Razorpay-Event-Id header, falling back
     to a hash of the raw body) via UNIQUE INSERT into webhook_events:
     a replayed event is acknowledged but processed exactly once.
  4. For payment_link.paid: match reference_id "recovery_<payment_id>",
     verify the link id matches the one we created, verify the ACTUAL
     paid amount from the Razorpay payload equals the expected net
     collection (gross − approved discount), then transition
     AWAITING_OUTCOME -> RECOVERED recording the verified paid amount
     as net recovered revenue.

Amount rule: amounts are integer paise and Payment Links are created
with partial payments disabled, so the check is EXACT (tolerance = 0
paise). A mismatch (partial payment, tampered/stale payload) is NOT a
recovery: it is audited as amount_mismatch and left for manual review
in AWAITING_OUTCOME.
"""
import hashlib
import json

from fastapi import APIRouter, Header, HTTPException, Request

from app.audit_db import audit
from app.config import MOCK_MODE
from app.database import get_connection
from app.razorpay_gateway import verify_webhook_signature
from app.state_service import get_transaction, transition, now_iso
from core.state_machine import IllegalTransition

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


def _record_event_once(event_id, event_type, raw_body: bytes) -> bool:
    """Returns True if this is the first time we see event_id."""
    conn = get_connection()
    cur = conn.execute(
        "INSERT OR IGNORE INTO webhook_events (event_id, event_type, payload) VALUES (?, ?, ?)",
        (event_id, event_type, raw_body.decode("utf-8", errors="replace")),
    )
    conn.commit()
    first_time = cur.rowcount == 1
    conn.close()
    return first_time


def _mark_recovered(payment_id: str, actual_paid_paise=None):
    """Transition to RECOVERED only when the verified paid amount
    matches the expected net collection. `actual_paid_paise` is the
    amount reported by Razorpay (webhook payload / fetched link); when
    the gateway supplies it, the recorded recovery amount is the
    VERIFIED amount, never a locally fabricated figure."""
    txn = get_transaction(payment_id)
    if not txn:
        return None, "transaction_not_found"
    gross = txn["amount"] or 0
    discount = txn.get("discount_amount") or 0
    expected_net = gross - discount

    if actual_paid_paise is not None and int(actual_paid_paise) != int(expected_net):
        audit(payment_id, "webhook",
              payment_link_id=txn.get("recovery_link_id"),
              payment_status="paid",
              gross_amount=gross, discount_amount=discount,
              outcome=(f"amount_mismatch: expected_net={expected_net} "
                       f"actual_paid={int(actual_paid_paise)} -> manual review"),
              provenance="MOCK" if MOCK_MODE else "LIVE_TEST_MODE")
        return txn, (f"amount_mismatch: expected net {expected_net} paise, "
                     f"actual paid {int(actual_paid_paise)} paise")

    net = int(actual_paid_paise) if actual_paid_paise is not None else expected_net
    try:
        transition(payment_id, "RECOVERED",
                   recovery_status="recovered",
                   net_recovered_amount=net,
                   recovered_at=now_iso())
    except IllegalTransition as exc:
        # e.g. duplicate delivery already handled, or link paid before
        # any action was initiated -- refuse to corrupt the lifecycle.
        return txn, f"illegal_transition: {exc}"
    audit(payment_id, "outcome",
          payment_link_id=txn.get("recovery_link_id"),
          payment_status="paid", outcome="RECOVERED",
          gross_amount=gross, discount_amount=discount,
          net_recovered_amount=net,
          reasoning=("verified paid amount from gateway payload"
                     if actual_paid_paise is not None
                     else "gateway payload carried no amount; expected net recorded"),
          provenance="MOCK" if MOCK_MODE else "LIVE_TEST_MODE")
    return get_transaction(payment_id), None


@router.post("/razorpay")
async def razorpay_webhook(
    request: Request,
    x_razorpay_signature: str = Header(None),
    x_razorpay_event_id: str = Header(None),
):
    raw_body = await request.body()

    if not x_razorpay_signature:
        raise HTTPException(status_code=400, detail="Missing Razorpay signature")

    if not verify_webhook_signature(raw_body, x_razorpay_signature):
        raise HTTPException(status_code=400, detail="Invalid Razorpay webhook signature")

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    event_type = payload.get("event", "unknown")
    event_id = x_razorpay_event_id or (
        "sha256_" + hashlib.sha256(raw_body).hexdigest()[:32]
    )

    if not _record_event_once(event_id, event_type, raw_body):
        # Duplicate delivery: acknowledge (200) so Razorpay stops
        # retrying, but do not process again.
        return {"status": "duplicate_ignored", "event_id": event_id, "event": event_type}

    if event_type != "payment_link.paid":
        return {"status": "ignored", "event": event_type}

    entity = (payload.get("payload", {}).get("payment_link", {}).get("entity", {}))
    reference_id = entity.get("reference_id") or ""
    link_id = entity.get("id")

    # Entity-status verification: even on a payment_link.paid event, only
    # an entity whose own status is "paid" may drive a recovery transition.
    if entity.get("status") != "paid":
        return {"status": "ignored",
                "reason": f"payment_link entity status is "
                          f"'{entity.get('status')}', not 'paid'"}

    if not reference_id.startswith("recovery_"):
        return {"status": "ignored", "reason": "Not a RevLoop recovery link"}

    payment_id = reference_id[len("recovery_"):]
    txn = get_transaction(payment_id)
    if not txn:
        return {"status": "ignored", "reason": "Transaction not found",
                "payment_id": payment_id}

    # Payment-link verification: the paid link must be the exact link
    # we created for this transaction.
    if txn.get("recovery_link_id") and link_id and txn["recovery_link_id"] != link_id:
        audit(payment_id, "webhook", payment_link_id=link_id,
              payment_status="paid", outcome="link_id_mismatch_ignored",
              provenance="MOCK" if MOCK_MODE else "LIVE_TEST_MODE")
        return {"status": "ignored", "reason": "payment_link id mismatch",
                "expected": txn["recovery_link_id"], "received": link_id}

    # Amount verification: prefer the payment_link entity's amount_paid,
    # falling back to the payment entity's amount if present.
    actual_paid = entity.get("amount_paid")
    if actual_paid is None:
        actual_paid = (payload.get("payload", {}).get("payment", {})
                       .get("entity", {}).get("amount"))

    updated, err = _mark_recovered(payment_id, actual_paid_paise=actual_paid)
    if err:
        status = "amount_mismatch" if err.startswith("amount_mismatch") else "ignored"
        return {"status": status, "reason": err, "payment_id": payment_id,
                "recovery_state": (updated or {}).get("recovery_state")}

    return {
        "status": "success",
        "event": event_type,
        "payment_id": payment_id,
        "recovery_state": updated["recovery_state"],
        "gross_amount": updated["amount"],
        "discount_amount": updated["discount_amount"],
        "net_recovered_amount": updated["net_recovered_amount"],
    }
