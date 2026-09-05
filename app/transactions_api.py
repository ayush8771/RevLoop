"""Transaction listing + test-transaction seeding (Test Mode helpers)."""
import random

from fastapi import APIRouter

from app.database import get_connection

router = APIRouter(prefix="/razorpay", tags=["Transactions"])

# Deterministic DEMO customer profiles. These are clearly-labeled TEST
# context values (provenance TEST_PROFILE) -- not fabricated real payment
# histories. They exist so the live demo can show context-aware
# probabilities: a loyal customer with 14 prior successes scores higher
# than a new customer with 1.
_DEMO_PROFILES = [
    {"label": "loyal",    "prior_success_count": 14, "customer_tenure_days": 730, "recent_failure_count": 0},
    {"label": "new",      "prior_success_count": 1,  "customer_tenure_days": 30,  "recent_failure_count": 2},
    {"label": "regular",  "prior_success_count": 6,  "customer_tenure_days": 365, "recent_failure_count": 1},
    {"label": "at_risk",  "prior_success_count": 2,  "customer_tenure_days": 90,  "recent_failure_count": 3},
]

_TEST_FAILURES = [
    ("INSUFFICIENT_FUNDS", "Insufficient balance in customer account"),
    ("BAD_CVV", "Card CVV validation failed"),
    ("CARD_EXPIRED", "Customer card has expired"),
    ("BANK_DECLINE", "Payment was declined by the bank"),
    ("BAD_REQUEST_ERROR", "Card payment failed"),
]


@router.post("/test-transaction")
def create_test_transaction():
    """Seed one TEST failed transaction (clearly synthetic ids/amounts)."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT payment_id FROM transactions WHERE payment_id LIKE 'pay_test_%'"
    ).fetchall()
    numbers = []
    for row in rows:
        try:
            numbers.append(int(row["payment_id"].replace("pay_test_", "")))
        except ValueError:
            pass
    n = max(numbers, default=0) + 1
    payment_id = f"pay_test_{n:03d}"
    error_code, error_description = _TEST_FAILURES[(n - 1) % len(_TEST_FAILURES)]
    amount = random.choice([49900, 129900, 249900, 549900])
    profile = _DEMO_PROFILES[(n - 1) % len(_DEMO_PROFILES)]
    conn.execute(
        """INSERT INTO transactions
           (payment_id, order_id, amount, currency, status, method, email,
            error_code, error_description, recovery_state,
            prior_success_count, customer_tenure_days, recent_failure_count,
            context_provenance)
           VALUES (?, ?, ?, 'INR', 'failed', 'card', ?, ?, ?, 'AT_RISK',
                   ?, ?, ?, ?)""",
        (payment_id, f"order_test_{n:03d}", amount,
         f"customer.{profile['label']}{n}@example.test", error_code, error_description,
         profile["prior_success_count"], profile["customer_tenure_days"],
         profile["recent_failure_count"], f"TEST_PROFILE:{profile['label']}"),
    )
    conn.commit()
    conn.close()
    return {"payment_id": payment_id, "order_id": f"order_test_{n:03d}",
            "amount": amount, "currency": "INR", "status": "failed",
            "error_code": error_code, "error_description": error_description,
            "customer_context": profile, "context_provenance": f"TEST_PROFILE:{profile['label']}",
            "provenance": "TEST"}


@router.get("/dashboard/transactions")
def dashboard_transactions():
    conn = get_connection()
    rows = conn.execute(
        """SELECT payment_id, amount, currency, status, method, error_code,
                  error_description, recovery_link, recovery_link_id, recovery_status,
                  recovery_state, attempt_count, diagnosis, chosen_action,
                  prior_success_count, customer_tenure_days, recent_failure_count,
                  context_provenance,
                  discount_amount, net_recovered_amount, created_at
           FROM transactions ORDER BY created_at DESC"""
    ).fetchall()
    conn.close()
    return {"transactions": [dict(r) for r in rows]}
