"use client";

import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { ReviewPacket } from "@/types/review-center";
import styles from "./review-center.module.css";

export interface ScopeClassificationInfo {
  recommendedScope?: string;
  suggestedScope?: string;
  confidence?: number;
  reasons?: string[];
  explanation?: string;
  reasoning?: string;
  probabilities?: Record<string, number>;
  internalDbRecordCount?: number;
  internalPreview?: Array<{
    id: string;
    partnerTxnId: string;
    amount: string;
    currency: string;
    status: string;
    transactionTime: string;
  }>;
  receivedRecordCount?: number;
}

interface Props {
  localPacket: ReviewPacket | null;
  scopeClassification: ScopeClassificationInfo | null;
  scopeLoading: boolean;
  scopeError: string;
  selectedScope: string;
  isSavingScope: boolean;
  onScopeChange: (scope: string) => void;
  onContinue: () => void;
  onCancel: () => void;
  onRetry: () => void;
}

export function GuidedReviewScopeStep({
  localPacket,
  scopeClassification,
  scopeLoading,
  scopeError,
  selectedScope,
  isSavingScope,
  onScopeChange,
  onContinue,
  onCancel,
  onRetry,
}: Props) {
  const [partnerExpanded, setPartnerExpanded] = useState(false);
  const [internalExpanded, setInternalExpanded] = useState(false);
  if (!localPacket) return null;

  const scopeConfidence = Math.round((scopeClassification?.probabilities?.[selectedScope] ?? 0) * 100);
  const scopeBorderColor = scopeConfidence >= 85 ? "#10b981" : scopeConfidence >= 60 ? "#f59e0b" : "#ef4444";
  const scopeBgColor = scopeConfidence >= 85 ? "rgba(16, 185, 129, 0.1)" : scopeConfidence >= 60 ? "rgba(245, 158, 11, 0.1)" : "rgba(239, 68, 68, 0.1)";
  const scopeLabelColor = scopeConfidence >= 85 ? "#10b981" : scopeConfidence >= 60 ? "#f59e0b" : "#ef4444";
  const partnerPreview = (localPacket.samplePreview ?? []).slice(0, 5);
  const internalPreview = (scopeClassification?.internalPreview ?? []).slice(0, 5);
  const partnerColumns = Array.from(new Set(partnerPreview.flatMap((row) => Object.keys(row.values))));

  return (
    <div className={styles.modalSection}>
      <h4 className={styles.modalTitle}>Confirm file scope</h4>

      {scopeLoading && (
        <div className={styles.loadingBlock}>
          <div className={styles.loadingSpinner} />
          <div className={styles.loadingText}>
            <h3>Running Scope Analysis</h3>
            <p className={styles.introText}>Analyzing file name hints, row-count gap, and same-day internal volume...</p>
          </div>
        </div>
      )}

      {scopeError && (
        <div className={styles.emptyBlock}>
          <h3 style={{ color: "var(--status-failed)" }}>Scope Analysis Failed</h3>
          <p className={styles.introText}>{scopeError}</p>
          <Button style={{ marginTop: 16 }} onClick={onRetry}>Retry</Button>
        </div>
      )}

      {!scopeLoading && !scopeError && scopeClassification && (
        <>
          <div className={styles.metricGrid}>
            <div className={styles.metricCard}>
              <div className={styles.metricLabel}>Internal DB Records</div>
              <div className={styles.metricValue}>{scopeClassification.internalDbRecordCount}</div>
              <p className={styles.introText} style={{ marginTop: 4 }}>Transactions stored in system for same day</p>
            </div>
            <div className={styles.metricCard}>
              <div className={styles.metricLabel}>Received Records</div>
              <div className={styles.metricValue}>{scopeClassification.receivedRecordCount}</div>
              <p className={styles.introText} style={{ marginTop: 4 }}>Records read from the uploaded file</p>
            </div>
          </div>

          {partnerPreview.length > 0 && (
            <section className={styles.sectionCard} style={{ marginTop: 16 }}>
              <div className={styles.sectionCardHeading}>
                <div>
                  <h5 className={styles.sectionCardTitle}>Partner file evidence</h5>
                  <p className={styles.sectionCardCopy}>
                    {partnerPreview.length} sample rows are attached to this packet. Expand to preview the partner data.
                  </p>
                </div>
                <button
                  type="button"
                  className={styles.iconButton}
                  aria-label={partnerExpanded ? "Hide partner file evidence" : "Show partner file evidence"}
                  aria-expanded={partnerExpanded}
                  onClick={() => setPartnerExpanded((expanded) => !expanded)}
                >
                  <svg aria-hidden="true" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                    {partnerExpanded ? (
                      <>
                        <path d="M2.5 12s3.5-6 9.5-6 9.5 6 9.5 6-3.5 6-9.5 6-9.5-6-9.5-6Z" />
                        <circle cx="12" cy="12" r="2.5" />
                      </>
                    ) : (
                      <>
                        <path d="M3 3l18 18" />
                        <path d="M10.6 5.2A10.4 10.4 0 0 1 12 5c6 0 9.5 7 9.5 7a17 17 0 0 1-3.1 3.8" />
                        <path d="M6.2 6.3C3.9 8 2.5 12 2.5 12s3.5 7 9.5 7a9.8 9.8 0 0 0 3.4-.6" />
                      </>
                    )}
                  </svg>
                </button>
              </div>
              {partnerExpanded && (
                <div style={{ overflowX: "auto" }}>
                  <table className={styles.fieldTable}>
                    <thead>
                      <tr>
                        <th>Row</th>
                        {partnerColumns.map((column) => <th key={column}>{column}</th>)}
                      </tr>
                    </thead>
                    <tbody>
                      {partnerPreview.map((row) => (
                        <tr key={row.id}>
                          <td>{row.id}</td>
                          {partnerColumns.map((column) => (
                            <td key={column}>{row.values[column] == null || row.values[column] === "" ? "-" : String(row.values[column])}</td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          )}

          {internalPreview.length > 0 && (
            <section className={styles.sectionCard} style={{ marginTop: 16 }}>
              <div className={styles.sectionCardHeading}>
                <div>
                  <h5 className={styles.sectionCardTitle}>Internal DB evidence</h5>
                  <p className={styles.sectionCardCopy}>
                    {internalPreview.length} sample rows from {scopeClassification.internalDbRecordCount ?? 0} internal transactions for the business date. Expand to preview the internal data.
                  </p>
                </div>
                <button
                  type="button"
                  className={styles.iconButton}
                  aria-label={internalExpanded ? "Hide internal DB evidence" : "Show internal DB evidence"}
                  aria-expanded={internalExpanded}
                  onClick={() => setInternalExpanded((expanded) => !expanded)}
                >
                  <svg aria-hidden="true" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                    {internalExpanded ? (
                      <>
                        <path d="M2.5 12s3.5-6 9.5-6 9.5 6 9.5 6-3.5 6-9.5 6-9.5-6-9.5-6Z" />
                        <circle cx="12" cy="12" r="2.5" />
                      </>
                    ) : (
                      <>
                        <path d="M3 3l18 18" />
                        <path d="M10.6 5.2A10.4 10.4 0 0 1 12 5c6 0 9.5 7 9.5 7a17 17 0 0 1-3.1 3.8" />
                        <path d="M6.2 6.3C3.9 8 2.5 12 2.5 12s3.5 7 9.5 7a9.8 9.8 0 0 0 3.4-.6" />
                      </>
                    )}
                  </svg>
                </button>
              </div>
              {internalExpanded && (
                <div style={{ overflowX: "auto" }}>
                  <table className={styles.fieldTable}>
                    <thead>
                      <tr><th>Partner transaction</th><th>Amount</th><th>Status</th><th>Transaction time</th></tr>
                    </thead>
                    <tbody>
                      {internalPreview.map((row) => (
                        <tr key={row.id || row.partnerTxnId}>
                          <td>{row.partnerTxnId || "-"}</td>
                          <td>{row.amount} {row.currency}</td>
                          <td>{row.status || "-"}</td>
                          <td>{row.transactionTime || "-"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          )}

          <div className={styles.scopeCard} style={{ borderColor: scopeBorderColor, backgroundColor: scopeBgColor }}>
            <div className={styles.scopeHeader}>
              <div>
                <div className={styles.scopeLabel} style={{ color: scopeLabelColor }}>
                  {selectedScope === scopeClassification?.suggestedScope ? "Recommended file scope" : "Selected file scope"}
                </div>
                <strong className={styles.scopeValue}>{selectedScope.replace(/_/g, " ")}</strong>
              </div>
              <Badge severity={scopeConfidence >= 85 ? "low" : scopeConfidence >= 60 ? "medium" : "critical"}>
                {scopeConfidence}% confidence
              </Badge>
            </div>
            <p className={styles.scopeReason} style={{ fontWeight: 600, color: "#fff", marginBottom: 12 }}>
              {selectedScope === "FULL_SNAPSHOT" && "File covers the full day, so the safest action is to replace the existing day snapshot with the uploaded partner file."}
              {selectedScope === "INCREMENTAL_APPEND" && "File looks like a delta feed, so new rows should be appended without wiping previously ingested data."}
              {selectedScope === "REPLACEMENT" && "File appears to contain correction/update rows, so matching records should be updated instead of appended."}
            </p>
            <div className={styles.scopeReasonBlock}>
              <strong className={styles.scopeReasonTitle}>Why this option was selected</strong>
              <div className={styles.reasonItem}>{scopeClassification.reasoning}</div>
            </div>
          </div>

          <div className={styles.scopeOptionGrid}>
            {[
              { value: "FULL_SNAPSHOT", label: "Full Snapshot", desc: "Overwrite the day snapshot with the uploaded file." },
              { value: "INCREMENTAL_APPEND", label: "Incremental Append", desc: "Append new partner rows without wiping prior data." },
              { value: "REPLACEMENT", label: "Replacement", desc: "Update matching rows when this file is a correction batch." }
            ].map((opt) => (
              <button
                key={opt.value}
                type="button"
                onClick={() => onScopeChange(opt.value)}
                className={`${styles.scopeOptionCard} ${selectedScope === opt.value ? styles.scopeOptionSelected : ""}`}
              >
                <strong className={styles.scopeOptionTitle}>{opt.label}</strong>
                <span className={styles.scopeOptionText}>{opt.desc}</span>
              </button>
            ))}
          </div>

          <div className={styles.actionRow} style={{ marginTop: 16 }}>
            <Button variant="secondary" onClick={onCancel}>Cancel</Button>
            <Button variant="primary" disabled={isSavingScope} onClick={onContinue}>
              {isSavingScope ? "Saving..." : "Continue"}
            </Button>
          </div>
        </>
      )}
    </div>
  );
}
