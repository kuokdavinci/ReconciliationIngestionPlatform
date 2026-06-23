import { useState } from "react";
import { Panel } from "@/components/ui/panel";
import { Button } from "@/components/ui/button";
import type { ReconciliationRun } from "@/types/reconciliation";
import styles from "./reconciliation.module.css";

interface Props {
  runStatus: ReconciliationRun | null;
  onTriggerRun?: () => Promise<void>;
}

export function RunStatusPanel({ runStatus, onTriggerRun }: Props) {
  const [running, setRunning] = useState(false);

  const handleRun = async () => {
    if (!onTriggerRun) return;
    setRunning(true);
    try {
      await onTriggerRun();
    } finally {
      setRunning(false);
    }
  };

  if (!runStatus) {
    return (
      <Panel>
        <div className={styles.statusPanelRow}>
          <p className={styles.statusPanelEmpty} style={{ margin: 0 }}>No reconciliation run data available.</p>
          {onTriggerRun && (
            <Button variant="primary" disabled={running} onClick={handleRun}>
              {running ? "Running..." : "Run Reconciliation"}
            </Button>
          )}
        </div>
      </Panel>
    );
  }

  const isCompleted = runStatus.status === "COMPLETED";
  const isProcessing = runStatus.status === "PROCESSING" || runStatus.status === "INGESTING";

  return (
    <Panel>
      <div className={styles.statusPanelRow}>
        <div>
          <p className={styles.statusPanelMeta}>
            Last run: {runStatus.completedAt ?? runStatus.startedAt}
          </p>
          <p className={styles.statusPanelState} style={{ color: isCompleted ? "var(--status-matched)" : "var(--status-warning)" }}>
            {runStatus.status}
          </p>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          <div className={styles.statusPanelMetric}>
            <p className={styles.statusPanelValue}>{runStatus.totalRows}</p>
            <p className={styles.statusPanelLabel}>Total Transactions</p>
          </div>
          {onTriggerRun && (
            <Button 
              variant="secondary" 
              disabled={running || isProcessing} 
              onClick={handleRun}
            >
              {running || isProcessing ? "Running..." : "Re-run Reconciliation"}
            </Button>
          )}
        </div>
      </div>
    </Panel>
  );
}
