"use client";

import { useEffect, useMemo, useState } from "react";
import { ApiError } from "@/lib/api/client";
import * as api from "@/lib/api/quarantine";
import * as reviewApi from "@/lib/api/review-center";
import { getCurrentActor, setCurrentActor } from "@/lib/actor";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { useToast } from "@/components/ui/toast";
import { useQuarantine } from "@/components/review-center/use-quarantine";
import type {
  QuarantineActionResponse,
  QuarantineIssueType,
  QuarantinePriority,
  QuarantineRecord,
  QuarantineGroupSummary,
  QuarantineReprocessMode,
  QuarantineStatus,
} from "@/types/quarantine";
import {
  QuarantineActionBar,
  QuarantineActionForm,
  QuarantineDetail,
  type ActionKind,
} from "./quarantine-detail";
import {
  ISSUE_TYPE_LABELS,
  ISSUE_TYPES,
  actionTimestampLabel,
  actorMetaLabel,
  badgeSeverity,
  issueTypeFor,
  issueTypeSeverity,
  outcomeLabel,
  summaryValue,
} from "./quarantine-presenters";
import styles from "./review-center.module.css";

function scenarioId(record: QuarantineRecord): string {
  const value = record.resolutionMetadata.demoScenarioId;
  return typeof value === "string" && value ? value : record._id;
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiError && error.errorCodes.length > 0) {
    return error.errorCodes.join(", ");
  }
  if (error instanceof Error) return error.message;
  return "The quarantine operation could not be completed.";
}

function actionId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `operator-action-${Date.now()}`;
}

interface QueueProps {
  initialReviewPacketId?: string;
  initialPostApprovalRunId?: string;
}

export function QuarantineQueue({ initialReviewPacketId, initialPostApprovalRunId }: QueueProps) {
  const [status, setStatus] = useState<QuarantineStatus | "">("");
  const [priority, setPriority] = useState<QuarantinePriority | "">("");
  const [issueType, setIssueType] = useState<QuarantineIssueType | "">("");
  const [overdue, setOverdue] = useState<"" | "true" | "false">("");
  const [claimedBy, setClaimedBy] = useState("");
  const [cursor, setCursor] = useState<string | undefined>();
  const [actor, setActor] = useState(() => getCurrentActor());
  const [actionKind, setActionKind] = useState<ActionKind | null>(null);
  const [reason, setReason] = useState("");
  const [correctedRow, setCorrectedRow] = useState("");
  const [reprocessMode, setReprocessMode] = useState<QuarantineReprocessMode>("REPLAY_SOURCE_ROW");
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [proceedingGroup, setProceedingGroup] = useState<string | null>(null);
  const { showToast } = useToast();

  const filters = useMemo(() => ({
    partner: "DEMO",
    status: status || undefined,
    priority: priority || undefined,
    issueType: issueType || undefined,
    overdue: overdue === "" ? undefined : overdue === "true",
    claimedBy: claimedBy.trim() || undefined,
    reviewPacketId: initialReviewPacketId,
    postApprovalRunId: initialPostApprovalRunId,
    cursor,
    limit: 100,
  }), [claimedBy, cursor, initialPostApprovalRunId, initialReviewPacketId, issueType, overdue, priority, status]);
  const queue = useQuarantine(filters);
  const selected = queue.selectedRecord;
  const groupedItems = useMemo(() => {
    const grouped = new Map<string, QuarantineRecord[]>();
    for (const record of queue.items) {
      const key = record.quarantineGroupKey || record.postApprovalRunId || record.reviewPacketId || record.sourceFileId;
      grouped.set(key, [...(grouped.get(key) ?? []), record]);
    }
    return [...grouped.entries()].map(([key, records]) => ({ key, records }));
  }, [queue.items]);
  const groupSummaries = useMemo(() => {
    const summaries = new Map<string, QuarantineGroupSummary>();
    for (const group of queue.groups) summaries.set(group.groupKey, group);
    return summaries;
  }, [queue.groups]);
  const [runStatusByGroup, setRunStatusByGroup] = useState<Record<string, string>>({});

  useEffect(() => {
    let cancelled = false;
    const groups = queue.groups.filter((group) => group.reviewPacketId && group.postApprovalRunId);
    if (groups.length === 0) {
      return () => {
        cancelled = true;
      };
    }

    void Promise.all(groups.map(async (group) => {
      try {
        const response = await reviewApi.getPostApproveRun(group.reviewPacketId as string);
        const status = response.run && typeof response.run.status === "string" ? response.run.status : null;
        return [group.groupKey, status] as const;
      } catch {
        return [group.groupKey, null] as const;
      }
    })).then((entries) => {
      if (!cancelled) {
        setRunStatusByGroup((current) => {
          const next = { ...current };
          for (const [groupKey, status] of entries) {
            if (status && current[groupKey] !== "COMPLETED") next[groupKey] = status;
          }
          return next;
        });
      }
    });

    return () => {
      cancelled = true;
    };
  }, [queue.groups]);

  const updateActor = (value: string) => {
    setActor(value);
    setCurrentActor(value);
  };

  const resetFilters = () => {
    setStatus("");
    setPriority("");
    setIssueType("");
    setOverdue("");
    setClaimedBy("");
    setCursor(undefined);
  };

  const openAction = (kind: ActionKind) => {
    setActionKind(kind);
    setReason("");
    setCorrectedRow("");
    setReprocessMode("REPLAY_SOURCE_ROW");
    setActionError(null);
  };

  const submitAction = async () => {
    if (!selected || !actionKind) return;
    const operatorId = actor.trim();
    if (!operatorId) {
      setActionError("Enter an operator actor before taking an action.");
      return;
    }
    const boundedReason = reason.trim();
    if (["REJECT", "ESCALATE", "RESUME"].includes(actionKind) && !boundedReason) {
      setActionError("A non-empty reason is required for this action.");
      return;
    }
    if (boundedReason.length > 500) {
      setActionError("Reason must be 500 characters or fewer.");
      return;
    }

    let parsedCorrectedRow: unknown;
    if (actionKind === "REPROCESS" && reprocessMode === "CORRECTED_ROW") {
      if (!correctedRow.trim()) {
        setActionError("A corrected row is required for corrected-row replay.");
        return;
      }
      try {
        parsedCorrectedRow = JSON.parse(correctedRow);
      } catch {
        setActionError("Corrected row must be valid JSON.");
        return;
      }
    }

    const fields = {
      operatorId,
      actionId: actionId(),
      expectedStatus: selected.status,
    };
    setBusy(true);
    setActionError(null);
    try {
      let result: QuarantineActionResponse | Record<string, unknown>;
      if (actionKind === "CLAIM") {
        result = await api.claimQuarantine(selected._id, fields);
      } else if (actionKind === "REPROCESS") {
        result = await api.reprocessQuarantine(selected._id, {
          ...fields,
          mode: reprocessMode,
          ...(parsedCorrectedRow === undefined ? {} : { correctedRow: parsedCorrectedRow }),
          mappingVersion: selected.configVersion ?? undefined,
        });
      } else if (actionKind === "ACCEPT_EXISTING") {
        result = await api.acceptExistingQuarantine(selected._id, fields);
      } else if (actionKind === "REJECT") {
        result = await api.rejectQuarantine(selected._id, { ...fields, reason: boundedReason });
      } else if (actionKind === "ESCALATE") {
        result = await api.escalateQuarantine(selected._id, { ...fields, reason: boundedReason });
      } else {
        if (!selected.sourceUnitKey) {
          setActionError("This row has no source unit available for resume.");
          return;
        }
        result = await api.resumeQuarantineSourceUnit(selected.sourceUnitKey, {
          ...fields,
          reason: boundedReason,
        });
      }
      const outcome = "outcome" in result && typeof result.outcome === "string" ? result.outcome : "COMPLETED";
      showToast(outcome, "success");
      setActionKind(null);
      await queue.refresh();
    } catch (error) {
      setActionError(errorMessage(error));
      showToast(errorMessage(error), "error");
    } finally {
      setBusy(false);
    }
  };

  const proceedGroup = async (groupKey: string, packetId: string) => {
    setProceedingGroup(groupKey);
    try {
      const result = await api.continuePostApprovalRun(packetId);
      if (result.outcome === "RECONCILED_AFTER_QUARANTINE" || result.outcome === "ALREADY_RECONCILED") {
        setRunStatusByGroup((current) => ({ ...current, [groupKey]: "COMPLETED" }));
      } else if (result.outcome === "WAITING_REVIEW") {
        setRunStatusByGroup((current) => ({ ...current, [groupKey]: "WAITING_REVIEW" }));
      }
      if (result.ok) {
        showToast(
          result.outcome === "RECONCILED_AFTER_QUARANTINE"
            ? "Reconciliation continued from this quarantine packet."
            : result.outcome === "ALREADY_RECONCILED"
              ? "This packet has already continued to reconciliation."
              : result.outcome,
          "success",
        );
      } else {
        showToast(result.outcome, "info");
      }
      await queue.refresh();
    } catch (error) {
      showToast(errorMessage(error), "error");
    } finally {
      setProceedingGroup(null);
    }
  };

  return (
    <div className={styles.quarantineQueue}>
      <div className={styles.quarantineToolbar}>
        <div>
          <h3 className={styles.eyebrow}>Quarantine review</h3>
          <p className={styles.introText}>Rows held before persistence. Review the issue, source sample, and next action.</p>
        </div>
        <label className={styles.quarantineActor}>
          <span>Operator actor</span>
          <input value={actor} onChange={(event) => updateActor(event.target.value)} aria-label="Operator actor" maxLength={128} />
        </label>
      </div>

      <div className={styles.quarantineSummary} aria-label="Quarantine summary">
        <div className={`${styles.metricCard} ${styles.metricCardWarning}`} aria-label={`${summaryValue(queue.summary?.pending)} pending`}>
          <div className={styles.metricLabel}>Pending</div>
          <div className={styles.metricValue}>{summaryValue(queue.summary?.pending)}</div>
          <div className={styles.metricHint}>awaiting claim</div>
        </div>
        <div className={`${styles.metricCard} ${styles.metricCardReview}`} aria-label={`${summaryValue(queue.summary?.reprocessing)} in review`}>
          <div className={styles.metricLabel}>In review</div>
          <div className={styles.metricValue}>{summaryValue(queue.summary?.reprocessing)}</div>
          <div className={styles.metricHint}>claimed rows</div>
        </div>
        <div className={`${styles.metricCard} ${styles.metricCardWarning}`} aria-label={`${summaryValue(queue.summary?.resolved)} resolved`}>
          <div className={styles.metricLabel}>Resolved</div>
          <div className={styles.metricValue}>{summaryValue(queue.summary?.resolved)}</div>
          <div className={styles.metricHint}>completed outcomes</div>
        </div>
        <div className={`${styles.metricCard} ${styles.metricCardDanger}`} aria-label={`${summaryValue(queue.summary?.rejected)} rejected`}>
          <div className={styles.metricLabel}>Rejected</div>
          <div className={styles.metricValue}>{summaryValue(queue.summary?.rejected)}</div>
          <div className={styles.metricHint}>terminal decisions</div>
        </div>
        <div className={`${styles.metricCard} ${styles.metricCardDanger}`} aria-label={`${summaryValue(queue.summary?.overdue)} overdue`}>
          <div className={styles.metricLabel}>Overdue</div>
          <div className={styles.metricValue}>{summaryValue(queue.summary?.overdue)}</div>
          <div className={styles.metricHint}>past review SLA</div>
        </div>
        <div className={`${styles.metricCard} ${styles.metricCardReview}`} aria-label={`${summaryValue(queue.summary?.highPriority)} high priority`}>
          <div className={styles.metricLabel}>High priority</div>
          <div className={styles.metricValue}>{summaryValue(queue.summary?.highPriority)}</div>
          <div className={styles.metricHint}>needs priority review</div>
        </div>
      </div>

      <div className={styles.quarantineFilters}>
        <label>Issue type<select aria-label="Quarantine issue type" value={issueType} onChange={(event) => { setIssueType(event.target.value as QuarantineIssueType | ""); setCursor(undefined); }}>
          <option value="">All issue types</option>
          {ISSUE_TYPES.map((type) => <option key={type} value={type}>{ISSUE_TYPE_LABELS[type]}</option>)}
        </select></label>
        <label>Status<select aria-label="Quarantine status" value={status} onChange={(event) => { setStatus(event.target.value as QuarantineStatus | ""); setCursor(undefined); }}>
          <option value="">All statuses</option>
          <option value="PENDING">Pending</option>
          <option value="REPROCESSING">In review</option>
          <option value="RESOLVED">Resolved</option>
          <option value="REJECTED">Rejected</option>
        </select></label>
        <label>Priority<select aria-label="Quarantine priority" value={priority} onChange={(event) => { setPriority(event.target.value as QuarantinePriority | ""); setCursor(undefined); }}>
          <option value="">All priorities</option>
          <option value="HIGH">High</option>
          <option value="NORMAL">Normal</option>
        </select></label>
        <label>Review timing<select aria-label="Quarantine overdue" value={overdue} onChange={(event) => { setOverdue(event.target.value as "" | "true" | "false"); setCursor(undefined); }}>
          <option value="">All timing</option>
          <option value="true">Overdue</option>
          <option value="false">On time</option>
        </select></label>
        <label>Claimed by<input aria-label="Claimed by" value={claimedBy} onChange={(event) => { setClaimedBy(event.target.value); setCursor(undefined); }} placeholder="Any operator" maxLength={128} /></label>
        <Button type="button" variant="tertiary" onClick={resetFilters}>Reset filters</Button>
      </div>

      {queue.error ? (
        <div className={styles.quarantineNotice} role="alert">
          <span>{errorMessage(queue.error)}</span>
          <Button type="button" onClick={() => void queue.refresh().catch(() => undefined)}>Retry</Button>
        </div>
      ) : null}

      {queue.loading && queue.items.length === 0 ? <div className={styles.emptyBlock}>Loading quarantined rows...</div> : null}
      {!queue.loading && queue.items.length === 0 ? <div className={styles.emptyBlock}>No quarantined rows match these filters.</div> : null}
      <div className={styles.quarantineList}>
        {groupedItems.map((group) => {
          const summary = groupSummaries.get(group.key);
          const reviewPacketId = summary?.reviewPacketId ?? group.records[0]?.reviewPacketId;
          const postApprovalRunId = summary?.postApprovalRunId ?? group.records[0]?.postApprovalRunId;
          const runStatus = runStatusByGroup[group.key];
          const runStatusLabel = runStatus === "COMPLETED"
            ? "Reconciled"
            : runStatus === "WAITING_REVIEW"
              ? "Needs review"
              : runStatus === "FAILED"
                ? "Failed"
                : runStatus === "RECONCILING"
                  ? "Reconciling"
                  : runStatus;
          const runStatusSeverity = runStatus === "COMPLETED"
            ? "low" as const
            : runStatus === "FAILED"
              ? "critical" as const
              : "medium" as const;
          const canProceed = Boolean(
            reviewPacketId
            && postApprovalRunId
            && summary
            && summary.pending === 0
            && summary.reprocessing === 0
            && (!runStatus || runStatus === "WAITING_REVIEW"),
          );
          return (
            <section key={group.key} className={styles.quarantineBatch}>
              <div className={styles.quarantineBatchHeader}>
                <div>
                  <span className={styles.metricEyebrow}>Quarantine packet</span>
                  <h4>{postApprovalRunId ? "Post-approval run" : "Review packet"}</h4>
                  <p className={styles.footerNote}>
                    Packet: {reviewPacketId ?? "—"} · Run: {postApprovalRunId ?? "—"}
                  </p>
                </div>
                <div className={styles.quarantineBatchStats}>
                  <Badge severity="medium" shape="pill">{summary?.total ?? group.records.length} records</Badge>
                  <Badge severity="high" shape="pill">{summary?.pending ?? group.records.filter((item) => item.status === "PENDING").length} pending</Badge>
                  {summary?.overdue ? <Badge severity="critical" shape="pill">{summary.overdue} overdue</Badge> : null}
                  {runStatusLabel ? <Badge severity={runStatusSeverity} shape="pill">{runStatusLabel}</Badge> : null}
                  {canProceed ? (
                    <Button
                      type="button"
                      variant="primary"
                      disabled={proceedingGroup === group.key}
                      onClick={() => { if (reviewPacketId) void proceedGroup(group.key, reviewPacketId); }}
                    >
                      {proceedingGroup === group.key ? "Proceeding..." : "Proceed to reconciliation"}
                    </Button>
                  ) : null}
                </div>
              </div>
              {group.records.map((record) => {
          const id = scenarioId(record);
          const type = issueTypeFor(record);
                return (
            <article key={record._id} className={styles.quarantineCard} data-testid={`quarantine-row-${id}`}>
              <div className={styles.quarantineCardHeader}>
                <div className={styles.quarantineCardTitle}>
                  <Badge severity={issueTypeSeverity(type)} shape="pill">{ISSUE_TYPE_LABELS[type]}</Badge>
                  <h4>{record.issueSummary ?? `${ISSUE_TYPE_LABELS[type]} issue`}</h4>
                </div>
                <div className={styles.quarantineCardBadges}>
                  <Badge severity={badgeSeverity(record.status)} shape="pill">{outcomeLabel(record.status)}</Badge>
                </div>
              </div>
              <div className={styles.quarantineCardMeta}>
                <span>{actorMetaLabel(record)}</span>
                <span>{actionTimestampLabel(record)}</span>
              </div>
              <div className={styles.quarantineCardFooter}>
                <span>Attempt {record.attemptCount} · Escalation {record.escalationLevel}</span>
                <Button type="button" variant="primary" onClick={() => queue.setSelectedId(record._id)} aria-label="Review now">Review now</Button>
              </div>
            </article>
                );
              })}
            </section>
          );
        })}
      </div>

      <div className={styles.quarantinePagination}>
        <span>{queue.items.length} rows on this page</span>
        <Button type="button" variant="tertiary" disabled={!queue.nextCursor || queue.loading} onClick={() => setCursor(queue.nextCursor ?? undefined)}>Next page</Button>
      </div>

      <Dialog
        open={Boolean(selected)}
        onClose={() => { setActionKind(null); queue.setSelectedId(null); }}
        title={selected ? `${ISSUE_TYPE_LABELS[issueTypeFor(selected)]} review` : undefined}
        panelClassName={styles.quarantineDialog}
        footer={selected ? (
          actionKind ? (
            <QuarantineActionForm
              actionKind={actionKind}
              busy={busy}
              actionError={actionError}
              reason={reason}
              correctedRow={correctedRow}
              reprocessMode={reprocessMode}
              onReasonChange={setReason}
              onCorrectedRowChange={setCorrectedRow}
              onReprocessModeChange={setReprocessMode}
              onCancel={() => setActionKind(null)}
              onSubmit={() => void submitAction()}
            />
          ) : (
            <QuarantineActionBar
              record={selected}
              actor={actor}
              onAction={openAction}
              onClose={() => { setActionKind(null); queue.setSelectedId(null); }}
            />
          )
        ) : null}
      >
        {selected ? (
          <QuarantineDetail record={selected} />
        ) : null}
      </Dialog>
    </div>
  );
}
