"use client";

import type { ScheduleJob } from "@/types/schedules";
import { ScheduleRecoverySummary } from "./schedule-recovery-summary";
import { ScheduleActions } from "./schedule-actions";
import styles from "./schedules.module.css";

interface Props {
  jobs: ScheduleJob[];
  onRunJob: (partner: string) => void;
  onBackfill: (partner: string) => void;
  onRetryRecovery?: (partner: string) => void;
  onViewRecovery?: (job: ScheduleJob) => void;
  runningPartners?: Record<string, boolean>;
  retryingRecoveryPartners?: Record<string, boolean>;
  emptyMessage?: string;
}

export function ScheduleTable({ jobs, onRunJob, onBackfill, onRetryRecovery, onViewRecovery, runningPartners = {}, retryingRecoveryPartners = {}, emptyMessage }: Props) {
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
        <colgroup>
          <col style={{ width: "20%" }} />
          <col style={{ width: "15%" }} />
          <col style={{ width: "18%" }} />
          <col style={{ width: "27%" }} />
          <col style={{ width: "20%" }} />
        </colgroup>
        <thead>
          <tr>
            {["Partner", "Schedule", "Destination", "Status", "Action"].map((h) => (
              <th key={h} className={styles.headCell}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {jobs.map((job, index) => {
            const isNearBottom = index >= jobs.length - 2 && jobs.length > 1;
            return (
              <tr key={job.partner}>
                <td className={styles.cell} data-label="Partner">
                  <div className={styles.partnerCellContent}>
                    <div className={styles.partnerHeaderRow}>
                      <span
                        className={`${styles.statusDot} ${job.enabled ? styles.dotEnabled : styles.dotDisabled}`}
                        title={job.enabled ? "Schedule Enabled" : "Schedule Disabled"}
                      />
                      <strong className={styles.partnerName}>{job.partner}</strong>
                    </div>
                    <div className={styles.partnerSubRow}>
                      <span className={styles.methodLabel}>{job.fetchMethod}</span>
                      {(job.pendingReviewPackets ?? 0) > 0 && (
                        <>
                          <span className={styles.subDot}>·</span>
                          <span className={styles.pendingBadge} title={`${job.pendingReviewPackets} packets pending review`}>
                            {job.pendingReviewPackets} pending
                          </span>
                        </>
                      )}
                    </div>
                  </div>
                </td>
                <td className={styles.cell} data-label="Schedule">
                  <code className={styles.scheduleCode}>{job.schedule || "—"}</code>
                </td>
                <td className={styles.cell} data-label="Destination">
                  <span className={styles.destinationPath} title={job.destination}>{job.destination}</span>
                </td>
                <td
                  className={`${styles.cell} ${styles.statusCell} ${onViewRecovery ? styles.clickableStatusCell : ""}`}
                  data-label="Status"
                  onClick={onViewRecovery ? () => onViewRecovery(job) : undefined}
                  title={onViewRecovery ? "Click to view full runtime & recovery details" : undefined}
                >
                  <ScheduleRecoverySummary job={job} />
                </td>
                <td className={styles.cell} data-label="Action">
                  <div className={styles.actionCell}>
                    <ScheduleActions
                      job={job}
                      dropup={isNearBottom}
                      running={Boolean(runningPartners[job.partner])}
                      retrying={Boolean(retryingRecoveryPartners[job.partner])}
                      onRun={() => onRunJob(job.partner)}
                      onBackfill={() => onBackfill(job.partner)}
                      onRetry={onRetryRecovery ? () => onRetryRecovery(job.partner) : undefined}
                      onViewRecovery={onViewRecovery ? () => onViewRecovery(job) : undefined}
                    />
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
