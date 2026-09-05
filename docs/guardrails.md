# Guardrails (deterministic authorization layer)

`core/guardrails/validator.py`. Runs twice per decision: before the EV
argmax (candidate filtering) and immediately before execution
(post-check on the concrete chosen action + discount).

| # | Rule | Enforcement |
|---|------|-------------|
| G1 | Max **3** recovery attempts per record | `attempt_count < 3` pre + post |
| G2 | Min **24h** between contact attempts | timestamp comparison (`last_attempt_at + 24h <= now`) via the Clock abstraction; the offline pipeline advances a **simulated** clock — nothing ever sleeps |
| G3 | Opt-out **permanently** blocks contact | pre + post; opt-out endpoint sets the flag |
| G4 | Fraud / do-not-contact → automatic stop | pre + post |
| G5 | Discount ceiling = **10%** of order value | post-check on the concrete discount amount (floored, so rounding can never breach it) |
| G6 | Duplicate Payment Link prevention | link-creating actions infeasible while an unpaid link is active; reminder/escalate **reuse** the active link |
| G7 | Unresolved stopping rule | > 5 unresolved decision cycles → auto stop, flagged as an exception in metrics |

Temporal blocks (G2 spacing, G6 active link) do **not** terminate a
record — the live API returns `blocked_temporarily` with
`next_allowed_at` and the record keeps its state. Permanent blocks
(G1, G3, G4, G7) transition the record to `STOPPED`.
