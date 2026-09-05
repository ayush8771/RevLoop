# RevLoop — AI Revenue Recovery Agent
# COMPLETE TESTING & RUNNABLE SETUP GUIDE — Windows PowerShell

Every command, route, port, variable, and expected output below was verified
against the actual frozen repository (`revloop-final-submission.zip`).
Nothing in this guide modifies the project.

Conventions used throughout:
- `PS>` blocks = commands you type into **Windows PowerShell**.
- "PASTE INTO FILE" blocks = text you put into a file (never typed into PowerShell).
- "PASTE INTO DASHBOARD" = values you enter on a website (e.g. Razorpay).

==================================================
## 1. PREREQUISITES
==================================================

You need exactly two things installed. Nothing else.

### 1.1 Python 3.10 or newer (3.11/3.12 recommended)

- **What it is:** the language runtime the whole project runs on.
- **Why RevLoop needs it:** the backend (FastAPI), the offline ML pipeline
  (scikit-learn/numpy), and the tests are all Python.
- **Check whether it is installed:**

```powershell
python --version
```

If that prints nothing or errors, also try the Windows launcher:

```powershell
py --version
```

- **Expected:** `Python 3.10.x` or higher. The repository was built and
  verified on Python 3.12. If neither command works, install Python from
  https://www.python.org/downloads/windows/ and during installation tick
  **"Add python.exe to PATH"**.

> If `python` works, use `python` in every command below. If only `py`
> works, replace `python` with `py` everywhere.

### 1.2 pip (comes bundled with Python)

- **What it is:** Python's package installer.
- **Why RevLoop needs it:** to install `requirements.txt`.
- **Check:**

```powershell
python -m pip --version
```

- **Expected:** any pip ≥ 21 is fine (e.g. `pip 24.x`).

### 1.3 Things you do NOT need

- **Git is NOT required.** The project ships as a ZIP; nothing in the code
  uses git.
- **No Node.js, no database server, no Docker.** The database is SQLite
  (a file, created automatically by Python's built-in `sqlite3`).
- The virtual-environment tool (`venv`) is built into Python — nothing to
  install.
- **Only for Section 8 (real Razorpay Test Mode):** you will additionally
  need one HTTPS tunnel tool (ngrok or cloudflared) so Razorpay's servers
  can reach your machine. Not needed for mock mode or the offline pipeline.
  Setup is covered in Section 8.

==================================================
## 2. EXTRACTING / OPENING THE PROJECT
==================================================

Assume the ZIP is in your Downloads folder. Adjust the path if yours is
elsewhere.

```powershell
# 2.1 Go to where the ZIP is
cd $HOME\Downloads

# 2.2 Confirm the ZIP is there
Get-ChildItem revloop-final-submission.zip

# 2.3 Extract it (creates a folder named "revloop" inside the destination)
Expand-Archive -Path .\revloop-final-submission.zip -DestinationPath $HOME\revloop-project -Force

# 2.4 Enter the project ROOT (note: the ZIP contains a "revloop" folder)
cd $HOME\revloop-project\revloop

# 2.5 Confirm you are in the right place
Get-Location
Get-ChildItem
```

**What you must see from `Get-ChildItem`** (this confirms you are in the
project root — the directory every later command runs from):

```
app/            core/           data/          docs/
frontend/       offline/        tests/         audit_runs/
metrics/        models/
README.md       requirements.txt    run_offline_pipeline.py
.env.example    .gitignore          conftest.py
```

If you do **not** see `requirements.txt` and `run_offline_pipeline.py`,
you are one folder too high or too low — `cd` until you do. Every command
in this guide is run from this folder.

==================================================
## 3. CREATE AND ACTIVATE PYTHON VIRTUAL ENVIRONMENT
==================================================

```powershell
# 3.1 Create the virtual environment (a private Python just for RevLoop)
python -m venv .venv

# 3.2 Activate it
.\.venv\Scripts\Activate.ps1
```

### If step 3.2 is blocked

If PowerShell prints *"running scripts is disabled on this system"*, your
execution policy is blocking the activation script. Run this **safe,
current-user-only** command once, then retry 3.2:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

(`RemoteSigned` for the current user only is the standard safe setting: it
allows local scripts like `Activate.ps1` while still blocking unsigned
scripts downloaded from the internet. It does not affect other users.)

### 3.3 Verify activation

```powershell
# Your prompt should now start with (.venv). Also verify:
Get-Command python | Select-Object Source
python --version
```

**Expected:** the `Source` path ends in `\revloop\.venv\Scripts\python.exe`
and the version is 3.10+. That proves you are using the project's private
Python.

==================================================
## 4. INSTALL DEPENDENCIES
==================================================

- **Which file controls dependencies:** `requirements.txt` in the project
  root. That is the only dependency file in the repository. Its exact
  contents: `fastapi`, `uvicorn`, `python-dotenv`, `razorpay`, `requests`,
  `PyJWT`, `numpy`, `scikit-learn`, `pydantic`, `pytest`, `httpx<1`.

```powershell
# 4.1 Install (with .venv active, from the project root)
python -m pip install -r requirements.txt

# 4.2 Verify the important packages landed
python -m pip show fastapi uvicorn razorpay scikit-learn | Select-String "Name|Version"
```

**Expected:** four Name/Version pairs print with no errors.

**If installation fails:**
- *Network/proxy error:* re-run the same command; pip resumes.
- *"error: Microsoft Visual C++ 14.0 required"* (rare; numpy/scikit-learn
  normally install as prebuilt wheels): make sure you are on Python
  3.10–3.12 (64-bit) so prebuilt wheels exist, then re-run.
- *Old pip:* `python -m pip install --upgrade pip` and retry.

==================================================
## 5. CONFIGURATION / .ENV FILE
==================================================

### The facts (verified in `app/config.py` and `app/auth.py`)

- **Yes, you create a `.env` file**, in the **project root** (same folder
  as `requirements.txt`), named exactly `.env` (no other name is read).
- It is loaded automatically at startup by `python-dotenv` — API keys are
  pasted into `.env`, never anywhere in the code.
- The project uses **`REVLOOP_*`** variables for its own settings and
  `RAZORPAY_*` / `GROQ_*` for provider credentials.
- `.gitignore` already excludes `.env`.

### Create it by copying the shipped template

```powershell
Copy-Item .env.example .env
notepad .env
```

### Complete `.env` template (PLACEHOLDERS ONLY — this is file content, not PowerShell)

```
# ---------- provider credentials ----------
RAZORPAY_KEY_ID=YOUR_VALUE_HERE
RAZORPAY_KEY_SECRET=YOUR_VALUE_HERE
RAZORPAY_WEBHOOK_SECRET=YOUR_VALUE_HERE
GROQ_API_KEY=YOUR_VALUE_HERE

# ---------- mode ----------
MOCK_MODE=true

# ---------- optional ----------
REVLOOP_AUTH_ENABLED=false
REVLOOP_ADMIN_USERNAME=admin
REVLOOP_ADMIN_PASSWORD=
REVLOOP_JWT_SECRET=
```

### Every supported variable, exactly as the code reads them

| Variable | Required? | What it does | Where the value comes from |
|---|---|---|---|
| `MOCK_MODE` | yes (default `true`) | `true` (also accepts `1/yes/on`) = fully credential-free demo with mock Payment Links. `false` = real Razorpay Test Mode API. | you choose |
| `RAZORPAY_KEY_ID` | only when `MOCK_MODE=false` | Razorpay API key id | Razorpay Dashboard → **Test Mode** → Settings → API Keys → *Generate Test Key* (see §8.1) |
| `RAZORPAY_KEY_SECRET` | only when `MOCK_MODE=false` | Razorpay API secret | shown **once** when you generate the test key — download/copy it immediately |
| `RAZORPAY_WEBHOOK_SECRET` | only when `MOCK_MODE=false` | verifies webhook signatures | **you invent this string yourself** and type the *same* value in two places: your `.env` and the "Secret" field when creating the webhook in the Razorpay dashboard (§8.2) |
| `GROQ_API_KEY` | optional, both modes | LLM drafting of reminder/call-script text only (never decisions) | https://console.groq.com → API Keys. **Leave empty and everything still works** — the app falls back to built-in compliant templates |
| `GROQ_MODEL` | optional | override LLM model name (default `llama-3.3-70b-versatile`) | leave unset |
| `REVLOOP_AUTH_ENABLED` | optional (default `false`) | turns JWT login on/off | leave `false` for testing |
| `REVLOOP_ADMIN_USERNAME` / `REVLOOP_ADMIN_PASSWORD` | only if auth enabled | admin login. **No default password exists** — if the password var is empty, no admin user is ever created | you choose |
| `REVLOOP_JWT_SECRET` | optional | stable JWT signing secret; if unset a random one is generated per start | you choose |
| `REVLOOP_DB` | optional (default `revloop.db`) | SQLite filename | leave unset |

### MOCK MODE configuration (Section 6 uses this)

Only one line matters; leave every credential blank:

```
MOCK_MODE=true
```

### REAL RAZORPAY TEST MODE configuration (Section 8 uses this)

```
MOCK_MODE=false
RAZORPAY_KEY_ID=YOUR_TEST_KEY_ID_HERE
RAZORPAY_KEY_SECRET=YOUR_TEST_KEY_SECRET_HERE
RAZORPAY_WEBHOOK_SECRET=YOUR_OWN_INVENTED_SECRET_HERE
```

The app **refuses to start** (clear `RuntimeError`) if `MOCK_MODE=false`
and any of those three is missing — that is intentional.

### Security rules (non-negotiable)

- **Never commit `.env`** (it is already in `.gitignore` — keep it there).
- **Never put the secrets on GitHub**, in screenshots, or in recordings.
- **Never paste your real keys/secrets into Claude, ChatGPT, or any AI tool.**
- Keep them local to your machine; regenerate the Razorpay key if you ever
  suspect exposure (Dashboard → API Keys → Regenerate).

==================================================
## 6. FIRST TEST: MOCK MODE
==================================================

### 6.1 Configuration

`.env` needs only `MOCK_MODE=true` (which `Copy-Item .env.example .env`
already gives you). All credentials blank.

### 6.2 Start the application

```powershell
# From the project root, with (.venv) active:
uvicorn app.main:app --port 8000
```

- **Working directory:** the project root (where `requirements.txt` is).
  Starting from anywhere else breaks imports and frontend serving.
- **Port:** 8000. (Uvicorn's default is also 8000; we pass it explicitly.
  The app's CORS list expects 8000, so do not pick a random other port.)

**Expected startup output** (order may vary slightly):

```
INFO:     Started server process [....]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
```

The first start also silently creates `revloop.db` (SQLite) and trains/loads
the probability model into `models/recovery_model.pkl` on first decision.
Leave this PowerShell window running; open a **second** PowerShell window
for any later commands.

### 6.3 Open the application

| What | URL |
|---|---|
| **Merchant UI (use this)** | http://127.0.0.1:8000/ui/ |
| Health check | http://127.0.0.1:8000/health |
| Interactive API docs (Swagger) | http://127.0.0.1:8000/docs |

Open **http://127.0.0.1:8000/ui/** in any browser.

- **Authentication: NOT required.** `REVLOOP_AUTH_ENABLED` defaults to
  `false`, and the repository defines **no default username/password at
  all** (an admin user is only ever created if you set
  `REVLOOP_ADMIN_PASSWORD` yourself). You land directly on the dashboard.
- Quick health verification from the second PowerShell window:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

Expected: `status: healthy`, `mock_mode: True`.

### 6.4 One complete mock recovery, step by step

The chain you are about to watch:
**failed payment → diagnosis → recovery probability → EV/action selection
→ guardrail validation → execute → mock Payment Link → simulated payment
→ signed webhook → RECOVERED.**

**STEP 1 — Create a failed payment**
1. *What you do:* on the dashboard (http://127.0.0.1:8000/ui/), click the
   blue **“+ Create test failed payment”** button (top right).
2. *Where:* Dashboard page.
3. *Expected result:* the metric cards update (Revenue at risk > ₹0) and a
   new row `pay_test_001` appears in the **Failed payments** table with an
   error such as `INSUFFICIENT_FUNDS`, state badge **At Risk**.
4. *Proof of success:* the row exists. (Internally this seeded a clearly
   labeled TEST transaction with a deterministic demo customer profile —
   the first one is `TEST_PROFILE:loyal`, 14 prior successes.)

**STEP 2 — Open the transaction**
1. Click **“Open →”** at the end of the `pay_test_001` row.
2. You land on the transaction page (`transaction.html?payment_id=pay_test_001`).
3. Expected: amount, error, “Attempts used 0 / 3”, state **At Risk**.

**STEP 3 — Analyze (diagnosis → probability → EV → guardrails)**
1. Click **“Step 1 · Analyze — AI recommends.”**
2. *Where:* transaction page, first button.
3. *Expected result:*
   - **AI Diagnosis & Recommendation** panel fills in: Customer context
     (e.g. `14 prior successes · 730d tenure · 0 recent failures
     [TEST_PROFILE:loyal]`), Diagnosis (e.g. *Insufficient Funds*),
     Confidence (e.g. 98%), Selected action, and a plain-English
     reasoning box.
   - **Candidate actions — Expected Value** table lists all four actions
     with P(recovery), Cost, and EV; the chosen row is highlighted green.
   - **Guardrail checks** panel shows green ✓ lines (max attempts,
     24h spacing, opt-out, fraud, discount ceiling, duplicate link…).
   - Green flash message: *“Decision computed (no customer contact yet).”*
4. *Proof:* state badge advances to **Decision Ready**; probabilities are
   visible per action. (Note the honesty footer: probabilities come from a
   model trained on simulated outcomes.)

**STEP 4 — Execute (guardrails authorize, link is created)**
1. Click **“Step 2 · Execute — guardrails authorize.”**
2. *Expected result:* flash *“Action executed: …”*; the **Payment Link**
   row in the summary now shows a mock link like
   `https://rzp.io/mock/plink_MOCK…`; state badge becomes
   **Awaiting Outcome**; Attempts used becomes **1 / 3**.
3. *Proof it succeeded — and that a link is NOT a recovery:* Net recovered
   is still “—”, and the dashboard’s **Net recovered** card is still ₹0.
4. *Bonus guardrail proof:* click Execute again immediately — you get
   *“Not executed: blocked_temporarily (Min 24H Spacing Not Elapsed)”* and
   the state does **not** change. That is guardrail G2 working.

**STEP 5 — Simulate the customer paying (mock)**
1. Click **“Simulate customer paying (mock)”** (this button only exists in
   mock mode).
2. *What happens internally (visible in the flash + server log):* the mock
   link is marked paid, then the frontend POSTs a **fully signed**
   `payment_link.paid` payload to the real webhook endpoint
   `/webhooks/razorpay`, which runs signature verification → event-id
   dedup → event-type check → entity status=="paid" check → reference-id
   check → link-id check → **amount check** → state transition.
3. *Expected result:* green flash *“Webhook verified → RECOVERED. Net
   ₹…”*; state badge turns green **Recovered**; “Net recovered” shows e.g.
   `₹44,910 (gross ₹49,900 − discount ₹4,990)` (exact numbers depend on
   the seeded amount/action).
4. *Proof:* go back to the Dashboard — **Net recovered** and **Net
   recovery rate** cards are now non-zero, and the Recoveries page lists
   the transaction with gross/discount/net columns filled.

**Optional API-only version of the same flow** (second PowerShell window):

```powershell
$t = Invoke-RestMethod -Method Post http://127.0.0.1:8000/razorpay/test-transaction
$pid2 = $t.payment_id
Invoke-RestMethod "http://127.0.0.1:8000/decision/analyze/$pid2"
Invoke-RestMethod -Method Post "http://127.0.0.1:8000/decision/execute/$pid2"
$m = Invoke-RestMethod -Method Post "http://127.0.0.1:8000/recovery/mock/pay/$pid2"
Invoke-RestMethod -Method Post http://127.0.0.1:8000/webhooks/razorpay `
  -ContentType "application/json" `
  -Headers @{ "X-Razorpay-Signature" = $m.x_razorpay_signature; "X-Razorpay-Event-Id" = "evt_manual_1" } `
  -Body ($m.webhook_body | ConvertTo-Json -Depth 10 -Compress)
Invoke-RestMethod http://127.0.0.1:8000/dashboard/summary
```

> Note: the signature was computed over the exact body the server returned;
> `ConvertTo-Json -Compress` re-serializes it identically for this payload.
> If you ever see “Invalid Razorpay webhook signature” here, use the UI
> button instead — it posts the byte-exact body.

### 6.5 Run the automated test suite (optional but recommended)

```powershell
python -m pytest tests/ -q
```

**Expected:** `37 passed` (a few deprecation warnings are normal).

==================================================
## 7. OFFLINE ML / EVALUATION PIPELINE
==================================================

- **Script:** `run_offline_pipeline.py` (project root). It internally uses
  `offline/generate_batch.py`, `offline/potential_outcomes.py`,
  `offline/policies.py`, `offline/compute_metrics.py`,
  `offline/dashboard.py`, and the model code in `core/probability/`.
- **Directory:** project root. **Server NOT required** — this is fully
  standalone; it can run while the server is stopped or running.
- **Reads:** only code + the calibration constants in
  `data/calibration/dataset_stats.py`. No network, no credentials.
- **Command:**

```powershell
python run_offline_pipeline.py
```

- **Generates:**
  - `data\output\batch_full.json` — the generated synthetic batch
  - `audit_runs\run_<timestamp>_<id>.jsonl` — append-only audit of every
    decision by both policies (a new file per run; old runs are kept)
  - `metrics\metrics.json` — all research metrics
  - `metrics\dashboard.html` — a static report you can open in a browser
  - `models\recovery_model.pkl` — the trained probability model (also used
    by the live server)

**Expected results (deterministic — you should get these same numbers):**

```
Agent recovery:       79.4%   net 848,380.12 (gross 931,495.19 − discounts 83,115.07)
Baseline recovery:    57.2%   net 661,728.76
Absolute improvement: 22.22 pp
Relative lift:        38.83%
Guardrail blocks:     37     Exceptions: 0
```

and inside `metrics\metrics.json`: Brier score ≈ **0.197**, ROC-AUC ≈
**0.68**, plus a calibration curve.

**What these mean, in plain language:**
- **Agent recovery rate (79.4%)** — of the simulated at-risk records, the
  EV-driven agent recovered 79.4%.
- **Baseline recovery rate (57.2%)** — the *Deterministic Default-Action
  Baseline* (always the default action — a Payment Link where applicable —
  under identical guardrails) recovered 57.2% **on the exact same records
  with the exact same fixed outcomes**, so the comparison is fair.
- **Absolute improvement (+22.22 pp)** — percentage-*point* gap: 79.4 − 57.2.
- **Relative lift (+38.83%)** — the agent recovers ~1.39× as many as the
  baseline (79.4 / 57.2 − 1).
- **Net recovered (₹848,380.12)** — money actually kept: gross recovered
  minus discounts given (a ₹10,000 order recovered with a 10% discount
  counts as ₹9,000).
- **Exceptions: 0** — no record hit the unresolved-cycle exception stop.
- **Brier score (≈0.197, lower is better)** — how far predicted
  probabilities were from actual (simulated) outcomes; 0.25 is the score
  of always guessing 50%, so 0.197 means the model is meaningfully
  informative.
- **ROC-AUC (≈0.68)** — how well the model ranks recoverable cases above
  unrecoverable ones (0.5 = coin flip, 1.0 = perfect).

**Honesty note (stated by the app itself):** all outcomes here are
**simulated** from a documented assumption table
(`docs/recovery_assumptions.md`). These metrics characterize the
controlled simulation environment, not real-world recovery performance.

==================================================
## 8. REAL RAZORPAY TEST MODE — COMPLETE SETUP
==================================================

Facts verified in code before writing this section:
- **Webhook route (exact):** `POST /webhooks/razorpay` (`app/webhooks.py`).
- **Webhook event required:** `payment_link.paid` (the only event the
  handler processes; all others are acknowledged and ignored).
- **Port:** 8000 (you start uvicorn with `--port 8000`).
- **Payment mechanism:** Razorpay **Payment Links**
  (`payment_link.create` / `payment_link.fetch`), created with
  `accept_partial: False`. Order creation is not used as a retry.
- **Localhost is NOT enough for the webhook.** Razorpay's servers must
  reach your machine over public HTTPS, so a tunnel is required. (The
  pull-based fallback `GET /recovery/verify/{payment_id}` works without a
  tunnel — see 8.5.)

### 8.1 Get Test Mode API keys (PASTE INTO DASHBOARD → then .env)

1. Sign in at https://dashboard.razorpay.com .
2. Switch the dashboard to **Test Mode** (mode switch in the dashboard —
   make sure it says Test, not Live).
3. Go to **Settings → API Keys** (in current dashboards this lives under
   *Account & Settings → API Keys / Website and app settings*).
4. Click **Generate Test Key**.
5. Copy **Key Id** (starts with `rzp_test_`) → `.env` `RAZORPAY_KEY_ID`.
6. Copy **Key Secret** (shown **only once** — download it) → `.env`
   `RAZORPAY_KEY_SECRET`.

### 8.2 Start a public HTTPS tunnel

Either tool works on Windows PowerShell; ngrok shown first.

**Option A — ngrok** (account required, free tier fine):
1. Download from https://ngrok.com/download , unzip `ngrok.exe`.
2. One-time auth (token from your ngrok dashboard):

```powershell
.\ngrok.exe config add-authtoken YOUR_NGROK_TOKEN_HERE
```

3. Start the tunnel (in its own PowerShell window; leave it running):

```powershell
.\ngrok.exe http 8000
```

4. Note the printed HTTPS URL, e.g. `https://ab12cd34.ngrok-free.app`.

**Option B — cloudflared** (no account needed):

```powershell
winget install Cloudflare.cloudflared
cloudflared tunnel --url http://127.0.0.1:8000
```

Note the printed `https://….trycloudflare.com` URL.

> Free tunnel URLs change every restart — if you restart the tunnel, update
> the webhook URL in the Razorpay dashboard to match.

### 8.3 Configure the webhook in Razorpay (PASTE INTO DASHBOARD)

1. Dashboard (still **Test Mode**) → **Settings → Webhooks → + Add New
   Webhook** (in current dashboards: *Account & Settings → Webhooks*).
2. **Webhook URL:** your tunnel URL + the exact route:
   `https://YOUR-TUNNEL-URL/webhooks/razorpay`
3. **Secret:** invent a random string yourself (e.g. 32+ characters) and
   enter it here. This is *your* signing secret, not something Razorpay
   gives you.
4. **Active Events:** tick **`payment_link.paid`** (found under the
   Payment Link group). Nothing else is needed.
5. Save.

### 8.4 Final `.env` for real Test Mode (PASTE INTO FILE)

```
MOCK_MODE=false
RAZORPAY_KEY_ID=YOUR_TEST_KEY_ID_HERE
RAZORPAY_KEY_SECRET=YOUR_TEST_KEY_SECRET_HERE
RAZORPAY_WEBHOOK_SECRET=THE_SAME_SECRET_YOU_TYPED_IN_STEP_8.3
GROQ_API_KEY=
```

Then **restart** the server so the new `.env` is read:

```powershell
# In the server window: Ctrl+C, then:
uvicorn app.main:app --port 8000
```

If a credential is missing you get an immediate, explicit `RuntimeError`
telling you which variable to set — that is the built-in safety check.

==================================================
## 9. REAL PAYMENT LINK TEST
==================================================

The flow and clicks are **identical to mock mode** — that is the point:
`MOCK_MODE=false` swaps only the gateway layer.

1. **Create the failed-payment record:** UI → **“+ Create test failed
   payment”**. (This seeder exists precisely so you can demo without a
   storefront; the record is clearly labeled TEST with a `TEST_PROFILE`
   demo customer context. Real deployments would ingest failures from
   `payment.failed` events instead.)
2. **How RevLoop decides:** open the transaction → **Step 1 · Analyze**.
   Same intelligence chain as Section 6 (diagnosis → P(recovery) per
   action → EV = P × amount − cost → deterministic guardrails). The LLM
   plays no part in this choice.
3. **Where the Payment Link comes from:** **Step 2 · Execute** now calls
   the real Razorpay Payment Links API (`payment_link.create`) with your
   test keys, `reference_id = recovery_<payment_id>`, exact amount
   (gross − any approved discount), `accept_partial: False`.
4. **What you see in the dashboard:** the Payment Link row shows a real
   `https://rzp.io/…` short URL (no `MOCK` in the id); state →
   **Awaiting Outcome**. The same link is also visible in the Razorpay
   dashboard under Payment Links (Test Mode).
5. **Open the Payment Link:** click it — Razorpay's hosted test checkout
   page opens (it is branded as test mode; no real money can move).
6. **Pay with Razorpay's test credentials:** Razorpay Test Mode only
   accepts its **documented test instruments** — real cards are refused.
   Use the official list at
   **https://razorpay.com/docs/payments/payments/test-card-details/**
   (test cards + OTP behavior) and the test UPI VPAs documented at
   **https://razorpay.com/docs/payments/payments/test-upi-details/**
   (`success@razorpay` simulates a successful UPI payment). Pick any
   *success* instrument from those official pages; this guide deliberately
   does not restate card numbers so you always use Razorpay's current list.

==================================================
## 10. WEBHOOK VERIFICATION
==================================================

The moment the test payment succeeds, this exact chain runs (all in
`app/webhooks.py`, in this order):

```
Razorpay servers
  → POST https://YOUR-TUNNEL/webhooks/razorpay        (raw JSON body)
  → 1. signature verification      HMAC-SHA256(raw body, RAZORPAY_WEBHOOK_SECRET)
                                   compared constant-time against X-Razorpay-Signature
  → 2. event-ID deduplication      event id inserted into webhook_events (UNIQUE);
                                   a replayed delivery returns duplicate_ignored
  → 3. event type validation       only payment_link.paid proceeds
  → 4. entity status validation    the payment_link entity itself must be status=="paid"
  → 5. reference ID validation     must be recovery_<payment_id> of a known transaction
  → 6. link ID validation          must equal the exact link RevLoop created
  → 7. amount validation           actual amount_paid (paise) must EXACTLY equal
                                   expected net = gross − approved discount
  → 8. state transition            AWAITING_OUTCOME → RECOVERED
                                   net_recovered_amount = the VERIFIED paid amount
  → 9. audit                       append-only 'outcome' row with run_id
```

**How to prove it worked — inspect all three:**

1. **UI:** transaction page → state badge **Recovered**, Net recovered
   shows the verified amount; Dashboard cards update. (If the page was
   already open, click **Verify payment** or refresh.)
2. **Server log** (the uvicorn PowerShell window): a
   `POST /webhooks/razorpay … 200` line at payment time.
3. **Database** (third PowerShell window, project root, venv active):

```powershell
python -c "import sqlite3; c=sqlite3.connect('revloop.db'); [print(r) for r in c.execute('SELECT payment_id, recovery_state, amount, discount_amount, net_recovered_amount FROM transactions')]"
python -c "import sqlite3; c=sqlite3.connect('revloop.db'); [print(r) for r in c.execute('SELECT run_id, event_type, outcome, net_recovered_amount, provenance FROM audit_log ORDER BY id')]"
```

Expected: the transaction row shows `RECOVERED` with the net amount, and
the audit trail shows `decision → execution → outcome/RECOVERED`, all
sharing one `live_YYYYMMDD_HHMMSS_xxxxxx` run id, provenance
`LIVE_TEST_MODE`.

> Razorpay's dashboard also shows delivery attempts and response codes for
> each webhook (Webhooks → your webhook → recent deliveries) — useful if
> nothing arrives.

==================================================
## 11. REAL END-TO-END EXPECTED RESULT
==================================================

Concrete example using the repository's own first seeded record (your
amount may differ — the seeder picks from ₹499 / ₹1,299 / ₹2,499 / ₹5,499;
the structure is exact):

| Field | Before payment | After verified webhook |
|---|---|---|
| `recovery_state` | `AWAITING_OUTCOME` | **`RECOVERED`** |
| `recovery_status` | `initiated` | `recovered` |
| Payment Link | real `https://rzp.io/…` link, unpaid | same link, `paid` |
| `attempt_count` | 1 | 1 |
| `net_recovered_amount` | 0 | **gross − discount**, e.g. amount ₹499.00 with the `discount_offer` action → discount ₹49.90 → **net ₹449.10** (stored as 44910 paise, and equal to the amount you actually paid at checkout) |
| `recovered_at` | empty | timestamp |
| Dashboard "Net recovered" | ₹0 | the same net figure |
| Audit log | decision + execution rows | + an `outcome` row: `RECOVERED`, verified amount, `LIVE_TEST_MODE`, same `run_id` |

If the agent chose `payment_link_recovery` instead of `discount_offer`
for your record, discount is ₹0 and net = gross. Both are correct; the
UI's Net recovered line always shows the arithmetic explicitly.

==================================================
## 12. TROUBLESHOOTING
==================================================

**`python` not found**
- Cause: Python not installed or not on PATH.
- Check: `python --version` then `py --version`.
- Fix: install from python.org with "Add to PATH" ticked; or use `py`
  everywhere. Close and reopen PowerShell after installing.

**`pip install` fails**
- Cause: network hiccup, ancient pip, or 32-bit/very old Python.
- Check: `python -m pip --version`, `python --version`.
- Fix: `python -m pip install --upgrade pip`, re-run the install; ensure
  Python 3.10–3.12 64-bit.

**PowerShell blocks `.venv` activation**
- Cause: execution policy `Restricted`.
- Check: `Get-ExecutionPolicy -List`.
- Fix: `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser`
  then re-run `.\.venv\Scripts\Activate.ps1`.

**`.env` seems ignored**
- Cause: file in the wrong folder, wrong name (`env.txt`, `.env.txt`), or
  server started before you edited it.
- Check: `Get-ChildItem -Force .env` from the project root (must list
  exactly `.env`); `Invoke-RestMethod http://127.0.0.1:8000/health` shows
  which mode is live.
- Fix: keep `.env` next to `requirements.txt`; **restart uvicorn** after
  every `.env` change (it is read once at startup). In Notepad use
  Save As → File name `".env"` (with quotes) → All Files.

**Server refuses to start: `RuntimeError: MOCK_MODE=false but …`**
- Cause: intentional guard — real mode without credentials.
- Fix: fill `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`,
  `RAZORPAY_WEBHOOK_SECRET` in `.env`, or set `MOCK_MODE=true`.

**Invalid Razorpay credentials (link creation fails with a 401 from Razorpay)**
- Cause: wrong key/secret, or Live keys used instead of Test keys.
- Check: key id should start with `rzp_test_`; UI flash shows the gateway
  error; server log shows the failing call.
- Fix: regenerate Test keys in the dashboard, update `.env`, restart.

**Port 8000 already in use** (`error while attempting to bind on address`)
- Check: `Get-NetTCPConnection -LocalPort 8000 | Select-Object OwningProcess`
  then `Get-Process -Id <that id>`.
- Fix: `Stop-Process -Id <that id>` (if it is a stale uvicorn), or start on
  another port `uvicorn app.main:app --port 8080` **and** tunnel that port
  instead (`ngrok http 8080`).

**Webhook never arrives (state stuck at AWAITING_OUTCOME after paying)**
- Causes: no tunnel; tunnel URL changed after a restart; wrong URL path in
  the dashboard; wrong event unticked.
- Check: the tunnel window shows each incoming request; Razorpay dashboard
  → Webhooks → recent deliveries shows attempts + response codes; the
  uvicorn window should log `POST /webhooks/razorpay`.
- Fix: webhook URL must be `https://<current-tunnel-host>/webhooks/razorpay`
  with event `payment_link.paid`; update it after any tunnel restart.
- **Tunnel-free fallback:** click **Verify payment** on the transaction
  page (or `Invoke-RestMethod http://127.0.0.1:8000/recovery/verify/<payment_id>`).
  It fetches the link directly from Razorpay and applies the identical
  verified transition, including the amount check.

**`Invalid Razorpay webhook signature` (HTTP 400)**
- Cause: the secret in `.env` differs from the secret typed into the
  Razorpay webhook form (typo/whitespace), or the server was not restarted
  after editing `.env`.
- Fix: make both strings byte-identical, restart uvicorn, redeliver or pay
  again.

**`duplicate_ignored` response**
- Not an error: event-ID deduplication working. The first delivery already
  processed the event; state is already correct.

**`amount_mismatch` response, no state change**
- Cause: the paid amount ≠ expected net (the design treats this as manual
  review, e.g. a partial/stale payload).
- Check: the audit log row spells out `expected_net=… actual_paid=…`.
- Action: this is the safety behavior, not a bug. For a normal full test
  payment it will not occur (links are `accept_partial: False`).

**`payment_link entity status is 'created', not 'paid'`**
- Cause: a non-paid entity arrived on a paid event (stale payload).
- Action: also by-design protection; pay the link and the real event will
  transition it.

**Payment Link not created on Execute**
- In mock mode: should never happen — check the flash message; if it says
  `blocked_temporarily` or `stopped`, that is a **guardrail** doing its job
  (24h spacing, max attempts, opt-out…), shown with the exact reason.
- In real mode: also check Razorpay credential errors in the server log.

**Login screen? Authentication failure?**
- There is no login unless you set `REVLOOP_AUTH_ENABLED=true`. If you did:
  an admin exists only if `REVLOOP_ADMIN_PASSWORD` was set **before**
  startup; log in via `POST /auth/login`. For testing, simplest is
  `REVLOOP_AUTH_ENABLED=false`.

**Groq errors / quota exceeded**
- Effect: none on decisions or recovery. Message drafting silently falls
  back to built-in compliant templates (the response even tells you the
  `fallback_reason`). Leave `GROQ_API_KEY` empty if in doubt.

**MOCK_MODE behaving unexpectedly**
- Remember it parses `1/true/yes/on` (case-insensitive) as true — anything
  else, including `False`, `0`, or a typo like `ture`, is **false** and
  will demand credentials. Check `/health` → `mock_mode` to see what the
  server actually loaded, and restart after changing `.env`.

==================================================
## 13. HOW TO STOP EVERYTHING
==================================================

```powershell
# 13.1 Stop FastAPI: focus the uvicorn window and press
#      Ctrl + C
#      (if it lingers: Get-Process -Name python | Stop-Process  — only if no other Python is running)

# 13.2 Stop the tunnel: focus the ngrok/cloudflared window and press
#      Ctrl + C

# 13.3 Deactivate the virtual environment (in any window where (.venv) shows)
deactivate

# 13.4 Clean restart later:
cd $HOME\revloop-project\revloop
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --port 8000
# (the SQLite database revloop.db persists between restarts; delete the file
#  only if you deliberately want a fresh empty demo)
```

==================================================
## 14. FINAL TEST CHECKLIST
==================================================

```
[ ] Prerequisites: python --version ≥ 3.10, pip works
[ ] Project folder: extracted, inside the folder containing requirements.txt
[ ] .venv created and activated ((.venv) in prompt)
[ ] pip install -r requirements.txt succeeded
[ ] .env created from .env.example (MOCK_MODE=true)
[ ] MOCK MODE: server starts, /ui/ loads, full seeded→Analyze→Execute→
    mock pay→RECOVERED loop done, pytest shows 37 passed
[ ] Offline pipeline run: 79.4% vs 57.2%, +22.22 pp, 0 exceptions
[ ] Razorpay Test Mode keys generated and in .env
[ ] Webhook created in dashboard (URL + your secret + payment_link.paid)
[ ] HTTPS tunnel running, URL matches the webhook config
[ ] MOCK_MODE=false, server restarted cleanly
[ ] Real Payment Link created via Step 2 · Execute
[ ] Real Test Mode payment made with Razorpay's documented test instrument
[ ] Webhook received (tunnel window + uvicorn log + Razorpay deliveries)
[ ] Payment verified (signature ✓ dedup ✓ status ✓ reference ✓ link ✓ amount ✓)
[ ] State AWAITING_OUTCOME → RECOVERED, net amount correct in UI + DB + audit
[ ] Final screenshots/video captured (dashboard, transaction page, audit query)
```

==================================================
## 15. EXACT COMMAND BLOCK
==================================================

Chronological, copy-pasteable. Lines starting with `#` are comments.

```powershell
# ---- one-time setup ----
cd $HOME\Downloads
Expand-Archive -Path .\revloop-final-submission.zip -DestinationPath $HOME\revloop-project -Force
cd $HOME\revloop-project\revloop
python -m venv .venv
.\.venv\Scripts\Activate.ps1          # if blocked: Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
python -m pip install -r requirements.txt
Copy-Item .env.example .env

# ---- configuration check ----
Get-ChildItem -Force .env
Get-Content .env                       # confirm MOCK_MODE=true for the first run

# ---- offline evaluation (no server needed) ----
python run_offline_pipeline.py

# ---- automated tests ----
python -m pytest tests/ -q             # expect: 37 passed

# ---- start the application (leave running; open a 2nd window for the rest) ----
uvicorn app.main:app --port 8000

# ---- in the SECOND window: mock end-to-end via API (or just use the UI) ----
cd $HOME\revloop-project\revloop
.\.venv\Scripts\Activate.ps1
Invoke-RestMethod http://127.0.0.1:8000/health
$t = Invoke-RestMethod -Method Post http://127.0.0.1:8000/razorpay/test-transaction
Invoke-RestMethod "http://127.0.0.1:8000/decision/analyze/$($t.payment_id)"
Invoke-RestMethod -Method Post "http://127.0.0.1:8000/decision/execute/$($t.payment_id)"
$m = Invoke-RestMethod -Method Post "http://127.0.0.1:8000/recovery/mock/pay/$($t.payment_id)"
Invoke-RestMethod -Method Post http://127.0.0.1:8000/webhooks/razorpay -ContentType "application/json" -Headers @{ "X-Razorpay-Signature" = $m.x_razorpay_signature; "X-Razorpay-Event-Id" = "evt_manual_1" } -Body ($m.webhook_body | ConvertTo-Json -Depth 10 -Compress)
Invoke-RestMethod http://127.0.0.1:8000/dashboard/summary

# ---- real Test Mode (after editing .env per the paste-section below and
#      configuring the Razorpay webhook): restart server, then tunnel ----
#   window 1: Ctrl+C, then: uvicorn app.main:app --port 8000
#   window 3: .\ngrok.exe http 8000        (or: cloudflared tunnel --url http://127.0.0.1:8000)
#   browser:  http://127.0.0.1:8000/ui/  → seed → Analyze → Execute → pay the real link

# ---- stopping ----
#   uvicorn window: Ctrl+C     tunnel window: Ctrl+C
deactivate
```

### Values you paste into `.env` (NOT PowerShell commands)

Mock mode (first run):
```
MOCK_MODE=true
```

Real Razorpay Test Mode (later):
```
MOCK_MODE=false
RAZORPAY_KEY_ID=YOUR_TEST_KEY_ID_HERE
RAZORPAY_KEY_SECRET=YOUR_TEST_KEY_SECRET_HERE
RAZORPAY_WEBHOOK_SECRET=YOUR_OWN_INVENTED_SECRET_HERE
GROQ_API_KEY=OPTIONAL_LEAVE_EMPTY_IF_NONE
```

==================================================
## 16. FILE-BY-FILE EXPLANATION
==================================================

| File / Folder | Purpose | Run manually? | When used |
|---|---|---|---|
| `app/main.py` | **Application entrypoint** — FastAPI app, routers, CORS, auth middleware, serves `frontend/` at `/ui` | Yes, via `uvicorn app.main:app --port 8000` | live server |
| `app/config.py` | Reads `.env`; MOCK_MODE switch; refuses to start real mode without credentials | No (imported) | server startup |
| `app/database.py` | SQLite schema + connection (`revloop.db`); creates tables on startup | No (imported) | server startup & every request |
| `app/decision_api.py` | `GET /decision/analyze/{id}`, `POST /decision/execute/{id}` — bridges live transactions into the core engine, persists decisions, drives state | No (imported) | live server |
| `app/razorpay_gateway.py` | **Razorpay gateway** — real `payment_link.create/fetch` (`accept_partial: False`) or mock links; webhook HMAC helpers | No (imported) | Execute / verify / webhook |
| `app/webhooks.py` | **Webhook handler** `POST /webhooks/razorpay`: signature → dedup → event → status → reference → link-id → amount → RECOVERED | No (imported) | payment time |
| `app/recovery_verification.py` | `GET /recovery/verify/{id}` pull-based verification; `POST /recovery/mock/pay/{id}` mock-mode payment simulator | No (imported) | verification & mock demo |
| `app/recoveries.py` | Recoveries list, `POST /recoveries/{id}/opt-out`, manual status PATCH (never RECOVERED) | No (imported) | live server |
| `app/transactions_api.py` | `POST /razorpay/test-transaction` seeder (TEST_PROFILE demo customers), transactions listing | No (imported) | demo seeding |
| `app/dashboard.py` | `GET /dashboard/summary` live product metrics (net accounting) | No (imported) | live server |
| `app/auth.py` | **Authentication** (JWT, off by default; no default secrets/passwords) | No (imported) | only if `REVLOOP_AUTH_ENABLED=true` |
| `app/audit_db.py` | Append-only audit inserts; per-session `live_…` run id | No (imported) | every decision/execution/outcome |
| `app/groq_client.py` | Optional LLM message drafting with template fallback (never decides) | No (imported) | Execute, message actions |
| `app/model_provider.py` / `app/state_service.py` | Model load/train-on-first-use; state-machine-safe DB transitions | No (imported) | live server |
| `core/decision/decision_engine.py` | **THE single decision authority** — EV argmax under guardrails | No (imported by both live & offline) | every decision |
| `core/probability/model.py` (+`build_training_data.py`) | **P(recovery \| context, action)** logistic model, Brier/AUC/calibration | No (imported) | decisions & pipeline |
| `core/guardrails/validator.py` | Deterministic guardrails G1–G7, pre + post checks | No (imported) | every decision |
| `core/diagnosis/` | Gateway-code rules + classifier fallback, with confidence | No (imported) | every decision |
| `core/state_machine.py`, `core/clock.py`, `core/audit/logger.py` | Legal-transition enforcement; real/simulated clock; offline JSONL audit | No (imported) | everywhere |
| `run_offline_pipeline.py` | **Offline evaluation entrypoint** (also trains the live model) | Yes: `python run_offline_pipeline.py` | offline evaluation only |
| `offline/` | Batch generator (DERIVED), fixed potential outcomes (SYNTHETIC), agent + baseline policies, metrics, static dashboard | No (imported by the pipeline) | offline evaluation only |
| `data/calibration/dataset_stats.py` | Documented public-dataset-derived parameters for the generator | No (imported) | offline evaluation only |
| `tests/` (`test_core.py`, `test_live_api.py`, `test_audit_pass.py`) + `conftest.py` | **37 automated tests** | Yes: `python -m pytest tests/ -q` | testing only |
| `frontend/` | Merchant UI (dashboard, recoveries, transaction intelligence page) | No — served automatically at `/ui/` | live server |
| `docs/` | Guardrails, provenance (REAL/DERIVED/SYNTHETIC/MOCK/TEST MODE), recovery assumptions, compliance policy (grounds the LLM) | No (read them!) | reference |
| `requirements.txt` | Dependency list | Used by pip once | setup |
| `.env.example` → `.env` | Configuration template → your local secrets | You edit `.env` | startup |
| `metrics/`, `audit_runs/`, `models/`, `data/output/` | Pipeline outputs (metrics.json, dashboard.html, audit JSONL, model .pkl, batch) | No — generated | after pipeline runs |

Categorized: **started directly** = `uvicorn app.main:app`,
`run_offline_pipeline.py`, `pytest tests/`. **Imported automatically** =
everything in `app/` and `core/`. **Offline-only** = `offline/`,
`data/calibration/`, `run_offline_pipeline.py`. **Tests-only** = `tests/`,
`conftest.py`.

==================================================
## 17. VERIFICATION REPORT (nothing was modified)
==================================================

No files were changed, no ZIP regenerated, no dependencies touched —
documentation only.

- **Files inspected for this guide:** `app/main.py`, `app/config.py`,
  `app/database.py`, `app/decision_api.py`, `app/transactions_api.py`,
  `app/webhooks.py`, `app/recovery_verification.py`, `app/recoveries.py`,
  `app/dashboard.py`, `app/auth.py`, `app/audit_db.py`,
  `app/razorpay_gateway.py`, `app/groq_client.py`,
  `core/decision/decision_engine.py`, `core/guardrails/validator.py`,
  `offline/compute_metrics.py`, `run_offline_pipeline.py`,
  `requirements.txt`, `.env.example`, `.gitignore`, `frontend/*`
  (`index.html`, `transaction.html`, `transaction.js`, `common.js`,
  `app.js`, `recoveries.html`), `tests/*`, `README.md`, `docs/*`.
- **Exact startup command:** `uvicorn app.main:app --port 8000`
  (from the project root, venv active).
- **Exact server port:** `8000`.
- **Exact webhook route:** `POST /webhooks/razorpay`
  (event: `payment_link.paid`).
- **Exact `.env` for MOCK_MODE:** `MOCK_MODE=true` (nothing else needed;
  all other variables may stay empty/absent).
- **Exact `.env` for real TEST MODE:** `MOCK_MODE=false`,
  `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, `RAZORPAY_WEBHOOK_SECRET`
  (all three mandatory — startup fails loudly otherwise);
  `GROQ_API_KEY` optional.
- **Exact offline pipeline command:** `python run_offline_pipeline.py`.
- **Exact test command:** `python -m pytest tests/ -q` → **37 passed**.
- **Exact expected end-to-end success:** seeded failed payment → Analyze
  (diagnosis + confidence, per-action P/cost/EV, guardrail ✓s) → Execute
  (Payment Link, state `AWAITING_OUTCOME`, attempts 1/3, net still ₹0) →
  customer pays → webhook passes signature/dedup/event/status/reference/
  link-id/amount checks → state **`RECOVERED`**, `net_recovered_amount` =
  verified paid amount = gross − discount (e.g. gross ₹499.00, discount
  ₹49.90, **net ₹449.10**), dashboard net metrics update, and one
  append-only audit trail (`decision → execution → outcome`) under a
  single `live_…` run id.
