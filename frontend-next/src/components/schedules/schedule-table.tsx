"use client";

import { Button } from "@/components/ui/button";
import type { ScheduleJob } from "@/types/schedules";
import { ScheduleRecoverySummary } from "./schedule-recovery-summary";
import styles from "./schedules.module.css";

interface Props {
  jobs: ScheduleJob[];
  onRunJob: (partner: string) => void;
  onRetryRecovery?: (partner: string) => void;
  onViewRecovery?: (job: ScheduleJob) => void;
  runningPartners?: Record<string, boolean>;
  retryingRecoveryPartners?: Record<string, boolean>;
  emptyMessage?: string;
}

export function ScheduleTable({ jobs, onRunJob, onRetryRecovery, onViewRecovery, runningPartners = {}, retryingRecoveryPartners = {}, emptyMessage }: Props) {
  if (jobs.length === 0) {
    return (
      <div style={{ padding: 24, textAlign: "center", color: "var(--text-muted)" }}>
        {emptyMessage || "No enabled automation jobs found."}
      </div>
    );
  }

  return (
    <div className={styles.tableWrap}>
    <table className={styles.table}>
      <thead>
        <tr>
          {["Partner", "Method", "Schedule", "Destination", "Runtime State", "Actions"].map((h) => (
            <th key={h} className={styles.headCell}>{h}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {jobs.map((job) => (
          <tr key={job.partner}>
            <td className={styles.cell}><strong>{job.partner}</strong></td>
            <td className={styles.cell}>{job.fetchMethod}</td>
            <td className={styles.cell}>
              <code style={{ fontFamily: "var(--font-mono)", fontSize: 12 }}>{job.schedule}</code>
            </td>
            <td className={styles.cell}>{job.destination}</td>
            <td className={`${styles.cell} ${styles.statusCell}`}>
              <ScheduleRecoverySummary job={job} />
            </td>
            <td className={styles.cell}>
              <div className={styles.actionCell}>
                <span className={styles.pendingMeta}>{job.pendingReviewPackets ?? 0} pending</span>
                <div className={styles.actionRow}>
                {onRetryRecovery && job.recovery?.retryable === true && (
                  <Button
                    variant="primary"
                    onClick={() => onRetryRecovery(job.partner)}
                    disabled={Boolean(retryingRecoveryPartners[job.partner]) || (
                      Boolean(job.activeRuntimeRun)
                      && job.status !== "RETRYING"
                      && job.latestRuntimeRun?.orchestration?.taskState !== "up_for_retry"
                    )}
                  >
                    {retryingRecoveryPartners[job.partner]
                      ? "Retrying…"
                      : job.status === "RETRYING" || job.latestRuntimeRun?.orchestration?.taskState === "up_for_retry"
                        ? "Manual retry"
                        : "Retry"}
                  </Button>
                )}
                {onViewRecovery && job.recovery && job.recovery.status !== "IDLE" && (
                  <Button variant="tertiary" onClick={() => onViewRecovery(job)}>
                    View recovery
                  </Button>
                )}
                <Button
                  variant="secondary"
                  onClick={() => onRunJob(job.partner)}
                  disabled={Boolean(runningPartners[job.partner])
                    || Boolean(job.activeRuntimeRun)
                    || job.recovery?.status === "WAITING_REVIEW"
                    || (job.recovery?.status === "FAILED" && job.recovery.retryable === true)}
                >
                  {runningPartners[job.partner] ? "Running..." : "Run Now"}
                </Button>
                </div>
              </div>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
    </div>
  );
}
