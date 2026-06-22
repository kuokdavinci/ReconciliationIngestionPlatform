"use client";

import { Dialog } from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { InsightItem } from "@/types/reconciliation";
import dialogStyles from "@/components/ui/dialog.module.css";
import styles from "./reconciliation.module.css";

interface Props {
  item: InsightItem | null;
  open: boolean;
  onClose: () => void;
}

const sevMap: Record<string, "low" | "medium" | "high" | "critical"> = {
  LOW: "low",
  MEDIUM: "medium",
  HIGH: "high",
  CRITICAL: "critical",
};

export function InsightExplainDialog({ item, open, onClose }: Props) {
  if (!item) return null;

  return (
    <Dialog open={open} onClose={onClose} title={item.title} panelClassName={dialogStyles.wide}>
      <div className={styles.dialogGrid}>
        <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
          <Badge severity={sevMap[item.severity] ?? "medium"}>{item.severity}</Badge>
          <Badge severity="neutral">{item.category}</Badge>
          <span style={{ fontSize: 12, color: "var(--text-muted)", marginLeft: "auto" }}>
            {item.affectedCount} records affected
            {item.confidence != null ? ` · ${item.confidence.toFixed(2)} confidence` : ""}
          </span>
        </div>

        <section className={styles.dialogSection}>
          <strong className={styles.dialogHeading}>Summary</strong>
          <p style={{ margin: 0, fontSize: 13, color: "var(--text-muted)", lineHeight: 1.5 }}>{item.shortSummary}</p>
        </section>

        {item.evidence && (
          <section className={styles.dialogSection}>
            <strong className={styles.dialogHeading}>Evidence</strong>
            <div className={styles.evidenceGrid}>
              {Object.entries(item.evidence).map(([key, value]) => (
                <div key={`${item.id}-${key}`}>
                  {key}: <strong style={{ color: "#fff" }}>{String(value)}</strong>
                </div>
              ))}
            </div>
          </section>
        )}

        {item.likelyCause && (
          <section className={styles.dialogSection}>
            <strong className={styles.dialogHeading}>Likely cause</strong>
            <p style={{ margin: 0, fontSize: 13, color: "var(--text-muted)", lineHeight: 1.5 }}>{item.likelyCause}</p>
          </section>
        )}

        {item.recommendation && (
          <section className={styles.dialogSection}>
            <strong className={styles.dialogHeading}>Recommended action</strong>
            <div className={styles.evidenceGrid}>
              <div>Action: <strong style={{ color: "#fff" }}>{item.recommendation.action}</strong></div>
              {item.recommendation.why && <div>Why: <strong style={{ color: "#fff" }}>{item.recommendation.why}</strong></div>}
              {item.recommendation.owner && <div>Owner: <strong style={{ color: "#fff" }}>{item.recommendation.owner}</strong></div>}
              {item.recommendation.priority && <div>Priority: <strong style={{ color: "#fff" }}>{item.recommendation.priority}</strong></div>}
              {item.recommendation.expectedOutcome && <div>Expected outcome: <strong style={{ color: "#fff" }}>{item.recommendation.expectedOutcome}</strong></div>}
            </div>
          </section>
        )}

        {item.impact && (
          <section className={styles.dialogSection}>
            <strong className={styles.dialogHeading}>Impact</strong>
            <div className={styles.evidenceGrid}>
              {item.impact.currentImpact && <div>Current impact: <strong style={{ color: "#fff" }}>{item.impact.currentImpact}</strong></div>}
              {item.impact.potentialImpact && <div>Potential impact: <strong style={{ color: "#fff" }}>{item.impact.potentialImpact}{item.impact.isEstimated ? " (estimate)" : ""}</strong></div>}
            </div>
          </section>
        )}

        {Array.isArray(item.samples) && item.samples.length > 0 && (
          <section className={styles.dialogSection}>
            <strong className={styles.dialogHeading}>Evidence samples</strong>
            <table className={styles.samplesTable}>
              <thead>
                <tr>
                  {Object.keys(item.samples[0]).map((key) => (
                    <th key={key}>{key}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {item.samples.slice(0, 3).map((sample, sampleIndex) => (
                  <tr key={`${item.id}-sample-${sampleIndex}`}>
                    {Object.entries(sample).map(([key, value]) => (
                      <td key={`${item.id}-sample-${sampleIndex}-${key}`}>{String(value)}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        )}
      </div>

      <div className={styles.footerButtons}>
        <Button variant="secondary">View records</Button>
        <Button variant="secondary" onClick={onClose}>Close</Button>
      </div>
    </Dialog>
  );
}
