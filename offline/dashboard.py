"""Static HTML report for an offline evaluation run (research metrics)."""
import json


def build_dashboard_html(metrics, path):
    a, b = metrics["agent"], metrics["baseline"]
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>RevLoop — Offline Evaluation</title>
<style>
 body{{font-family:system-ui,sans-serif;margin:2rem auto;max-width:900px;color:#1a1a2e}}
 .cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:1rem}}
 .card{{border:1px solid #ddd;border-radius:10px;padding:1rem}}
 .big{{font-size:1.6rem;font-weight:700}} .muted{{color:#666;font-size:.85rem}}
 table{{border-collapse:collapse;width:100%;margin-top:1rem}}
 td,th{{border:1px solid #ddd;padding:.5rem;text-align:right}} th:first-child,td:first-child{{text-align:left}}
 .note{{background:#fff8e1;border:1px solid #f0d060;border-radius:8px;padding:.8rem;margin:1rem 0;font-size:.9rem}}
</style></head><body>
<h1>RevLoop — Offline Evaluation (research metrics)</h1>
<div class="note"><b>Provenance:</b> {metrics["comparison_note"]}</div>
<div class="cards">
 <div class="card"><div class="muted">Agent recovery rate</div><div class="big">{a["recovery_rate"]*100:.1f}%</div></div>
 <div class="card"><div class="muted">Baseline recovery rate</div><div class="big">{b["recovery_rate"]*100:.1f}%</div></div>
 <div class="card"><div class="muted">Absolute improvement</div><div class="big">{metrics["absolute_improvement_pp"]} pp</div></div>
 <div class="card"><div class="muted">Relative lift</div><div class="big">{metrics["relative_lift_pct"]}%</div></div>
</div>
<table>
<tr><th></th><th>Agent (EV policy)</th><th>Deterministic Default-Action Baseline</th></tr>
<tr><td>Records</td><td>{a["n_records"]}</td><td>{b["n_records"]}</td></tr>
<tr><td>Recovered</td><td>{a["n_recovered"]}</td><td>{b["n_recovered"]}</td></tr>
<tr><td>Gross recovered</td><td>{a["gross_amount_recovered"]:,}</td><td>{b["gross_amount_recovered"]:,}</td></tr>
<tr><td>Discounts given</td><td>{a["discount_amount_total"]:,}</td><td>{b["discount_amount_total"]:,}</td></tr>
<tr><td><b>Net recovered</b></td><td><b>{a["net_amount_recovered"]:,}</b></td><td><b>{b["net_amount_recovered"]:,}</b></td></tr>
</table>
<h2>Probability model (held-out)</h2>
<p>Brier: {metrics["probability_model_calibration"]["brier_score"]:.4f} ·
ROC-AUC: {metrics["probability_model_calibration"]["roc_auc"]} ·
rows: {metrics["probability_model_calibration"]["n_held_out_rows"]}</p>
<p class="muted">Guardrail blocks: {metrics["guardrail_blocks_total"]} · Exceptions: {metrics["n_exceptions"]}
· Throughput: {metrics["throughput_records_per_sec"]} rec/s</p>
<details><summary>Raw metrics JSON</summary><pre>{json.dumps(metrics, indent=2)}</pre></details>
</body></html>"""
    with open(path, "w") as f:
        f.write(html)
