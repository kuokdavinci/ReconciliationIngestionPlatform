"use client";

import { useState, useEffect, useRef } from "react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Panel } from "@/components/ui/panel";
import { approveMapping } from "@/lib/api/mapping-studio";
import { getJob, runJob } from "@/lib/api/automation";
import { getCurrentActor } from "@/lib/actor";
import type { StudioWizardState } from "@/types/mapping";
import type { RuntimeRunSummary } from "@/types/schedules";
import styles from "./mapping-studio.module.css";

interface Props {
  wizard: StudioWizardState;
  onBack: () => void;
  onOpenReconciliation?: () => void;
}

interface RuntimeRun {
  id?: string;
  status?: string;
  partner?: string;
  date?: string;
  stats?: {
    total_rows?: number;
    valid_rows?: number;
    invalid_rows?: number;
    duration_seconds?: number;
  };
  reconciliationCount?: number | null;
  message?: string;
}

const TERMINAL_STATUSES = new Set(["COMPLETED", "FAILED", "CANCELLED"]);

function readNumber(value: unknown): number | undefined {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() !== "") {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : undefined;
  }
  return undefined;
}

function normalizeRuntimeRun(runtime: RuntimeRunSummary): RuntimeRun {
  const stats = runtime.stats ?? {};
  return {
    ...runtime,
    stats: {
      total_rows: readNumber(stats.total_rows ?? stats.totalRows),
      valid_rows: readNumber(stats.valid_rows ?? stats.successRows),
      invalid_rows: readNumber(stats.invalid_rows ?? stats.failedRows),
      duration_seconds: readNumber(stats.duration_seconds ?? stats.durationSeconds),
    },
  };
}

function getErrorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Không thể tải trạng thái pipeline.";
}

function latestRunMatchesQueuedRun(
  latestRun: RuntimeRunSummary | null | undefined,
  queuedRunId: string | null,
): boolean {
  return Boolean(queuedRunId && latestRun?.id === queuedRunId);
}

export function MappingStudioExecuteStep({ wizard, onBack, onOpenReconciliation }: Props) {
  const [running, setRunning] = useState(false);
  const [runData, setRunData] = useState<RuntimeRun | null>(null);
  const [error, setError] = useState<string | null>(null);
  const sawActiveRun = useRef(false);
  const queuedRunId = useRef<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    const loadRuntimeRun = async () => {
      try {
        const job = await getJob(wizard.partner);
        if (cancelled) return;
        const latestRun = job?.latestRuntimeRun;

        if (job?.activeRuntimeRun) {
          sawActiveRun.current = true;
          setRunData(normalizeRuntimeRun(job.activeRuntimeRun));
          setError(null);
        } else if (!running || sawActiveRun.current || latestRunMatchesQueuedRun(latestRun, queuedRunId.current)) {
          if (latestRun) {
            const normalized = normalizeRuntimeRun(latestRun);
            setRunData(normalized);
            setError(null);
            if (running && TERMINAL_STATUSES.has(normalized.status ?? "")) {
              setRunning(false);
            }
          }
        }
      } catch (loadError) {
        if (!cancelled) setError(getErrorMessage(loadError));
      }
    };

    void loadRuntimeRun();
    if (running) {
      const timer = window.setInterval(() => void loadRuntimeRun(), 2000);
      return () => {
        cancelled = true;
        window.clearInterval(timer);
      };
    }

    return () => {
      cancelled = true;
    };
  }, [running, wizard.partner]);

  const handleApproveAndRun = async () => {
    setError(null);
    setRunning(true);
    sawActiveRun.current = false;
    queuedRunId.current = null;

    try {
      const configId = wizard.draftMappingId ?? wizard.config?._id;
      if (configId && wizard.configStatus?.toUpperCase() === "PENDING_APPROVAL") {
        await approveMapping(configId, getCurrentActor());
      }

      const response = await runJob(wizard.partner);
      queuedRunId.current = response.runtimeRunId;
      setRunData({
        id: response.runtimeRunId,
        partner: wizard.partner,
        status: "QUEUED",
        message: response.message,
      });
    } catch (runError) {
      queuedRunId.current = null;
      setError(getErrorMessage(runError));
      setRunning(false);
    }
  };

  const status = runData?.status || (running ? "RUNNING" : "READY");
  const isCompleted = status === "COMPLETED";
  const isFailed = status === "FAILED" || status === "CANCELLED";

  return (
    <div>
      <h2 className={styles.studioTitle}>Step 4: Approve & Execute Reconciliation Pipeline</h2>
      <p className={styles.studioSubtitle}>
        Review finalized configuration health, approve handoff, and trigger end-to-end file ingestion and reconciliation.
      </p>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 20 }}>
        <Panel>
          <h3 style={{ margin: "0 0 12px 0", fontSize: 14, color: "var(--text-primary)" }}>Config Handoff Summary</h3>
          <div style={{ display: "flex", flexDirection: "column", gap: 8, fontSize: 13, color: "var(--text-muted)" }}>
            <div>Partner: <strong style={{ color: "var(--text-primary)" }}>{wizard.partner}</strong></div>
            <div>File Name: <strong style={{ color: "var(--text-primary)" }}>{wizard.fileName || "filedrop_sample.xlsx"}</strong></div>
            <div>Mapped Fields: <strong style={{ color: "var(--text-primary)" }}>{wizard.config?.fieldMappings?.length || 0} fields</strong></div>
            <div>Status: <Badge severity="low">{wizard.configStatus || "APPROVED"}</Badge></div>
          </div>
        </Panel>

        <Panel>
          <h3 style={{ margin: "0 0 12px 0", fontSize: 14, color: "var(--text-primary)" }}>Pipeline Operation Control</h3>
          <p style={{ fontSize: 13, color: "var(--text-muted)", marginBottom: 16 }}>
            Click below to execute file ingestion, dynamic normalization, and core reconciliation engine.
          </p>
          <div style={{ display: "flex", gap: 12 }}>
            <Button variant="primary" disabled={running} onClick={handleApproveAndRun} style={{ flex: 1 }}>
              {running ? "🔄 Processing Ingestion & Reconciliation..." : isCompleted ? "🔁 Re-run Pipeline (Idempotency Check)" : "🚀 Approve & Start Pipeline"}
            </Button>
          </div>
          {error && (
            <p role="alert" style={{ color: "var(--status-unmatched)", fontSize: 13, margin: "12px 0 0" }}>
              {error}
            </p>
          )}
        </Panel>
      </div>

      {/* Real-time Pipeline Stats Display */}
      <Panel>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
          <h3 style={{ margin: 0, fontSize: 15, color: "var(--text-primary)" }}>📊 Pipeline Execution Stats</h3>
          <Badge severity={isCompleted ? "low" : isFailed ? "critical" : running ? "medium" : "neutral"}>
            {status}
          </Badge>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12, textAlign: "center" }}>
          <div style={{ padding: 12, background: "rgba(255,255,255,0.03)", borderRadius: 6 }}>
            <div style={{ fontSize: 20, fontWeight: 700, color: "var(--text-primary)" }}>
              {runData?.stats?.total_rows ?? (running ? "..." : 0)}
            </div>
            <div style={{ fontSize: 12, color: "var(--text-muted)" }}>Total Ingested</div>
          </div>

          <div style={{ padding: 12, background: "rgba(34,197,94,0.05)", borderRadius: 6 }}>
            <div style={{ fontSize: 20, fontWeight: 700, color: "var(--status-matched)" }}>
              {runData?.stats?.valid_rows ?? (running ? "..." : 0)}
            </div>
            <div style={{ fontSize: 12, color: "var(--text-muted)" }}>Normalized (Valid)</div>
          </div>

          <div style={{ padding: 12, background: "rgba(239,68,68,0.05)", borderRadius: 6 }}>
            <div style={{ fontSize: 20, fontWeight: 700, color: "var(--status-unmatched)" }}>
              {runData?.stats?.invalid_rows ?? (running ? "..." : 0)}
            </div>
            <div style={{ fontSize: 12, color: "var(--text-muted)" }}>Errors / Violations</div>
          </div>

          <div style={{ padding: 12, background: "rgba(59,130,246,0.05)", borderRadius: 6 }}>
            <div style={{ fontSize: 20, fontWeight: 700, color: "var(--brand-accent-blue)" }}>
              {runData?.stats?.duration_seconds ? `${runData.stats.duration_seconds}s` : (running ? "..." : "0s")}
            </div>
            <div style={{ fontSize: 12, color: "var(--text-muted)" }}>Execution Latency</div>
          </div>
        </div>

        {isCompleted && (
          <div style={{ marginTop: 16, padding: 12, background: "rgba(34,197,94,0.1)", borderRadius: 6, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span style={{ fontSize: 13, color: "var(--status-matched)" }}>
              ✅ Reconciliation completed successfully! Transactions ingest & match finished.
            </span>
            {onOpenReconciliation && (
              <Button variant="secondary" onClick={onOpenReconciliation} style={{ height: 32, fontSize: 12 }}>
                View Reconciliation Results ➔
              </Button>
            )}
          </div>
        )}
      </Panel>

      <div style={{ display: "flex", justifyContent: "space-between", marginTop: 24 }}>
        <Button variant="secondary" onClick={onBack} disabled={running}>
          ← Back to Validate
        </Button>
      </div>
    </div>
  );
}
