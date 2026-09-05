"""
Append-only, run-scoped audit logging.

Offline: each pipeline run writes its own JSONL file under
audit_runs/run_<run_id>.jsonl -- previous runs are never overwritten.

Live: the FastAPI app appends rows to an `audit_log` SQLite table
(INSERT-only; there is no update/delete code path anywhere).
"""
import json
import os
import uuid
from datetime import datetime, timezone


def new_run_id():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "_" + uuid.uuid4().hex[:6]


class JsonlAuditLogger:
    def __init__(self, directory, run_id=None):
        os.makedirs(directory, exist_ok=True)
        self.run_id = run_id or new_run_id()
        self.path = os.path.join(directory, f"run_{self.run_id}.jsonl")
        # append mode: even a reused run_id never truncates prior entries
        self._fh = open(self.path, "a")

    def log(self, entry: dict):
        entry = dict(entry)
        entry.setdefault("run_id", self.run_id)
        entry.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
        self._fh.write(json.dumps(entry, default=str) + "\n")
        self._fh.flush()

    def close(self):
        self._fh.close()
