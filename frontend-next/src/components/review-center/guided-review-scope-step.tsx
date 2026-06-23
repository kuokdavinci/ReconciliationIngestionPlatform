"use client";

import * as api from "@/lib/api/review-center";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { ReviewPacket } from "@/types/review-center";
import styles from "./review-center.module.css";

interface Props {
  localPacket: ReviewPacket | null;
  scopeClassification: any;
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
  if (!localPacket) return null;

  const scopeConfidence = Math.round((scopeClassification?.probabilities?.[selectedScope] ?? 0) * 100);
  const scopeBorderColor = scopeConfidence >= 85 ? "#10b981" : scopeConfidence >= 60 ? "#f59e0b" : "#ef4444";
  const scopeBgColor = scopeConfidence >= 85 ? "rgba(16, 185, 129, 0.1)" : scopeConfidence >= 60 ? "rgba(245, 158, 11, 0.1)" : "rgba(239, 68, 68, 0.1)";
  const scopeLabelColor = scopeConfidence >= 85 ? "#10b981" : scopeConfidence >= 60 ? "#f59e0b" : "#ef4444";

  return (
    <div className={styles.modalSection}>
      <h4 className={styles.modalTitle}>Confirm file scope</h4>

      {scopeLoading && (
        <div className={styles.loadingBlock}>
          <div className={styles.loadingSpinner} />
          <div className={styles.loadingText}>
            <h3>Running LLM Scope Analysis</h3>
            <p className={styles.introText}>Analyzing file name hints, received record counts, and database status...</p>
          </div>
        </div>
      )}

      {scopeError && (
        <div className={styles.emptyBlock}>
          <h3 style={{ color: "var(--status-failed)" }}>LLM Scope Analysis Failed</h3>
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
