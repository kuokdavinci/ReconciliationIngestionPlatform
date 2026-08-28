import type { RecoveryStatus, ScheduleJob } from "@/types/schedules";
import { Badge } from "@/components/ui/badge";
import { isActiveRuntimeStatus } from "./recovery-status";
import styles from "./schedules.module.css";

interface Props {
  job: ScheduleJob;
}

function parseErrorSummary(lastError?: string | null, errorCode?: string | null): string {
  if (errorCode) return errorCode;
  if (!lastError) return "Execution failed";
  const line = lastError.split("\n")[0].trim();
  // Shorten common error messages into clean readable text
  if (line.toLowerCase().includes("filedrop directory does not exist")) {
    return "Directory unavailable";
  }
  if (line.toLowerCase().includes("connection refused")) {
    return "Connection refused";
  }
  if (line.toLowerCase().includes("timeout")) {
    return "Request timed out";
  }
  return line.length > 28 ? line.slice(0, 28) + "…" : line;
}

function statusSeverity(status: string): "neutral" | "critical" | "high" | "medium" | "low" {
  if (["Failed", "Blocked", "Backfill Failed"].includes(status)) return "critical";
  if (["Waiting Review", "Retrying", "Running", "Backfill", "Backfill Review"].includes(status)) return "medium";
  if (["Ready", "Safe Duplicate"].includes(status)) return "low";
  return "neutral";
}

export function ScheduleRecoverySummary({ job }: Props) {
  const recovery = job.recovery;
  const recoveryStatus = recovery?.status as RecoveryStatus | undefined;
  const airflowTaskState = String(job.latestRuntimeRun?.orchestration?.taskState || "").toLowerCase();
  const isRetrying = job.status === "RETRYING" || airflowTaskState === "up_for_retry";
  const isActive = isActiveRuntimeStatus(job.status);
  const isFailed = job.status === "FAILED" || recoveryStatus === "FAILED";
  const isBlocked = job.status === "BLOCKED" || recoveryStatus === "BLOCKED";
  const isWaitingReview = job.status === "WAITING_REVIEW" || recoveryStatus === "WAITING_REVIEW";
  const isSafeDuplicate = job.status === "SAFE_DUPLICATE" || job.safeDuplicate === true || recovery?.safeDuplicate === true;
  const runtimeStats = job.latestRuntimeRun?.stats || {};
  const topRuleCodes = Array.isArray(runtimeStats.topRuleCodes) ? runtimeStats.topRuleCodes : [];
  const batchFatalCode = topRuleCodes.find((code): code is string => typeof code === "string");
  const isBatchFatal = isFailed && runtimeStats.qualityDecision === "FAIL" && Boolean(batchFatalCode);
  const backfillStatus = job.activeBackfill?.status;
  const hasBackfill = Boolean(job.activeBackfill);
  const backfillWaitingForReview = backfillStatus === "WAITING_CONFIG";
  const backfillFailed = backfillStatus === "FAILED";

  // Primary Status
  let primaryLabel = "Ready";
  if (hasBackfill) {
    primaryLabel = backfillFailed ? "Backfill Failed" : backfillWaitingForReview ? "Backfill Review" : "Backfill";
  } else if (isFailed) {
    primaryLabel = "Failed";
  } else if (isBlocked) {
    primaryLabel = "Blocked";
  } else if (isRetrying) {
    primaryLabel = "Retrying";
  } else if (isActive) {
    primaryLabel = "Running";
  } else if (isWaitingReview) {
    primaryLabel = "Waiting Review";
  } else if (isSafeDuplicate) {
    primaryLabel = "Safe Duplicate";
  }

  // Secondary Line (Max 1 short line, ONLY when relevant)
  let subLine: string | null = null;
  if (hasBackfill) {
    const label = String(backfillStatus || "ACTIVE").replaceAll("_", " ");
    subLine = `${label}${job.activeBackfill?.currentDate ? ` · ${job.activeBackfill.currentDate}` : ""}`;
  } else if (isFailed || isBlocked) {
    if (isBatchFatal) {
      subLine = `BATCH_FATAL · ${batchFatalCode}`;
    } else if (recovery?.lastError || recovery?.errorCode) {
      subLine = parseErrorSummary(recovery.lastError, recovery.errorCode);
    } else if (recoveryStatus === "FAILED") {
      subLine = "Recovery failed";
    } else {
      subLine = "Directory unavailable";
    }
  } else if ((isActive || isRetrying) && recovery && recovery.totalUnitCount > 0) {
    subLine = `${recovery.completedUnitCount} / ${recovery.totalUnitCount} units`;
  } else if (isWaitingReview) {
    subLine = "Action required";
  } else if (isSafeDuplicate) {
    subLine = job.duplicateMessage || recovery?.duplicateMessage || "Already processed; skipped safely";
  }

  const ariaLabel = `${job.partner} status ${primaryLabel}${subLine ? `. ${subLine}` : ""}`;

  return (
    <div className={styles.scheduleSummaryCompact} aria-label={ariaLabel}>
      <div className={styles.statusPrimaryRow}>
        <Badge severity={statusSeverity(primaryLabel)} shape="pill">{primaryLabel}</Badge>
      </div>

      {subLine && (
        <div className={styles.statusSecondaryLine} title={subLine}>
          {subLine}
        </div>
      )}
    </div>
  );
}
