"""
Batch-level offline research metrics (kept separate from the live
product's operational dashboard metrics). Reports agent vs baseline on
IDENTICAL potential outcomes: recovery rates, absolute improvement in
percentage points, relative lift, and gross / discount / net revenue.
"""


def _summarize(results):
    n = len(results)
    recovered = [r for r in results if r["recovered"]]
    return {
        "n_records": n,
        "n_recovered": len(recovered),
        "recovery_rate": round(len(recovered) / n, 4) if n else 0.0,
        "gross_amount_recovered": round(sum(r["gross_amount_recovered"] for r in results), 2),
        "discount_amount_total": round(sum(r["discount_amount"] for r in results), 2),
        "net_amount_recovered": round(sum(r["net_amount_recovered"] for r in results), 2),
    }


from offline.policies import BASELINE_NAME, BASELINE_DEFINITION


def compute_metrics(agent_results, baseline_results, calibration_report, elapsed_sec):
    agent = _summarize(agent_results)
    baseline = _summarize(baseline_results)

    abs_improvement_pp = round((agent["recovery_rate"] - baseline["recovery_rate"]) * 100, 2)
    rel_lift = (
        round((agent["recovery_rate"] / baseline["recovery_rate"] - 1) * 100, 2)
        if baseline["recovery_rate"] > 0 else None
    )
    net_lift = (
        round((agent["net_amount_recovered"] / baseline["net_amount_recovered"] - 1) * 100, 2)
        if baseline["net_amount_recovered"] > 0 else None
    )

    total_at_risk = round(sum(r["amount_inr"] for r in agent_results), 2)
    exceptions = [r for r in agent_results
                  if r["final_guardrail_reason"] == "unresolved_cycles_exceeded_exception"]

    return {
        "comparison_note": (
            "Agent and baseline were evaluated on IDENTICAL fixed potential outcomes: "
            "same record + same action + same attempt = same outcome for both policies. "
            "Outcomes are SYNTHETIC (simulated), not real-world labels."
        ),
        "total_amount_at_risk": total_at_risk,
        "agent": agent,
        "baseline": baseline,
        "baseline_name": BASELINE_NAME,
        "baseline_definition": BASELINE_DEFINITION,
        "absolute_improvement_pp": abs_improvement_pp,
        "relative_lift_pct": rel_lift,
        "net_revenue_relative_lift_pct": net_lift,
        "guardrail_blocks_total": sum(r["guardrail_block_count"] for r in agent_results),
        "n_exceptions": len(exceptions),
        "probability_model_calibration": calibration_report,
        "elapsed_sec": round(elapsed_sec, 3),
        "throughput_records_per_sec": round(len(agent_results) / elapsed_sec, 1) if elapsed_sec else None,
    }
