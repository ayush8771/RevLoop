async function loadSummary() {
  const s = await api("/dashboard/summary");
  document.getElementById("m-at-risk").textContent = inr(s.revenue_at_risk);
  document.getElementById("m-net").textContent = inr(s.net_recovered);
  document.getElementById("m-disc").textContent = inr(s.discounts_given);
  document.getElementById("m-rate").textContent = s.net_recovery_rate_pct + "%";
}

async function loadMode() {
  const h = await api("/health");
  document.getElementById("mode-note").textContent =
    h.mock_mode ? "MOCK MODE — no Razorpay credentials, mock Payment Links"
                : "Razorpay TEST MODE";
}

async function loadTransactions() {
  const d = await api("/razorpay/dashboard/transactions");
  const tbody = document.querySelector("#txn-table tbody");
  if (!d.transactions.length) {
    tbody.innerHTML = `<tr><td colspan="8" class="loading">No transactions yet — create a test failed payment.</td></tr>`;
    return;
  }
  tbody.innerHTML = d.transactions.map(t => `
    <tr>
      <td class="mono">${t.payment_id}</td>
      <td>${inr(t.amount, t.currency)}</td>
      <td>${t.error_code || "—"}</td>
      <td>${fmt(t.diagnosis)}</td>
      <td>${fmt(t.chosen_action)}</td>
      <td>${stateBadge(t.recovery_state)}</td>
      <td>${t.net_recovered_amount ? inr(t.net_recovered_amount) : "—"}</td>
      <td><a href="transaction.html?payment_id=${encodeURIComponent(t.payment_id)}">Open →</a></td>
    </tr>`).join("");
}

document.getElementById("seed-btn").addEventListener("click", async () => {
  await api("/razorpay/test-transaction", { method: "POST" });
  await Promise.all([loadSummary(), loadTransactions()]);
});

loadMode(); loadSummary(); loadTransactions();
