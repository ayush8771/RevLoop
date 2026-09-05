"""
RevLoop — offline evaluation pipeline.

Run: python run_offline_pipeline.py

  1. Generate the hybrid-calibrated batch (DERIVED shape; 80/20
     record-level train/holdout split)
  2. Train the diagnosis fallback classifier
  3. Build counterfactual training rows (SYNTHETIC outcomes) and train
     P(recovery | context, action); evaluate Brier / ROC-AUC /
     calibration on the held-out split
  4. Run the EV agent over the full batch (multi-cycle, guardrails,
     simulated 24h clock)
  5. Run the naive baseline over the SAME fixed potential outcomes
  6. Compute research metrics, write run-scoped audit JSONL,
     metrics/metrics.json, metrics/dashboard.html
  7. Persist the trained probability model for the live app
     (models/recovery_model.pkl)
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.audit.logger import JsonlAuditLogger
from core.diagnosis.classifier import DiagnosisClassifier
from core.probability.build_training_data import build_rows
from core.probability.model import RecoveryProbabilityModel
from offline.generate_batch import generate_batch, split_batch
from offline.policies import run_ev_policy, run_baseline_policy
from offline.compute_metrics import compute_metrics
from offline.dashboard import build_dashboard_html

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def main(n_records=180):
    print("=== RevLoop — offline evaluation pipeline ===\n")

    print("[1/6] Generating hybrid-calibrated batch (DERIVED)...")
    batch = generate_batch(n_records)
    train_records, holdout_records = split_batch(batch)
    os.makedirs(os.path.join(BASE_DIR, "data", "output"), exist_ok=True)
    with open(os.path.join(BASE_DIR, "data", "output", "batch_full.json"), "w") as f:
        json.dump(batch, f, indent=2)
    print(f"    {len(batch)} records -> {len(train_records)} train / {len(holdout_records)} holdout")

    print("[2/6] Training diagnosis fallback classifier...")
    diag_clf = DiagnosisClassifier().fit(train_records)
    print(f"    held-out diagnosis accuracy: {diag_clf.held_out_accuracy:.3f} "
          f"(majority-class baseline: {diag_clf.majority_class_baseline_accuracy:.3f})")

    print("[3/6] Training recovery-probability model (SYNTHETIC labels)...")
    train_rows = build_rows(train_records, diag_clf, salt=1001)
    holdout_rows = build_rows(holdout_records, diag_clf, salt=2002)
    prob_model = RecoveryProbabilityModel().fit(train_rows)
    calibration = prob_model.evaluate(holdout_rows)
    print(f"    Brier (held-out): {calibration['brier_score']:.4f}  "
          f"ROC-AUC: {calibration['roc_auc']}")

    print("[4/6] Running EV agent policy (simulated clock, guardrails)...")
    audit = JsonlAuditLogger(os.path.join(BASE_DIR, "audit_runs"))
    start = time.time()
    agent_results = run_ev_policy(
        json.loads(json.dumps(batch)), diag_clf, prob_model, audit)
    elapsed = time.time() - start
    print(f"    done in {elapsed:.3f}s")

    print("[5/6] Running naive baseline on IDENTICAL potential outcomes...")
    baseline_results = run_baseline_policy(
        json.loads(json.dumps(batch)), diag_clf, audit)
    audit.close()

    print("[6/6] Computing metrics + dashboard...")
    metrics = compute_metrics(agent_results, baseline_results, calibration, elapsed)
    metrics["diagnosis_classifier_held_out_accuracy"] = diag_clf.held_out_accuracy
    metrics["diagnosis_classifier_majority_baseline_accuracy"] = diag_clf.majority_class_baseline_accuracy
    metrics["audit_run_id"] = audit.run_id
    os.makedirs(os.path.join(BASE_DIR, "metrics"), exist_ok=True)
    with open(os.path.join(BASE_DIR, "metrics", "metrics.json"), "w") as f:
        json.dump(metrics, f, indent=2)
    build_dashboard_html(metrics, os.path.join(BASE_DIR, "metrics", "dashboard.html"))

    os.makedirs(os.path.join(BASE_DIR, "models"), exist_ok=True)
    prob_model.save(os.path.join(BASE_DIR, "models", "recovery_model.pkl"))

    a, b = metrics["agent"], metrics["baseline"]
    print("\n=== RESULTS (SYNTHETIC outcomes — not real-world labels) ===")
    print(f"Total at risk:        {metrics['total_amount_at_risk']:,.2f}")
    print(f"Agent recovery:       {a['recovery_rate']*100:.1f}%  net {a['net_amount_recovered']:,.2f} "
          f"(gross {a['gross_amount_recovered']:,.2f} − discounts {a['discount_amount_total']:,.2f})")
    print(f"Baseline recovery:    {b['recovery_rate']*100:.1f}%  net {b['net_amount_recovered']:,.2f}")
    print(f"Absolute improvement: {metrics['absolute_improvement_pp']} pp")
    print(f"Relative lift:        {metrics['relative_lift_pct']}%")
    print(f"Guardrail blocks:     {metrics['guardrail_blocks_total']}   "
          f"Exceptions: {metrics['n_exceptions']}")
    print(f"\nAudit run:  audit_runs/run_{audit.run_id}.jsonl")
    print("Metrics:    metrics/metrics.json")
    print("Dashboard:  metrics/dashboard.html")
    print("Live model: models/recovery_model.pkl")
    return metrics


if __name__ == "__main__":
    main()
