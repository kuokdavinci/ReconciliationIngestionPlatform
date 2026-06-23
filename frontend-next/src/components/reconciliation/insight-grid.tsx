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

const sevColor: Record<string, { border: string; bg: string; label: string }> = {
  CRITICAL: { border: "#ef4444", bg: "rgba(239, 68, 68, 0.1)", label: "#ef4444" },
  HIGH: { border: "#f97316", bg: "rgba(249, 115, 22, 0.1)", label: "#f97316" },
  MEDIUM: { border: "#f59e0b", bg: "rgba(245, 158, 11, 0.1)", label: "#f59e0b" },
  LOW: { border: "#10b981", bg: "rgba(16, 185, 129, 0.1)", label: "#10b981" },
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
        {items.slice(0, 2).map((item, index) => {
          const color = sevColor[item.severity] ?? sevColor.MEDIUM;
          return (
            <div
              key={item.id}
              className={styles.insightCard}
              onClick={() => onExplain(item)}
              style={{ borderColor: color.border, background: color.bg }}
            >
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
          );
        })}
      </div>
    </div>
  );
}
