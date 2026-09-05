"""
Ground-truth recovery-outcome simulator with FIXED POTENTIAL OUTCOMES.

Implements the assumption table in docs/recovery_assumptions.md, but
outcome draws are deterministic in (record_id, action, attempt_number):
the same record given the same action on the same attempt produces the
SAME outcome no matter which policy asks. This makes the agent-vs-
baseline comparison fair -- the two policies face identical worlds and
differ only in which action they choose.

Everything produced here is provenance=SYNTHETIC: simulated
intervention outcomes are NOT real-world labels. They exist because
public data with logged agent-intervention outcomes does not exist.
"""
import hashlib

BASE_RATES = {
    "insufficient_funds": {"payment_link_recovery": 0.35, "discount_offer": 0.55, "reminder_message": 0.20, "escalate_call": 0.45},
    "card_issue":         {"payment_link_recovery": 0.55, "discount_offer": 0.60, "reminder_message": 0.15, "escalate_call": 0.40},
    "card_expired":       {"payment_link_recovery": 0.30, "discount_offer": 0.35, "reminder_message": 0.30, "escalate_call": 0.35},
    "bank_decline":       {"payment_link_recovery": 0.30, "discount_offer": 0.50, "reminder_message": 0.15, "escalate_call": 0.40},
    "subscription_lapse": {"payment_link_recovery": 0.45, "discount_offer": 0.55, "reminder_message": 0.25, "escalate_call": 0.40},
    "checkout_abandon":   {"payment_link_recovery": 0.25, "discount_offer": 0.35, "reminder_message": 0.18},
    "invoice_overdue":    {"reminder_message": 0.20, "escalate_call": 0.40},
}
# Note on card_expired: a Payment Link lets the customer enter a NEW
# card, so unlike a blind same-card retry its assumed success rate is
# not near-zero. Documented assumption, not a measured fact.

ACTIONS_BY_REASON = {k: list(v.keys()) for k, v in BASE_RATES.items()}
OUTCOME_SEED = 20260901  # global seed for the potential-outcome table


def true_probability(failure_reason, action, record, attempt_number):
    if record.get("fraud_flag") or record.get("opted_out"):
        return 0.0
    base = BASE_RATES.get(failure_reason, {}).get(action)
    if base is None:
        return 0.0
    p = base
    if record.get("prior_success_count", 0) >= 5:
        p += 0.10
    if attempt_number >= 3:
        p -= 0.15
    return max(0.0, min(1.0, p))


def _uniform_draw(record_id, action, attempt_number, seed=OUTCOME_SEED):
    """Deterministic U(0,1) draw keyed only on (record, action, attempt)."""
    key = f"{seed}|{record_id}|{action}|{attempt_number}".encode()
    h = hashlib.sha256(key).hexdigest()
    return int(h[:12], 16) / float(16 ** 12)


def potential_outcome(failure_reason, action, record, attempt_number):
    """
    Returns (success: bool, true_p: float). Deterministic:
    same record + same action + same attempt => same outcome,
    for the agent policy and the baseline policy alike.
    """
    p = true_probability(failure_reason, action, record, attempt_number)
    u = _uniform_draw(record["record_id"], action, attempt_number)
    return u < p, p


def training_outcome(failure_reason, action, record, attempt_number, salt):
    """
    Independent draws for building the probability model's training set
    (salted so training rows don't reuse the evaluation world's exact
    outcome table -- the model must learn rates, not memorize draws).
    """
    p = true_probability(failure_reason, action, record, attempt_number)
    u = _uniform_draw(record["record_id"], action, attempt_number, seed=salt)
    return u < p, p
