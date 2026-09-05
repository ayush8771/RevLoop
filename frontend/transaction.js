const paymentId = new URLSearchParams(window.location.search).get("payment_id");
let mockMode = false;

function flash(msg, isError = false) {
  const el = document.getElementById("flash");
  el.textContent = msg;
  el.style.color = isError ? "#ff7b72" : "#7ce38b";
}

function renderDecision(d) {
  if (d.customer_context) {
    const c = d.customer_context;
    document.getElementById("ai-context").textContent =
      `${c.prior_success_count} prior successes · ${c.customer_tenure_days}d tenure · ` +
      `${c.recent_failure_count} recent failures [${c.provenance}]`;
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
         ${c.passed ? "✓" : "✗"} ${c.rule} — ${c.detail}</li>`).join("");
  }
}

function renderTxn(t) {
  document.getElementById("txn-title").textContent = t.payment_id;
  document.getElementById("txn-state").innerHTML = stateBadge(t.recovery_state);
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
    if (d.message) document.getElementById("message-box").textContent =
      d.message.text + `\n\n[generator: ${d.message.generator} · grounded on: ${d.message.grounded_on}]`;
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
  const h = await api("/health");
  mockMode = h.mock_mode;
  if (mockMode) document.getElementById("mock-pay-btn").style.display = "";
  await refresh();
})();
