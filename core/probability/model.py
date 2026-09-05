"""
Recovery-probability model: P(recovery | context, action).

Logistic regression over one-hot (failure_reason, action) + numeric
context features: amount, prior successful payments, customer tenure,
attempt number, hours since failure. Interpretable and
fast; XGBoost is an optional later upgrade, not required for P0.

Held-out evaluation is by RECORD (80/20 record-level split upstream),
reporting Brier score, ROC-AUC and a calibration curve.

HONESTY: the model is trained on SIMULATED intervention outcomes
(offline/potential_outcomes.py). Simulated outcomes are not real-world
labels; in production this exact pipeline would train on logged real
intervention outcomes instead.
"""
import pickle

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import OneHotEncoder
from sklearn.calibration import calibration_curve
from sklearn.metrics import brier_score_loss, roc_auc_score

REASON_LIST = [
    "insufficient_funds", "card_issue", "card_expired", "bank_decline",
    "subscription_lapse", "checkout_abandon", "invoice_overdue",
]
ACTION_LIST = ["payment_link_recovery", "discount_offer", "reminder_message", "escalate_call"]


class RecoveryProbabilityModel:
    def __init__(self):
        self.encoder = OneHotEncoder(
            categories=[REASON_LIST, ACTION_LIST], handle_unknown="ignore"
        )
        self.model = LogisticRegression(max_iter=2000)
        self.calibration_report_ = {}

    def _featurize(self, rows):
        cat = self.encoder.transform(
            [[r["failure_reason"], r["action"]] for r in rows]
        ).toarray()
        num = np.array([[
            r["amount_inr"] / 1000.0,
            r["prior_success_count"],
            r["customer_tenure_days"] / 100.0,
            r["attempt_number"],
            r.get("hours_since_failure", 24.0) / 24.0,
        ] for r in rows])
        return np.hstack([cat, num])

    def fit(self, train_rows):
        self.encoder.fit([[r, a] for r in REASON_LIST for a in ACTION_LIST])
        X = self._featurize(train_rows)
        y = np.array([r["outcome"] for r in train_rows])
        self.model.fit(X, y)
        return self

    def predict_proba(self, rows):
        X = self._featurize(rows)
        return self.model.predict_proba(X)[:, 1]

    def evaluate(self, held_out_rows):
        y_true = np.array([r["outcome"] for r in held_out_rows])
        y_pred = self.predict_proba(held_out_rows)
        brier = float(brier_score_loss(y_true, y_pred))
        try:
            auc = float(roc_auc_score(y_true, y_pred))
        except ValueError:
            auc = None
        frac_pos, mean_pred = calibration_curve(y_true, y_pred, n_bins=8, strategy="quantile")
        self.calibration_report_ = {
            "brier_score": brier,
            "roc_auc": auc,
            "n_held_out_rows": len(held_out_rows),
            "calibration_curve": {
                "mean_predicted": mean_pred.tolist(),
                "fraction_positive": frac_pos.tolist(),
            },
            "label_provenance": "SYNTHETIC (simulated intervention outcomes, not real-world labels)",
        }
        return self.calibration_report_

    def predict_one(self, context, failure_reason, action, attempt_number):
        row = {
            "failure_reason": failure_reason, "action": action,
            "amount_inr": context["amount_inr"],
            "prior_success_count": context.get("prior_success_count", 0),
            "customer_tenure_days": context.get("customer_tenure_days", 0),
            "attempt_number": attempt_number,
            "hours_since_failure": context.get("hours_since_failure", 24.0),
        }
        return float(self.predict_proba([row])[0])

    def save(self, path):
        with open(path, "wb") as f:
            pickle.dump(self, f)

    @staticmethod
    def load(path):
        with open(path, "rb") as f:
            return pickle.load(f)
