"use client";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { ReviewPacket } from "@/types/review-center";
import { summarizeReviewPacket } from "@/lib/state/review-summary";
import styles from "./review-center.module.css";

interface Props {
  packet: ReviewPacket | null;
  onOpenReview: () => void;
}

const gateStatusSeverity: Record<string, "low" | "medium" | "high" | "critical"> = {
  pass: "low",
  warn: "medium",
  fail: "critical",
};

function formatBusinessDate(value?: string) {
  if (!value) return "-";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value.slice(0, 10);
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Ho_Chi_Minh",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(parsed);
}

export function ReviewSummaryDrawer({ packet, onOpenReview }: Props) {
  if (!packet) {
    return (
      <div className={styles.emptyBlock}>
        <p>Select a pending item to view its review summary.</p>
      </div>
    );
  }

  const summary = summarizeReviewPacket(packet);
  const riskSev = packet.riskSummary?.severity ?? "medium";
  const isBatchFatal = packet.qualityGateStatus === "FAIL";
  const batchFatalCodes = packet.qualityGateSummary?.errorCodes?.join(" · ") || "BATCH_FATAL";
  const sevMap: Record<string, "low" | "medium" | "high" | "critical"> = {
    low: "low", medium: "medium", high: "high", critical: "critical",
  };

  return (
    <div>
      <div className={styles.summaryBadges}>
        {isBatchFatal && <Badge severity="critical">BATCH FATAL</Badge>}
        <Badge severity={sevMap[riskSev]}>{riskSev.toUpperCase()} RISK</Badge>
        {summary.runtimeValidated
          ? <Badge severity="low">Runtime validated</Badge>
          : <Badge severity="medium">Runtime validate pending</Badge>}
      </div>

      <h3 className={styles.summaryTitle}>
        {packet.isVirtual ? "Draft mapping update" : "Format verification required"}
      </h3>
      <p className={styles.summaryReason}>
        {packet.recommendedAction?.reason ?? "Awaiting reviewer decision."}
      </p>

      <div className={styles.summaryStack}>
        <div className={styles.recommendPanel}>
          <strong className={styles.recommendLabel}>Recommended next step</strong>
          <p className={styles.recommendText}>
            {summary.readyToActivate
              ? "Validation is clean enough to activate the draft and continue runtime processing."
              : "Review the validation gates and mapping readiness before activating the next runtime."}
          </p>
        </div>
        <div className={styles.metaGrid}>
          <div className={styles.metaRow}>
            <strong className={styles.metaLabel}>File:</strong>
            <span className={styles.metaValue}>{packet.fileName}</span>
          </div>
          <div className={styles.metaRow}>
            <strong className={styles.metaLabel}>Runtime:</strong>
            <span className={styles.metaValue}>
              {packet.activeRuntimeConfigId ? "Current runtime available" : "No active runtime"}
            </span>
          </div>
          <div className={styles.metaRow}>
            <strong className={styles.metaLabel}>Draft mapping:</strong>
            <span className={styles.metaValue}>
              {summary.mappingReady ? "Ready" : "Missing"}
            </span>
          </div>
          <div className={styles.metaRow}>
            <strong className={styles.metaLabel}>Reconciliation date:</strong>
            <span className={styles.metaValue}>
              {formatBusinessDate(packet.reconciliationDate)}
            </span>
          </div>
        </div>
      </div>

      {isBatchFatal && (
        <div className={`${styles.recommendPanel} ${styles.validationFailed}`}>
          <strong className={styles.recommendLabel}>Batch processing stopped</strong>
          <p className={styles.recommendText}>
            The file quality gate failed before row-level quarantine and reconciliation. No quarantine records were created.
          </p>
          <div className={styles.metaGrid}>
            <div className={styles.metaRow}>
              <strong className={styles.metaLabel}>Outcome:</strong>
              <span className={styles.metaValue}>BATCH_FATAL</span>
            </div>
            <div className={styles.metaRow}>
              <strong className={styles.metaLabel}>Error codes:</strong>
              <span className={styles.metaValue}>{batchFatalCodes}</span>
            </div>
            <div className={styles.metaRow}>
              <strong className={styles.metaLabel}>Failed rows:</strong>
              <span className={styles.metaValue}>{packet.qualityGateSummary?.failedRows ?? 0}</span>
            </div>
          </div>
        </div>
      )}

      {/* Validation gates */}
      {packet.validationGates.length > 0 && (
        <div className={styles.gateList}>
          <h4 className={styles.gateTitle}>Validation Gates</h4>
          {packet.validationGates.map((gate) => (
            <div key={gate.gateKey} className={styles.gateRow}>
              <div className={styles.gateCopy}>
                <strong className={styles.gateLabel}>{gate.label}</strong>
                {gate.message && <span className={styles.gateMessage}>{gate.message}</span>}
              </div>
              <Badge severity={gateStatusSeverity[gate.status] ?? "medium"}>{gate.status}</Badge>
            </div>
          ))}
        </div>
      )}

      <div className={styles.ctaStack}>
        <Button variant="primary" className={styles.fullButton} style={{ height: 44, fontWeight: 800 }} onClick={onOpenReview}>
          {isBatchFatal ? "View batch failure" : "Open Review"}
        </Button>
        <Button variant="secondary" className={styles.fullButton}>
          Open Mapping Studio
        </Button>
      </div>
    </div>
  );
}
