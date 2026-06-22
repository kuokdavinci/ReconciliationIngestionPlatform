"use client";

import type { InsightItem } from "@/types/reconciliation";
import { Badge } from "@/components/ui/badge";
import styles from "./reconciliation.module.css";

const sevMap: Record<string, "low" | "medium" | "high" | "critical"> = {
  LOW: "low",
  MEDIUM: "medium",
  HIGH: "high",
  CRITICAL: "critical",
};

interface Props {
  title: string;
  items: InsightItem[] | null;
  onExplain: (item: InsightItem) => void;
}

export function InsightGrid({ title, items, onExplain }: Props) {
  if (!items || items.length === 0) {
    return (
      <div className={styles.insightColumn}>
        <div className={styles.insightEmpty}>
          <div className={styles.insightColumnTitle}>{title}</div>
          <div style={{ marginTop: "auto", color: "var(--text-muted)", fontSize: 13 }}>No notable signals.</div>
        </div>
      </div>
    );
  }

  return (
    <div className={styles.insightColumn}>
      <div className={styles.insightCards}>
        {items.slice(0, 2).map((item, index) => (
          <div key={item.id} className={styles.insightCard} onClick={() => onExplain(item)}>
            {index === 0 && (
              <div className={styles.insightColumnTitle}>{title}</div>
            )}
            <div className={styles.insightHeader}>
              <div className={styles.insightHeaderLeft}>
                <Badge severity={sevMap[item.severity] ?? "medium"}>{item.severity}</Badge>
                <strong className={styles.insightTitle}>{item.title}</strong>
              </div>
              <span className={styles.insightCount}>{item.affectedCount} affected</span>
            </div>
            <div className={styles.insightMetrics}>
              {(item.metrics ?? []).slice(0, 3).map((metric, idx) => (
                <span key={`${item.id}-${metric.label}-${idx}`} className={styles.insightMetric}>
                  <strong>{metric.value}</strong>{metric.label ? ` ${metric.label}` : ""}
                </span>
              ))}
            </div>
            <p className={styles.insightSummary}>{item.shortSummary}</p>
            <div className={styles.insightActions}>
              <span className={styles.insightMeta}>{item.partner ?? item.category}</span>
              <span className={styles.insightAction}>Explain</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
