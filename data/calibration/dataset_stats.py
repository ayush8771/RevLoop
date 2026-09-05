"""
Calibration constants for the synthetic data generator.

IMPORTANT / HONESTY NOTE:
These numbers are derived from publicly documented summary statistics of
three public datasets (Olist Brazilian E-Commerce, IEEE-CIS / Vesta Fraud
Detection, and public invoice/receivables datasets on Kaggle), NOT from a
live download of the raw data. No raw records from these datasets are
redistributed anywhere in this repository. Only distributional shape
(means, spreads, rates) is used to make the synthetic batch realistic.
Recovery outcomes are NEVER taken from these sources -- no public dataset
contains agent-intervention recovery-outcome labels. Recovery outcomes are
generated separately from a documented assumption table
(see docs/recovery_assumptions.md).

Sources:
  - Olist Brazilian E-Commerce Public Dataset:
    https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce
  - IEEE-CIS Fraud Detection (Vesta):
    https://www.kaggle.com/c/ieee-fraud-detection
  - Public invoice / accounts-receivable late-payment datasets (Kaggle)
"""

# ---- Olist-derived (order value, payment mix, delivery delay) ----
OLIST_ORDER_VALUE_MEAN_INR = 6500      # scaled to INR context for this project
OLIST_ORDER_VALUE_STD_INR = 4200
OLIST_ORDER_VALUE_MIN_INR = 300
OLIST_ORDER_VALUE_MAX_INR = 45000
OLIST_INSTALLMENT_SHARE = 0.42          # fraction of orders paid in installments
OLIST_DELIVERY_DELAY_MEAN_DAYS = 2.5
OLIST_DELIVERY_DELAY_STD_DAYS = 3.0

# ---- IEEE-CIS / Vesta-derived (fraud base rate, txn amount pattern) ----
IEEE_CIS_FRAUD_RATE = 0.035             # ~3.5% documented positive rate
IEEE_CIS_FRAUD_AMOUNT_MULTIPLIER = 1.8  # fraud txns skew higher amount on average

# ---- Invoice / receivables-derived (days overdue distribution) ----
INVOICE_OVERDUE_MEAN_DAYS = 18
INVOICE_OVERDUE_STD_DAYS = 14
INVOICE_OVERDUE_MIN_DAYS = 1
INVOICE_OVERDUE_MAX_DAYS = 120

# ---- Other calibrated behavioral rates (documented assumptions, not measured) ----
OPT_OUT_RATE = 0.05                     # fraction of customers who have opted out of contact
MISSING_GATEWAY_CODE_RATE = 0.12        # deliberate messiness: gateway code sometimes absent
