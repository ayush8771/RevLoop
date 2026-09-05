"""
Live app configuration. Credentials come ONLY from environment
variables / .env (see .env.example). Nothing is hardcoded.

MOCK_MODE=true (default) lets the whole product run end-to-end with no
Razorpay credentials: the gateway returns clearly-labelled mock Payment
Links and a mock webhook endpoint can simulate the customer paying.
With MOCK_MODE=false, real test-mode keys are required and the real
Razorpay Payment Link API is called.
"""
import os

from dotenv import load_dotenv

load_dotenv()


def _bool(name, default):
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


MOCK_MODE = _bool("MOCK_MODE", True)

RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID", "")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET", "")
RAZORPAY_WEBHOOK_SECRET = os.getenv("RAZORPAY_WEBHOOK_SECRET", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

AUTH_ENABLED = _bool("REVLOOP_AUTH_ENABLED", False)

DATABASE_FILE = os.getenv("REVLOOP_DB", "revloop.db")

if not MOCK_MODE and (not RAZORPAY_KEY_ID or not RAZORPAY_KEY_SECRET):
    raise RuntimeError(
        "MOCK_MODE=false but Razorpay API credentials are missing. "
        "Set RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET in .env, or run with MOCK_MODE=true."
    )
if not MOCK_MODE and not RAZORPAY_WEBHOOK_SECRET:
    raise RuntimeError(
        "MOCK_MODE=false but RAZORPAY_WEBHOOK_SECRET is missing. Set it in .env."
    )
