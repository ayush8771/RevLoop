"""
Offline policy runners.

Both policies run over the SAME batch and the SAME fixed
potential-outcome table (offline/potential_outcomes.py): for a given
(record, action, attempt) the world responds identically to either
policy. Only the chosen action differs -- that is the entire measured
difference between agent and baseline.

Both policies pass through the SAME guardrail layer and the SAME
simulated clock (each attempt advances simulated time past the 24h
spacing window; nothing ever sleeps).

Revenue accounting: gross amount, discount amount, and net recovered
amount are tracked separately. A recovered discount_offer nets
amount - discount, never the gross amount.
"""
from core.clock import SimulatedClock
from core.decision.decision_engine import decide
from core.diagnosis.classifier import diagnose
from core.guardrails.validator import (
    GuardrailContext, MAX_ATTEMPTS, MIN_HOURS_BETWEEN_ATTEMPTS,
    feasible_actions, validate_chosen_action,
)
from offline.potential_outcomes import ACTIONS_BY_REASON, potential_outcome

ADVANCE_HOURS = MIN_HOURS_BETWEEN_ATTEMPTS + 1  # simulated wait between cycles


def _new_ctx(record):
    return GuardrailContext(
        record_id=record["record_id"],
        amount=record["amount_inr"],
        opted_out=record.get("opted_out", False),
        fraud_flag=record.get("fraud_flag", False),
    )


def _result_row(record, reason, recovered, gross, discount, blocks, block_reason, attempts):
    net = round(gross - discount, 2) if recovered else 0.0
    return {
        "record_id": record["record_id"],
        "amount_inr": record["amount_inr"],
        "diagnosis": reason,
        "recovered": recovered,
        "gross_amount_recovered": gross if recovered else 0.0,
        "discount_amount": discount if recovered else 0.0,
        "net_amount_recovered": net,
        "attempts_used": attempts,
        "guardrail_block_count": blocks,
        "final_guardrail_reason": block_reason,
    }


def run_ev_policy(records, diagnosis_classifier, probability_model, audit_logger):
    results = []
    for record in records:
        clock = SimulatedClock()
        ctx = _new_ctx(record)
        diagnosis = diagnose(record, diagnosis_classifier)
        reason = diagnosis[0]
        context = {
            "amount_inr": record["amount_inr"],
            "prior_success_count": record["prior_success_count"],
            "customer_tenure_days": record["customer_tenure_days"],
            "hours_since_failure": record.get("hours_since_failure", 24.0),
        }
        recovered, gross, discount = False, 0.0, 0.0
        blocks, block_reason = 0, None

        while not recovered:
            ctx.unresolved_cycles = ctx.attempt_count  # each cycle so far unresolved
            decision = decide(
                context, ctx, probability_model, diagnosis,
                clock.now(), ACTIONS_BY_REASON.get(reason, []),
            )
            entry = {
                "policy": "ev_agent",
                "record_id": record["record_id"],
                "attempt_number": decision.attempt_number,
                "simulated_time": clock.now().isoformat(),
                "provenance": "DERIVED+SYNTHETIC",
                **decision.to_dict(),
            }
            if decision.action == "stop":
                blocks += 1
                block_reason = decision.guardrail_reason
                audit_logger.log(entry)
                break

            success, true_p = potential_outcome(
                reason, decision.action, record, decision.attempt_number
            )
            entry["true_outcome_success"] = success
            entry["true_probability_SYNTHETIC"] = true_p
            audit_logger.log(entry)

            ctx.attempt_count += 1
            ctx.last_attempt_at = clock.now()

            if success:
                recovered = True
                gross = record["amount_inr"]
                discount = decision.discount_amount if decision.action == "discount_offer" else 0.0
            else:
                clock.advance(hours=ADVANCE_HOURS)  # simulated wait, never a real sleep
                if ctx.attempt_count >= MAX_ATTEMPTS:
                    # one final decide() would stop on G1; record it via loop
                    pass

        results.append(_result_row(record, reason, recovered, gross, discount,
                                   blocks, block_reason, ctx.attempt_count))
    return results


BASELINE_NAME = "Deterministic Default-Action Baseline"
BASELINE_DEFINITION = (
    "For each record: take the diagnosed failure reason's applicable action "
    "set; the default action is payment_link_recovery when it is applicable "
    "to that reason (all failed-payment and checkout-abandonment reasons), "
    "otherwise the first applicable action in the fixed action-table order "
    "(reminder_message for invoice_overdue, which has no Payment Link "
    "action). That single default action is attempted every cycle it is "
    "guardrail-feasible. No probabilities, no EV ranking. Identical "
    "guardrails, identical simulated-clock discipline, and the identical "
    "fixed potential-outcome table as the EV agent: same record + same "
    "action + same attempt => same outcome for both policies."
)


def run_baseline_policy(records, diagnosis_classifier, audit_logger):
    """See BASELINE_NAME / BASELINE_DEFINITION above."""
    results = []
    for record in records:
        clock = SimulatedClock()
        ctx = _new_ctx(record)
        reason, _conf, _method = diagnose(record, diagnosis_classifier)
        candidates = ACTIONS_BY_REASON.get(reason, [])
        naive_action = "payment_link_recovery" if "payment_link_recovery" in candidates else (
            candidates[0] if candidates else None
        )
        recovered, gross = False, 0.0
        blocks, block_reason = 0, None

        while not recovered and naive_action:
            ctx.unresolved_cycles = ctx.attempt_count
            feasible, breason, _checks = feasible_actions(ctx, [naive_action], clock.now())
            if not feasible:
                blocks += 1
                block_reason = breason
                audit_logger.log({
                    "policy": "baseline", "record_id": record["record_id"],
                    "attempt_number": ctx.attempt_count + 1, "action": "stop",
                    "guardrail_reason": breason, "provenance": "DERIVED+SYNTHETIC",
                })
                break
            ok, breason2, _c = validate_chosen_action(ctx, naive_action, clock.now())
            if not ok:
                blocks += 1
                block_reason = breason2
                break

            attempt_number = ctx.attempt_count + 1
            success, _p = potential_outcome(reason, naive_action, record, attempt_number)
            audit_logger.log({
                "policy": "baseline", "record_id": record["record_id"],
                "attempt_number": attempt_number, "action": naive_action,
                "true_outcome_success": success, "provenance": "DERIVED+SYNTHETIC",
            })
            ctx.attempt_count += 1
            ctx.last_attempt_at = clock.now()
            if success:
                recovered = True
                gross = record["amount_inr"]
            else:
                clock.advance(hours=ADVANCE_HOURS)

        # baseline never discounts
        results.append(_result_row(record, reason, recovered, gross, 0.0,
                                   blocks, block_reason, ctx.attempt_count))
    return results
