"""
Live decision + execution endpoints. Every recovery decision in the
product goes through core/decision/decision_engine.decide() -- there is
no other decision path (the legacy rules engine and heuristic risk
engine were removed).

Live scope: FAILED PAYMENTS, recovered via Razorpay Payment Links.
The decision engine still scores the full offline action space where
applicable; the live executor implements the actions that Payment Link
infrastructure genuinely supports:

  payment_link_recovery -> create Payment Link at gross amount
  discount_offer        -> create Payment Link at gross − guardrail-
                           approved discount (≤ 10%)
  reminder_message      -> Groq/template message referencing the active
                           (or newly created) Payment Link
  escalate_call         -> Groq/template call script for a human agent
  stop                  -> no contact

A record only ever becomes RECOVERED via a verified payment (webhook
or verification endpoint) -- never merely because a link was created.
"""
import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException

from app.audit_db import audit
from app.config import MOCK_MODE
from app.database import get_connection
from app.groq_client import draft_message
from app.model_provider import get_model
from app.razorpay_gateway import create_payment_link
from app.state_service import get_transaction, transition, now_iso
from core.clock import RealClock
from core.decision.decision_engine import decide
from core.diagnosis.rules import diagnose_live_transaction
from core.guardrails.validator import GuardrailContext, MIN_HOURS_BETWEEN_ATTEMPTS

router = APIRouter(prefix="/decision", tags=["Decision Engine"])

clock = RealClock()

LIVE_CANDIDATE_ACTIONS = [
    "payment_link_recovery", "discount_offer", "reminder_message", "escalate_call",
]

# Documented fallback defaults, used ONLY when a transaction carries no
# persisted customer context (a merchant integration or the TEST_PROFILE
# seeder normally supplies values; provenance is reported either way).
DEFAULT_PRIOR_SUCCESS_COUNT = 1
DEFAULT_CUSTOMER_TENURE_DAYS = 180
DEFAULT_RECENT_FAILURE_COUNT = 1


def _customer_context(txn):
    """Persisted per-transaction customer context with honest provenance."""
    has_stored = txn.get("prior_success_count") is not None
    return {
        "prior_success_count": (txn.get("prior_success_count")
                                if has_stored else DEFAULT_PRIOR_SUCCESS_COUNT),
        "customer_tenure_days": (txn.get("customer_tenure_days")
                                 if txn.get("customer_tenure_days") is not None
                                 else DEFAULT_CUSTOMER_TENURE_DAYS),
        "recent_failure_count": (txn.get("recent_failure_count")
                                 if txn.get("recent_failure_count") is not None
                                 else DEFAULT_RECENT_FAILURE_COUNT),
        "provenance": txn.get("context_provenance") or "DEFAULT_FALLBACK",
    }


def _hours_since_failure(txn):
    try:
        created = datetime.fromisoformat(str(txn["created_at"]).replace("Z", "+00:00"))
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        return max(0.5, (clock.now() - created).total_seconds() / 3600.0)
    except (ValueError, TypeError):
        return 24.0


def _diagnose(txn):
    reason, conf, method = diagnose_live_transaction(txn)
    if reason is None:
        # honest default when the gateway signal is ambiguous
        reason, conf, method = "card_issue", 0.40, "default_ambiguous_code"
    return reason, conf, method


def _active_link_id(txn):
    if txn.get("recovery_link_id") and txn.get("recovery_status") in ("initiated", "pending"):
        return txn["recovery_link_id"]
    return None


def _guardrail_ctx(txn):
    return GuardrailContext(
        record_id=txn["payment_id"],
        amount=txn["amount"] / 100.0,
        attempt_count=txn.get("attempt_count") or 0,
        last_attempt_at=txn.get("last_attempt_at"),
        opted_out=bool(txn.get("opted_out")),
        fraud_flag=bool(txn.get("fraud_flag")),
        unresolved_cycles=txn.get("unresolved_cycles") or 0,
        active_payment_link_id=_active_link_id(txn),
    )


def _decide_for(txn):
    diagnosis = _diagnose(txn)
    cust = _customer_context(txn)
    context = {
        "amount_inr": txn["amount"] / 100.0,
        "prior_success_count": cust["prior_success_count"],
        "customer_tenure_days": cust["customer_tenure_days"],
        "hours_since_failure": _hours_since_failure(txn),
    }
    return decide(context, _guardrail_ctx(txn), get_model(), diagnosis,
                  clock.now(), LIVE_CANDIDATE_ACTIONS)


def _decision_payload(txn, decision):
    next_allowed_at = None
    if txn.get("last_attempt_at"):
        try:
            last = datetime.fromisoformat(str(txn["last_attempt_at"]).replace("Z", "+00:00"))
            next_allowed_at = (last + timedelta(hours=MIN_HOURS_BETWEEN_ATTEMPTS)).isoformat()
        except (ValueError, TypeError):
            pass
    return {
        "payment_id": txn["payment_id"],
        "amount": txn["amount"],
        "currency": txn["currency"],
        "customer_context": _customer_context(txn),
        "recovery_state": txn.get("recovery_state"),
        "attempt_count": txn.get("attempt_count") or 0,
        "next_allowed_at": next_allowed_at,
        "diagnosis": decision.diagnosis,
        "diagnosis_confidence": decision.diagnosis_confidence,
        "diagnosis_method": decision.diagnosis_method,
        "candidate_actions": decision.candidate_actions,
        "scored_candidates": decision.scored_candidates,
        "chosen_action": decision.action,
        "reasoning": decision.reasoning,
        "guardrail_checks": decision.guardrail_checks,
        "guardrail_reason": decision.guardrail_reason,
        "discount_amount_paise": int(round(decision.discount_amount * 100)),
        "probability_note": (
            "P(recovery) values come from a model trained on SIMULATED intervention "
            "outcomes (documented assumptions), not real-world labels."
        ),
        "mock_mode": MOCK_MODE,
    }


_PATHS_TO_DECISION_READY = {
    "AT_RISK": ["DIAGNOSED", "DECISION_READY"],
    "DIAGNOSED": ["DECISION_READY"],
    "DECISION_READY": [],
    "AWAITING_OUTCOME": ["FAILED", "RE_EVALUATE", "DIAGNOSED", "DECISION_READY"],
    "FAILED": ["RE_EVALUATE", "DIAGNOSED", "DECISION_READY"],
    "RE_EVALUATE": ["DIAGNOSED", "DECISION_READY"],
}


def _walk_to(payment_id, current_state, target="DECISION_READY"):
    """Advance the lifecycle to `target` along legal transitions only."""
    for step in _PATHS_TO_DECISION_READY.get(current_state, []):
        transition(payment_id, step)


@router.get("/analyze/{payment_id}")
def analyze(payment_id: str):
    """Diagnose + score + choose (no execution, no side effects on the
    customer). Persists the intelligence outputs and advances
    AT_RISK -> DIAGNOSED -> DECISION_READY."""
    txn = get_transaction(payment_id)
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")

    decision = _decide_for(txn)

    conn = get_connection()
    conn.execute(
        """UPDATE transactions SET diagnosis=?, diagnosis_confidence=?,
           chosen_action=?, decision_json=? WHERE payment_id=?""",
        (decision.diagnosis, decision.diagnosis_confidence, decision.action,
         json.dumps(decision.to_dict()), payment_id),
    )
    conn.commit()
    conn.close()

    state = txn.get("recovery_state") or "AT_RISK"
    if state == "AT_RISK":
        transition(payment_id, "DIAGNOSED")
        transition(payment_id, "DECISION_READY")
    elif state == "DIAGNOSED":
        transition(payment_id, "DECISION_READY")
    elif state == "RE_EVALUATE":
        transition(payment_id, "DIAGNOSED")
        transition(payment_id, "DECISION_READY")

    audit(payment_id, "decision",
          diagnosis=decision.diagnosis, diagnosis_confidence=decision.diagnosis_confidence,
          candidates=decision.scored_candidates, chosen_action=decision.action,
          reasoning=decision.reasoning, guardrail_checks=decision.guardrail_checks,
          gross_amount=txn["amount"],
          discount_amount=int(round(decision.discount_amount * 100)),
          provenance="LIVE_TEST_MODE" if not MOCK_MODE else "MOCK")

    txn = get_transaction(payment_id)
    return _decision_payload(txn, decision)


@router.post("/execute/{payment_id}")
def execute(payment_id: str):
    """Re-runs the decision on fresh state, passes guardrail post-check,
    then executes: ... -> GUARDRAIL_APPROVED -> ACTION_INITIATED ->
    AWAITING_OUTCOME. Duplicate Payment Links are structurally
    prevented (guardrail G6 + reuse of the active link). Temporal
    guardrail blocks (e.g. 24h spacing) do NOT terminate the record;
    only permanent reasons transition it to STOPPED."""
    txn = get_transaction(payment_id)
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")
    state = txn.get("recovery_state") or "AT_RISK"
    if state in ("RECOVERED", "STOPPED"):
        raise HTTPException(status_code=409, detail=f"Transaction is terminal: {state}")

    # Fresh decision immediately before execution (guardrails run twice
    # inside decide(): pre-filter + pre-execution post-check).
    decision = _decide_for(txn)

    PERMANENT_STOP_REASONS = {
        "fraud_or_dnc_auto_stop", "opted_out_permanent_stop",
        "max_attempts_exceeded", "unresolved_cycles_exceeded_exception",
        "post_check_fraud_or_dnc", "post_check_opted_out", "post_check_max_attempts",
    }

    if decision.action == "stop":
        if decision.guardrail_reason in PERMANENT_STOP_REASONS:
            _walk_to(payment_id, state, "DECISION_READY")
            transition(payment_id, "STOPPED",
                       chosen_action="stop",
                       decision_json=json.dumps(decision.to_dict()))
            audit(payment_id, "guardrail_stop",
                  diagnosis=decision.diagnosis, chosen_action="stop",
                  reasoning=decision.reasoning,
                  guardrail_checks=decision.guardrail_checks,
                  outcome=decision.guardrail_reason)
            txn = get_transaction(payment_id)
            return _decision_payload(txn, decision) | {"status": "stopped"}
        # Temporal block (24h spacing, active duplicate link, ...):
        # no state change; the record stays in its current state.
        audit(payment_id, "guardrail_stop",
              diagnosis=decision.diagnosis, chosen_action="stop",
              reasoning=decision.reasoning,
              guardrail_checks=decision.guardrail_checks,
              outcome=f"blocked_temporarily:{decision.guardrail_reason}")
        return _decision_payload(txn, decision) | {"status": "blocked_temporarily"}

    # Advance the lifecycle to DECISION_READY along a legal path, then
    # approve and execute.
    _walk_to(payment_id, state, "DECISION_READY")
    transition(payment_id, "GUARDRAIL_APPROVED")

    discount_paise = int(round(decision.discount_amount * 100))
    gross_paise = txn["amount"]
    link = None
    message = None

    active_link_id = _active_link_id(txn)
    if decision.action in ("payment_link_recovery", "discount_offer"):
        # G6 guarantees no active link exists here; create exactly one.
        link = create_payment_link(
            amount_paise=gross_paise - (discount_paise if decision.action == "discount_offer" else 0),
            currency=txn["currency"] or "INR",
            description=("RevLoop payment recovery"
                         + (" (discount applied)" if decision.action == "discount_offer" else "")),
            reference_id=f"recovery_{payment_id}",
            customer_email=txn.get("email"),
            customer_contact=txn.get("contact"),
        )
    elif decision.action in ("reminder_message", "escalate_call"):
        # Reuse the active link if present; otherwise create one so the
        # customer has a way to pay from the message.
        if active_link_id:
            from app.razorpay_gateway import fetch_payment_link
            link = fetch_payment_link(active_link_id)
        else:
            link = create_payment_link(
                amount_paise=gross_paise,
                currency=txn["currency"] or "INR",
                description="RevLoop payment recovery",
                reference_id=f"recovery_{payment_id}",
                customer_email=txn.get("email"),
                customer_contact=txn.get("contact"),
            )
        message = draft_message(decision.action, txn,
                                payment_link_url=link.get("short_url"),
                                discount_paise=0)

    transition(
        payment_id, "ACTION_INITIATED",
        chosen_action=decision.action,
        decision_json=json.dumps(decision.to_dict()),
        recovery_link=link.get("short_url") if link else txn.get("recovery_link"),
        recovery_link_id=link.get("id") if link else txn.get("recovery_link_id"),
        recovery_status="initiated",
        discount_amount=discount_paise if decision.action == "discount_offer" else (txn.get("discount_amount") or 0),
        attempt_count=(txn.get("attempt_count") or 0) + 1,
        last_attempt_at=now_iso(),
        unresolved_cycles=(txn.get("unresolved_cycles") or 0) + 1,
    )
    transition(payment_id, "AWAITING_OUTCOME")

    audit(payment_id, "execution",
          diagnosis=decision.diagnosis, diagnosis_confidence=decision.diagnosis_confidence,
          candidates=decision.scored_candidates, chosen_action=decision.action,
          reasoning=decision.reasoning, guardrail_checks=decision.guardrail_checks,
          execution_id=link.get("id") if link else None,
          payment_link_id=link.get("id") if link else None,
          payment_status=link.get("status") if link else None,
          gross_amount=gross_paise, discount_amount=discount_paise,
          provenance="MOCK" if MOCK_MODE else "LIVE_TEST_MODE")

    txn = get_transaction(payment_id)
    result = _decision_payload(txn, decision) | {
        "status": "action_initiated",
        "payment_link": link.get("short_url") if link else None,
        "payment_link_id": link.get("id") if link else None,
        "link_reused": bool(active_link_id and decision.action in ("reminder_message", "escalate_call")),
    }
    if message:
        result["message"] = message
    return result
