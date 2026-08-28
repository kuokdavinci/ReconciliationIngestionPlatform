"use client";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { PostApprovalRun, ValidationStateSummary } from "@/types/review-center";
import type { BackfillRun } from "@/types/schedules";
import styles from "./review-center.module.css";

interface Props {
  postApprovalRun: PostApprovalRun | null;
  backfillRun: BackfillRun | null;
  backfillError?: string | null;
  isApproved: boolean;
  validationState: ValidationStateSummary | null;
  isSubmitting: boolean;
  onApproveActivate: () => void;
  onReject: () => void;
  onBack: () => void;
  onClose: () => void;
  onOpenQuarantine: (params: { packetId: string; postApprovalRunId?: string }) => void;
}

export function GuidedReviewDecisionStep({
  postApprovalRun,
  backfillRun,
  backfillError,
  isApproved,
  validationState,
  isSubmitting,
  onApproveActivate,
  onReject,
  onBack,
  onClose,
  onOpenQuarantine,
}: Props) {
  const isBatchFatal = postApprovalRun?.qualityGateStatus === "FAIL";
  const batchFatalCodes = postApprovalRun?.qualityGateSummary?.errorCodes?.join(" · ") || "BATCH_FATAL";
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
        description: "Reading, normalizing, validating, and persisting partner transactions safely.",
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
  const backfillSeverity = backfillRun?.status === "COMPLETED"
    ? "low" as const
    : backfillRun?.status === "FAILED"
      ? "critical" as const
      : "medium" as const;

  return (
    <div className={styles.modalSection}>
      <h4 className={styles.modalTitle}>Decision</h4>

      {!postApprovalRun && !isApproved && (
        <>
          <div className={styles.recommendPanel}>
            <strong className={styles.recommendLabel}>Decision summary</strong>
            <p className={styles.recommendText}>
              {validationState?.canProceed
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
              <Button variant="primary" disabled={!validationState?.canProceed || isSubmitting} onClick={onApproveActivate}>
                {isSubmitting ? "Processing..." : "Approve & Activate"}
              </Button>
            </div>
          </div>
        </>
      )}

      {backfillRun && (
        <div className={styles.approveProgress}>
          <div className={styles.recommendPanel}>
            <div className={styles.sectionCardHeading}>
              <div>
                <span className={styles.metricEyebrow}>Ordered backfill</span>
                <h5 className={styles.sectionCardTitle}>{backfillRun.partner} · daily runtime detail</h5>
                <p className={styles.sectionCardCopy}>
                  Airflow is processing each business date sequentially. The next day starts only after the previous day completes.
                </p>
              </div>
              <Badge severity={backfillSeverity}>{backfillRun.status}</Badge>
            </div>
            <div className={styles.metricGrid}>
              <div className={styles.metricCard}>
                <div className={styles.metricLabel}>Completed days</div>
                <div className={styles.metricValue}>{backfillRun.completedDays}/{backfillRun.totalDays}</div>
                <div className={styles.metricHint}>{backfillRun.fromDate} → {backfillRun.toDate}</div>
              </div>
              <div className={styles.metricCard}>
                <div className={styles.metricLabel}>Current date</div>
                <div className={styles.metricValue} style={{ fontSize: 18 }}>{backfillRun.currentDate || "-"}</div>
                <div className={styles.metricHint}>business date in progress</div>
              </div>
            </div>
          </div>

          {backfillError && <div className={styles.validationFailed}>{backfillError}</div>}
          <div className={styles.progressCard}>
            <div className={styles.sectionCardHeading}>
              <div>
                <h5 className={styles.sectionCardTitle}>Daily execution</h5>
                <p className={styles.sectionCardCopy}>Runtime, status, and message for every date in this backfill.</p>
              </div>
            </div>
            <div style={{ display: "grid", gap: 8 }}>
              {backfillRun.days.map((day) => {
                const severity = day.status === "COMPLETED" ? "low" as const : day.status === "FAILED" ? "critical" as const : day.status === "RUNNING" || day.status === "WAITING_CONFIG" ? "medium" as const : "neutral" as const;
                return (
                  <div key={day.businessDate} className={styles.evidenceRow}>
                    <div>
                      <strong>{day.businessDate}</strong>
                      <div className={styles.footerNote}>{day.message || (day.status === "PENDING" ? "Waiting for previous date" : "Processing")}</div>
                      {day.runtimeRunId && <code className={styles.freshnessVersionCode}>{day.runtimeRunId}</code>}
                    </div>
                    <Badge severity={severity}>{day.status}</Badge>
                  </div>
                );
              })}
            </div>
          </div>

          <div className={styles.actionRow} style={{ justifyContent: "center", marginTop: 12 }}>
            <Button variant="secondary" onClick={onClose}>
              {backfillRun.status === "COMPLETED" || backfillRun.status === "FAILED" ? "Close" : "Close and keep processing"}
            </Button>
          </div>
        </div>
      )}

      {!backfillRun && (postApprovalRun || isApproved) && (
        <div className={styles.approveProgress}>
          {postApprovalRun?.stats && Object.keys(postApprovalRun.stats).length > 0 && (
            <div className={`${styles.sectionCard} ${styles.pipelineMetricsHero}`}>
              <div className={styles.sectionCardHeading}>
                <div>
                  <span className={styles.metricEyebrow}>Pipeline proof</span>
                  <h5 className={styles.sectionCardTitle}>Ingestion performance</h5>
                  <p className={styles.sectionCardCopy}>
                    A compact view of what the pipeline read, persisted, skipped, and sent to reconciliation.
                  </p>
                </div>
                <Badge severity="neutral">CONFLICT-SAFE</Badge>
              </div>
              <div className={`${styles.metricGrid} ${styles.ingestionMetricsGrid}`}>
                <div className={styles.metricCard}>
                  <div className={styles.metricLabel}>Input</div>
                  <div className={styles.metricValue}>{postApprovalRun.stats.totalRows ?? 0}</div>
                  <div className={styles.metricHint}>rows read</div>
                </div>
                <div className={`${styles.metricCard} ${styles.metricCardSuccess}`}>
                  <div className={styles.metricLabel}>Inserted</div>
                  <div className={styles.metricValue}>{postApprovalRun.stats.successRows ?? 0}</div>
                  <div className={styles.metricHint}>new rows persisted</div>
                </div>
                <div className={`${styles.metricCard} ${styles.metricCardWarning}`}>
                  <div className={styles.metricLabel}>Duplicates</div>
                  <div className={styles.metricValue}>{postApprovalRun.stats.duplicateRows ?? 0}</div>
                  <div className={styles.metricHint}>safely skipped</div>
                </div>
                <div className={`${styles.metricCard} ${styles.metricCardDanger}`}>
                  <div className={styles.metricLabel}>Failed</div>
                  <div className={styles.metricValue}>{postApprovalRun.stats.failedRows ?? 0}</div>
                  <div className={styles.metricHint}>validation failures</div>
                </div>
                <div className={styles.metricCard}>
                  <div className={styles.metricLabel}>Recon output</div>
                  <div className={styles.metricValue}>{postApprovalRun.stats.reconciliationCount ?? postApprovalRun.reconciliationCount ?? 0}</div>
                  <div className={styles.metricHint}>results produced</div>
                </div>
              </div>
              <div className={styles.evidenceRow}>
                <span>Idempotency</span>
                <strong>
                  {(postApprovalRun.stats.duplicateRows ?? 0) > 0
                    ? `${postApprovalRun.stats.duplicateRows} duplicate row(s) skipped without failing the batch.`
                    : "No duplicate rows detected in this run."}
                </strong>
              </div>
            </div>
          )}

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

          {isBatchFatal && (
            <div className={`${styles.recommendPanel} ${styles.validationFailed}`} style={{ marginTop: 12 }}>
              <strong className={styles.recommendLabel}>BATCH FATAL — quality gate failed</strong>
              <p className={styles.recommendText}>
                Processing stopped during the file quality gate. No row-level quarantine was created and reconciliation did not start.
              </p>
              <div className={styles.evidenceRow}>
                <span>Error codes</span>
                <strong>{batchFatalCodes}</strong>
              </div>
            </div>
          )}

          {postApprovalRun?.qualityGateStatus === "REVIEW_REQUIRED" && (
            <div className={`${styles.recommendPanel} ${styles.validationFailed}`} style={{ marginTop: 12 }}>
              <strong className={styles.recommendLabel}>Quality gate requires review</strong>
              <p className={styles.recommendText}>
                {postApprovalRun.qualityGateSummary?.activeRows ?? 0} quarantine record(s) must be resolved before reconciliation can continue.
              </p>
              <Button variant="primary" onClick={() => onOpenQuarantine({ packetId: postApprovalRun?.packetId ?? "", postApprovalRunId: postApprovalRun?.id })}>
                Open quarantine review
              </Button>
            </div>
          )}

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
                  {postApprovalRun?.status === "WAITING_REVIEW" && item.key === "ingestion" ? (
                    <Badge severity="medium">Review required</Badge>
                  ) : isFailed ? (
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

          <div className={styles.actionRow} style={{ justifyContent: "center", marginTop: 12 }}>
            {postApprovalRun?.status === "FAILED" ? (
              <Button variant="secondary" onClick={isBatchFatal ? onClose : onBack}>
                {isBatchFatal ? "Close" : "Return to Step 3"}
              </Button>
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
