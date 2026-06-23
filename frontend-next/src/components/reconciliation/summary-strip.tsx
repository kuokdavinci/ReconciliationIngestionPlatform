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

  const hasDiscrepancy = stats.unmatched + stats.missingPartner + stats.missingInternal > 0;
  const reviewCount = stats.reviewedCount ?? 0;
  const totalReview = stats.totalReviewable ?? (stats.unmatched + stats.missingPartner + stats.missingInternal);
  const reviewRate = totalReview > 0 ? Math.round((reviewCount / totalReview) * 100) : 100;

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
      <div className={`${styles.summaryCard} ${reviewRate === 100 ? styles.summaryCardSuccess : styles.summaryCardDanger}`} style={{
        borderLeft: `3px solid ${reviewRate === 100 ? "#10b981" : "#ef4444"}`,
      }}>
        <span className={styles.summaryLabel}>Review Progress</span>
        <strong className={styles.summaryValue} style={{ color: reviewRate === 100 ? "#10b981" : "#ef4444" }}>
          {!hasDiscrepancy ? (
            "No reviews needed"
          ) : (
            `${reviewCount}/${totalReview} (${reviewRate}%)`
          )}
        </strong>
      </div>
    </div>
  );
}
