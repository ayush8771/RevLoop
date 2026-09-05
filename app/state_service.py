"""State-machine-validated transitions for live transactions."""
from datetime import datetime, timezone

from app.database import get_connection
from core.state_machine import assert_transition


def get_transaction(payment_id):
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM transactions WHERE payment_id = ?", (payment_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def transition(payment_id, new_state, **extra_updates):
    """
    Validates current_state -> new_state against core/state_machine.py
    and applies it plus any extra column updates atomically.
    """
    conn = get_connection()
    row = conn.execute(
        "SELECT recovery_state FROM transactions WHERE payment_id = ?", (payment_id,)
    ).fetchone()
    if not row:
        conn.close()
        raise KeyError(f"transaction {payment_id} not found")
    assert_transition(row["recovery_state"] or "AT_RISK", new_state)

    sets = ["recovery_state = ?"]
    vals = [new_state]
    for col, val in extra_updates.items():
        sets.append(f"{col} = ?")
        vals.append(val)
    vals.append(payment_id)
    conn.execute(f"UPDATE transactions SET {', '.join(sets)} WHERE payment_id = ?", vals)
    conn.commit()
    conn.close()


def now_iso():
    return datetime.now(timezone.utc).isoformat()
