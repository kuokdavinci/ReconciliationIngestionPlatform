import type { RecoveryStatus } from "@/types/schedules";

export const ACTIVE_RUNTIME_STATUSES = new Set([
  "QUEUED",
  "FETCHING",
  "INGESTING",
  "RETRYING",
  "WAITING_RECONCILE",
  "RECONCILING",
]);

export function isActiveRuntimeStatus(status: string) {
  return ACTIVE_RUNTIME_STATUSES.has(status);
}

export function isMirroredRecoveryStatus(runtimeStatus: string, recoveryStatus: RecoveryStatus) {
  if (runtimeStatus === "WAITING_REVIEW" && recoveryStatus === "WAITING_REVIEW") {
    return true;
  }
  return recoveryStatus === "PROCESSING" && isActiveRuntimeStatus(runtimeStatus);
}

export function recoverySeverity(status: RecoveryStatus) {
  if (status === "FAILED" || status === "BLOCKED") return "critical" as const;
  if (status === "PROCESSING" || status === "PENDING" || status === "WAITING_REVIEW") return "medium" as const;
  if (status === "COMPLETED" || status === "REPLAYED") return "low" as const;
  return "neutral" as const;
}

export function recoveryLabel(status: RecoveryStatus) {
  if (status === "WAITING_REVIEW") return "Waiting review";
  if (status === "REPLAYED") return "Safe replay";
  return status;
}

export function runtimeLabel(status: string) {
  if (status === "RETRYING") return "RETRYING";
  if (isActiveRuntimeStatus(status)) return "RUNNING";
  if (status === "WAITING_REVIEW") return "WAITING REVIEW";
  if (status === "PENDING") return "PENDING";
  if (status === "FAILED") return "FAILED";
  return "READY";
}

export function runtimeSeverity(status: string) {
  if (status === "FAILED") return "critical" as const;
  if (isActiveRuntimeStatus(status) || status === "PENDING" || status === "WAITING_REVIEW") {
    return "medium" as const;
  }
  return "low" as const;
}
