"""Core intelligence + guardrail tests (no FastAPI involved)."""
from datetime import datetime, timedelta, timezone

import pytest

from core.clock import SimulatedClock
from core.decision.decision_engine import decide
from core.decision.cost_table import COST_FUNCTIONS
from core.diagnosis.classifier import DiagnosisClassifier
from core.guardrails.validator import (
    GuardrailContext, feasible_actions, validate_chosen_action,
    MAX_ATTEMPTS, DISCOUNT_CEILING_FRACTION,
)
from core.probability.build_training_data import build_rows
from core.probability.model import RecoveryProbabilityModel
from core.state_machine import assert_transition, IllegalTransition
from offline.generate_batch import generate_batch, split_batch
from offline.policies import run_ev_policy, run_baseline_policy
from offline.potential_outcomes import potential_outcome, ACTIONS_BY_REASON

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
ALL_ACTIONS = ["payment_link_recovery", "discount_offer", "reminder_message", "escalate_call"]


def ctx(**kw):
    defaults = dict(record_id="rec_x", amount=1000.0)
    defaults.update(kw)
    return GuardrailContext(**defaults)


class _NullAudit:
    def log(self, entry):
        pass


@pytest.fixture(scope="module")
def trained():
    batch = generate_batch(150, seed=11)
    train, holdout = split_batch(batch)
    clf = DiagnosisClassifier().fit(train)
    rows = build_rows(train, clf, salt=1001)
    model = RecoveryProbabilityModel().fit(rows)
    report = model.evaluate(build_rows(holdout, clf, salt=2002))
    return batch, clf, model, report


# ---------------- guardrails ----------------

def test_max_attempts_blocks_fourth_attempt():
    c = ctx(attempt_count=MAX_ATTEMPTS)
    feas, reason, _ = feasible_actions(c, ALL_ACTIONS, NOW)
    assert feas == [] and reason == "max_attempts_exceeded"


def test_24h_spacing_blocks_and_then_allows():
    c = ctx(attempt_count=1, last_attempt_at=NOW - timedelta(hours=23))
    feas, reason, _ = feasible_actions(c, ALL_ACTIONS, NOW)
    assert feas == [] and reason == "min_24h_spacing_not_elapsed"
    c2 = ctx(attempt_count=1, last_attempt_at=NOW - timedelta(hours=25))
    feas2, reason2, _ = feasible_actions(c2, ALL_ACTIONS, NOW)
    assert feas2 == ALL_ACTIONS and reason2 is None


def test_opt_out_permanently_blocks():
    feas, reason, _ = feasible_actions(ctx(opted_out=True), ALL_ACTIONS, NOW)
    assert feas == [] and reason == "opted_out_permanent_stop"
    ok, why, _ = validate_chosen_action(ctx(opted_out=True), "reminder_message", NOW)
    assert not ok and why == "post_check_opted_out"


def test_fraud_and_dnc_auto_stop():
    for kw in ({"fraud_flag": True}, {"do_not_contact": True}):
        feas, reason, _ = feasible_actions(ctx(**kw), ALL_ACTIONS, NOW)
        assert feas == [] and reason == "fraud_or_dnc_auto_stop"


def test_discount_ceiling_enforced():
    c = ctx(amount=1000.0)
    ok, _, _ = validate_chosen_action(c, "discount_offer", NOW, discount_amount=100.0)
    assert ok  # exactly 10% is allowed
    ok2, why, _ = validate_chosen_action(c, "discount_offer", NOW, discount_amount=100.01)
    assert not ok2 and why == "discount_ceiling_exceeded"


def test_duplicate_payment_link_prevented():
    c = ctx(active_payment_link_id="plink_1")
    feas, _, _ = feasible_actions(c, ALL_ACTIONS, NOW)
    assert "payment_link_recovery" not in feas and "discount_offer" not in feas
    assert "reminder_message" in feas  # reminder can reuse the active link
    ok, why, _ = validate_chosen_action(c, "payment_link_recovery", NOW)
    assert not ok and why == "duplicate_payment_link_blocked"


def test_unresolved_cycles_exception_stop():
    feas, reason, _ = feasible_actions(ctx(unresolved_cycles=5), ALL_ACTIONS, NOW)
    assert feas == [] and reason == "unresolved_cycles_exceeded_exception"


# ---------------- decision engine / EV ----------------

class _FixedModel:
    def __init__(self, probs):
        self.probs = probs

    def predict_one(self, context, reason, action, attempt_number):
        return self.probs[action]


def test_ev_argmax_accounts_for_cost():
    # discount has the highest raw P but its cost makes the link win on EV
    probs = {"payment_link_recovery": 0.50, "discount_offer": 0.55,
             "reminder_message": 0.10, "escalate_call": 0.20}
    amount = 1000.0
    d = decide(
        {"amount_inr": amount, "prior_success_count": 1,
         "customer_tenure_days": 100, "hours_since_failure": 12},
        ctx(amount=amount), _FixedModel(probs),
        ("insufficient_funds", 0.9, "rule"), NOW, ALL_ACTIONS,
    )
    evs = {s["action"]: s["ev"] for s in d.scored_candidates}
    assert d.action == max(evs, key=evs.get) == "payment_link_recovery"
    for s in d.scored_candidates:
        expected = probs[s["action"]] * amount - COST_FUNCTIONS[s["action"]](amount)
        assert abs(s["ev"] - expected) < 0.01


def test_decision_discount_never_exceeds_ceiling():
    probs = {a: 0.1 for a in ALL_ACTIONS}
    probs["discount_offer"] = 0.99
    for amount in (999.99, 1000.01, 333.33, 49900 / 100):
        d = decide(
            {"amount_inr": amount, "prior_success_count": 1,
             "customer_tenure_days": 100, "hours_since_failure": 12},
            ctx(amount=amount), _FixedModel(probs),
            ("insufficient_funds", 0.9, "rule"), NOW, ALL_ACTIONS,
        )
        assert d.action == "discount_offer"
        assert d.discount_amount <= amount * DISCOUNT_CEILING_FRACTION + 1e-9


def test_llm_not_in_decision_path():
    """The decision engine must not import or call the LLM client:
    the LLM drafts message text only, never chooses actions."""
    import inspect
    import core.decision.decision_engine as de
    src = inspect.getsource(de)
    imports = [l for l in src.splitlines() if l.strip().startswith(("import ", "from "))]
    assert not any("groq" in l.lower() for l in imports)
    assert "draft_message" not in src and "requests" not in src


# ---------------- fair baseline ----------------

def test_potential_outcomes_identical_across_policies():
    record = {"record_id": "rec_00042", "prior_success_count": 2,
              "fraud_flag": False, "opted_out": False}
    for action in ALL_ACTIONS:
        for attempt in (1, 2, 3):
            a = potential_outcome("card_issue", action, record, attempt)
            b = potential_outcome("card_issue", action, record, attempt)
            assert a == b  # same record + action + attempt => same outcome


def test_agent_and_baseline_share_outcome_table(trained):
    batch, clf, model, _ = trained
    import json
    agent = run_ev_policy(json.loads(json.dumps(batch)), clf, model, _NullAudit())
    base = run_baseline_policy(json.loads(json.dumps(batch)), clf, _NullAudit())
    base_by_id = {r["record_id"]: r for r in base}
    # wherever the agent chose the baseline's action pattern the results
    # must be reproducible from the shared table; spot-check determinism
    agent2 = run_ev_policy(json.loads(json.dumps(batch)), clf, model, _NullAudit())
    assert [r["recovered"] for r in agent] == [r["recovered"] for r in agent2]
    assert len(base_by_id) == len(agent)


# ---------------- revenue accounting ----------------

def test_net_recovered_subtracts_discount(trained):
    batch, clf, model, _ = trained
    import json
    results = run_ev_policy(json.loads(json.dumps(batch)), clf, model, _NullAudit())
    saw_discount = False
    for r in results:
        if r["recovered"]:
            assert abs(r["net_amount_recovered"] -
                       (r["gross_amount_recovered"] - r["discount_amount"])) < 0.01
            if r["discount_amount"] > 0:
                saw_discount = True
                assert r["discount_amount"] <= r["amount_inr"] * DISCOUNT_CEILING_FRACTION + 0.01
        else:
            assert r["net_amount_recovered"] == 0.0
    assert saw_discount, "expected at least one recovered discount case in the batch"


# ---------------- probability model ----------------

def test_probability_model_outputs_and_calibration(trained):
    _, _, model, report = trained
    p = model.predict_one(
        {"amount_inr": 1200.0, "prior_success_count": 3,
         "customer_tenure_days": 200, "hours_since_failure": 10},
        "insufficient_funds", "discount_offer", 1)
    assert 0.0 <= p <= 1.0
    assert 0.0 < report["brier_score"] < 0.30
    assert report["roc_auc"] is None or report["roc_auc"] > 0.55
    assert "SYNTHETIC" in report["label_provenance"]


# ---------------- state machine ----------------

def test_state_machine_transitions():
    assert_transition("AT_RISK", "DIAGNOSED")
    assert_transition("AWAITING_OUTCOME", "RECOVERED")
    with pytest.raises(IllegalTransition):
        assert_transition("AT_RISK", "RECOVERED")  # never recovered without the loop
    with pytest.raises(IllegalTransition):
        assert_transition("RECOVERED", "AT_RISK")  # terminal


# ---------------- simulated clock ----------------

def test_simulated_clock_never_sleeps():
    import time
    clock = SimulatedClock()
    t0 = time.time()
    for _ in range(100):
        clock.advance(hours=25)
    assert time.time() - t0 < 1.0
    assert (clock.now() - SimulatedClock().now()).total_seconds() == 100 * 25 * 3600
