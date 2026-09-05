"""
Pull-based payment verification: fetch the exact Payment Link from the
gateway and, if paid, apply the same AWAITING_OUTCOME -> RECOVERED
transition and net-revenue accounting as the webhook path. Also
provides the mock customer-payment simulator used in MOCK_MODE demos.
"""
import json

from fastapi import APIRouter, HTTPException

from app.config import MOCK_MODE
from app.razorpay_gateway import (
    fetch_payment_link, mock_mark_link_paid,
    compute_webhook_signature,
)
from app.state_service import get_transaction
from app.webhooks import _mark_recovered

router = APIRouter(prefix="/recovery", tags=["Recovery Verification"])


@router.get("/verify/{payment_id}")
def verify_recovery(payment_id: str):
    txn = get_transaction(payment_id)
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")

    link_id = txn.get("recovery_link_id")
    if not link_id:
        return {"payment_id": payment_id, "verified": False,
                "status": "no_recovery_link",
                "message": "No Payment Link has been created for this transaction"}

    try:
        link = fetch_payment_link(link_id)
    except Exception as exc:
        raise HTTPException(status_code=502,
                            detail=f"Unable to fetch Razorpay Payment Link: {exc}")

    link_status = link.get("status")
    if link_status == "paid" and txn.get("recovery_state") == "AWAITING_OUTCOME":
        updated, err = _mark_recovered(
            payment_id, actual_paid_paise=link.get("amount_paid"))
        if err:
            return {"payment_id": payment_id, "verified": True,
                    "link_status": link_status, "status": err}
        return {
            "payment_id": payment_id, "verified": True, "link_status": "paid",
            "recovery_state": updated["recovery_state"],
            "gross_amount": updated["amount"],
            "discount_amount": updated["discount_amount"],
            "net_recovered_amount": updated["net_recovered_amount"],
        }

    return {
        "payment_id": payment_id,
        "verified": link_status == "paid",
        "link_status": link_status,
        "recovery_state": txn.get("recovery_state"),
        "amount_paid": link.get("amount_paid", 0),
    }


@router.post("/mock/pay/{payment_id}")
def mock_customer_pays(payment_id: str):
    """
    MOCK MODE ONLY. Simulates the customer paying the active Payment
    Link, then drives the REAL webhook path: builds a payment_link.paid
    payload, signs it with the (mock) webhook secret, and returns the
    payload + signature so it can be POSTed to /webhooks/razorpay --
    or, for one-click demos, processes it through the same handler
    logic in-process via an internal HTTP call from the frontend.
    """
    if not MOCK_MODE:
        raise HTTPException(status_code=403, detail="Only available in MOCK_MODE")
    txn = get_transaction(payment_id)
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")
    link_id = txn.get("recovery_link_id")
    if not link_id:
        raise HTTPException(status_code=409, detail="No Payment Link to pay")

    link = mock_mark_link_paid(link_id)
    event = {
        "event": "payment_link.paid",
        "payload": {"payment_link": {"entity": link}},
    }
    raw = json.dumps(event).encode()
    signature = compute_webhook_signature(raw)
    return {
        "note": ("Mock customer payment recorded. POST the body below to "
                 "/webhooks/razorpay with header X-Razorpay-Signature to "
                 "exercise the full verified webhook path."),
        "webhook_body": event,
        "x_razorpay_signature": signature,
        "payment_link": {"id": link_id, "status": link["status"]},
    }
