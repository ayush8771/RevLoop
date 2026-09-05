"""
Guardrail / validation layer -- DELIBERATELY a plain, deterministic
rules engine. This is the correct place for hard, auditable,
non-negotiable limits: the AI/ML layers recommend, this layer
authorizes. It never scores or ranks actions -- it only removes them.

It runs twice per decision:
  1. BEFORE the EV argmax (pre-check): filters the candidate action
     list so infeasible actions never even enter the EV comparison.
  2. IMMEDIATELY BEFORE execution (post-check): re-verifies the chosen
     action, so nothing executes on stale state.

Enforced rules (see docs/guardrails.md):
  G1  max 3 recovery attempts per record
  G2  minimum 24h between contact attempts (timestamp-based,
      via the Clock abstraction -- never enforced by sleeping)
  G3  opt-out permanently blocks all contact
  G4  fraud flag / do-not-contact -> automatic stop
  G5  discount ceiling = 10% of order value
  G6  duplicate Payment Link prevention (one active link per record)
  G7  unresolved stopping rule: > MAX_UNRESOLVED_CYCLES decision
      cycles without resolution -> auto stop, flagged as exception
"""
from dataclasses import dataclass, field
from datetime import timedelta

from core.clock import parse_ts

MAX_ATTEMPTS = 3
MIN_HOURS_BETWEEN_ATTEMPTS = 24
DISCOUNT_CEILING_FRACTION = 0.10
MAX_UNRESOLVED_CYCLES = 5

# Actions that contact the customer (subject to spacing/attempt limits).
CONTACT_ACTIONS = {
    "payment_link_recovery", "reminder_message", "discount_offer", "escalate_call",
}


@dataclass
class GuardrailContext:
    """Normalized view of a record/transaction for guardrail evaluation."""
    record_id: str
    amount: float                       # order value (gross, same unit throughout)
    attempt_count: int = 0              # completed contact attempts so far
    last_attempt_at: object = None      # ISO string or datetime or None
    opted_out: bool = False
    fraud_flag: bool = False
    do_not_contact: bool = False
    unresolved_cycles: int = 0
    active_payment_link_id: str = None  # unpaid, unexpired link if any
    checks: list = field(default_factory=list)


def _check(ctx, name, passed, detail):
    ctx.checks.append({"rule": name, "passed": bool(passed), "detail": detail})
    return passed


def feasible_actions(ctx: GuardrailContext, candidate_actions, now):
    """
    Pre-check. Returns (feasible_actions, block_reason, checks).
    block_reason is set only when NOTHING is feasible (a stop condition).
    """
    ctx.checks = []

    # G4: fraud / do-not-contact -> hard stop
    if not _check(ctx, "G4_fraud_dnc", not (ctx.fraud_flag or ctx.do_not_contact),
                  "fraud_flag or do_not_contact set" if (ctx.fraud_flag or ctx.do_not_contact) else "clear"):
        return [], "fraud_or_dnc_auto_stop", ctx.checks

    # G3: opt-out -> permanent stop
    if not _check(ctx, "G3_opt_out", not ctx.opted_out,
                  "customer opted out (permanent)" if ctx.opted_out else "clear"):
        return [], "opted_out_permanent_stop", ctx.checks

    # G7: unresolved stopping rule
    if not _check(ctx, "G7_unresolved_cycles", ctx.unresolved_cycles < MAX_UNRESOLVED_CYCLES,
                  f"unresolved_cycles={ctx.unresolved_cycles} (max {MAX_UNRESOLVED_CYCLES})"):
        return [], "unresolved_cycles_exceeded_exception", ctx.checks

    # G1: max attempts
    if not _check(ctx, "G1_max_attempts", ctx.attempt_count < MAX_ATTEMPTS,
                  f"attempt_count={ctx.attempt_count} (max {MAX_ATTEMPTS})"):
        return [], "max_attempts_exceeded", ctx.checks

    # G2: 24h spacing (timestamp comparison -- Clock-provided `now`)
    last = parse_ts(ctx.last_attempt_at)
    if last is not None:
        next_allowed = last + timedelta(hours=MIN_HOURS_BETWEEN_ATTEMPTS)
        spacing_ok = now >= next_allowed
        _check(ctx, "G2_min_spacing", spacing_ok,
               f"last_attempt_at={last.isoformat()}, next_allowed_at={next_allowed.isoformat()}")
        if not spacing_ok:
            return [], "min_24h_spacing_not_elapsed", ctx.checks
    else:
        _check(ctx, "G2_min_spacing", True, "no prior attempt")

    feasible = []
    for action in candidate_actions:
        # G6: duplicate Payment Link prevention -- a second link-creating
        # action is infeasible while a link is still active; the record
        # must resolve (paid/expired/cancelled) or reuse the existing link.
        if action in ("payment_link_recovery", "discount_offer") and ctx.active_payment_link_id:
            _check(ctx, "G6_duplicate_link", False,
                   f"{action} blocked: active link {ctx.active_payment_link_id} exists")
            continue
        feasible.append(action)

    if ctx.active_payment_link_id and all(
        c["rule"] != "G6_duplicate_link" for c in ctx.checks
    ):
        _check(ctx, "G6_duplicate_link", True, "no conflicting link-creating action requested")
    elif not ctx.active_payment_link_id:
        _check(ctx, "G6_duplicate_link", True, "no active payment link")

    if not feasible:
        return [], "no_feasible_actions", ctx.checks
    return feasible, None, ctx.checks


def validate_chosen_action(ctx: GuardrailContext, action, now,
                           discount_amount: float | None = None):
    """
    Post-check, run immediately before execution. Returns
    (ok, block_reason, checks). Re-verifies stop conditions and the
    discount ceiling on the *actual* discount about to be applied.
    """
    checks = []

    def chk(name, passed, detail):
        checks.append({"rule": name, "passed": bool(passed), "detail": detail})
        return passed

    if not chk("G4_fraud_dnc", not (ctx.fraud_flag or ctx.do_not_contact), "post-check"):
        return False, "post_check_fraud_or_dnc", checks
    if not chk("G3_opt_out", not ctx.opted_out, "post-check"):
        return False, "post_check_opted_out", checks
    if not chk("G1_max_attempts", ctx.attempt_count < MAX_ATTEMPTS,
               f"attempt_count={ctx.attempt_count}"):
        return False, "post_check_max_attempts", checks

    last = parse_ts(ctx.last_attempt_at)
    if action in CONTACT_ACTIONS and last is not None:
        next_allowed = last + timedelta(hours=MIN_HOURS_BETWEEN_ATTEMPTS)
        if not chk("G2_min_spacing", now >= next_allowed,
                   f"next_allowed_at={next_allowed.isoformat()}"):
            return False, "post_check_min_spacing", checks

    # G5: discount ceiling on the concrete discount amount
    if action == "discount_offer":
        ceiling = ctx.amount * DISCOUNT_CEILING_FRACTION
        amt = discount_amount if discount_amount is not None else ceiling
        if not chk("G5_discount_ceiling", amt <= ceiling + 1e-9,
                   f"discount={amt}, ceiling={ceiling}"):
            return False, "discount_ceiling_exceeded", checks

    # G6 re-check
    if action in ("payment_link_recovery", "discount_offer"):
        if not chk("G6_duplicate_link", not ctx.active_payment_link_id,
                   f"active link: {ctx.active_payment_link_id}"):
            return False, "duplicate_payment_link_blocked", checks

    return True, None, checks
