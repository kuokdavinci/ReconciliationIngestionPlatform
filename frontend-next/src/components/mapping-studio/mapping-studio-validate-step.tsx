"use client";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import type { StudioWizardState } from "@/types/mapping";
import styles from "./mapping-studio.module.css";

interface Props {
  wizard: StudioWizardState;
  onRunTest: () => void;
  onRestoreVersion: (versionId: string) => void;
  onHandoff: () => void;
  onOpenReviewCenter: () => void;
  onBack: () => void;
}

export function MappingStudioValidateStep({
  wizard,
  onRunTest,
  onRestoreVersion,
  onHandoff,
  onOpenReviewCenter,
  onBack,
}: Props) {
  const score = wizard.validation?.score ?? 100;
  const scoreClass = score >= 90 ? "matched" : score >= 75 ? "warning" : "critical";
  const scoreLabel = score >= 90 ? "Excellent" : score >= 75 ? "Good" : "Review Needed";

  const errors = wizard.validation?.errors || [];
  const warnings = wizard.validation?.warnings || [];
  const passedChecks = [
    errors.some((e: string) => e.includes("required")) ? null : "Required fields are mapped for the canonical output.",
    warnings.some((w: string) => w.includes("multiple")) ? null : "Duplicate mapping check passed.",
    warnings.some((w: string) => w.includes("neither")) ? null : "Each field has either a source column or a constant.",
  ].filter(Boolean);

  const testOutputHtml = wizard.testOutput ? (
    <textarea readOnly className={styles.outputTextarea} value={JSON.stringify(wizard.testOutput, null, 2)} />
  ) : (
    <div style={{ padding: 24, textAlign: "center", color: "var(--text-muted)" }}>
      Click &quot;Run Transformation Test&quot; to verify output layout.
    </div>
  );

  return (
    <div>
      <h2 className={styles.studioTitle}>Validate & Prepare Review Handoff</h2>
      <p className={styles.studioSubtitle}>
        Resolve blocking issues, inspect warnings, test the transformed output, and then hand the draft to Review Center.
      </p>

      {wizard.draftMappingId && (
        <div className={styles.infoBanner}>
          <span style={{ color: "var(--brand-accent-blue)" }}>✅</span>
          <div style={{ fontSize: 13, color: "var(--text-primary)", flexGrow: 1 }}>
            This draft requires Review Center action before activation.
          </div>
          <div style={{ display: "flex", gap: 8, alignItems: "center", marginLeft: "auto" }}>
            <Badge severity="neutral">{wizard.configStatus || "PENDING_APPROVAL"}</Badge>
            <Button
              variant={wizard.handoffConfirmed ? "secondary" : "primary"}
              onClick={onHandoff}
              style={{ height: 32, padding: "0 12px", fontSize: 12 }}
            >
              {wizard.handoffConfirmed ? "Handoff Confirmed" : "Confirm Ready"}
            </Button>
            <Button
              variant="default"
              onClick={onOpenReviewCenter}
              style={{ height: 32, padding: "0 12px", fontSize: 12 }}
            >
              Open Review Center
            </Button>
          </div>
        </div>
      )}

      <div className={styles.validationGrid}>
        <div className={styles.validationCard}>
          <h3 style={{ margin: "0 0 16px 0", fontSize: 14, textTransform: "uppercase", letterSpacing: "0.05em", color: "var(--text-muted)" }}>
            Mapping Quality Score
          </h3>
          <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: 8 }}>
            <strong className={`${styles.scoreNumber} ${score < 75 ? styles.scoreLow : styles.scoreHigh}`}>
              {score}
            </strong>
            <span style={{ fontSize: 14, color: "var(--text-muted)" }}>/ 100</span>
          </div>
          <Badge severity={scoreClass === "critical" ? "critical" : scoreClass === "warning" ? "medium" : "low"}>{scoreLabel}</Badge>
          <div className={styles.validationGroup}>
            <div className={styles.validationGroupTitle}>Passed Checks</div>
            {passedChecks.length > 0 ? passedChecks.map((check, i) => (
              <div key={i} className={`${styles.validationItem} ${styles.matched}`}>
                <span>✓</span>
                <span>{check}</span>
              </div>
            )) : <div style={{ color: "var(--text-muted)" }}>None</div>}
          </div>
        </div>

        <div className={styles.validationCard}>
          <h3 style={{ margin: "0 0 16px 0", fontSize: 14, textTransform: "uppercase", letterSpacing: "0.05em", color: "var(--text-muted)" }}>
            Validation Results
          </h3>
          <div className={styles.validationGroup}>
            <div className={`${styles.validationGroupTitle} ${styles.critical}`}>Blocking Errors</div>
            {errors.length > 0 ? errors.map((err: string, i: number) => (
              <div key={i} className={`${styles.validationItem} ${styles.critical}`}>
                <span>✕</span>
                <span>{err}</span>
              </div>
            )) : <div style={{ color: "var(--text-muted)" }}>None</div>}
          </div>
          <div className={styles.validationGroup}>
            <div className={`${styles.validationGroupTitle} ${styles.warning}`}>Warnings</div>
            {warnings.length > 0 ? warnings.map((warn: string, i: number) => (
              <div key={i} className={`${styles.validationItem} ${styles.warning}`}>
                <span>⚠</span>
                <span>{warn}</span>
              </div>
            )) : <div style={{ color: "var(--text-muted)" }}>None</div>}
          </div>
        </div>

        <div className={styles.validationCard}>
          <h3 style={{ margin: "0 0 12px 0", fontSize: 14, textTransform: "uppercase", letterSpacing: "0.05em", color: "var(--text-muted)" }}>
            Schema Versions
          </h3>
          <div style={{ maxHeight: 160, overflowY: "auto", border: "1px solid var(--border)", borderRadius: 4 }}>
            {wizard.versions.length > 0 ? (
              <table className={styles.versionTable}>
                <thead>
                  <tr>
                    <th>Version</th>
                    <th>Published Date</th>
                    <th style={{ textAlign: "right" }}>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {wizard.versions.map((v: Record<string, unknown>, i: number) => (
                    <tr key={i}>
                      <td style={{ fontWeight: 700 }}>{(v.configVersion as string) || "latest"}</td>
                      <td style={{ color: "var(--text-muted)" }}>{v.publishedAt ? new Date(v.publishedAt as string).toLocaleString() : "N/A"}</td>
                      <td style={{ textAlign: "right" }}>
                        <Button variant="default" onClick={() => onRestoreVersion(v._id as string)} style={{ height: 26, padding: "0 10px", fontSize: 11 }}>
                          Restore
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <div style={{ padding: 10, textAlign: "center", color: "var(--text-muted)", fontSize: 12 }}>
                No previous versions.
              </div>
            )}
          </div>
        </div>
      </div>

      <div style={{ padding: 20, background: "var(--bg-surface)", border: "1px solid var(--border)", borderRadius: 8, marginBottom: 24 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
          <h3 style={{ margin: 0, fontSize: 15, fontWeight: 700, color: "#fff" }}>Test Mapping Transformation Result</h3>
          <Button variant="primary" onClick={onRunTest}>Run Transformation Test</Button>
        </div>
        {testOutputHtml}
      </div>

      <div style={{ display: "flex", gap: 12 }}>
        <Button variant="default" onClick={onBack}>Back to Step 2</Button>
        {!wizard.draftMappingId && (
          <Button variant="primary">Mark Ready for Review</Button>
        )}
      </div>
    </div>
  );
}
