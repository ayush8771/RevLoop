"""Append-only audit writes for the live app. INSERT-only by design --
no update or delete code path exists for audit_log anywhere.

Every event in one live server session shares LIVE_RUN_ID
(live_YYYYMMDD_HHMMSS_<short-id>, generated once per process start);
historical runs are never overwritten -- rows only accumulate."""
import json
import secrets
from datetime import datetime, timezone

from app.database import get_connection

LIVE_RUN_ID = "live_{}_{}".format(
    datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S"), secrets.token_hex(3)
)


def audit(transaction_id, event_type, *, diagnosis=None, diagnosis_confidence=None,
          candidates=None, chosen_action=None, reasoning=None, guardrail_checks=None,
          execution_id=None, payment_link_id=None, payment_status=None,
          gross_amount=None, discount_amount=None, net_recovered_amount=None,
          outcome=None, provenance="LIVE_TEST_MODE"):
    conn = get_connection()
    conn.execute(
        """INSERT INTO audit_log (
             run_id, transaction_id, event_type, diagnosis, diagnosis_confidence,
             candidates_json, chosen_action, reasoning, guardrail_json,
             execution_id, payment_link_id, payment_status,
             gross_amount, discount_amount, net_recovered_amount, outcome, provenance
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (LIVE_RUN_ID, transaction_id, event_type, diagnosis, diagnosis_confidence,
         json.dumps(candidates) if candidates is not None else None,
         chosen_action, reasoning,
         json.dumps(guardrail_checks) if guardrail_checks is not None else None,
         execution_id, payment_link_id, payment_status,
         gross_amount, discount_amount, net_recovered_amount, outcome, provenance),
    )
    conn.commit()
    conn.close()
