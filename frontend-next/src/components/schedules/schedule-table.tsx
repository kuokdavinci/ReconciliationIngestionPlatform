"use client";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { ScheduleJob } from "@/types/schedules";
import styles from "./schedules.module.css";

interface Props {
  jobs: ScheduleJob[];
  onRunJob: (partner: string) => void;
  runningPartners?: Record<string, boolean>;
}

export function ScheduleTable({ jobs, onRunJob, runningPartners = {} }: Props) {
  if (jobs.length === 0) {
    return (
      <div style={{ padding: 24, textAlign: "center", color: "var(--text-muted)" }}>
        No enabled automation jobs found.
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
            <td className={styles.cell}>
              <div className={styles.statusCell}>
                <div className={styles.statusBadges}>
                {job.enabled ? <Badge severity="low">Enabled</Badge> : <Badge severity="critical">Disabled</Badge>}
                <Badge severity={job.status === "HEALTHY" ? "low" : "medium"}>{job.status}</Badge>
                {job.hasPendingFile && <Badge severity="medium">Pending file</Badge>}
                </div>
                <div className={styles.statusText}>{job.statusMessage}</div>
              </div>
            </td>
            <td className={styles.cell}>
              <div className={styles.actionRow}>
                <Badge severity="neutral">{job.pendingReviewPackets ?? 0} pending</Badge>
                <Button variant="secondary" onClick={() => onRunJob(job.partner)} disabled={Boolean(runningPartners[job.partner])}>
                  {runningPartners[job.partner] ? "Running..." : "Run Now"}
                </Button>
              </div>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
    </div>
  );
}
