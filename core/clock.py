"""
Clock abstraction so the 24h-spacing guardrail can be enforced with
timestamps in both environments:

- RealClock: wall-clock time, used by the live FastAPI app.
- SimulatedClock: manually-advanced time, used by the offline
  evaluation pipeline (a 3-attempt recovery loop spanning simulated
  days runs in milliseconds -- we never sleep for 24h).
"""
from datetime import datetime, timedelta, timezone


class RealClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class SimulatedClock:
    def __init__(self, start: datetime | None = None):
        self._now = start or datetime(2026, 9, 1, tzinfo=timezone.utc)

    def now(self) -> datetime:
        return self._now

    def advance(self, hours: float = 0.0, minutes: float = 0.0):
        self._now += timedelta(hours=hours, minutes=minutes)
        return self._now


def parse_ts(value):
    """Parse an ISO timestamp (or None) into an aware datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
