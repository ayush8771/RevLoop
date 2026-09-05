"""
SQLite persistence for the live product (failed-payment recovery scope).

Tables:
  users           auth accounts
  webhook_events  webhook deduplication (UNIQUE event_id)
  transactions    payments + full recovery lifecycle state
  audit_log       append-only decision/execution/outcome audit trail
"""
import sqlite3
from pathlib import Path

from app.config import DATABASE_FILE

DATABASE_PATH = Path(__file__).resolve().parent.parent / DATABASE_FILE


def get_connection():
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_database():
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS webhook_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT UNIQUE NOT NULL,
            event_type TEXT NOT NULL,
            payload TEXT NOT NULL,
            received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            payment_id TEXT UNIQUE,
            order_id TEXT,
            amount INTEGER,                -- gross order value, paise
            currency TEXT,
            status TEXT,                   -- gateway payment status ('failed', ...)
            method TEXT,
            email TEXT,
            contact TEXT,
            error_code TEXT,
            error_description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            -- recovery execution
            recovery_link TEXT,
            recovery_link_id TEXT,
            recovery_status TEXT,          -- initiated | pending | recovered | failed | expired
            -- recovery lifecycle (state machine, core/state_machine.py)
            recovery_state TEXT DEFAULT 'AT_RISK',
            attempt_count INTEGER DEFAULT 0,
            last_attempt_at TIMESTAMP,
            next_allowed_at TIMESTAMP,
            unresolved_cycles INTEGER DEFAULT 0,
            opted_out INTEGER DEFAULT 0,
            fraud_flag INTEGER DEFAULT 0,
            -- intelligence outputs
            diagnosis TEXT,
            diagnosis_confidence REAL,
            chosen_action TEXT,
            decision_json TEXT,
            -- revenue accounting (all paise)
            discount_amount INTEGER DEFAULT 0,
            prior_success_count INTEGER,
            customer_tenure_days INTEGER,
            recent_failure_count INTEGER,
            context_provenance TEXT,
            net_recovered_amount INTEGER DEFAULT 0,
            recovered_at TIMESTAMP
        )""")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL DEFAULT 'live',
            transaction_id TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            event_type TEXT NOT NULL,      -- decision | execution | webhook | outcome | guardrail_stop
            diagnosis TEXT,
            diagnosis_confidence REAL,
            candidates_json TEXT,
            chosen_action TEXT,
            reasoning TEXT,
            guardrail_json TEXT,
            execution_id TEXT,
            payment_link_id TEXT,
            payment_status TEXT,
            gross_amount INTEGER,
            discount_amount INTEGER,
            net_recovered_amount INTEGER,
            outcome TEXT,
            provenance TEXT
        )""")
    # lightweight migration for databases created before the
    # customer-context columns existed
    existing = {r[1] for r in conn.execute("PRAGMA table_info(transactions)")}
    for col, ddl in [
        ("prior_success_count", "prior_success_count INTEGER"),
        ("customer_tenure_days", "customer_tenure_days INTEGER"),
        ("recent_failure_count", "recent_failure_count INTEGER"),
        ("context_provenance", "context_provenance TEXT"),
    ]:
        if col not in existing:
            conn.execute(f"ALTER TABLE transactions ADD COLUMN {ddl}")
    conn.commit()
    conn.close()
