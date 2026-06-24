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
  const stageOrder = ["approval", "ingestion", "reconciliation", "cache_invalidation"] as const;
  const currentStageIndex = postApprovalRun?.stage ? stageOrder.indexOf(postApprovalRun.stage) : -1;
  const stageItems = [
    {
      key: "approval",
      title: "Approve Mapping",
      description: "Persisting the operator decision and scheduling background processing.",
    },
    {
      key: "ingestion",
      title: "Ingest Partner File",
      description: "Importing partner transactions into database.",
    },
    {
      key: "reconciliation",
      title: "Run Reconciliation",
      description: "Computing discrepancies and matching transactions.",
    },
    {
      key: "cache_invalidation",
      title: "Refresh Insight Cache",
      description: "Publishing updated results and insight views.",
    },
  ] as const;

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

          {stageItems.map((item, index) => {
            const isCurrent = postApprovalRun?.stage === item.key && postApprovalRun?.status !== "COMPLETED" && postApprovalRun?.status !== "FAILED";
            const isDone = postApprovalRun?.status === "COMPLETED" || (currentStageIndex >= 0 && index < currentStageIndex);
            const isFailed = postApprovalRun?.status === "FAILED" && postApprovalRun?.stage === item.key;

            return (
              <div key={item.key} className={styles.progressCard}>
                <div className={styles.progressHeader}>
                  <div>
                    <h5 className={styles.progressTitle}>{item.title}</h5>
                    <p className={styles.progressCopy}>{item.description}</p>
                  </div>
                  {isFailed ? (
                    <Badge severity="critical">Failed</Badge>
                  ) : isCurrent ? (
                    <div className={styles.spinner} />
                  ) : isDone ? (
                    <Badge severity="low">Done</Badge>
                  ) : (
                    <Badge severity="neutral">Queued</Badge>
                  )}
                </div>
              </div>
            );
          })}

          {postApprovalRun?.stats && Object.keys(postApprovalRun.stats).length > 0 && (
            <div className={styles.sectionCard}>
              <h5 className={styles.sectionCardTitle}>Processed Row Counts</h5>
              <div className={styles.metricGrid} style={{ gridTemplateColumns: "repeat(5, 1fr)" }}>
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
                <div className={styles.metricCard}>
                  <div className={styles.metricLabel} style={{ fontSize: "10px" }}>Recon Results</div>
                  <div className={styles.metricValue} style={{ fontSize: "20px" }}>{postApprovalRun.stats.resultCount ?? 0}</div>
                </div>
                <div className={styles.metricCard}>
                  <div className={styles.metricLabel} style={{ fontSize: "10px" }}>Recon Count</div>
                  <div className={styles.metricValue} style={{ fontSize: "20px" }}>{postApprovalRun.stats.reconciliationCount ?? postApprovalRun.reconciliationCount ?? 0}</div>
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
