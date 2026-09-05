# RevLoop — AI Revenue Recovery Agent

**Razorpay AI Buildathon 2026 · Track 03 — AI Revenue Recovery**

AI revenue recovery for failed payments:

```text
Observe → Diagnose → Predict → Decide → Validate → Execute → Verify → Measure → Re-evaluate
```

**Core rule: AI/ML recommends. Deterministic guardrails authorize. Execution performs. Verified outcomes update state.** The LLM never makes a financial decision — it only drafts message text.

## What RevLoop does

RevLoop closes the revenue-recovery loop for failed payments. It diagnoses the failure, estimates recovery probability for each candidate intervention, calculates expected value, selects the best guardrail-feasible action, executes it through Razorpay Payment Links, and only marks revenue as recovered after the payment outcome is independently verified.

There is exactly **one decision authority**:
`core/decision/decision_engine.py`.

## Architecture

![RevLoop Architecture](docs/revloop-architecture.jpeg)

For a detailed Windows PowerShell setup, testing, Razorpay Test Mode walkthrough, troubleshooting guide, and final verification checklist, see [`docs/RevLoop-RUNBOOK-Windows-PowerShell.md`](./docs/RevLoop-RUNBOOK-Windows-PowerShell.md).

### Live path

```text
Merchant UI (frontend/, served at /ui)
   ↓
FastAPI (app/)
   ↓
Decision Engine (core/decision/decision_engine.py)     ← the ONLY decision path
   ├─ Diagnosis (core/diagnosis: gateway-code rules → classifier fallback, with confidence)
   ├─ P(recovery | context, action) (core/probability: logistic regression;
   │    features: prior successes, attempt count, failure type, time since
   │    failure, amount, customer tenure)
   ├─ EV(action) = P × amount − cost(action) (core/decision/cost_table.py)
   └─ Deterministic guardrails, run twice (core/guardrails/validator.py)
   ↓ approve / stop
Execution: Razorpay Payment Link (app/razorpay_gateway.py; MOCK or real Test Mode)
   ↓ customer pays
Webhook: raw-body HMAC signature verification → event-id deduplication
         → link-id verification → PAID-AMOUNT verification (actual paid
         amount from the Razorpay payload must equal expected net =
         gross − discount, exact to the paise; mismatch → audited for
         manual review, no state change)
         → AWAITING_OUTCOME → RECOVERED (app/webhooks.py)
   ↓
Audit (append-only) + product metrics → re-evaluate or stop
```

Live scope is **failed payments** (the workflow backed by real Razorpay Payment Link infrastructure). Checkout-abandonment and overdue-invoice flows exist in the **offline evaluation environment only**.

The recovery mechanism is the **Razorpay Payment Link** (`payment_link.create` / `payment_link.fetch` / `payment_link.paid` webhook). Order creation is not a payment retry and is not used as one.

## Quick start (no credentials needed)

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                    # defaults: MOCK_MODE=true

# offline research pipeline (also trains + saves the live model)
python run_offline_pipeline.py          # → metrics/metrics.json, metrics/dashboard.html,
                                        #   audit_runs/run_<id>.jsonl, models/recovery_model.pkl

# tests
pytest tests/ -q

# live product
uvicorn app.main:app --reload           # → http://127.0.0.1:8000/ui/ (API docs at /docs)
```

**Windows PowerShell:** use the complete [`RevLoop Windows PowerShell Runbook`](./docs/RevLoop-RUNBOOK-Windows-PowerShell.md) instead of adapting the shell commands above manually.

### Mock-mode demo flow

Create a test failed payment (seeded with a deterministic, clearly-labeled `TEST_PROFILE` customer context — e.g. a loyal customer with 14 prior successes scores a higher P(recovery) than a new customer with 1; provenance is shown in the API and UI) →

**Analyze** (diagnosis + confidence, P(recovery) per action, EVs, chosen action, reasoning, guardrail checks) →

**Execute** (creates a mock Payment Link; state → `AWAITING_OUTCOME`) →

**Simulate customer paying** (marks the mock link paid, then posts a signed `payment_link.paid` payload through the real webhook handler: signature verification, dedup, status, reference, link-id and amount checks; state → `RECOVERED`, net revenue recorded) →

dashboard shows gross / discounts / **net**.

## Real Razorpay Test Mode

The real Razorpay Test Mode path has been **validated end-to-end**:

1. RevLoop created a real Razorpay Test Mode Payment Link.
2. The test payment was completed for the approved discounted amount.
3. Razorpay delivered `payment_link.paid` to `POST /webhooks/razorpay` through a public HTTPS tunnel.
4. RevLoop verified the webhook and transitioned the transaction from `AWAITING_OUTCOME` to `RECOVERED`.
5. The database and append-only audit trail recorded the verified result under a `LIVE_TEST_MODE` run ID.

For the validated test run, a ₹1,299.00 transaction with a ₹129.90 discount produced a verified paid/net amount of **₹1,169.10**.

Production/live-mode payments have **not** been tested.

To reproduce the Test Mode flow, use [`docs/RevLoop-RUNBOOK-Windows-PowerShell.md`](./docs/RevLoop-RUNBOOK-Windows-PowerShell.md).

## Guardrails

See `docs/guardrails.md`:

- max 3 attempts
- 24h spacing (timestamp-based; offline uses a simulated clock — never sleeps)
- permanent opt-out
- fraud/DNC auto-stop
- 10% discount ceiling
- duplicate-Payment-Link prevention
- unresolved-cycle stop (exception flagged)

Validation runs before EV ranking **and** immediately before execution.

## State machine

```text
AT_RISK → DIAGNOSED → DECISION_READY → GUARDRAIL_APPROVED
        → ACTION_INITIATED → AWAITING_OUTCOME → RECOVERED | FAILED
FAILED  → RE_EVALUATE → (next cycle) | STOPPED
```

Creating a Payment Link is **not** a recovery. `RECOVERED` is only reachable through verified payment (webhook or the verification endpoint), and never manually.

## Fair baseline & honest measurement

The offline evaluation uses **fixed potential outcomes**: the outcome of (record, action, attempt) is a deterministic function, so the EV agent and the **Deterministic Default-Action Baseline** (default action = `payment_link_recovery` where applicable to the diagnosed reason, otherwise the first applicable action, attempted whenever guardrail-feasible — precise definition in `offline/policies.py`) face identical worlds and differ only in chosen actions.

Reported metrics include baseline rate, agent rate, **absolute improvement in percentage points**, relative lift, and gross / discount / **net** recovered revenue.

The probability model is evaluated on a held-out 20% record split using Brier score, ROC-AUC, and a calibration curve. **All recovery outcomes are simulated** (`docs/provenance.md`, `docs/recovery_assumptions.md`); simulated intervention outcomes are not real-world labels.

### Current offline evaluation

```text
180 records → 144 train / 36 holdout

Agent recovery:       79.4%
Baseline recovery:    57.2%
Absolute improvement: 22.22 pp
Relative lift:        38.83%
Net recovered:        ₹848,380.12
Guardrail blocks:     37
Exceptions:            0
Brier:                0.1968
ROC-AUC:              0.6790
```

These figures characterize the controlled simulation environment. They are **not claimed as real-world recovery performance**.

## LLM (Groq)

`app/groq_client.py` drafts reminder messages and escalation call scripts via **policy-grounded LLM generation**: the full `docs/compliance_policy.md` is placed in the system prompt (this is prompt grounding, **not RAG** — no retrieval index exists and none is claimed).

The LLM never chooses financial actions.

Without `GROQ_API_KEY` (or on any API failure) it falls back to deterministic templates that cite the compliance rule they follow.

## Data provenance

RevLoop deliberately distinguishes:

- **REAL** — external production/test-system observations where applicable
- **DERIVED** — distributions/parameters derived from public dataset statistics
- **SYNTHETIC** — generated records and simulated intervention outcomes used for offline evaluation
- **MOCK** — credential-free local demo behavior
- **TEST MODE** — real Razorpay sandbox interactions

This provenance is surfaced in the product, documentation, and audit records.

## Repository map

```text
core/        shared intelligence: diagnosis, probability, decision, guardrails,
             state machine, clock, audit logger

app/         live FastAPI product: config, DB, gateway, webhooks, decision API,
             verification, recoveries, dashboard, auth, Groq client

offline/     evaluation environment: batch generator (DERIVED), potential
             outcomes (SYNTHETIC), agent + baseline policies, research metrics

frontend/    merchant UI with the full intelligence panel:
             diagnosis + confidence, P(recovery), EVs, chosen action,
             reasoning, guardrail results, link, net recovered

tests/       37 tests covering guardrails, EV, fairness, revenue, state machine,
             webhook signature/dedup/transition, audit append-only behavior, API

docs/        guardrails, provenance, recovery assumptions, compliance policy,
             architecture diagram, and Windows PowerShell runbook
```

## Security

No secrets are stored in code.

`.env` is git-ignored; `.env.example` documents every supported variable.

No default admin password or JWT secret is created.

Auth (JWT) is available via `REVLOOP_AUTH_ENABLED=true` with administrator credentials supplied in `.env`.

Do not commit:

```text
.env
revloop.db
.venv/
__pycache__/
.pytest_cache/
audit_runs/*.jsonl
metrics/metrics.json
models/*.pkl
data/output/*
```

## Validation performed

The frozen implementation has been validated with:

```text
37 automated tests: PASS
Offline evaluation: PASS
Mock end-to-end recovery: PASS
Real Razorpay Test Mode Payment Link: PASS
Real Razorpay Test Mode payment: PASS
Real payment_link.paid webhook delivery: PASS
Final RECOVERED state + database + audit verification: PASS
```

## Known limitations

- Live probabilities come from a model trained on **simulated** outcomes; live customer context is persisted per transaction and seeded from clearly-labeled TEST_PROFILE demo values (with a documented DEFAULT_FALLBACK when absent) until a merchant integration supplies real history.
- Diagnosis for ambiguous live error codes falls back to a stated low-confidence default rather than a live-trained classifier.
- Single-process SQLite; fine for demo/Test Mode scale.
- Production/live-mode payments have not been tested.
- The offline recovery metrics are controlled simulation results, not real-world recovery claims.
- Deliberately not built: contextual bandit, multi-agent, voice, WebSockets, vector DB/RAG, microservices, and XGBoost as a required dependency.
