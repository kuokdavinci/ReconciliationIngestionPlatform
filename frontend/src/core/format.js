export function percent(value, total) {
  if (!total) return 0;
  return Math.round((value / total) * 1000) / 10;
}

export function formatNumber(value) {
  return Number(value || 0).toLocaleString("en-US");
}

export function formatAmount(value) {
  if (value === null || value === undefined || value === "") return "-";
  if (typeof value === "string" && Number.isNaN(Number(value))) return value;
  return formatNumber(value) + " VND";
}

export function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, ch => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#039;"
  }[ch]));
}

export function boldNumbers(text) {
  if (!text) return "";
  return text.replace(/\b(\d+(?:\.\d+)?%|\b\d+(?:,\d{3})*(?:\.\d+)?(?:[MKmk])?\s*VND|\b\d+(?:,\d{3})*(?:\.\d+)?(?:[MKmk])?)\b/gi, "<strong>$1</strong>");
}
