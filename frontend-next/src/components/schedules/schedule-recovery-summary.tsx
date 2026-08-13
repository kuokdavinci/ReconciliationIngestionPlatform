import type { RecoveryStatus, ScheduleJob } from "@/types/schedules";
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
  const backfillStatus = job.activeBackfill?.status;
  const hasBackfill = Boolean(job.activeBackfill);
  const backfillWaitingForReview = backfillStatus === "WAITING_CONFIG";
  const backfillFailed = backfillStatus === "FAILED";

  // Primary Status
  let primaryLabel = "Ready";
  let statusDotClass = styles.statusDotReady;
  let textClass = styles.statusTextReady;

  if (hasBackfill) {
    primaryLabel = backfillFailed ? "Backfill Failed" : backfillWaitingForReview ? "Backfill Review" : "Backfill";
    statusDotClass = backfillFailed ? styles.statusDotFailed : backfillWaitingForReview ? styles.statusDotWarning : styles.statusDotRunning;
    textClass = backfillFailed ? styles.statusTextFailed : backfillWaitingForReview ? styles.statusTextWarning : styles.statusTextRunning;
  } else if (isFailed) {
    primaryLabel = "Failed";
    statusDotClass = styles.statusDotFailed;
    textClass = styles.statusTextFailed;
  } else if (isBlocked) {
    primaryLabel = "Blocked";
    statusDotClass = styles.statusDotFailed;
    textClass = styles.statusTextFailed;
  } else if (isRetrying) {
    primaryLabel = "Retrying";
    statusDotClass = styles.statusDotRunning;
    textClass = styles.statusTextRunning;
  } else if (isActive) {
    primaryLabel = "Running";
    statusDotClass = styles.statusDotRunning;
    textClass = styles.statusTextRunning;
  } else if (isWaitingReview) {
    primaryLabel = "Waiting Review";
    statusDotClass = styles.statusDotWarning;
    textClass = styles.statusTextWarning;
  } else if (isSafeDuplicate) {
    primaryLabel = "Safe Duplicate";
    statusDotClass = styles.statusDotReady;
    textClass = styles.statusTextReady;
  }

  // Secondary Line (Max 1 short line, ONLY when relevant)
  let subLine: string | null = null;
  if (hasBackfill) {
    const label = String(backfillStatus || "ACTIVE").replaceAll("_", " ");
    subLine = `${label}${job.activeBackfill?.currentDate ? ` · ${job.activeBackfill.currentDate}` : ""}`;
  } else if (isFailed || isBlocked) {
    if (recovery?.lastError || recovery?.errorCode) {
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
        <span className={`${styles.statusIndicatorDot} ${statusDotClass}`} />
        <span className={`${styles.statusPrimaryLabel} ${textClass}`}>{primaryLabel}</span>
      </div>

      {subLine && (
        <div className={styles.statusSecondaryLine} title={subLine}>
          {subLine}
        </div>
      )}
    </div>
  );
}
