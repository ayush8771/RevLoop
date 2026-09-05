"""Recovery listing / manual status management / opt-out."""
from fastapi import APIRouter, HTTPException

from app.audit_db import audit
from app.database import get_connection
from app.state_service import get_transaction, transition
from core.state_machine import IllegalTransition

router = APIRouter(prefix="/recoveries", tags=["Recoveries"])


@router.get("")
def get_recoveries():
    conn = get_connection()
    rows = conn.execute(
        """SELECT payment_id, order_id, amount, currency, method,
                  error_code, error_description, recovery_link,
                  recovery_link_id, recovery_status, recovery_state,
                  attempt_count, diagnosis, diagnosis_confidence,
                  chosen_action, discount_amount, net_recovered_amount,
                  created_at, recovered_at
           FROM transactions
           WHERE recovery_link IS NOT NULL OR recovery_state != 'AT_RISK'
           ORDER BY created_at DESC"""
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@router.post("/{payment_id}/opt-out")
def opt_out(payment_id: str):
    """Customer opt-out: permanently blocks all further contact (guardrail G3)."""
    txn = get_transaction(payment_id)
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")
    conn = get_connection()
    conn.execute("UPDATE transactions SET opted_out = 1 WHERE payment_id = ?", (payment_id,))
    conn.commit()
    conn.close()
    audit(payment_id, "guardrail_stop", outcome="customer_opted_out",
          reasoning="opt-out recorded; all future contact permanently blocked (G3)")
    return {"payment_id": payment_id, "opted_out": True}


@router.patch("/{payment_id}/status")
def update_recovery_status(payment_id: str, status: str):
    """
    Manual lifecycle update for non-webhook outcomes (e.g. link
    expired, agent marks a call attempt failed). RECOVERED cannot be
    set manually -- it requires the verified webhook/verification path.
    """
    allowed = {"failed", "expired", "re_evaluate", "stopped"}
    if status not in allowed:
        raise HTTPException(status_code=400,
                            detail=f"status must be one of {sorted(allowed)}")
    txn = get_transaction(payment_id)
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")
    try:
        if status in ("failed", "expired"):
            transition(payment_id, "FAILED", recovery_status=status)
        elif status == "re_evaluate":
            transition(payment_id, "RE_EVALUATE")
        else:
            transition(payment_id, "STOPPED", recovery_status="failed")
    except IllegalTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    audit(payment_id, "outcome", outcome=status.upper())
    return {"payment_id": payment_id, "recovery_state": get_transaction(payment_id)["recovery_state"]}
