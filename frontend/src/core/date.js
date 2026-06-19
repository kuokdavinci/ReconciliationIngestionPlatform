export function parseIsoDate(value) {
  const [year, month, day] = String(value || "").split("-").map(Number);
  if (!year || !month || !day) return null;
  const utcDate = new Date(Date.UTC(year, month - 1, day));
  return Number.isNaN(utcDate.getTime()) ? null : utcDate;
}

export function formatIsoDate(date) {
  const year = date.getUTCFullYear();
  const month = String(date.getUTCMonth() + 1).padStart(2, "0");
  const day = String(date.getUTCDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

export function formatDisplayDate(value) {
  const parsed = parseIsoDate(value);
  if (!parsed) return String(value || "-");
  const day = String(parsed.getUTCDate()).padStart(2, "0");
  const month = String(parsed.getUTCMonth() + 1).padStart(2, "0");
  const year = parsed.getUTCFullYear();
  return `${day}/${month}/${year}`;
}

export function formatDisplayDateTime(value) {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value || "-";
  const day = String(parsed.getDate()).padStart(2, "0");
  const month = String(parsed.getMonth() + 1).padStart(2, "0");
  const year = parsed.getFullYear();
  const hours = String(parsed.getHours()).padStart(2, "0");
  const minutes = String(parsed.getMinutes()).padStart(2, "0");
  const seconds = String(parsed.getSeconds()).padStart(2, "0");
  return `${day}/${month}/${year} ${hours}:${minutes}:${seconds}`;
}

export function shiftIsoDate(value, offsetDays) {
  const base = parseIsoDate(value) || new Date();
  const shifted = new Date(base.getTime());
  shifted.setUTCDate(shifted.getUTCDate() + offsetDays);
  return formatIsoDate(shifted);
}

export function parseFlexibleDateInput(value, fallbackDate, parseIsoDateImpl = parseIsoDate, formatIsoDateImpl = formatIsoDate) {
  const raw = String(value || "").trim();
  if (!raw) return null;

  if (/^\d{4}-\d{2}-\d{2}$/.test(raw)) {
    return parseIsoDateImpl(raw) ? raw : null;
  }

  const fallback = parseIsoDateImpl(fallbackDate) || new Date();
  const fallbackYear = fallback.getUTCFullYear();
  let year;
  let month;
  let day;

  if (/^\d{4}$/.test(raw)) {
    month = Number(raw.slice(0, 2));
    day = Number(raw.slice(2, 4));
    year = fallbackYear;
  } else {
    const normalized = raw.replace(/[.\s-]+/g, "/");
    const parts = normalized.split("/").filter(Boolean);
    if (parts.length === 2) {
      [day, month] = parts.map(Number);
      year = fallbackYear;
    } else if (parts.length === 3) {
      [day, month, year] = parts.map(Number);
    } else {
      return null;
    }
  }

  if (!year || !month || !day) return null;
  const parsed = new Date(Date.UTC(year, month - 1, day));
  if (
    Number.isNaN(parsed.getTime()) ||
    parsed.getUTCFullYear() !== year ||
    parsed.getUTCMonth() !== month - 1 ||
    parsed.getUTCDate() !== day
  ) {
    return null;
  }

  return formatIsoDateImpl(parsed);
}
