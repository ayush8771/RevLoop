"""
Groq LLM client for customer-facing MESSAGE TEXT only (reminder
messages, escalation call scripts). The LLM never chooses recovery
actions, amounts, or discounts -- those come exclusively from the
decision engine + guardrails.

Grounding: the full text of docs/compliance_policy.md is placed in the
system prompt, and the message must follow it. This is policy-grounded LLM generation (prompt-grounding)
on a policy document, NOT retrieval-augmented generation -- no
retrieval index is involved, and we do not claim one.

If GROQ_API_KEY is unset or the call fails, drafting falls back
cleanly to deterministic templates that cite the compliance rule they
follow, so the product works with zero credentials.
"""
import os

import requests

from app.config import GROQ_API_KEY

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

_POLICY_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "docs", "compliance_policy.md",
)


def _load_policy():
    try:
        with open(_POLICY_PATH) as f:
            return f.read()
    except OSError:
        return "(compliance policy file missing)"


def _template_message(action, txn, payment_link_url, discount_paise):
    amount = txn["amount"] / 100.0
    link_part = f" You can complete it securely here: {payment_link_url}" if payment_link_url else ""
    if action == "reminder_message":
        body = (f"Hi, your payment of INR {amount:,.2f} could not be completed."
                f"{link_part} If you have already paid, please ignore this message.")
        rule = "Rule 3 (neutral, informative tone)"
    elif action == "discount_offer":
        disc = (discount_paise or 0) / 100.0
        body = (f"Hi, your payment of INR {amount:,.2f} could not be completed. "
                f"Complete it now and INR {disc:,.2f} will be applied as a one-time "
                f"adjustment (final amount INR {amount - disc:,.2f}).{link_part}")
        rule = "Rule 4 (discount must state exact value)"
    elif action == "escalate_call":
        body = (f"CALL SCRIPT: 1) Confirm you are speaking with the account holder. "
                f"2) State that a payment of INR {amount:,.2f} failed "
                f"({txn.get('error_description') or 'reason unavailable'}). "
                f"3) Offer the secure payment link. 4) Do not pressure; "
                f"offer to opt out of further contact on request.")
        rule = "Rule 5 (escalation ladder)"
    else:
        body = f"Payment of INR {amount:,.2f} is pending.{link_part}"
        rule = "Rule 3"
    return {"text": body, "generator": "template_fallback", "grounded_on": rule}


def draft_message(action, txn, payment_link_url=None, discount_paise=0):
    """Returns {text, generator, grounded_on}."""
    if not GROQ_API_KEY:
        return _template_message(action, txn, payment_link_url, discount_paise)

    policy = _load_policy()
    amount = txn["amount"] / 100.0
    user_prompt = (
        f"Draft a short {'phone call script for a human agent' if action == 'escalate_call' else 'customer message'} "
        f"for a failed payment recovery.\n"
        f"Amount: INR {amount:,.2f}\n"
        f"Failure reason: {txn.get('error_description') or txn.get('error_code') or 'unknown'}\n"
        f"Payment link: {payment_link_url or 'none'}\n"
        f"Approved discount (already authorized by guardrails, do not change it): "
        f"INR {(discount_paise or 0) / 100.0:,.2f}\n"
        f"Keep it under 80 words, neutral tone."
    )
    try:
        resp = requests.post(
            GROQ_URL,
            headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
            json={
                "model": GROQ_MODEL,
                "max_completion_tokens": 300,
                "reasoning_effort": "low",
                "messages": [
                    {"role": "system",
                     "content": ("You draft payment-recovery messages. You MUST follow this "
                                 "compliance policy exactly and never invent discounts, "
                                 "amounts, or urgency beyond it:\n\n" + policy)},
                    {"role": "user", "content": user_prompt},
                ],
            },
            timeout=15,
        )
        resp.raise_for_status()
        text = resp.json()["choices"][0]["message"]["content"].strip()
        if not text:
            raise ValueError("Groq returned empty message content")
        return {"text": text, "generator": f"groq:{GROQ_MODEL}",
                "grounded_on": "compliance_policy.md (policy-grounded generation)"}
    except Exception as exc:  # clean fallback on any API failure
        fallback = _template_message(action, txn, payment_link_url, discount_paise)
        fallback["fallback_reason"] = f"groq_call_failed: {type(exc).__name__}"
        return fallback