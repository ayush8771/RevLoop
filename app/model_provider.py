"""
Provides the trained recovery-probability model to the live app.

Loads models/recovery_model.pkl if the offline pipeline has produced
one; otherwise trains a fresh model at startup from a generated batch
(fast: logistic regression over ~120 records) and saves it.

HONESTY: this model is trained on SIMULATED intervention outcomes.
Its live probabilities are model outputs under documented assumptions,
not measurements -- they are surfaced to the merchant as such. In
production the identical pipeline would retrain on logged real
outcomes.
"""
import os

from core.diagnosis.classifier import DiagnosisClassifier
from core.probability.build_training_data import build_rows
from core.probability.model import RecoveryProbabilityModel
from offline.generate_batch import generate_batch, split_batch

MODEL_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "models", "recovery_model.pkl",
)

_model = None


def get_model() -> RecoveryProbabilityModel:
    global _model
    if _model is not None:
        return _model
    if os.path.exists(MODEL_PATH):
        _model = RecoveryProbabilityModel.load(MODEL_PATH)
        return _model
    batch = generate_batch(120, seed=7)
    train_records, _ = split_batch(batch)
    clf = DiagnosisClassifier().fit(train_records)
    rows = build_rows(train_records, clf, salt=1001)
    _model = RecoveryProbabilityModel().fit(rows)
    os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
    _model.save(MODEL_PATH)
    return _model
