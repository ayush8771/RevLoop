# Data & result provenance

| Tag | Meaning | Where |
|-----|---------|-------|
| REAL | Directly observed live data | Razorpay Payment Link / webhook objects when `MOCK_MODE=false` with test-mode keys (still Razorpay **Test Mode**, no real money) |
| DERIVED | Synthetic records whose behavioral distributions are **parameterized using documented statistics derived from public datasets**; no raw dataset is downloaded, embedded, or redistributed. Sources: Olist Brazilian E-Commerce (https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce), IEEE-CIS Fraud Detection (https://www.kaggle.com/c/ieee-fraud-detection), public accounts-receivable/late-payment datasets on Kaggle. Parameters live in `data/calibration/dataset_stats.py`. | `offline/generate_batch.py` |
| SYNTHETIC | Simulated recovery outcomes from the documented assumption table. **Not real-world labels** — the probability model's metrics measure learning of the simulated world only. | `offline/potential_outcomes.py` |
| MOCK | Locally fabricated Razorpay objects (`"mock": true`, `plink_MOCK…`) when `MOCK_MODE=true` | `app/razorpay_gateway.py` |
| TEST MODE | Razorpay's sandbox: real API, no real money | real code path |

The audit trail tags every entry. Nothing generated or simulated is
ever presented as real.
