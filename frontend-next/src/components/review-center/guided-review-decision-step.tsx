"use client";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { PostApprovalRun } from "@/types/review-center";
import styles from "./review-center.module.css";

interface Props {
  postApprovalRun: PostApprovalRun | null;
  isApproved: boolean;
  validationState: any;
  isSubmitting: boolean;
  onApproveActivate: () => void;
  onReject: () => void;
  onBack: () => void;
  onClose: () => void;
}

export function GuidedReviewDecisionStep({
  postApprovalRun,
  isApproved,
  validationState,
  isSubmitting,
  onApproveActivate,
  onReject,
  onBack,
  onClose,
}: Props) {
  return (
    <div className={styles.modalSection}>
      <h4 className={styles.modalTitle}>Decision</h4>

      {!postApprovalRun && !isApproved && (
        <>
          <div className={styles.recommendPanel}>
            <strong className={styles.recommendLabel}>Decision summary</strong>
            <p className={styles.recommendText}>
              {validationState.canProceed
                ? "The latest draft mapping configuration is ready for approval. Approving will activate it, ingest the uploaded partner file, and run reconciliation."
                : "This packet still has validation issues. Please return to validation and ensure runtime mapping passes before approving."}
            </p>
          </div>

          <div className={styles.actionRow} style={{ marginTop: 16 }}>
            <Button variant="secondary" onClick={onBack}>Back</Button>
            <div className={styles.actionGroup}>
              <Button variant="secondary" disabled={isSubmitting} onClick={onReject}>
                Reject change
              </Button>
              <Button variant="primary" disabled={!validationState.canProceed || isSubmitting} onClick={onApproveActivate}>
                {isSubmitting ? "Processing..." : "Approve & Activate"}
              </Button>
            </div>
          </div>
        </>
      )}

      {(postApprovalRun || isApproved) && (
        <div className={styles.approveProgress}>
          <div className={styles.recommendPanel} style={{ background: "rgba(255, 255, 255, 0.02)", borderColor: "rgba(255, 255, 255, 0.08)" }}>
            <div style={{ display: "flex", justifyContent: "space-between", flexWrap: "wrap", gap: 12 }}>
              <div>
                <strong className={styles.recommendLabel} style={{ color: "var(--text-muted)", textTransform: "uppercase" }}>
                  Pipeline Status
                </strong>
                <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 4 }}>
                  <Badge severity={postApprovalRun?.status === "COMPLETED" ? "low" : postApprovalRun?.status === "FAILED" ? "critical" : "medium"}>
                    {postApprovalRun?.status || "QUEUED"}
                  </Badge>
                  {postApprovalRun?.stage && (
                    <Badge severity="neutral">
                      {postApprovalRun.stage.replace(/_/g, " ").toUpperCase()}
                    </Badge>
                  )}
                </div>
              </div>
              {postApprovalRun?.updatedAt && (
                <span className={styles.footerNote} style={{ fontSize: "11px" }}>
                  Updated: {new Date(postApprovalRun.updatedAt).toLocaleTimeString()}
                </span>
              )}
            </div>
            <div style={{ marginTop: 12, fontSize: "13px", color: "#fff" }}>
              {postApprovalRun?.message || "Post-approval background task has started."}
            </div>
          </div>

          <div className={styles.progressCard}>
            <div className={styles.progressHeader}>
              <div>
                <h5 className={styles.progressTitle}>Ingest Partner File</h5>
                <p className={styles.progressCopy}>Importing partner transactions into database.</p>
              </div>
              {postApprovalRun?.stage === "approval" ? (
                <Badge severity="neutral">Queued</Badge>
              ) : postApprovalRun?.stage === "ingestion" && postApprovalRun?.status !== "COMPLETED" && postApprovalRun?.status !== "FAILED" ? (
                <div className={styles.spinner} />
              ) : postApprovalRun?.status === "FAILED" && postApprovalRun?.stage === "ingestion" ? (
                <Badge severity="critical">Failed</Badge>
              ) : (
                <Badge severity="low">Done</Badge>
              )}
            </div>
          </div>

          <div className={styles.progressCard}>
            <div className={styles.progressHeader}>
              <div>
                <h5 className={styles.progressTitle}>Run Reconciliation</h5>
                <p className={styles.progressCopy}>Computing discrepancies and matching transactions.</p>
              </div>
              {postApprovalRun?.status === "COMPLETED" ? (
                <Badge severity="low">Done</Badge>
              ) : postApprovalRun?.status === "FAILED" && postApprovalRun?.stage === "reconciliation" ? (
                <Badge severity="critical">Failed</Badge>
              ) : postApprovalRun?.stage === "reconciliation" ? (
                <div className={styles.spinner} />
              ) : (
                <Badge severity="neutral">Queued</Badge>
              )}
            </div>
          </div>

          {postApprovalRun?.stats && Object.keys(postApprovalRun.stats).length > 0 && (
            <div className={styles.sectionCard}>
              <h5 className={styles.sectionCardTitle}>Processed Row Counts</h5>
              <div className={styles.metricGrid} style={{ gridTemplateColumns: "repeat(3, 1fr)" }}>
                <div className={styles.metricCard}>
                  <div className={styles.metricLabel} style={{ fontSize: "10px" }}>Total Rows</div>
                  <div className={styles.metricValue} style={{ fontSize: "20px" }}>{postApprovalRun.stats.totalRows ?? 0}</div>
                </div>
                <div className={styles.metricCard}>
                  <div className={styles.metricLabel} style={{ fontSize: "10px" }}>Success Rows</div>
                  <div className={styles.metricValue} style={{ fontSize: "20px", color: "#10b981" }}>{postApprovalRun.stats.successRows ?? 0}</div>
                </div>
                <div className={styles.metricCard}>
                  <div className={styles.metricLabel} style={{ fontSize: "10px" }}>Failed Rows</div>
                  <div className={styles.metricValue} style={{ fontSize: "20px", color: "#ef4444" }}>{postApprovalRun.stats.failedRows ?? 0}</div>
                </div>
              </div>
            </div>
          )}

          <div className={styles.actionRow} style={{ justifyContent: "center", marginTop: 12 }}>
            {postApprovalRun?.status === "FAILED" ? (
              <Button variant="secondary" onClick={onBack}>Return to Step 3</Button>
            ) : (
              <Button variant="secondary" onClick={onClose}>
                {postApprovalRun?.status === "COMPLETED" ? "Close" : "Close and Keep Processing in Background"}
              </Button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
