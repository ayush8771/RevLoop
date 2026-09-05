"""
Diagnosis layer, rule-based path: deterministic mapping from gateway
signal to failure_reason. Covers both the offline synthetic schema
(raw_signal.gateway_response_code) and live Razorpay transactions
(error_code / error_description). When no code is available the
classifier fallback (classifier.py) fills the gap.
"""

GATEWAY_CODE_TO_REASON = {
    "INSUFFICIENT_FUNDS": "insufficient_funds",
    "BAD_CVV": "card_issue",
    "CARD_EXPIRED": "card_expired",
    "BANK_DECLINE": "bank_decline",
    "MANDATE_FAILED": "subscription_lapse",
}

# Razorpay live error codes / description keywords -> failure reason.
# BAD_REQUEST_ERROR alone is ambiguous; keywords in the description
# disambiguate, otherwise the classifier fallback handles it.
RAZORPAY_DESCRIPTION_KEYWORDS = [
    ("insufficient", "insufficient_funds"),
    ("balance", "insufficient_funds"),
    ("expired", "card_expired"),
    ("cvv", "card_issue"),
    ("card", "card_issue"),
    ("declined by the bank", "bank_decline"),
    ("declined", "bank_decline"),
    ("mandate", "subscription_lapse"),
]


def diagnose_rule_based(record):
    """Offline schema. Returns (failure_reason|None, confidence, method)."""
    rtype = record.get("type")
    if rtype == "checkout_abandon":
        return "checkout_abandon", 1.0, "rule"
    if rtype == "overdue_invoice":
        return "invoice_overdue", 1.0, "rule"
    code = (record.get("raw_signal") or {}).get("gateway_response_code")
    if code in GATEWAY_CODE_TO_REASON:
        return GATEWAY_CODE_TO_REASON[code], 0.98, "rule"
    return None, 0.0, "unknown"


def diagnose_live_transaction(txn):
    """
    Live Razorpay transaction row (dict with error_code /
    error_description). Returns (failure_reason|None, confidence, method).
    """
    code = (txn.get("error_code") or "").upper()
    if code in GATEWAY_CODE_TO_REASON:
        return GATEWAY_CODE_TO_REASON[code], 0.98, "rule"
    desc = (txn.get("error_description") or "").lower()
    for kw, reason in RAZORPAY_DESCRIPTION_KEYWORDS:
        if kw in desc:
            return reason, 0.85, "rule_keyword"
    return None, 0.0, "unknown"
