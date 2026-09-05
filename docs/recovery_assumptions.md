# Recovery Outcome Assumptions (simulation environment)

**These are simulation assumptions, not measured real-world recovery
rates.** No public dataset contains labeled "agent intervened →
customer paid" outcomes (that data is proprietary to payment
processors), so the offline evaluation environment uses this explicit,
documented assumption model. Every number below is implemented
verbatim in `offline/potential_outcomes.py` (`BASE_RATES`,
`true_probability`) — this document and that module are kept in exact
sync.

## Base success probability per (failure_reason, action)

| failure_reason      | payment_link_recovery | discount_offer | reminder_message | escalate_call |
|---------------------|----------------------:|---------------:|-----------------:|--------------:|
| insufficient_funds  | 0.35 | 0.55 | 0.20 | 0.45 |
| card_issue          | 0.55 | 0.60 | 0.15 | 0.40 |
| card_expired        | 0.30 | 0.35 | 0.30 | 0.35 |
| bank_decline        | 0.30 | 0.50 | 0.15 | 0.40 |
| subscription_lapse  | 0.45 | 0.55 | 0.25 | 0.40 |
| checkout_abandon    | 0.25 | 0.35 | 0.18 | n/a  |
| invoice_overdue     | n/a  | n/a  | 0.20 | 0.40 |

`n/a` means the action is not in that reason's applicable action set
(`ACTIONS_BY_REASON`): invoice recovery has no Payment Link action in
this environment, and checkout abandonment is not escalated to a call.

**Note on `card_expired`:** the action here is a *Payment Link*, not a
blind same-card retry. A Payment Link lets the customer enter a new
card, so its assumed success rate (0.30) is not near-zero the way a
same-card retry against an expired card would be. Documented
assumption, not a measured fact.

## Per-record modifiers (applied **additively**, then clipped to [0, 1])

- `+0.10` if `prior_success_count >= 5` (established, reliable payer)
- `−0.15` if `attempt_number >= 3` (contact fatigue on the 3rd attempt)
- probability forced to `0.0` if `fraud_flag` or `opted_out` is true
  (these records are guardrail-stopped before any action is attempted
  anyway; the zero makes the outcome table consistent regardless)
- amount has **no** direct effect on probability in this model (kept
  simple and auditable rather than fit to a plausible-sounding curve)

## Outcome determinism (fair comparison)

`potential_outcome(record, action, attempt)` draws a deterministic
uniform value from `sha256(seed | record_id | action | attempt)` and
compares it to the probability above. Therefore **same record + same
action + same attempt ⇒ same outcome** for the EV agent and the
Deterministic Default-Action Baseline alike — the two policies face an
identical world and differ only in which actions they choose.
Training data for the probability model uses independently *salted*
draws (`training_outcome`) so the model learns rates rather than
memorizing the evaluation world's exact outcomes.

## Provenance of these numbers

Authored assumptions for this project, directionally informed by
publicly discussed payments-industry commentary (soft-decline
follow-up success is commonly cited in the 30–60% range in industry
blog posts) — **not** peer-reviewed or measured figures. If challenged,
the honest answer is: "these are documented starting assumptions used
to generate a training/evaluation batch, chosen to be directionally
realistic, not measured ground truth." All model metrics (Brier,
ROC-AUC, calibration) and all agent-vs-baseline results characterize
performance **in this controlled simulation environment only**.
