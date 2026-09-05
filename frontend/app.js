async function loadSummary() {
  try {
    const s = await api("/dashboard/summary");
    document.getElementById("m-at-risk").textContent = inr(s.revenue_at_risk);
    document.getElementById("m-net").textContent = inr(s.net_recovered);
    document.getElementById("m-disc").textContent = inr(s.discounts_given);
    document.getElementById("m-rate").textContent = s.net_recovery_rate_pct + "%";
  } catch (e) {
    ["m-at-risk", "m-net", "m-disc", "m-rate"].forEach(id => {
      document.getElementById(id).textContent = "—";
    });
    console.error("Failed to load dashboard summary:", e.message);
  }
}

async function loadMode() {
  try {
    const h = await api("/health");
    document.getElementById("mode-note").innerHTML = modeBannerHtml(h.mock_mode);
  } catch (e) {
    document.getElementById("mode-note").textContent = "Status unavailable";
  }
}

// Turns the raw transaction list into a scannable "N total · N
// recovered · N awaiting · ..." strip, reusing the same fetch that
// already populates the table — no extra API calls.
function renderStateCounts(transactions) {
  const el = document.getElementById("state-counts");
  if (!transactions.length) { el.innerHTML = ""; return; }
  const counts = {};
  transactions.forEach(t => {
    const k = t.recovery_state || "AT_RISK";
    counts[k] = (counts[k] || 0) + 1;
  });
  const order = ["RECOVERED", "AWAITING_OUTCOME", "ACTION_INITIATED", "GUARDRAIL_APPROVED",
    "DECISION_READY", "DIAGNOSED", "AT_RISK", "RE_EVALUATE", "FAILED", "STOPPED"];
  const parts = [`<span class="count-item"><b>${transactions.length}</b> total</span>`];
  order.filter(k => counts[k]).forEach(k => {
    parts.push(`<span class="count-item"><b>${counts[k]}</b> ${fmt(k).toLowerCase()}</span>`);
  });
  el.innerHTML = parts.join("");
}

async function loadTransactions() {
  const tbody = document.querySelector("#txn-table tbody");
  try {
    const d = await api("/razorpay/dashboard/transactions");
    if (!d.transactions.length) {
      tbody.innerHTML = `<tr><td colspan="8" class="loading">No transactions yet — create a test failed payment.</td></tr>`;
      renderStateCounts([]);
      return;
    }
    tbody.innerHTML = d.transactions.map(t => txnRow(t, false)).join("");
    renderStateCounts(d.transactions);
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="8" class="loading">Couldn't load transactions — ${e.message}</td></tr>`;
    document.getElementById("state-counts").innerHTML = "";
  }
}

document.getElementById("seed-btn").addEventListener("click", async () => {
  await api("/razorpay/test-transaction", { method: "POST" });
  await Promise.all([loadSummary(), loadTransactions()]);
});

loadMode(); loadSummary(); loadTransactions();
