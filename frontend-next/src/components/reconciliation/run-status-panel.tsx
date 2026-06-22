import { Panel } from "@/components/ui/panel";
import type { ReconciliationRun } from "@/types/reconciliation";
import styles from "./reconciliation.module.css";

interface Props {
  runStatus: ReconciliationRun | null;
}

export function RunStatusPanel({ runStatus }: Props) {
  if (!runStatus) {
    return (
      <Panel>
        <p className={styles.statusPanelEmpty}>No reconciliation run data available.</p>
      </Panel>
    );
  }

  const isCompleted = runStatus.status === "COMPLETED";
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
        <div className={styles.statusPanelMetric}>
          <p className={styles.statusPanelValue}>{runStatus.totalRows}</p>
          <p className={styles.statusPanelLabel}>Total Transactions</p>
        </div>
      </div>
    </Panel>
  );
}
