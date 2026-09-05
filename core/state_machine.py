"""
Recovery lifecycle state machine. A record is only ever RECOVERED via a
verified payment outcome (webhook + verification), never merely because
a Payment Link was created.

AT_RISK -> DIAGNOSED -> DECISION_READY -> GUARDRAIL_APPROVED
        -> ACTION_INITIATED -> AWAITING_OUTCOME -> RECOVERED / FAILED
FAILED  -> RE_EVALUATE (next cycle) or STOPPED
"""

STATES = [
    "AT_RISK", "DIAGNOSED", "DECISION_READY", "GUARDRAIL_APPROVED",
    "ACTION_INITIATED", "AWAITING_OUTCOME", "RECOVERED", "FAILED",
    "RE_EVALUATE", "STOPPED",
]

ALLOWED_TRANSITIONS = {
    "AT_RISK": {"DIAGNOSED", "STOPPED"},
    "DIAGNOSED": {"DECISION_READY", "STOPPED"},
    "DECISION_READY": {"GUARDRAIL_APPROVED", "STOPPED"},
    "GUARDRAIL_APPROVED": {"ACTION_INITIATED", "STOPPED"},
    "ACTION_INITIATED": {"AWAITING_OUTCOME", "FAILED", "STOPPED"},
    "AWAITING_OUTCOME": {"RECOVERED", "FAILED", "STOPPED"},
    "FAILED": {"RE_EVALUATE", "STOPPED"},
    "RE_EVALUATE": {"DIAGNOSED", "STOPPED"},
    "RECOVERED": set(),   # terminal
    "STOPPED": set(),     # terminal
}


class IllegalTransition(Exception):
    pass


def assert_transition(current: str, new: str):
    current = current or "AT_RISK"
    if new not in ALLOWED_TRANSITIONS.get(current, set()):
        raise IllegalTransition(f"{current} -> {new} is not a legal transition")
    return True
