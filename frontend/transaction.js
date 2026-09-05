const paymentId = new URLSearchParams(window.location.search).get("payment_id");
let mockMode = false;

// Maps each real lifecycle state to how far the fixed pipeline has
// progressed, so the flow legend doubles as a live progress
// indicator rather than static decoration.
const STATE_STEP = {
  AT_RISK: 0,
  DIAGNOSED: 2,
  DECISION_READY: 3,
  GUARDRAIL_APPROVED: 4,
  ACTION_INITIATED: 5,
  AWAITING_OUTCOME: 5,
  RECOVERED: 6,
  FAILED: 6,
  RE_EVALUATE: 2,
  STOPPED: 4,
};

function updateFlowLegend(state) {
  const reached = STATE_STEP[state] ?? 0;
  document.querySelectorAll("#flow-legend .step").forEach(el => {
    const n = Number(el.dataset.step);
    el.classList.toggle("done", n < reached);
    el.classList.toggle("current", n === reached);
  });
}

function flash(msg, isError = false) {
  const el = document.getElementById("flash");
  el.textContent = msg;
  el.style.color = isError ? "var(--danger)" : "var(--success)";
}

async function loadMode() {
  try {
    const h = await api("/health");
    mockMode = h.mock_mode;
    document.getElementById("mode-note").innerHTML = modeBannerHtml(h.mock_mode);
    if (mockMode) document.getElementById("mock-pay-btn").style.display = "";
  } catch (e) {
    document.getElementById("mode-note").textContent = "Status unavailable";
  }
}

// The backend only attaches `message` to the execute response when the
// selected action actually is a message/call action (see groq_client.py).
// This just makes that existing signal explicit in the UI instead of
// leaving the placeholder text unchanged when it doesn't apply.
function renderMessage(message) {
  const box = document.getElementById("message-box");
  if (message) {
    box.textContent = message.text +
      `\n\n[generator: ${message.generator} · grounded on: ${message.grounded_on}]`;
    box.classList.add("has-message");
  } else {
    box.textContent = "Not applicable for this recovery action.\n\n" +
      "Customer communication is generated only when RevLoop selects a message or call action.";
    box.classList.remove("has-message");
  }
}

function renderDecision(d) {
  if (d.customer_context) {
    const c = d.customer_context;
    document.getElementById("ai-context").innerHTML =
      `${c.prior_success_count} prior successes · ${c.customer_tenure_days}d tenure · ` +
      `${c.recent_failure_count} recent failures` + provenanceTag(c.provenance);
  }
  document.getElementById("ai-diagnosis").textContent = fmt(d.diagnosis);
  document.getElementById("ai-confidence").textContent =
    d.diagnosis_confidence != null ? (d.diagnosis_confidence * 100).toFixed(0) + "%" : "—";
  document.getElementById("ai-method").textContent = fmt(d.diagnosis_method);
  document.getElementById("ai-action").textContent = fmt(d.chosen_action);
  document.getElementById("ai-discount").textContent =
    d.discount_amount_paise ? inr(d.discount_amount_paise) : "None";
  document.getElementById("ai-reasoning").textContent = d.reasoning || "—";

  const tbody = document.querySelector("#ev-table tbody");
  if (d.scored_candidates && d.scored_candidates.length) {
    tbody.innerHTML = d.scored_candidates
      .slice().sort((a, b) => b.ev - a.ev)
      .map(s => `<tr class="${s.action === d.chosen_action ? "chosen" : ""}">
        <td>${fmt(s.action)}</td><td>${(s.probability * 100).toFixed(1)}%</td>
        <td>₹${s.cost.toLocaleString("en-IN")}</td><td>₹${s.ev.toLocaleString("en-IN")}</td></tr>`)
      .join("");
  } else {
    tbody.innerHTML = `<tr><td colspan="4" class="loading">No feasible candidates (guardrail stop: ${fmt(d.guardrail_reason)}).</td></tr>`;
  }

  const gl = document.getElementById("guardrails");
  if (d.guardrail_checks && d.guardrail_checks.length) {
    gl.innerHTML = d.guardrail_checks.map(c =>
      `<li class="${c.passed ? "guardrail-pass" : "guardrail-fail"}">
         <span>${c.passed ? "✓" : "✗"}</span>
         <span><span class="g-rule">${c.rule}</span> <span class="g-detail">— ${c.detail}</span></span></li>`).join("");
  }
}

function renderTxn(t) {
  document.getElementById("txn-title").textContent = t.payment_id;
  document.getElementById("txn-state").innerHTML = stateBadge(t.recovery_state);
  updateFlowLegend(t.recovery_state);
  document.getElementById("txn-amount").textContent = inr(t.amount, t.currency);
  document.getElementById("txn-error").textContent =
    (t.error_code || "—") + (t.error_description ? " · " + t.error_description : "");
  document.getElementById("txn-attempts").textContent = (t.attempt_count || 0) + " / 3";
  document.getElementById("txn-recovery-status").textContent = fmt(t.recovery_status);
  document.getElementById("txn-net").textContent =
    t.net_recovered_amount ? `${inr(t.net_recovered_amount)} (gross ${inr(t.amount)} − discount ${inr(t.discount_amount)})` : "—";
  const linkEl = document.getElementById("txn-link");
  linkEl.innerHTML = t.recovery_link
    ? `<a href="${t.recovery_link}" target="_blank" class="mono">${t.recovery_link}</a>` : "—";
}

async function refresh() {
  const all = await api("/razorpay/dashboard/transactions");
  const t = all.transactions.find(x => x.payment_id === paymentId);
  if (t) renderTxn(t);
}

async function analyze() {
  try {
    const d = await api(`/decision/analyze/${paymentId}`);
    renderDecision(d);
    document.getElementById("txn-next-allowed").textContent = d.next_allowed_at || "now";
    await refresh();
    flash("Decision computed (no customer contact yet).");
  } catch (e) { flash(e.message, true); }
}

async function execute() {
  try {
    const d = await api(`/decision/execute/${paymentId}`, { method: "POST" });
    renderDecision(d);
    document.getElementById("txn-next-allowed").textContent = d.next_allowed_at || "now";
    if (d.status === "action_initiated") renderMessage(d.message);
    await refresh();
    flash(d.status === "action_initiated"
      ? `Action executed: ${fmt(d.chosen_action)}${d.payment_link ? " → " + d.payment_link : ""}`
      : `Not executed: ${d.status} (${fmt(d.guardrail_reason)})`, d.status !== "action_initiated");
  } catch (e) { flash(e.message, true); }
}

async function verify() {
  try {
    const v = await api(`/recovery/verify/${paymentId}`);
    await refresh();
    flash(`Link status: ${v.link_status || v.status}` +
      (v.net_recovered_amount ? ` — net recovered ${inr(v.net_recovered_amount)}` : ""));
  } catch (e) { flash(e.message, true); }
}

async function mockPay() {
  try {
    const m = await api(`/recovery/mock/pay/${paymentId}`, { method: "POST" });
    // Drive the REAL webhook path with the signed payload.
    const res = await fetch(API_BASE + "/webhooks/razorpay", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Razorpay-Signature": m.x_razorpay_signature,
        "X-Razorpay-Event-Id": "evt_mock_" + Date.now(),
      },
      body: JSON.stringify(m.webhook_body),
    });
    const w = await res.json();
    await refresh();
    flash(w.status === "success"
      ? `Webhook verified → RECOVERED. Net ${inr(w.net_recovered_amount)}`
      : `Webhook: ${w.status} ${w.reason || ""}`, w.status !== "success");
  } catch (e) { flash(e.message, true); }
}

async function optOut() {
  try {
    await api(`/recoveries/${paymentId}/opt-out`, { method: "POST" });
    flash("Customer opted out — all future contact permanently blocked (guardrail G3).");
  } catch (e) { flash(e.message, true); }
}

document.getElementById("analyze-btn").addEventListener("click", analyze);
document.getElementById("execute-btn").addEventListener("click", execute);
document.getElementById("verify-btn").addEventListener("click", verify);
document.getElementById("mock-pay-btn").addEventListener("click", mockPay);
document.getElementById("optout-btn").addEventListener("click", optOut);

(async () => {
  await loadMode();
  await refresh();
})();
