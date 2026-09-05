"""
Razorpay gateway wrapper -- the ONLY module that talks to Razorpay.

Recovery mechanism: Razorpay PAYMENT LINKS (POST /v1/payment_links via
the official SDK), not Order creation -- a Payment Link is a customer-
facing URL through which the customer completes the failed payment
(possibly with a different card/method), which is the correct recovery
primitive. Order creation is not a payment retry and is not used here.

Two modes (app/config.MOCK_MODE):
  REAL (test-mode keys): razorpay.Client payment_link.create / fetch.
  MOCK: deterministic mock link objects persisted in-memory, clearly
        labelled "mock": true, so the entire product flow (including
        webhooks) runs with no credentials.

Webhook signature verification is implemented directly as
HMAC-SHA256(raw_body, webhook_secret) compared constant-time --
identical to razorpay.Utility.verify_webhook_signature -- so it is
independently testable and works in mock mode too. It MUST be fed the
raw request body bytes, never re-serialized JSON.
"""
import hashlib
import hmac
import secrets

from app.config import (
    MOCK_MODE, RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET, RAZORPAY_WEBHOOK_SECRET,
)

# In mock mode an unset webhook secret falls back to a fixed, obviously
# non-secret value so the demo webhook flow still exercises real
# signature verification code. Real mode requires the env var (enforced
# in config.py).
MOCK_WEBHOOK_SECRET = "mock_webhook_secret_not_for_production"


def webhook_secret():
    return RAZORPAY_WEBHOOK_SECRET or (MOCK_WEBHOOK_SECRET if MOCK_MODE else "")


def compute_webhook_signature(raw_body: bytes, secret: str | None = None) -> str:
    secret = secret if secret is not None else webhook_secret()
    return hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()


def verify_webhook_signature(raw_body: bytes, signature: str,
                             secret: str | None = None) -> bool:
    if not signature:
        return False
    expected = compute_webhook_signature(raw_body, secret)
    return hmac.compare_digest(expected, signature)


class _MockLinkStore:
    def __init__(self):
        self.links = {}

    def create(self, payload):
        link_id = "plink_MOCK" + secrets.token_hex(6)
        link = {
            "id": link_id,
            "entity": "payment_link",
            "status": "created",
            "amount": payload["amount"],
            "amount_paid": 0,
            "currency": payload.get("currency", "INR"),
            "description": payload.get("description", ""),
            "reference_id": payload.get("reference_id", ""),
            "customer": payload.get("customer", {}),
            "short_url": f"https://rzp.io/mock/{link_id}",
            "payments": [],
            "mock": True,
        }
        self.links[link_id] = link
        return link

    def fetch(self, link_id):
        if link_id not in self.links:
            raise KeyError(f"mock payment link {link_id} not found")
        return self.links[link_id]

    def mark_paid(self, link_id):
        link = self.fetch(link_id)
        link["status"] = "paid"
        link["amount_paid"] = link["amount"]
        link["payments"] = [{
            "payment_id": "pay_MOCK" + secrets.token_hex(6),
            "status": "captured",
            "amount": link["amount"],
        }]
        return link


_mock_store = _MockLinkStore()
_real_client = None


def _client():
    global _real_client
    if _real_client is None:
        import razorpay  # official SDK; real network call path
        _real_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))
    return _real_client


def create_payment_link(*, amount_paise: int, currency: str, description: str,
                        reference_id: str, customer_email: str | None,
                        customer_contact: str | None):
    """
    Create a Razorpay Payment Link. `amount_paise` is the amount the
    customer will actually pay (gross minus any approved discount).
    """
    payload = {
        "amount": int(amount_paise),
        "currency": currency or "INR",
        "accept_partial": False,  # exact-amount collection only; the webhook
                                  # amount check relies on this being explicit
        "description": description,
        "reference_id": reference_id,
        "notify": {"sms": False, "email": bool(customer_email)},
    }
    customer = {}
    if customer_email:
        customer["email"] = customer_email
    if customer_contact:
        customer["contact"] = customer_contact
    if customer:
        payload["customer"] = customer

    if MOCK_MODE:
        return _mock_store.create(payload)
    return _client().payment_link.create(payload)


def fetch_payment_link(link_id: str):
    if MOCK_MODE:
        return _mock_store.fetch(link_id)
    return _client().payment_link.fetch(link_id)


def mock_mark_link_paid(link_id: str):
    """MOCK MODE ONLY: simulate the customer paying the link."""
    if not MOCK_MODE:
        raise RuntimeError("mock_mark_link_paid is only available in MOCK_MODE")
    return _mock_store.mark_paid(link_id)
