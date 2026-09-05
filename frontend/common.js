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

function stateBadge(state) {
  const cls = state === "RECOVERED" ? "recovered"
    : state === "AWAITING_OUTCOME" ? "awaiting"
    : state === "STOPPED" ? "stopped" : "";
  return `<span class="badge ${cls}">${fmt(state || "AT_RISK")}</span>`;
}

async function api(path, opts = {}) {
  const res = await fetch(API_BASE + path, {
    headers: { "Content-Type": "application/json" }, ...opts,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || res.statusText);
  return data;
}
