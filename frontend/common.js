// Shared helpers. API served from the same origin (frontend is mounted
// at /ui by FastAPI), so relative URLs work with uvicorn on any port.
const API_BASE = window.location.origin;

function inr(paise, currency = "INR") {
  return new Intl.NumberFormat("en-IN", {
    style: "currency", currency, maximumFractionDigits: 0,
  }).format((paise || 0) / 100);
}

function fmt(s) {
  if (!s) return "—";
  return String(s).replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
}

// Maps every real lifecycle state (core/state_machine.py STATES) to a
// distinct badge treatment. Previously only 3 of 10 states had styling;
// the rest fell through to an unstyled default and were visually
// indistinguishable from each other and from AT_RISK.
const STATE_BADGE_CLASS = {
  AT_RISK: "at-risk",
  DIAGNOSED: "diagnosed",
  DECISION_READY: "decision-ready",
  GUARDRAIL_APPROVED: "approved",
  ACTION_INITIATED: "action-initiated",
  AWAITING_OUTCOME: "awaiting",
  RECOVERED: "recovered",
  FAILED: "failed",
  RE_EVALUATE: "re-evaluate",
  STOPPED: "stopped",
};

function stateBadge(state) {
  const key = state || "AT_RISK";
  const cls = STATE_BADGE_CLASS[key] || "at-risk";
  return `<span class="badge ${cls}">${fmt(key)}</span>`;
}

// Provenance gets an intentional visual tag rather than being buried
// as plain text. `raw` looks like "TEST_PROFILE:at_risk" or
// "DEFAULT_FALLBACK" as returned by the decision API.
function provenanceTag(raw) {
  if (!raw) return "";
  const isTest = raw.startsWith("TEST_PROFILE");
  const isDefault = raw === "DEFAULT_FALLBACK";
  const cls = isTest ? "test" : isDefault ? "default" : "";
  const label = isTest ? raw.split(":")[1] || "test" : fmt(raw);
  return `<span class="provenance-tag ${cls}">${label}</span>`;
}

// Shared row template — used by both the dashboard table (app.js) and
// the recoveries table, so a formatting fix only needs one edit.
// `withLink` includes the diagnosis/gross/discount/link columns used
// on the Recoveries page; the dashboard table omits them.
function txnRow(t, withLink) {
  const openCell = `<td><a class="view-link" href="transaction.html?payment_id=${encodeURIComponent(t.payment_id)}">View recovery →</a></td>`;
  if (!withLink) {
    return `<tr>
      <td class="mono">${t.payment_id}</td>
      <td>${inr(t.amount, t.currency)}</td>
      <td>${t.error_code || "—"}</td>
      <td>${fmt(t.diagnosis)}</td>
      <td>${fmt(t.chosen_action)}</td>
      <td>${stateBadge(t.recovery_state)}</td>
      <td>${t.net_recovered_amount ? inr(t.net_recovered_amount) : "—"}</td>
      ${openCell}
    </tr>`;
  }
  return `<tr>
    <td class="mono">${t.payment_id}</td>
    <td>${fmt(t.diagnosis)}</td>
    <td>${fmt(t.chosen_action)}</td>
    <td>${stateBadge(t.recovery_state)}</td>
    <td>${inr(t.amount, t.currency)}</td>
    <td>${t.discount_amount ? inr(t.discount_amount) : "—"}</td>
    <td>${t.net_recovered_amount ? inr(t.net_recovered_amount) : "—"}</td>
    <td>${t.recovery_link ? `<a href="${t.recovery_link}" target="_blank">link</a>` : "—"}</td>
    ${openCell}
  </tr>`;
}

// Consistent mode banner, usable on every page (previously index.html
// only) so a direct deep link to transaction/recoveries never hides
// whether Payment Links are real or mocked.
function modeBannerHtml(mockMode) {
  const label = mockMode
    ? "MOCK MODE — no Razorpay credentials, mock Payment Links"
    : "Razorpay TEST MODE";
  return `<span class="mode-banner"><span class="dot"></span>${label}</span>`;
}

async function api(path, opts = {}) {
  const res = await fetch(API_BASE + path, {
    headers: { "Content-Type": "application/json" }, ...opts,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || res.statusText);
  return data;
}
