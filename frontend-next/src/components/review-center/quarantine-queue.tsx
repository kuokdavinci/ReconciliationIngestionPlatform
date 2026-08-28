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
  QuarantineDuplicateEvidence,
  QuarantineIssueType,
  QuarantinePriority,
  QuarantineRecord,
  QuarantineGroupSummary,
  QuarantineSampleField,
  QuarantineReprocessMode,
  QuarantineStatus,
} from "@/types/quarantine";
import styles from "./review-center.module.css";

type ActionKind = "CLAIM" | "REPROCESS" | "ACCEPT_EXISTING" | "REJECT" | "ESCALATE" | "RESUME";
const ISSUE_TYPES: QuarantineIssueType[] = ["SCHEMA", "REQUIRED_FIELD", "FORMAT", "DUPLICATE", "RECOVERY", "OTHER"];

const ISSUE_TYPE_LABELS: Record<QuarantineIssueType, string> = {
  SCHEMA: "Schema",
  REQUIRED_FIELD: "Required field",
  FORMAT: "Format",
  DUPLICATE: "Duplicate",
  RECOVERY: "Recovery",
  OTHER: "Other",
};

const ISSUE_TYPE_CODES: Record<QuarantineIssueType, string[]> = {
  SCHEMA: ["REQUIRED_SCHEMA_PATH", "MISSING_REQUIRED_SOURCE_COLUMN", "SCHEMA_CONFIG_DRIFT", "SOURCE_STRUCTURE_UNREADABLE", "CONFIG_VALIDATION"],
  REQUIRED_FIELD: ["MISSING_REQUIRED_FIELD"],
  FORMAT: ["MALFORMED_ROW", "INVALID_AMOUNT", "NEGATIVE_AMOUNT", "INVALID_TIMESTAMP", "INVALID_STATUS"],
  DUPLICATE: ["EQUIVALENT_DUPLICATE", "CONFLICTING_DUPLICATE"],
  RECOVERY: ["SOURCE_UNIT_RECOVERY_REQUIRED"],
  OTHER: [],
};

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

function badgeSeverity(status: QuarantineStatus): "critical" | "high" | "medium" {
  if (status === "REJECTED") return "critical";
  if (status === "REPROCESSING") return "high";
  return "medium";
}

function outcomeLabel(status: QuarantineStatus): string {
  if (status === "REPROCESSING") return "In review";
  if (status === "PENDING") return "Pending review";
  return status.charAt(0) + status.slice(1).toLowerCase();
}

function duplicateStatusLabel(status: QuarantineDuplicateEvidence["status"]): string {
  if (status === "EQUIVALENT") return "Exact duplicate";
  if (status === "CONFLICT") return "Conflict";
  return "Unavailable";
}

function timestampEntry(entries: QuarantineSampleField[]): QuarantineSampleField | undefined {
  return entries.find((entry) => /(transdate|timestamp|transactiontime)$/i.test(entry.canonicalPath ?? entry.sourceField));
}

function issueTypeFor(record: Pick<QuarantineRecord, "issueType" | "errorCodes">): QuarantineIssueType {
  if (record.issueType) return record.issueType;
  const code = record.errorCodes[0]?.toUpperCase();
  return ISSUE_TYPES.find((type) => ISSUE_TYPE_CODES[type].includes(code)) ?? "OTHER";
}

function issueTypeClass(type: QuarantineIssueType): string {
  if (type === "DUPLICATE") return styles.issueTypeDuplicate;
  if (type === "FORMAT" || type === "RECOVERY") return styles.issueTypeFormat;
  return styles.issueTypeRequired;
}

function issueCardClass(type: QuarantineIssueType): string {
  if (type === "DUPLICATE") return styles.quarantineCardDuplicate;
  if (type === "FORMAT" || type === "RECOVERY") return styles.quarantineCardFormat;
  return styles.quarantineCardRequired;
}

function formatDate(value?: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString();
}

function isOverdue(record: QuarantineRecord): boolean {
  return (
    (record.status === "PENDING" || record.status === "REPROCESSING") &&
    Boolean(record.reviewDueAt) &&
    new Date(record.reviewDueAt ?? 0).getTime() <= Date.now()
  );
}

function canResolve(record: QuarantineRecord, actor: string): boolean {
  return record.status === "REPROCESSING" && Boolean(actor.trim()) && record.claimedBy === actor.trim();
}

function summaryValue(value: number | undefined): number {
  return typeof value === "number" ? value : 0;
}

function humanizeFieldName(value: string): string {
  return value
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

function displaySampleValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "object") {
    try {
      return JSON.stringify(value);
    } catch {
      return "[UNAVAILABLE]";
    }
  }
  return String(value);
}

function sampleEntries(record: QuarantineRecord): QuarantineSampleField[] {
  if (record.evidence?.sampleFields?.length) return record.evidence.sampleFields;
  if (!record.rawRow || typeof record.rawRow !== "object" || Array.isArray(record.rawRow)) {
    if (!Array.isArray(record.rawRow)) return [];
    return record.rawRow.slice(0, 12).map((value, index) => ({
      sourceField: `Column ${index + 1}`,
      canonicalPath: null,
      column: index + 1,
      value,
      state: "UNKNOWN",
    }));
  }
  return Object.entries(record.rawRow as Record<string, unknown>)
    .filter(([key]) => !/(password|secret|token|apikey|authorization|credential|fingerprint)/i.test(key))
    .slice(0, 12)
    .map(([sourceField, value]) => ({
      sourceField,
      canonicalPath: null,
      column: null,
      value,
      state: "UNKNOWN",
    }));
}

function reviewInstruction(record: QuarantineRecord): string {
  const code = record.errorCodes[0];
  if (code === "CONFLICTING_DUPLICATE") {
    return "Compare this sample with the existing transaction before choosing a resolution.";
  }
  if (code === "EQUIVALENT_DUPLICATE") {
    return "Confirm the sample matches the persisted transaction, then accept the existing record.";
  }
  if (code === "SOURCE_UNIT_RECOVERY_REQUIRED") {
    return "Confirm the source unit is available and resume it from the durable checkpoint.";
  }
  if (code === "INVALID_TIMESTAMP") {
    return "Check the source date value and mapping before replaying this row.";
  }
  if (record.status === "PENDING") {
    return "Claim this row, inspect the sample, then choose the appropriate resolution.";
  }
  if (record.status === "REPROCESSING") {
    return "Verify the sample and choose source replay, accept existing, or reject.";
  }
  return "This row is terminal. Review the recorded outcome and bounded history.";
}

function resolutionPrompt(record: QuarantineRecord, resolving: boolean): string {
  if (resolving) return "Choose the bounded resolution after reviewing the issue and source row.";
  if (record.status === "PENDING") return "Claim the row to make a resolution, or escalate it for another review.";
  if (record.status === "REPROCESSING") return `Owned by ${record.claimedBy ?? "another operator"}; switch actor to continue.`;
  return "No further resolution is available for this terminal row.";
}

function actorMetaLabel(record: QuarantineRecord): string {
  if (record.claimedBy) return `Owner: ${record.claimedBy}`;
  if (record.lastActionActor) return `Action by: ${record.lastActionActor}`;
  return "Owner: Unclaimed";
}

function actionTimestampLabel(record: QuarantineRecord): string {
  return `${record.lastActionActor ? "Action at" : "Updated at"}: ${formatDate(record.lastActionAt ?? record.updatedAt)}`;
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
            <article key={record._id} className={`${styles.quarantineCard} ${issueCardClass(type)}`} data-testid={`quarantine-row-${id}`}>
              <div className={styles.quarantineCardHeader}>
                <div className={styles.quarantineCardTitle}>
                  <Badge className={issueTypeClass(type)} shape="pill">{ISSUE_TYPE_LABELS[type]}</Badge>
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

function actionTitle(kind: ActionKind): string {
  if (kind === "CLAIM") return "Claim";
  if (kind === "ACCEPT_EXISTING") return "Accept existing";
  if (kind === "REPROCESS") return "Reprocess";
  if (kind === "RESUME") return "Resume source unit";
  return kind.charAt(0) + kind.slice(1).toLowerCase();
}

function QuarantineActionForm({
  actionKind,
  busy,
  actionError,
  reason,
  correctedRow,
  reprocessMode,
  onReasonChange,
  onCorrectedRowChange,
  onReprocessModeChange,
  onCancel,
  onSubmit,
}: {
  actionKind: ActionKind;
  busy: boolean;
  actionError: string | null;
  reason: string;
  correctedRow: string;
  reprocessMode: QuarantineReprocessMode;
  onReasonChange: (value: string) => void;
  onCorrectedRowChange: (value: string) => void;
  onReprocessModeChange: (value: QuarantineReprocessMode) => void;
  onCancel: () => void;
  onSubmit: () => void;
}) {
  const title = actionTitle(actionKind);
  return (
    <section className={`${styles.sectionCard} ${styles.quarantineActionForm}`} aria-labelledby="quarantine-action-details">
      <div className={styles.quarantineSectionHeading}>
        <div>
          <h3 id="quarantine-action-details" className={styles.quarantineSectionTitle}>{title}</h3>
          <p className={styles.quarantineSectionCopy}>Confirm this action using the current row state. The detail stays open after completion.</p>
        </div>
      </div>
      {actionKind === "REPROCESS" ? (
        <>
          <label>Replay mode<select value={reprocessMode} onChange={(event) => onReprocessModeChange(event.target.value as QuarantineReprocessMode)}>
            <option value="REPLAY_SOURCE_ROW">Replay authoritative source row</option>
            <option value="CORRECTED_ROW">Submit corrected row</option>
          </select></label>
          {reprocessMode === "CORRECTED_ROW" ? <label>Corrected row JSON<textarea value={correctedRow} onChange={(event) => onCorrectedRowChange(event.target.value)} placeholder='{"id":"...","amount":"..."}' rows={6} /></label> : null}
        </>
      ) : null}
      {actionKind === "ACCEPT_EXISTING" ? <p className={styles.quarantineHint}>The existing record is verified internally; internal identifiers are never displayed here.</p> : null}
      {["REJECT", "ESCALATE", "RESUME"].includes(actionKind) ? <label>Reason<textarea value={reason} onChange={(event) => onReasonChange(event.target.value)} maxLength={500} rows={4} placeholder="Add a bounded operator reason" /></label> : null}
      {actionError ? <p className={styles.quarantineFormError} role="alert">{actionError}</p> : null}
      <div className={styles.quarantineDialogActions}>
        <Button type="button" variant="tertiary" disabled={busy} onClick={onCancel}>Cancel</Button>
        <Button type="button" variant="primary" disabled={busy} onClick={onSubmit}>{busy ? "Working..." : `Confirm ${title.toLowerCase()}`}</Button>
      </div>
    </section>
  );
}

function SampleFieldTable({ entries }: { entries: QuarantineSampleField[] }) {
  return entries.length > 0 ? (
    <div className={styles.quarantineSampleTableWrap}>
      <table className={styles.quarantineSampleTable} aria-label="Sanitized sample row">
        <thead><tr><th scope="col">Source field</th><th scope="col">Canonical</th><th scope="col">Value</th><th scope="col">Review</th></tr></thead>
        <tbody>
          {entries.map((entry, index) => {
            const flagged = entry.state === "MISSING" || entry.state === "INVALID";
            return (
              <tr key={`${entry.sourceField}-${index}`} className={flagged ? styles.quarantineSampleErrorRow : undefined}>
                <th scope="row" className={styles.quarantineSampleField}>{humanizeFieldName(entry.sourceField)}</th>
                <td className={styles.quarantineSampleCanonical}>{entry.canonicalPath ? humanizeFieldName(entry.canonicalPath) : "—"}</td>
                <td className={styles.quarantineSampleValue}>{displaySampleValue(entry.value)}</td>
                <td>{flagged ? <span className={styles.quarantineSampleFlag}>{entry.state === "MISSING" ? "Missing" : "Check"}</span> : <span className={styles.quarantineSampleOkay}>{entry.state === "UNKNOWN" ? "Unknown" : "OK"}</span>}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  ) : (
    <p className={styles.quarantineEmptySample}>No sanitized sample evidence is available for this row.</p>
  );
}

function QuarantineEvidencePanel({
  record,
  type,
  entries,
}: {
  record: QuarantineRecord;
  type: QuarantineIssueType;
  entries: QuarantineSampleField[];
}) {
  const mapping = record.evidence?.mapping;
  const duplicate = record.evidence?.duplicate;
  const sourceTimestamp = timestampEntry(entries);
  const isDuplicate = type === "DUPLICATE";
  const evidenceTitle = isDuplicate ? "Compare records" : "Offending row";
  const evidenceCopy = isDuplicate
    ? "Safe comparison fields only; internal identifiers and metadata are hidden."
    : `Sanitized source evidence for row ${record.rowNumber ?? "—"}.`;

  return (
    <section className={`${styles.sectionCard} ${styles.quarantineSampleCard}`} aria-labelledby="quarantine-offending-row">
      <div className={styles.quarantineSectionHeading}>
        <div>
          <h3 id="quarantine-offending-row" className={styles.quarantineSectionTitle}>{evidenceTitle}</h3>
          <p className={styles.quarantineSectionCopy}>{evidenceCopy}</p>
        </div>
        <span className={styles.quarantineSampleCount}>{isDuplicate ? "Safe fields" : `${entries.length} fields`}</span>
      </div>

      {isDuplicate ? (
        duplicate ? (
          <>
            <div className={styles.quarantineCompareStatus}>
              <Badge severity={duplicate.status === "CONFLICT" ? "critical" : "medium"} shape="pill">{duplicateStatusLabel(duplicate.status)}</Badge>
              <span>{duplicate.status === "EQUIVALENT" ? "All available safe fields match." : duplicate.status === "CONFLICT" ? "Review the differing fields before resolving." : "The existing transaction is not available for comparison."}</span>
            </div>
            <div className={styles.quarantineSampleTableWrap}>
              <table className={styles.quarantineSampleTable} aria-label="Incoming and existing transaction comparison">
                <thead><tr><th scope="col">Field</th><th scope="col">Incoming</th><th scope="col">Existing</th><th scope="col">Result</th></tr></thead>
                <tbody>
                  {(sourceTimestamp ? [
                    ...duplicate.fields,
                    { name: "timestamp", incoming: sourceTimestamp.value, existing: "Not shown", result: "UNAVAILABLE" as const },
                  ] : duplicate.fields).map((field) => {
                    const exactDuplicate = duplicate.status === "EQUIVALENT" && field.name !== "timestamp";
                    const isDiff = !exactDuplicate && field.result === "DIFF";
                    const result = exactDuplicate ? "MATCH" : field.result;
                    return (
                    <tr key={field.name} className={isDiff ? styles.quarantineSampleErrorRow : undefined}>
                      <th scope="row" className={styles.quarantineSampleField}>{humanizeFieldName(field.name)}</th>
                      <td className={styles.quarantineSampleValue}>{displaySampleValue(field.incoming)}</td>
                      <td className={styles.quarantineSampleValue}>{displaySampleValue(field.existing)}</td>
                      <td>
                        <span className={isDiff ? styles.quarantineSampleFlag : styles.quarantineSampleOkay}>
                          {result === "DIFF" ? "Diff" : result === "MATCH" ? "Match" : "Unavailable"}
                        </span>
                      </td>
                    </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </>
        ) : (
          <p className={styles.quarantineEmptySample}>No safe existing transaction comparison is available.</p>
        )
      ) : (
        type === "SCHEMA" || type === "REQUIRED_FIELD" ? (
          mapping?.requiredFields?.length ? (
            <div className={styles.quarantineMappingEvidence}>
              <div className={styles.quarantineSubsectionHeading}>
                <div>
                  <h4>Required field evidence</h4>
                  <p>Expected mapping and observed sample value in one view.</p>
                </div>
                <span>{mapping.configVersion ?? record.configVersion ?? "Config unavailable"}</span>
              </div>
              <div className={styles.quarantineSampleTableWrap}>
                <table className={styles.quarantineSampleTable} aria-label="Required field evidence">
                  <thead><tr><th scope="col">Canonical field</th><th scope="col">Source field</th><th scope="col">Type</th><th scope="col">Value</th><th scope="col">Review</th></tr></thead>
                  <tbody>
                    {mapping.requiredFields.map((field) => {
                      const sample = entries.find((entry) => entry.canonicalPath === field.canonicalPath || entry.sourceField === field.sourceField);
                      const state = field.state === "MISSING" || sample?.state === "MISSING"
                        ? "MISSING"
                        : sample?.state === "INVALID"
                          ? "INVALID"
                          : field.state;
                      const flagged = state === "MISSING" || state === "INVALID";
                      return (
                        <tr key={field.canonicalPath} className={flagged ? styles.quarantineSampleErrorRow : undefined}>
                          <th scope="row" className={styles.quarantineSampleField}>{humanizeFieldName(field.canonicalPath)}</th>
                          <td>{field.sourceField || (field.column == null ? "—" : `Column ${field.column}`)}</td>
                          <td>{field.type}</td>
                          <td className={styles.quarantineSampleValue}>{displaySampleValue(sample?.value)}</td>
                          <td><span className={flagged ? styles.quarantineSampleFlag : styles.quarantineSampleOkay}>{state}</span></td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              {mapping.observedColumns?.length ? <p className={styles.quarantineObservedColumns}><strong>Observed columns:</strong> {mapping.observedColumns.join(", ")}</p> : null}
            </div>
          ) : (
            <SampleFieldTable entries={entries} />
          )
        ) : (
          <SampleFieldTable entries={entries} />
        )
      )}
    </section>
  );
}

function QuarantineDetail({
  record,
}: {
  record: QuarantineRecord;
}) {
  const entries = sampleEntries(record);
  const type = issueTypeFor(record);
  const primaryError = record.errors?.[0];
  const primaryErrorReason = primaryError && typeof primaryError.reason === "string" ? primaryError.reason : null;
  return (
    <div className={styles.quarantineDetail} data-testid="quarantine-detail-panel">
      <div className={styles.summaryBadges}>
        <Badge className={issueTypeClass(type)} shape="pill">{ISSUE_TYPE_LABELS[type]}</Badge>
        <Badge severity={badgeSeverity(record.status)} shape="pill">{outcomeLabel(record.status)}</Badge>
        <Badge severity={record.priority === "HIGH" ? "high" : "medium"} shape="pill">{record.priority} priority</Badge>
        {isOverdue(record) ? <Badge severity="critical" shape="pill">Overdue</Badge> : null}
      </div>
      <section className={`${styles.sectionCard} ${styles.quarantineDecisionCard}`} aria-labelledby="quarantine-validation-issue">
        <div className={styles.quarantineSectionHeading}>
          <div>
            <h3 id="quarantine-validation-issue" className={styles.quarantineSectionTitle}>Validation issue</h3>
            <p className={styles.quarantineSectionCopy}>{record.errorCodes[0] ?? "Quarantined row"}</p>
          </div>
        </div>
        <p className={styles.quarantineInstruction}>{reviewInstruction(record)}</p>
        {primaryErrorReason ? <p className={styles.quarantineErrorReason}>{primaryErrorReason}</p> : null}
      </section>

      <QuarantineEvidencePanel record={record} type={type} entries={entries} />

      <section className={styles.sectionCard} aria-labelledby="quarantine-source-context">
        <div className={styles.quarantineSectionHeading}>
          <h3 id="quarantine-source-context" className={styles.quarantineSectionTitle}>Source context</h3>
          <span className={styles.quarantineSampleCount}>Origin</span>
        </div>
        <div className={styles.quarantineDetailGrid}>
          <span><strong>Partner</strong>{record.partner}</span>
          <span><strong>Source file</strong>{record.sourceFileId}</span>
          <span><strong>Source unit</strong>{record.sourceUnitKey ?? "—"}</span>
          <span><strong>Row</strong>{record.rowNumber ?? "—"}</span>
          <span><strong>Phase</strong>{record.phase}</span>
          <span><strong>Severity</strong>{record.severity}</span>
          <span><strong>Config</strong>{record.configVersion ?? "—"}</span>
        </div>
      </section>

      <section className={styles.sectionCard} aria-labelledby="quarantine-review-status">
        <div className={styles.quarantineSectionHeading}>
          <h3 id="quarantine-review-status" className={styles.quarantineSectionTitle}>Review status</h3>
          <span className={styles.quarantineSampleCount}>Lifecycle</span>
        </div>
        <div className={styles.quarantineDetailGrid}>
          <span><strong>{record.claimedBy ? "Owner" : record.status === "REJECTED" && record.lastActionActor ? "Rejected by" : record.status === "RESOLVED" && record.lastActionActor ? "Resolved by" : "Owner"}</strong>{record.claimedBy ?? record.lastActionActor ?? "Unclaimed"}</span>
          <span><strong>Due</strong>{formatDate(record.reviewDueAt)}</span>
          <span><strong>Attempts</strong>{record.attemptCount}</span>
          <span><strong>Escalation</strong>{record.escalationLevel}/3</span>
        </div>
      </section>

      <details className={styles.quarantineHistoryDetails}>
        <summary>Resolution history <span>{record.resolutionHistory?.length ?? 0} events</span></summary>
        {record.resolutionHistory?.length ? <div className={styles.quarantineHistory}>{record.resolutionHistory.slice(0, 50).map((event) => <div key={event.eventId}><strong>{event.outcome ?? event.action}</strong><span>{event.actor} · {formatDate(event.timestamp)}</span><small>{event.reason}</small></div>)}</div> : <p className={styles.sectionCardCopy}>No operator actions recorded for this row.</p>}
      </details>
    </div>
  );
}

function QuarantineActionBar({
  record,
  actor,
  onAction,
  onClose,
}: {
  record: QuarantineRecord;
  actor: string;
  onAction: (kind: ActionKind) => void;
  onClose: () => void;
}) {
  const resolving = canResolve(record, actor);
  const pending = record.status === "PENDING";
  const active = pending || record.status === "REPROCESSING";
  const sourceUnitReady = Boolean(record.sourceUnitKey && scenarioId(record) === "DEMO-RECOVERY-001");

  return (
    <section className={`${styles.sectionCard} ${styles.quarantineResolutionCard}`} aria-labelledby="quarantine-resolution">
      <div className={styles.quarantineSectionHeading}>
        <div>
          <h3 id="quarantine-resolution" className={styles.quarantineSectionTitle}>Recommended action</h3>
          <p className={styles.quarantineSectionCopy}>{resolutionPrompt(record, resolving)}</p>
        </div>
      </div>
      {record.status === "REPROCESSING" && !resolving ? <p className={styles.quarantineOwnerWarning}>This row is owned by {record.claimedBy ?? "another operator"}. Switch the actor to continue.</p> : null}
      <div className={styles.quarantineDialogActions}>
        {pending ? <Button type="button" variant="primary" onClick={() => onAction("CLAIM")}>Claim</Button> : null}
        {active && record.escalationLevel < 3 ? <Button type="button" variant="tertiary" onClick={() => onAction("ESCALATE")}>Escalate</Button> : null}
        {resolving ? <>
          <Button type="button" variant="primary" onClick={() => onAction("REPROCESS")}>Reprocess</Button>
          <Button type="button" variant="secondary" onClick={() => onAction("ACCEPT_EXISTING")}>Accept existing</Button>
          <Button type="button" variant="tertiary" className={styles.quarantineRejectButton} onClick={() => onAction("REJECT")}>Reject</Button>
        </> : null}
        {sourceUnitReady ? <Button type="button" variant="secondary" onClick={() => onAction("RESUME")}>Resume source unit</Button> : null}
        <Button type="button" variant="tertiary" onClick={onClose}>Close</Button>
      </div>
    </section>
  );
}
