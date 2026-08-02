"use client";

import { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Panel } from "@/components/ui/panel";
import type { StudioWizardState } from "@/types/mapping";
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
  reconciliationCount?: number;
  message?: string;
}

export function MappingStudioExecuteStep({ wizard, onBack, onOpenReconciliation }: Props) {
  const [running, setRunning] = useState(false);
  const [runData, setRunData] = useState<RuntimeRun | null>(null);

  // Real-time polling while running
  useEffect(() => {
    const fetchLatestRun = async () => {
      try {
        const today = new Date().toISOString().split("T")[0];
        const res = await fetch(`/api/v1/reconciliation/latest-run?partner=${encodeURIComponent(wizard.partner)}&date=${today}`);
        if (res.ok) {
          const data = await res.json();
          if (data && data.run) {
            setRunData(data.run);
          }
        }
      } catch {
        // Fallback silently if API is offline
      }
    };

    fetchLatestRun();
    let timer: NodeJS.Timeout;
    if (running) {
      timer = setInterval(fetchLatestRun, 2000);
    }
    return () => {
      if (timer) clearInterval(timer);
    };
  }, [running, wizard.partner]);

  const handleApproveAndRun = async () => {
    setRunning(true);
    try {
      const today = new Date().toISOString().split("T")[0];
      
      // 1. Approve mapping config if it's currently PENDING_APPROVAL
      const config = wizard.config as ({ id?: string; _id?: string } | null | undefined);
      const configId = config?.id || config?._id;
      if (configId) {
        await fetch(`/api/v1/mapping-configs/${configId}/approve`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ approvedBy: "AI_ASSIST_USER" }),
        }).catch(() => {});
      }

      // 2. Trigger Scheduler automation run to fetch & ingest file
      await fetch(`/api/v1/automation/jobs/${wizard.partner}/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Actor": "AI_ASSIST_WIZARD" },
      }).catch(() => {});

      // 3. Trigger Reconciliation Engine
      const res = await fetch("/api/v1/reconciliation/run", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Actor": "AI_ASSIST_WIZARD" },
        body: JSON.stringify({
          partner: wizard.partner,
          date: today,
          triggeredBy: "AI_ASSIST_WIZARD",
        }),
      });

      if (res.ok) {
        const data = await res.json();
        setRunData(data.run || data);
      }
    } catch (err) {
      console.error("Execution failed:", err);
    } finally {
      setTimeout(() => setRunning(false), 3000);
    }
  };

  const status = runData?.status || (running ? "RUNNING" : "READY");
  const isCompleted = status === "COMPLETED";

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
              {running ? "🔄 Processing Ingestion & Reconciliation..." : isCompleted ? "🔁 Re-run Pipeline (Idempotency Check)" : "🚀 Approve & Trigger Reconciliation"}
            </Button>
          </div>
        </Panel>
      </div>

      {/* Real-time Pipeline Stats Display */}
      <Panel>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
          <h3 style={{ margin: 0, fontSize: 15, color: "var(--text-primary)" }}>📊 Pipeline Execution Stats</h3>
          <Badge severity={isCompleted ? "low" : running ? "medium" : "neutral"}>
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
