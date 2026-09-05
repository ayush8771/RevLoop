"""
THE single decision authority for RevLoop.

Both the live FastAPI product and the offline evaluation pipeline call
`decide(...)` here. There is deliberately no other decision path: the
old rules-based recovery_engine.py and heuristic risk_engine.py from
the original product repo were removed.

Flow per decision cycle:

    Diagnose -> P(recovery | context, action) -> EV(action)
             -> Guardrail pre-check (filters candidates BEFORE argmax)
             -> argmax EV
             -> Guardrail post-check (immediately before execution)

    EV(action) = P(recovery | context, action) x amount - cost(action)

The ML layers only RECOMMEND. The deterministic guardrail layer
AUTHORIZES. The LLM (Groq) never participates in this choice at all --
it only drafts customer-facing message text after a decision is made.
"""
import math
from dataclasses import dataclass, field, asdict

from core.decision.cost_table import COST_FUNCTIONS, DISCOUNT_CEILING_FRACTION
from core.guardrails.validator import (
    GuardrailContext, feasible_actions, validate_chosen_action,
)


@dataclass
class Decision:
    record_id: str
    diagnosis: str
    diagnosis_confidence: float
    diagnosis_method: str
    candidate_actions: list
    scored_candidates: list           # [{action, probability, cost, ev}]
    action: str                       # chosen action ("stop" possible)
    reasoning: str
    guardrail_checks: list = field(default_factory=list)
    guardrail_reason: str = None      # set when guardrails forced a stop
    discount_amount: float = 0.0      # concrete discount if action == discount_offer
    attempt_number: int = 1

    def to_dict(self):
        return asdict(self)


def decide(context, guardrail_ctx: GuardrailContext, probability_model,
           diagnosis, now, candidate_actions):
    """
    context: dict with amount_inr, prior_success_count,
             customer_tenure_days, hours_since_failure
    guardrail_ctx: GuardrailContext for the same record
    diagnosis: (failure_reason, confidence, method) -- already computed
    candidate_actions: full action space applicable to the diagnosis
    """
    reason, diag_conf, diag_method = diagnosis
    attempt_number = guardrail_ctx.attempt_count + 1

    feasible, block_reason, checks = feasible_actions(
        guardrail_ctx, candidate_actions, now
    )

    if not feasible:
        return Decision(
            record_id=guardrail_ctx.record_id,
            diagnosis=reason, diagnosis_confidence=diag_conf,
            diagnosis_method=diag_method,
            candidate_actions=list(candidate_actions),
            scored_candidates=[],
            action="stop",
            reasoning=(f"{guardrail_ctx.record_id}: no guardrail-feasible action "
                       f"({block_reason}) -> stop"),
            guardrail_checks=checks,
            guardrail_reason=block_reason,
            attempt_number=attempt_number,
        )

    scored = []
    for action in feasible:
        p = probability_model.predict_one(context, reason, action, attempt_number)
        cost = COST_FUNCTIONS[action](context["amount_inr"])
        ev = p * context["amount_inr"] - cost
        scored.append({
            "action": action,
            "probability": round(p, 4),
            "cost": round(cost, 2),
            "ev": round(ev, 2),
        })

    # Walk candidates best-EV-first; each must pass its own guardrail
    # post-check immediately before it can be selected for execution.
    best = None
    discount_amount = 0.0
    all_checks = list(checks)
    post_block = None
    for cand in sorted(scored, key=lambda s: s["ev"], reverse=True):
        if cand["ev"] <= 0:
            # EV(stop) = 0: acting would be expected to lose money, so
            # stop beats every remaining (worse) candidate.
            post_block = "no_positive_ev_action"
            break
        cand_discount = 0.0
        if cand["action"] == "discount_offer":
            # floor to 2 decimals so rounding can never breach the G5 ceiling
            cand_discount = math.floor(
                context["amount_inr"] * DISCOUNT_CEILING_FRACTION * 100
            ) / 100.0
        ok, post_block, post_checks = validate_chosen_action(
            guardrail_ctx, cand["action"], now, cand_discount or None
        )
        all_checks += post_checks
        if ok:
            best = cand
            discount_amount = cand_discount
            break

    if best is None:
        return Decision(
            record_id=guardrail_ctx.record_id,
            diagnosis=reason, diagnosis_confidence=diag_conf,
            diagnosis_method=diag_method,
            candidate_actions=list(candidate_actions),
            scored_candidates=scored,
            action="stop",
            reasoning=(f"{guardrail_ctx.record_id}: no executable candidate — "
                       + ("every feasible action has EV <= 0 and EV(stop) = 0, so stopping "
                          "is the value-maximizing choice"
                          if post_block == "no_positive_ev_action"
                          else f"no candidate passed the pre-execution post-check "
                               f"(last: {post_block})") + " -> stop"),
            guardrail_checks=all_checks,
            guardrail_reason=post_block,
            attempt_number=attempt_number,
        )

    others = ", ".join(
        f"{s['action']}=EV {s['ev']}" for s in scored if s["action"] != best["action"]
    )
    reasoning = (
        f"{guardrail_ctx.record_id}: diagnosis={reason} "
        f"(conf={diag_conf:.2f}, {diag_method}), attempt={attempt_number}. "
        f"Chose {best['action']} (P={best['probability']}, cost={best['cost']}, "
        f"EV={best['ev']})" + (f" over [{others}]." if others else " -- only feasible option.")
    )

    return Decision(
        record_id=guardrail_ctx.record_id,
        diagnosis=reason, diagnosis_confidence=diag_conf,
        diagnosis_method=diag_method,
        candidate_actions=list(candidate_actions),
        scored_candidates=scored,
        action=best["action"],
        reasoning=reasoning,
        guardrail_checks=all_checks,
        guardrail_reason=None,
        discount_amount=discount_amount,
        attempt_number=attempt_number,
    )
