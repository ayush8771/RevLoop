"""
Diagnosis fallback classifier: when a failed_payment record has no
usable gateway code, predicts the most likely failure_reason from other
available features instead of leaving it unknown. Trained on records
where the code IS present (so ground truth exists), evaluated via
held-out accuracy against a majority-class baseline. Reports a
per-prediction confidence (max predicted class probability).
"""
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score

from core.diagnosis.rules import GATEWAY_CODE_TO_REASON, diagnose_rule_based

REASON_LABELS = list(dict.fromkeys(GATEWAY_CODE_TO_REASON.values()))


def _featurize(record):
    raw = record.get("raw_signal") or {}
    return [
        record.get("amount_inr", 0.0),
        record.get("prior_success_count", 0),
        record.get("customer_tenure_days", 0),
        raw.get("hour_of_day", 12),
    ]


class DiagnosisClassifier:
    def __init__(self):
        self.model = LogisticRegression(max_iter=5000, C=1.0)
        self.scaler = StandardScaler()
        self.label_to_idx = {l: i for i, l in enumerate(REASON_LABELS)}
        self.idx_to_label = {i: l for l, i in self.label_to_idx.items()}
        self.held_out_accuracy = None
        self.majority_class_baseline_accuracy = None

    def fit(self, records):
        labeled = [
            r for r in records
            if r.get("type") == "failed_payment"
            and (r.get("raw_signal") or {}).get("gateway_response_code") is not None
        ]
        X_raw = np.array([_featurize(r) for r in labeled])
        y = np.array([
            self.label_to_idx[GATEWAY_CODE_TO_REASON[r["raw_signal"]["gateway_response_code"]]]
            for r in labeled
        ])
        X_train_raw, X_test_raw, y_train, y_test = train_test_split(
            X_raw, y, test_size=0.25, random_state=42, stratify=y
        )
        self.scaler.fit(X_train_raw)
        self.model.fit(self.scaler.transform(X_train_raw), y_train)
        preds = self.model.predict(self.scaler.transform(X_test_raw))
        self.held_out_accuracy = float(accuracy_score(y_test, preds))
        majority = int(np.bincount(y_train).argmax())
        self.majority_class_baseline_accuracy = float(
            accuracy_score(y_test, [majority] * len(y_test))
        )
        return self

    def predict_with_confidence(self, record):
        x = self.scaler.transform(np.array([_featurize(record)]))
        proba = self.model.predict_proba(x)[0]
        idx = int(np.argmax(proba))
        return self.idx_to_label[idx], float(proba[idx])


def diagnose(record, classifier: "DiagnosisClassifier | None"):
    """Returns (failure_reason, confidence, method)."""
    reason, conf, method = diagnose_rule_based(record)
    if method != "unknown":
        return reason, conf, method
    if classifier is None:
        # honest default when no classifier is available
        return "insufficient_funds", 0.30, "default_most_common"
    reason, conf = classifier.predict_with_confidence(record)
    return reason, conf, "classifier_fallback"
