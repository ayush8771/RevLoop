"""
Hardcoded, documented cost-per-action table used in the EV decision
function. These are stated assumptions (flagged as such), not measured
operational costs -- exactly like the recovery-outcome assumption table.
"""

ASSUMED_DISCOUNT_REDEMPTION_RATE = 0.80   # assumed fraction of offered discounts redeemed
FLAT_LINK_COST = 2.0                      # payment-link creation/notification cost (assumed)
FLAT_REMINDER_COST = 5.0
FLAT_ESCALATION_COST = 50.0
DISCOUNT_CEILING_FRACTION = 0.10          # mirrors guardrail G5


def cost_payment_link_recovery(amount):
    return FLAT_LINK_COST


def cost_discount_offer(amount):
    # expected cost = ceiling discount x assumed redemption rate + link cost
    return amount * DISCOUNT_CEILING_FRACTION * ASSUMED_DISCOUNT_REDEMPTION_RATE + FLAT_LINK_COST


def cost_reminder_message(amount):
    return FLAT_REMINDER_COST


def cost_escalate_call(amount):
    return FLAT_ESCALATION_COST


def cost_stop(amount):
    return 0.0


COST_FUNCTIONS = {
    "payment_link_recovery": cost_payment_link_recovery,
    "discount_offer": cost_discount_offer,
    "reminder_message": cost_reminder_message,
    "escalate_call": cost_escalate_call,
    "stop": cost_stop,
}
