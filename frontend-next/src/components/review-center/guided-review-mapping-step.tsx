"use client";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import styles from "./review-center.module.css";

interface Props {
  aiMapping: any;
  aiMappingLoading: boolean;
  aiMappingError: string;
  sigHeaders: string[];
  sourceBackedMappings: any[];
  constantMappings: any[];
  fieldMappings: any[];
  isSavingMapping: boolean;
  onMappingChange: (sourceColumn: number, newPath: string) => void;
  onSaveMapping: () => void;
  onBack: () => void;
}

export function GuidedReviewMappingStep({
  aiMapping,
  aiMappingLoading,
  aiMappingError,
  sigHeaders,
  sourceBackedMappings,
  constantMappings,
  fieldMappings,
  isSavingMapping,
  onMappingChange,
  onSaveMapping,
  onBack,
}: Props) {
  return (
    <div className={styles.modalSection}>
      <div>
        <h4 className={styles.modalTitle}>Draft Mapping Review</h4>
        <p className={styles.introText}>Review the AI proposal and adjust the partner field mapping before runtime validation.</p>
      </div>

      {aiMappingLoading && (
        <div className={styles.loadingBlock}>
          <div className={styles.loadingSpinner} />
          <div className={styles.loadingText}>
            <h3>Generating Draft Mapping</h3>
            <p className={styles.introText}>Building partner-to-canonical field suggestions from the current sample rows...</p>
          </div>
        </div>
      )}

      {aiMappingError && (
        <div className={styles.emptyBlock}>
          <h3 style={{ color: "var(--status-failed)" }}>Draft Mapping Generation Failed</h3>
          <p className={styles.introText}>{aiMappingError}</p>
        </div>
      )}

      {!aiMappingLoading && !aiMappingError && aiMapping && (
        <>
          <div className={styles.metricGrid}>
            <div className={styles.metricCard}>
              <div className={styles.metricLabel}>Partner Columns Available</div>
              <div className={styles.metricValue}>{sigHeaders.length}</div>
              <p className={styles.introText} style={{ marginTop: 4 }}>Columns detected in the incoming partner file</p>
            </div>
            <div className={styles.metricCard}>
              <div className={styles.metricLabel}>Candidate Columns For Reconciliation</div>
              <div className={styles.metricValue}>{sourceBackedMappings.length}</div>
              <p className={styles.introText} style={{ marginTop: 4 }}>Columns currently selected from the partner file</p>
            </div>
          </div>

          <div className={styles.scopeCard} style={{ borderColor: "#10b981" }}>
            <div className={styles.scopeHeader}>
              <div>
                <div className={styles.scopeLabel} style={{ color: "#10b981" }}>Recommended mapping setup</div>
                <strong className={styles.scopeValue}>{fieldMappings.filter(m => m.path).length} canonical fields mapped</strong>
              </div>
              <Badge severity="low">Ready to review</Badge>
            </div>
            <p className={styles.scopeReason} style={{ color: "#fff", marginBottom: 12 }}>
              The current draft covers fields required for runtime processing. You can adjust the mappings below if needed.
            </p>
            {aiMapping.configHealth?.reasoning && (
              <div className={styles.scopeReasonBlock}>
                <strong className={styles.scopeReasonTitle}>Why this mapping is recommended</strong>
                <div className={styles.reasonItem}>{aiMapping.configHealth.reasoning}</div>
              </div>
            )}
          </div>

          {constantMappings.length > 0 && (
            <div className={styles.sectionCard}>
              <h5 className={styles.sectionCardTitle}>Runtime constants and rule-based values</h5>
              <div className={styles.constraintGrid}>
                {constantMappings.map((m: any, idx: number) => (
                  <div key={idx} className={styles.constraintCard}>
                    <div className={styles.constraintLabel}>{m.path}</div>
                    <div className={styles.constraintValue}>{m.constant || "Rule mapping"}</div>
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className={styles.sectionCard}>
            <h5 className={styles.sectionCardTitle}>AI Suggestion / Draft Mapping</h5>
            <table className={styles.fieldTable}>
              <thead>
                <tr>
                  <th>Partner Column</th>
                  <th>Populate Via</th>
                  <th>Canonical Field</th>
                </tr>
              </thead>
              <tbody>
                {sourceBackedMappings.map((m: any, idx: number) => {
                  const sourceCol = Number(m.column);
                  const headerLabel = sourceCol > 0 && sigHeaders[sourceCol - 1] ? sigHeaders[sourceCol - 1] : (m.sourceField || `Column ${sourceCol}`);
                  const populateVia = m.type === "CONSTANT" ? "Constant" : sourceCol > 0 ? `Source column ${sourceCol}` : "Source column";

                  return (
                    <tr key={idx}>
                      <td><code>{headerLabel}</code></td>
                      <td style={{ color: "var(--text-muted)" }}>{populateVia}</td>
                      <td>
                        <select
                          aria-label="Canonical field mapping"
                          value={m.path || ""}
                          onChange={(e) => onMappingChange(sourceCol, e.target.value)}
                          style={{
                            width: "100%",
                            background: "rgba(0,0,0,0.3)",
                            border: "1px solid #444",
                            color: "#fff",
                            borderRadius: "4px",
                            padding: "4px",
                            fontSize: "12px"
                          }}
                        >
                          <option value="">unmapped</option>
                          <option value="id">partner_txn_id</option>
                          <option value="amount">amount</option>
                          <option value="currency">currency</option>
                          <option value="status">status</option>
                          <option value="transDate">transaction_time</option>
                        </select>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          <div className={styles.actionRow} style={{ marginTop: 16 }}>
            <Button variant="secondary" onClick={onBack}>Back</Button>
            <div className={styles.actionGroup}>
              <Button variant="secondary" onClick={() => { window.open("/mapping-studio", "_blank"); }}>
                Open full Mapping Studio
              </Button>
              <Button variant="primary" disabled={isSavingMapping} onClick={onSaveMapping}>
                {isSavingMapping ? "Saving..." : "Save draft mapping"}
              </Button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
