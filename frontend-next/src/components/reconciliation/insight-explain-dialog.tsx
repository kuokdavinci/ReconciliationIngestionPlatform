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
      <div style={{ display: "flex", gap: 6, alignItems: "center", marginBottom: 16, flexWrap: "wrap" }}>
        <Badge severity={sevMap[item.severity] ?? "medium"}>{item.severity}</Badge>
        <Badge severity="neutral">{item.category}</Badge>
        <span style={{ fontSize: 12, color: "var(--text-muted)", marginLeft: "auto" }}>
          {item.affectedCount} records affected
          {item.confidence != null ? ` · ${item.confidence.toFixed(2)} confidence` : ""}
        </span>
      </div>

      <div style={{
        display: "grid",
        gridTemplateColumns: "1.6fr 1fr",
        gap: 20,
        alignItems: "start"
      }}>
        {/* Left Column: Analysis & Details */}
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <section className={styles.dialogSection} style={{ background: "rgba(255,255,255,0.015)", padding: 16, borderRadius: 10, border: "1px solid rgba(255,255,255,0.04)" }}>
            <strong className={styles.dialogHeading} style={{ fontSize: 12, textTransform: "uppercase", letterSpacing: "0.05em", color: "var(--text-muted)" }}>Analysis Summary</strong>
            <p style={{ margin: "8px 0 0", fontSize: 13.5, color: "#fff", lineHeight: 1.6 }}>{item.shortSummary}</p>
          </section>

          {item.likelyCause && (
            <section className={styles.dialogSection} style={{ background: "rgba(255,255,255,0.015)", padding: 16, borderRadius: 10, border: "1px solid rgba(255,255,255,0.04)" }}>
              <strong className={styles.dialogHeading} style={{ fontSize: 12, textTransform: "uppercase", letterSpacing: "0.05em", color: "var(--text-muted)" }}>Likely Cause</strong>
              <p style={{ margin: "8px 0 0", fontSize: 13.5, color: "rgba(255, 255, 255, 0.85)", lineHeight: 1.6 }}>{item.likelyCause}</p>
            </section>
          )}

          {Array.isArray(item.samples) && item.samples.length > 0 && (
            <section className={styles.dialogSection} style={{ background: "rgba(255,255,255,0.01)", padding: 16, borderRadius: 10, border: "1px solid rgba(255,255,255,0.03)" }}>
              <strong className={styles.dialogHeading} style={{ fontSize: 12, textTransform: "uppercase", letterSpacing: "0.05em", color: "var(--text-muted)", marginBottom: 8, display: "block" }}>Evidence Samples</strong>
              <div style={{ overflowX: "auto" }}>
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
                          <td key={`${item.id}-sample-${sampleIndex}-${key}`} style={{ fontSize: 12.5 }}>{String(value)}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}
        </div>

        {/* Right Column: Actions & Impact */}
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          {item.recommendation && (
            <section className={styles.dialogSection} style={{
              background: "rgba(16, 185, 129, 0.04)",
              border: "1px solid rgba(16, 185, 129, 0.15)",
              padding: 18,
              borderRadius: 12,
              boxShadow: "inset 0 1px 0 rgba(16, 185, 129, 0.1)"
            }}>
              <strong className={styles.dialogHeading} style={{ color: "#10b981", fontSize: 12, textTransform: "uppercase", letterSpacing: "0.05em" }}>Next Actions</strong>
              <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 8, fontSize: 13 }}>
                <div>
                  <div style={{ fontSize: 11, color: "#10b981", fontWeight: 700, textTransform: "uppercase" }}>Recommended Action</div>
                  <div style={{ color: "#fff", fontWeight: 600, marginTop: 2, lineHeight: 1.4 }}>{item.recommendation.action}</div>
                </div>
                {item.recommendation.priority && (
                  <div style={{ display: "flex", justifyContent: "space-between", borderTop: "1px solid rgba(255,255,255,0.04)", paddingTop: 6 }}>
                    <span style={{ color: "var(--text-muted)" }}>Priority</span>
                    <strong style={{ color: item.recommendation.priority.toLowerCase() === "high" ? "#f59e0b" : "#fff" }}>{item.recommendation.priority}</strong>
                  </div>
                )}
                {item.recommendation.owner && (
                  <div style={{ display: "flex", justifyContent: "space-between" }}>
                    <span style={{ color: "var(--text-muted)" }}>Owner</span>
                    <strong style={{ color: "#fff" }}>{item.recommendation.owner}</strong>
                  </div>
                )}
                {item.recommendation.why && (
                  <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 4, fontStyle: "italic", borderTop: "1px solid rgba(255,255,255,0.04)", paddingTop: 6 }}>
                    Why: {item.recommendation.why}
                  </div>
                )}
              </div>
            </section>
          )}

          {item.impact && (
            <section className={styles.dialogSection} style={{
              background: "rgba(239, 68, 68, 0.03)",
              border: "1px solid rgba(239, 68, 68, 0.1)",
              padding: 16,
              borderRadius: 12
            }}>
              <strong className={styles.dialogHeading} style={{ color: "#ef4444", fontSize: 12, textTransform: "uppercase", letterSpacing: "0.05em" }}>Impact Analysis</strong>
              <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 6, fontSize: 12.5 }}>
                {item.impact.currentImpact && (
                  <div>
                    <span style={{ color: "var(--text-muted)", display: "block" }}>Current Impact</span>
                    <strong style={{ color: "#fff" }}>{item.impact.currentImpact}</strong>
                  </div>
                )}
                {item.impact.potentialImpact && (
                  <div style={{ borderTop: "1px solid rgba(255,255,255,0.04)", paddingTop: 6, marginTop: 4 }}>
                    <span style={{ color: "var(--text-muted)", display: "block" }}>Potential Risk</span>
                    <strong style={{ color: "#fff" }}>{item.impact.potentialImpact}{item.impact.isEstimated ? " (estimate)" : ""}</strong>
                  </div>
                )}
              </div>
            </section>
          )}

          {item.evidence && Object.keys(item.evidence).length > 0 && (
            <section className={styles.dialogSection} style={{ background: "rgba(255,255,255,0.01)", padding: 14, borderRadius: 10, border: "1px solid rgba(255,255,255,0.03)", fontSize: 12.5 }}>
              <strong className={styles.dialogHeading} style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: "0.05em", color: "var(--text-muted)", marginBottom: 8, display: "block" }}>Observability Metadata</strong>
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                {Object.entries(item.evidence).map(([key, value]) => (
                  <div key={`${item.id}-${key}`} style={{ display: "flex", justifyContent: "space-between" }}>
                    <span style={{ color: "var(--text-muted)", textTransform: "capitalize" }}>{key.replace(/([A-Z])/g, ' $1')}</span>
                    <strong style={{ color: "#fff" }}>{String(value)}</strong>
                  </div>
                ))}
              </div>
            </section>
          )}
        </div>
      </div>

      <style jsx>{`
        @media (max-width: 980px) {
          div[style*="gridTemplateColumns"] {
            grid-template-columns: 1fr !important;
          }
        }
      `}</style>

      <div className={styles.footerButtons} style={{ marginTop: 24 }}>
        <Button variant="secondary" onClick={onClose}>Close</Button>
      </div>
    </Dialog>
  );
}
