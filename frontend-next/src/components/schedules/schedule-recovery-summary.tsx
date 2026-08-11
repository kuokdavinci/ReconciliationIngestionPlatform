import { Badge } from "@/components/ui/badge";
import type { RecoveryStatus, ScheduleJob } from "@/types/schedules";
import { RecoveryCountdown } from "./recovery-countdown";
import {
  recoveryLabel,
  recoverySeverity,
  isMirroredRecoveryStatus,
  runtimeLabel,
  runtimeSeverity,
} from "./recovery-status";
import styles from "./schedules.module.css";

interface Props {
  job: ScheduleJob;
}

function recoveryDetail(recovery: NonNullable<ScheduleJob["recovery"]>) {
  if (recovery.status === "FAILED" || recovery.status === "BLOCKED") {
    const value = recovery.errorCode || recovery.lastError;
    return value ? { label: "Error", value, kind: "error" as const } : null;
  }
  if (recovery.retryable && recovery.nextRetryAt) {
    return { label: "Next", value: recovery.nextRetryAt, kind: "retry" as const };
  }
  if (recovery.lastCompletedUnitKey) {
    return { label: "Last completed", value: recovery.lastCompletedUnitKey, kind: "completed" as const };
  }
  return null;
}

function detailText(
  recovery: NonNullable<ScheduleJob["recovery"]> | null | undefined,
  job: ScheduleJob,
) {
  const detail = recovery ? recoveryDetail(recovery) : null;
  if (!detail) return job.duplicateMessage || job.statusMessage || "No runtime message";
  if (detail.kind === "retry") return `Retry scheduled for ${detail.value}`;
  return `${detail.label}: ${detail.value}`;
}

export function ScheduleRecoverySummary({ job }: Props) {
  const recovery = job.recovery;
  const recoveryStatus = recovery?.status as RecoveryStatus | undefined;
  const detail = recovery ? recoveryDetail(recovery) : null;
  const progress = recovery && recovery.totalUnitCount > 0
    ? `${recovery.completedUnitCount}/${recovery.totalUnitCount}`
    : null;
  const airflowTaskState = String(job.latestRuntimeRun?.orchestration?.taskState || "").toLowerCase();
  const isRetrying = job.status === "RETRYING" || airflowTaskState === "up_for_retry";
  const showRecoveryStatus = Boolean(
    recoveryStatus &&
    recoveryStatus !== "IDLE" &&
    !isMirroredRecoveryStatus(job.status, recoveryStatus),
  );
  const ariaLabel = [
    job.partner,
    `Runtime ${runtimeLabel(job.status)}`,
    showRecoveryStatus ? `Recovery ${recoveryLabel(recoveryStatus!)}` : null,
    recovery?.currentUnitKey ? `Current ${recovery.currentUnitKey}` : null,
    progress ? `Progress ${progress}` : null,
    detailText(recovery, job),
  ].filter(Boolean).join(". ");

  return (
    <div className={styles.scheduleSummary} aria-label={ariaLabel}>
      <div className={styles.scheduleSummaryBadges}>
        <Badge severity={job.enabled ? "low" : "critical"}>{job.enabled ? "Enabled" : "Disabled"}</Badge>
        <Badge severity={runtimeSeverity(job.status)}>{runtimeLabel(job.status)}</Badge>
        {isRetrying && <Badge severity="medium">Retrying</Badge>}
      </div>

      {showRecoveryStatus && recoveryStatus && (
        <div className={styles.scheduleSummaryRecovery}>
          <Badge severity={recoverySeverity(recoveryStatus)}>
            Recovery: {recoveryLabel(recoveryStatus)}
          </Badge>
        </div>
      )}

      {progress && (
        <div className={styles.scheduleSummaryProgress}>
          <strong>Progress</strong>
          <span className={styles.scheduleSummaryCurrent}>{progress} units</span>
        </div>
      )}

      <div className={`${styles.scheduleSummaryDetail} ${detail?.kind === "error" ? styles.scheduleSummaryDetailError : ""}`}>
        {detail?.kind === "retry" ? (
          <>
            <strong>{detail.label}</strong>
            <RecoveryCountdown target={detail.value} />
          </>
        ) : detail ? (
          <>
            <strong>{detail.label}</strong>
            <span className={styles.scheduleSummaryDetailValue} title={detail.value}>{detail.value}</span>
          </>
        ) : (
          <span className={styles.scheduleSummaryDetailValue} title={detailText(recovery, job)}>
            {detailText(recovery, job)}
          </span>
        )}
      </div>
    </div>
  );
}
