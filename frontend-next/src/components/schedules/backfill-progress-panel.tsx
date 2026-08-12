"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { getBackfillRun } from "@/lib/api/automation";
import type { BackfillDay, BackfillRun } from "@/types/schedules";
import styles from "./backfill.module.css";

interface Props {
  runId: string | null;
  onClose: () => void;
}

function daySeverity(status: BackfillDay["status"]) {
  if (status === "COMPLETED") return "low" as const;
  if (status === "FAILED") return "critical" as const;
  if (status === "RUNNING" || status === "WAITING_CONFIG") return "medium" as const;
  return "neutral" as const;
}

export function BackfillProgressPanel({ runId, onClose }: Props) {
  const router = useRouter();
  const [run, setRun] = useState<BackfillRun | null>(null);
  const [error, setError] = useState<string | null>(null);
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!runId) return;
    let cancelled = false;
    const load = async () => {
      try {
        const next = await getBackfillRun(runId);
        if (!cancelled) {
          setRun(next);
          setError(null);
        }
      } catch (reason) {
        if (!cancelled) setError(reason instanceof Error ? reason.message : "Failed to load backfill progress.");
      }
    };
    void load();
    const interval = window.setInterval(() => { void load(); }, 3000);
    closeRef.current?.focus();
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [runId]);

  if (!runId) return null;
  const progress = run ? `${run.completedDays}/${run.totalDays}` : "-";
  const reviewPacketId = run?.approvalContext?.reviewPacketId;

  return (
    <div className={styles.overlay} onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <aside className={styles.panel} role="dialog" aria-modal="true" aria-labelledby="backfill-progress-title">
        <div className={styles.header}>
          <div>
            <p className={styles.eyebrow}>BACKFILL · AIRFLOW</p>
            <h2 id="backfill-progress-title">{run?.partner || "Backfill progress"}</h2>
            {run && <p className={styles.range}>{run.fromDate} → {run.toDate}</p>}
          </div>
          <button ref={closeRef} type="button" className={styles.close} onClick={onClose} aria-label="Close backfill progress">✕</button>
        </div>
        <div className={styles.body}>
          {error && <p className={styles.error} role="alert">{error}</p>}
          {!run && !error && <p className={styles.description}>Loading backfill progress…</p>}
          {run && (
            <>
              <div className={styles.hero}>
                <div><span>Overall progress</span><strong>{progress} days</strong></div>
                <Badge severity={run.status === "FAILED" ? "critical" : run.status === "COMPLETED" ? "low" : "medium"}>{run.status}</Badge>
              </div>
              {reviewPacketId && run.status === "WAITING_CONFIG" && (
                <div className={styles.approvalNotice}>
                  <strong>Mapping approval required</strong>
                  <span>Approve the VNPAY mapping before the ordered run can continue.</span>
                  <Button variant="primary" onClick={() => router.push(`/review-center?packet=${encodeURIComponent(reviewPacketId)}`)}>
                    Open Guided Review
                  </Button>
                </div>
              )}
              <div className={styles.dayList}>
                {run.days.map((day) => (
                  <div className={styles.dayRow} key={day.businessDate}>
                    <div>
                      <strong>{day.businessDate}</strong>
                      <span>{day.message || (day.status === "PENDING" ? "Waiting for previous day" : "")}</span>
                    </div>
                    <Badge severity={daySeverity(day.status)}>{day.status}</Badge>
                  </div>
                ))}
              </div>
              {run.orchestration?.dagRunId && (
                <p className={styles.meta}>Airflow run: <code>{run.orchestration.dagRunId}</code></p>
              )}
            </>
          )}
        </div>
      </aside>
    </div>
  );
}
