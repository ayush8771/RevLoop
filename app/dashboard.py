"""Live product dashboard metrics (operational; deliberately separate
from the offline research metrics in metrics/metrics.json)."""
from fastapi import APIRouter

from app.database import get_connection

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("/summary")
def dashboard_summary():
    conn = get_connection()
    q = lambda sql: conn.execute(sql).fetchone()  # noqa: E731
    at_risk = q("SELECT COALESCE(SUM(amount),0) v, COUNT(*) c FROM transactions WHERE status='failed'")
    recovered = q("""SELECT COALESCE(SUM(amount),0) gross,
                            COALESCE(SUM(discount_amount),0) disc,
                            COALESCE(SUM(net_recovered_amount),0) net,
                            COUNT(*) c
                     FROM transactions WHERE recovery_state='RECOVERED'""")
    links = q("SELECT COUNT(*) c FROM transactions WHERE recovery_link IS NOT NULL")
    awaiting = q("SELECT COUNT(*) c FROM transactions WHERE recovery_state='AWAITING_OUTCOME'")
    stopped = q("SELECT COUNT(*) c FROM transactions WHERE recovery_state='STOPPED'")
    conn.close()

    rate = round(recovered["net"] / at_risk["v"] * 100, 2) if at_risk["v"] else 0.0
    return {
        "revenue_at_risk": at_risk["v"],
        "failed_payments": at_risk["c"],
        "recovery_links": links["c"],
        "awaiting_outcome": awaiting["c"],
        "stopped": stopped["c"],
        "recovered_payments": recovered["c"],
        "gross_recovered": recovered["gross"],
        "discounts_given": recovered["disc"],
        "net_recovered": recovered["net"],
        "net_recovery_rate_pct": rate,
        "note": ("net_recovered = gross − discounts. A 10,000 order recovered with a "
                 "10% discount counts as 9,000 recovered, not 10,000. Live product "
                 "metrics; offline research metrics live in metrics/metrics.json."),
    }
