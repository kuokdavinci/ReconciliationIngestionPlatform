export function statusLabel(value) {
  const raw = String(value || "");
  const labels = {
    MATCHED: "Matched",
    MATCHED_FAILED: "Matched with Failure",
    MATCHED_REVERSED: "Matched and Reversed",
    AMOUNT_MISMATCH: "Amount Mismatch",
    STATUS_MISMATCH: "Status Mismatch",
    MULTIPLE_MISMATCH: "Multiple Mismatch",
    MISSING_INTERNAL: "Missing Internal",
    MISSING_PARTNER: "Missing Partner",
    UNMAPPED_SKIPPED: "Unmapped",
    APPROVED: "Approved",
    PENDING_APPROVAL: "Pending Review",
    REJECTED: "Rejected",
    SUPERSEDED: "Superseded",
    PROCESSING: "Processing",
    COMPLETED: "Completed",
    FAILED: "Failed",
    ACTIVE: "Active",
    NEEDS_REVIEW: "Needs Review",
    BLOCKED: "Blocked",
    NO_ACTIVITY: "No Activity",
    STALE: "Stale",
    ENABLED: "Enabled",
    DISABLED: "Disabled",
    PAUSED: "Paused",
    PENDING: "Pending",
    HEALTHY: "Healthy",
    MONITOR: "Monitor",
    LOW: "Low",
    MEDIUM: "Medium",
    HIGH: "High",
    QUEUED: "Queued",
    FETCHING: "Fetching",
    INGESTING: "Ingesting",
    WAITING_REVIEW: "Waiting Review",
    WAITING_RECONCILE: "Waiting Reconcile",
    RECONCILING: "Reconciling"
  };
  return labels[raw] || raw.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
}

export function badge(value) {
  const text = statusLabel(value);
  const raw = String(value || "").toUpperCase();
  const toneMap = {
    "MATCHED": { tone: "matched", icon: "check_circle" },
    "MATCHED_FAILED": { tone: "warning", icon: "warning" },
    "MATCHED_REVERSED": { tone: "processing", icon: "sync" },
    "AMOUNT_MISMATCH": { tone: "critical", icon: "error" },
    "STATUS_MISMATCH": { tone: "warning", icon: "warning" },
    "MULTIPLE_MISMATCH": { tone: "critical", icon: "error" },
    "MISSING_INTERNAL": { tone: "warning", icon: "warning" },
    "MISSING_PARTNER": { tone: "critical", icon: "error" },
    "UNMAPPED_SKIPPED": { tone: "neutral", icon: "help" },
    "APPROVED": { tone: "matched", icon: "check_circle" },
    "PENDING_APPROVAL": { tone: "warning", icon: "pending" },
    "REJECTED": { tone: "critical", icon: "cancel" },
    "SUPERSEDED": { tone: "processing", icon: "history" },
    "PROCESSING": { tone: "processing", icon: "sync" },
    "COMPLETED": { tone: "matched", icon: "check_circle" },
    "FAILED": { tone: "critical", icon: "cancel" },
    "ACTIVE": { tone: "matched", icon: "check_circle" },
    "NEEDS_REVIEW": { tone: "warning", icon: "rate_review" },
    "BLOCKED": { tone: "critical", icon: "block" },
    "NO_ACTIVITY": { tone: "neutral", icon: "info" },
    "STALE": { tone: "warning", icon: "history" },
    "ENABLED": { tone: "matched", icon: "check_circle" },
    "DISABLED": { tone: "critical", icon: "block" },
    "PAUSED": { tone: "warning", icon: "pause_circle" },
    "PENDING": { tone: "warning", icon: "pending" },
    "HEALTHY": { tone: "matched", icon: "check_circle" },
    "MONITOR": { tone: "warning", icon: "visibility" },
    "LOW": { tone: "matched", icon: "check_circle" },
    "MEDIUM": { tone: "warning", icon: "warning" },
    "HIGH": { tone: "critical", icon: "error" },
    "QUEUED": { tone: "processing", icon: "schedule" },
    "FETCHING": { tone: "processing", icon: "download" },
    "INGESTING": { tone: "processing", icon: "settings" },
    "WAITING_REVIEW": { tone: "warning", icon: "rate_review" },
    "WAITING_RECONCILE": { tone: "processing", icon: "pending" },
    "RECONCILING": { tone: "processing", icon: "sync" }
  };
  const toneData = toneMap[raw] || { tone: "neutral", icon: "info" };
  return `<span class="badge ${toneData.tone}" style="display: inline-flex; align-items: center; gap: 4px;">
    <span class="material-symbols-outlined" style="font-size: 13px;">${toneData.icon}</span>
    <span>${text}</span>
  </span>`;
}

export function severityBadge(value) {
  const level = String(value || "medium").toLowerCase();
  const label = level.toUpperCase();
  return `<span class="badge severity-${level}">${label}</span>`;
}

export function reconciliationRowClass(status) {
  const normalized = String(status || "").toUpperCase();
  if (!normalized || normalized === "MATCHED") return "recon-row-neutral";
  if (normalized.includes("MISSING")) return "recon-row-critical";
  if (normalized.includes("AMOUNT") || normalized.includes("MULTIPLE")) return "recon-row-critical";
  if (normalized.includes("STATUS") || normalized.includes("UNMAPPED")) return "recon-row-warning";
  return "recon-row-warning";
}
