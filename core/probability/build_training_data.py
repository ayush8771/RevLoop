"""
Builds the training set for the recovery-probability model.

For every (record, applicable action, attempt), simulates a
counterfactual outcome via the documented assumption model
(offline/potential_outcomes.py, salted draws). Produces rows of
(features, action) -> outcome -- the shape of offline logged-outcome
data a real recovery system would learn from in production. All rows
are provenance=SYNTHETIC.
"""
from core.diagnosis.classifier import diagnose
from offline.potential_outcomes import ACTIONS_BY_REASON, training_outcome


def build_rows(records, diagnosis_classifier, salt=777):
    rows = []
    for record in records:
        if record.get("fraud_flag") or record.get("opted_out"):
            continue  # guardrail-excluded records never enter probability training
        reason, _conf, _method = diagnose(record, diagnosis_classifier)
        for attempt_number in (1, 2, 3):
            for action in ACTIONS_BY_REASON.get(reason, []):
                success, _p = training_outcome(
                    reason, action, record, attempt_number, salt=salt + attempt_number
                )
                rows.append({
                    "record_id": record["record_id"],
                    "failure_reason": reason,
                    "action": action,
                    "attempt_number": attempt_number,
                    "amount_inr": record["amount_inr"],
                    "prior_success_count": record["prior_success_count"],
                    "customer_tenure_days": record["customer_tenure_days"],
                    "hours_since_failure": record.get("hours_since_failure", 24.0),
                    "outcome": int(success),
                    "provenance": "SYNTHETIC",
                })
    return rows
