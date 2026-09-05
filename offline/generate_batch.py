"""
Generates the offline evaluation batch (provenance=DERIVED).

Record SHAPE (amounts, timing, fraud rate, overdue-day distribution)
is parameterized using documented statistics derived from public datasets (Olist order values,
IEEE-CIS fraud base rate, receivables overdue-day patterns -- see
data/calibration/dataset_stats.py). No raw real rows are embedded or
redistributed. Recovery OUTCOMES are generated separately and tagged
SYNTHETIC (offline/potential_outcomes.py) so the two kinds of
"not directly observed reality" are never confused in the audit trail.

The offline batch keeps all three flows -- failed_payment,
checkout_abandon, overdue_invoice -- for a rich EV evaluation. The
LIVE app deliberately scopes to failed payments only (the workflow
backed by real Razorpay Payment Link infrastructure).
"""
import json
import os
import random
import sys

import numpy as np
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data.calibration.dataset_stats import (
    OLIST_ORDER_VALUE_MEAN_INR, OLIST_ORDER_VALUE_STD_INR,
    OLIST_ORDER_VALUE_MIN_INR, OLIST_ORDER_VALUE_MAX_INR,
    IEEE_CIS_FRAUD_RATE, IEEE_CIS_FRAUD_AMOUNT_MULTIPLIER,
    INVOICE_OVERDUE_MEAN_DAYS, INVOICE_OVERDUE_STD_DAYS,
    INVOICE_OVERDUE_MIN_DAYS, INVOICE_OVERDUE_MAX_DAYS,
    OPT_OUT_RATE, MISSING_GATEWAY_CODE_RATE,
)

RECORD_TYPES = ["failed_payment", "checkout_abandon", "overdue_invoice"]
TYPE_WEIGHTS = [0.5, 0.3, 0.2]

GATEWAY_CODES_BY_REASON = {
    "insufficient_funds": "INSUFFICIENT_FUNDS",
    "card_issue": "BAD_CVV",
    "card_expired": "CARD_EXPIRED",
    "bank_decline": "BANK_DECLINE",
    "subscription_lapse": "MANDATE_FAILED",
}
FAILED_PAYMENT_REASON_WEIGHTS = {
    "insufficient_funds": 0.30, "card_issue": 0.20, "card_expired": 0.15,
    "bank_decline": 0.20, "subscription_lapse": 0.15,
}


def _clip_normal(rng_np, mean, std, lo, hi):
    return float(min(max(rng_np.normal(mean, std), lo), hi))


def generate_batch(n_records=180, seed=42):
    rng = random.Random(seed)
    rng_np = np.random.default_rng(seed)
    records = []
    for i in range(n_records):
        rtype = rng.choices(RECORD_TYPES, weights=TYPE_WEIGHTS, k=1)[0]
        fraud_flag = rng.random() < IEEE_CIS_FRAUD_RATE
        opted_out = (not fraud_flag) and (rng.random() < OPT_OUT_RATE)
        amount = _clip_normal(
            rng_np, OLIST_ORDER_VALUE_MEAN_INR, OLIST_ORDER_VALUE_STD_INR,
            OLIST_ORDER_VALUE_MIN_INR, OLIST_ORDER_VALUE_MAX_INR,
        )
        if fraud_flag:
            amount *= IEEE_CIS_FRAUD_AMOUNT_MULTIPLIER
        amount = round(amount, 2)
        prior_success_count = int(rng_np.poisson(3))
        customer_tenure_days = int(_clip_normal(rng_np, 180, 150, 0, 900))
        hours_since_failure = round(rng.uniform(1, 72), 1)

        raw_signal = {}
        if rtype == "failed_payment":
            # Context-modified weights give the diagnosis classifier
            # genuine learnable signal (plausible patterns, stated as
            # assumptions, not measured facts).
            weights = dict(FAILED_PAYMENT_REASON_WEIGHTS)
            if customer_tenure_days > 500:
                weights["card_expired"] *= 3.0
            if prior_success_count <= 1:
                weights["insufficient_funds"] *= 2.5
            total_w = sum(weights.values())
            true_reason = rng.choices(
                list(weights.keys()),
                weights=[w / total_w for w in weights.values()], k=1,
            )[0]
            if rng.random() < MISSING_GATEWAY_CODE_RATE:
                raw_signal["gateway_response_code"] = None  # deliberate messiness
            else:
                raw_signal["gateway_response_code"] = GATEWAY_CODES_BY_REASON[true_reason]
            raw_signal["hour_of_day"] = (
                rng.choice(list(range(22, 24)) + list(range(0, 5)))
                if true_reason == "bank_decline" else rng.randint(5, 21)
            )
        elif rtype == "checkout_abandon":
            true_reason = "checkout_abandon"
            raw_signal["cart_value"] = amount
            raw_signal["time_on_checkout_sec"] = int(_clip_normal(rng_np, 300, 200, 10, 1800))
        else:
            true_reason = "invoice_overdue"
            days_overdue = int(_clip_normal(
                rng_np, INVOICE_OVERDUE_MEAN_DAYS, INVOICE_OVERDUE_STD_DAYS,
                INVOICE_OVERDUE_MIN_DAYS, INVOICE_OVERDUE_MAX_DAYS,
            ))
            raw_signal["days_overdue"] = days_overdue
            raw_signal["invoice_due_date"] = (
                datetime(2026, 9, 1) - timedelta(days=days_overdue)
            ).date().isoformat()

        records.append({
            "record_id": f"rec_{i:05d}",
            "type": rtype,
            "true_failure_reason": true_reason,  # hidden ground truth, eval only
            "amount_inr": amount,
            "customer_id": f"cust_{rng.randint(1, 6000):05d}",
            "merchant_id": f"merch_{rng.randint(1, 5):02d}",
            "created_at": (datetime(2026, 9, 1) - timedelta(hours=hours_since_failure)).isoformat(),
            "hours_since_failure": hours_since_failure,
            "raw_signal": raw_signal,
            "prior_success_count": prior_success_count,
            "customer_tenure_days": customer_tenure_days,
            "fraud_flag": fraud_flag,
            "opted_out": opted_out,
            "provenance": "DERIVED",
        })
    return records


def split_batch(records, holdout_frac=0.2, seed=42):
    rng = random.Random(seed)
    shuffled = records[:]
    rng.shuffle(shuffled)
    n_holdout = int(len(shuffled) * holdout_frac)
    return shuffled[n_holdout:], shuffled[:n_holdout]
