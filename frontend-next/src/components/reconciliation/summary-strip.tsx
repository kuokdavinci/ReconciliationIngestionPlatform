import type { ReconciliationStats } from "@/types/reconciliation";
import styles from "./reconciliation.module.css";

interface Props {
  stats: ReconciliationStats | null;
}

export function SummaryStrip({ stats }: Props) {
  if (!stats) {
    return (
      <div className={styles.summaryGrid}>
        <div className={styles.summaryCard}>
          <span className={styles.summaryLabel}>Match Rate</span>
          <strong className={styles.summaryValue}>—</strong>
        </div>
      </div>
    );
  }

  return (
    <div className={styles.summaryGrid}>
      <div className={styles.summaryCard}>
        <span className={styles.summaryLabel}>Match Rate</span>
        <strong className={styles.summaryValue} style={{ color: stats.matchRate >= 90 ? "#10b981" : "#f59e0b" }}>
          {stats.matchRate.toFixed(1)}%
        </strong>
      </div>
      <div className={styles.summaryCard}>
        <span className={styles.summaryLabel}>Matched</span>
        <strong className={styles.summaryValue} style={{ color: "#10b981" }}>{stats.matched.toLocaleString()}</strong>
      </div>
      <div className={`${styles.summaryCard} ${styles.summaryCardWarm}`}>
        <span className={styles.summaryLabel}>Unmatched</span>
        <strong className={styles.summaryValue} style={{ color: "#f59e0b" }}>{stats.unmatched.toLocaleString()}</strong>
      </div>
      <div className={`${styles.summaryCard} ${styles.summaryCardDanger}`}>
        <span className={styles.summaryLabel}>Missing</span>
        <strong className={styles.summaryValue} style={{ color: "#ef4444" }}>{(stats.missingPartner + stats.missingInternal).toLocaleString()}</strong>
      </div>
    </div>
  );
}
