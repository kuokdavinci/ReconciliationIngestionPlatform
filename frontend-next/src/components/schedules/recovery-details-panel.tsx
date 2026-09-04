"use client";

import { useEffect, useRef, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type {
  IngestionBatchMetrics,
  IngestionStageSummary,
  RecoveryStatus,
  RecoveryUnitSummary,
  ScheduleJob,
} from "@/types/schedules";
import { RecoveryCountdown } from "./recovery-countdown";
import styles from "./schedules.module.css";

interface Props {
  job: ScheduleJob | null;
  onClose: () => void;
  onRefresh?: () => void;
  onRetry?: () => void;
  retrying?: boolean;
  onResolve?: (action: "RETRY" | "SKIP", reason: string) => void;
  resolving?: boolean;
}

function statusSeverity(status: RecoveryStatus) {
  if (status === "FAILED" || status === "BLOCKED") return "critical" as const;
  if (status === "PROCESSING" || status === "PENDING" || status === "WAITING_REVIEW") return "medium" as const;
  if (status === "COMPLETED" || status === "PARTIAL" || status === "REPLAYED") return "low" as const;
  return "neutral" as const;
}

function unitSymbol(status: RecoveryUnitSummary["status"]) {
  if (status === "COMPLETED" || status === "SKIPPED" || status === "REPLAYED") return "✓";
  if (status === "FAILED" || status === "BLOCKED" || status === "WAITING_REVIEW") return "!";
  return "○";
}

function eventSymbol(status: string) {
  const normalized = status.toUpperCase();
  if (["COMPLETED", "SKIPPED", "REPLAYED", "RESOLVED"].includes(normalized)) return "✓";
  if (["FAILED", "BLOCKED"].includes(normalized)) return "!";
  if (["PROCESSING", "PENDING", "WAITING_REVIEW"].includes(normalized)) return "•";
  return "○";
}

function unitLabel(unit: RecoveryUnitSummary) {
  return unit.label || (unit.page ? `Page ${unit.page}` : unit.unitKey);
}

function formatDateTime(value?: string | null) {
  if (!value) return "-";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function formatDuration(value?: number | null) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  return `${value.toFixed(2)} ms`;
}

function formatCount(value?: number | null) {
  return typeof value === "number" && Number.isFinite(value) ? String(value) : "—";
}

function formatStageName(value: string) {
  return value.replaceAll("_", " ");
}

function displayStage(currentStage: string | null | undefined, status: string | null | undefined) {
  if (status === "COMPLETED") return "COMPLETED";
  if (status === "PARTIAL") return "COMPLETED WITH REJECTS";
  if (status === "FAILED" || status === "BLOCKED") return status;
  return currentStage || "—";
}

function hasSnapshot(value?: IngestionStageSummary | null): value is IngestionStageSummary {
  return Boolean(value && Object.keys(value).length > 0);
}

function runtimeStatusSeverity(status?: string | null) {
  if (status === "FAILED" || status === "BLOCKED") return "critical" as const;
  if (status === "COMPLETED" || status === "PARTIAL" || status === "SAFE_DUPLICATE") return "low" as const;
  if (status) return "medium" as const;
  return "neutral" as const;
}

function timingEntries(metrics?: IngestionBatchMetrics | null) {
  if (!metrics) return [];
  return [
    ["Parse rows", metrics.parseRowsMs],
    ["Normalize", metrics.normalizeMs],
    ["Validate", metrics.validateMs],
    ["COPY", metrics.copyMs],
    ["Insert / classify", metrics.insertClassifyMs],
    ["Transaction", metrics.transactionOverheadMs],
    ["Batch wall time", metrics.totalBatchWallMs],
    ["Persistence window", metrics.persistenceWindowMs],
    ["Slowest batch", metrics.slowestBatchMs],
  ] as const;
}

export function RecoveryDetailsPanel({
  job,
  onClose,
  onRefresh,
  onRetry,
  retrying = false,
  onResolve,
  resolving = false,
}: Props) {
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const [resolutionDraft, setResolutionDraft] = useState({ partner: "", reason: "" });
  const isOpen = Boolean(job && (job.recovery || job.latestRuntimeRun || job.latestFile?.stageSummary));
  const recovery = job?.recovery;
  const runtimeRun = job?.latestRuntimeRun;
  const runtimeStats = runtimeRun?.stats || {};
  const stageSummary = runtimeRun
    ? (hasSnapshot(runtimeRun.stageSummary) ? runtimeRun.stageSummary : null)
    : (hasSnapshot(job?.latestFile?.stageSummary) ? job.latestFile?.stageSummary : null);
  const runtimeStatus = runtimeRun?.status || job?.status;
  const configurationReviewRequired = recovery?.errorCode === "configuration_approval_required";
  const configurationReviewResolved = configurationReviewRequired
    && ["COMPLETED", "PARTIAL", "REPLAYED"].includes(recovery?.status || "");
  const isSafeDuplicate = job?.safeDuplicate === true
    || recovery?.safeDuplicate === true
    || runtimeStats.safeDuplicate === true
    || ["FILE_DUPLICATE", "FETCH_UNIT_REPLAY", "NO_NEW_FILE", "SAFE_DUPLICATE"].includes(String(runtimeStats.outcome));
  const resolutionReason = resolutionDraft.partner === (job?.partner || "")
    ? resolutionDraft.reason
    : "";

  useEffect(() => {
    if (!isOpen) return;
    const previouslyFocused = document.activeElement as HTMLElement | null;
    closeButtonRef.current?.focus();
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
      if (event.key !== "Tab") return;
      const panel = closeButtonRef.current?.closest("aside");
      if (!panel) return;
      const focusable = Array.from(panel.querySelectorAll<HTMLElement>(
        'button, textarea, input, select, a[href], [tabindex]:not([tabindex="-1"])',
      )).filter((element) => !element.hasAttribute("disabled"));
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", handleKeyDown);
      previouslyFocused?.focus();
    };
  }, [isOpen, onClose]);

  if (!job || !isOpen) return null;

  return (
    <div className={styles.recoveryOverlay} onMouseDown={(event) => {
      if (event.target === event.currentTarget) onClose();
    }}>
      <aside
        className={styles.recoveryPanel}
        role="dialog"
        aria-modal="true"
        aria-labelledby="recovery-details-title"
      >
        <div className={styles.recoveryPanelHeader}>
          <div>
            <p className={styles.recoveryPanelEyebrow}>{job.fetchMethod} · {recovery?.mode || "SCHEDULED"}</p>
            <h2 id="recovery-details-title" className={styles.recoveryPanelTitle}>{job.partner}</h2>
          </div>
          <button ref={closeButtonRef} type="button" className={styles.recoveryClose} onClick={onClose} aria-label="Close recovery details">
            <span className="material-symbols-outlined" aria-hidden="true">close</span>
          </button>
        </div>

        <div className={styles.recoveryPanelBody}>
          <div className={styles.recoveryStatusHeader}>
            <Badge severity={isSafeDuplicate ? "low" : recovery ? statusSeverity(recovery.status) : runtimeStatusSeverity(runtimeStatus)}>
              {isSafeDuplicate ? "SAFE DUPLICATE" : recovery?.status || runtimeStatus || "—"}
            </Badge>
            <span className={styles.recoveryStreamKey}>{recovery?.streamKey || runtimeRun?.id || "No stream identity"}</span>
          </div>

          {runtimeRun && (
            <section className={styles.runtimeResultCard} aria-labelledby="runtime-result-title">
              <div className={styles.runtimeResultHeader}>
                <h3 id="runtime-result-title" className={styles.recoverySectionTitle}>Runtime result</h3>
                {isSafeDuplicate && <Badge severity="low">Skipped safely</Badge>}
              </div>
              <dl className={styles.recoveryMetaGrid}>
                <div><dt>Status</dt><dd>{isSafeDuplicate ? "SAFE_DUPLICATE" : runtimeRun.status || "-"}</dd></div>
                <div><dt>Runtime ID</dt><dd>{runtimeRun.id || runtimeRun._id || "-"}</dd></div>
                <div><dt>Source outcome</dt><dd>{String(runtimeStats.duplicateSourceOutcome || runtimeStats.outcome || "-")}</dd></div>
                <div><dt>Reconciliation</dt><dd>{runtimeRun.reconciliationCount ?? "Skipped"}</dd></div>
              </dl>
              <p className={styles.recoveryRuntimeMessage}>
                {isSafeDuplicate
                  ? job?.duplicateMessage || recovery?.duplicateMessage || runtimeRun.message || "The source was already processed and no new records were written."
                  : runtimeRun.message || "-"}
              </p>
            </section>
          )}

          <section className={styles.observabilitySection} aria-labelledby="ingestion-observability-title">
            <div className={styles.observabilityHeader}>
              <h3 id="ingestion-observability-title" className={styles.recoverySectionTitle}>Ingestion observability</h3>
              <span className={styles.observabilityNote}>Source-unit / terminal boundary snapshot</span>
            </div>
            {!stageSummary ? (
              <p className={styles.recoveryEmpty}>No persisted snapshot yet.</p>
            ) : (
              <>
                <dl className={styles.recoveryMetaGrid}>
                  <div><dt>Stage / outcome</dt><dd>{displayStage(stageSummary.currentStage, runtimeStatus)}</dd></div>
                  <div><dt>Status</dt><dd>{runtimeStatus || "—"}</dd></div>
                  <div><dt>Last persisted snapshot</dt><dd>{formatDateTime(stageSummary.updatedAt || runtimeRun?.updatedAt || job.latestFile?.updatedAt)}</dd></div>
                  <div><dt>Total duration</dt><dd>{formatDuration(stageSummary.durationMs ?? stageSummary.wallClockMs)}</dd></div>
                  <div><dt>Current unit</dt><dd>{stageSummary.currentUnitKey || recovery?.currentUnitKey || "—"}</dd></div>
                  <div><dt>Current page</dt><dd>{formatCount(stageSummary.currentPage ?? recovery?.currentPage)}</dd></div>
                  <div><dt>Runtime ID</dt><dd>{runtimeRun?.id || runtimeRun?._id || "—"}</dd></div>
                  <div><dt>Source file ID</dt><dd>{runtimeRun?.sourceFileId || job.latestFile?.id || "—"}</dd></div>
                </dl>

                <div className={styles.observabilitySubsection}>
                  <h4 className={styles.observabilitySubheading}>Stage durations</h4>
                  {Object.entries(stageSummary.stageDurationsMs || {}).length === 0 ? (
                    <p className={styles.recoveryEmpty}>No stage timings persisted.</p>
                  ) : (
                    <dl className={styles.observabilityMetricGrid}>
                      {Object.entries(stageSummary.stageDurationsMs || {}).map(([stage, value]) => (
                        <div key={stage}><dt>{formatStageName(stage)}</dt><dd>{formatDuration(value)}</dd></div>
                      ))}
                    </dl>
                  )}
                </div>

                <div className={styles.observabilitySubsection}>
                  <h4 className={styles.observabilitySubheading}>Row counters</h4>
                  <dl className={styles.observabilityMetricGrid}>
                    <div><dt>Input rows</dt><dd>{formatCount(stageSummary.inputRows)}</dd></div>
                    <div><dt>Persisted</dt><dd>{formatCount(stageSummary.persistedRows)}</dd></div>
                    <div><dt>Rejected</dt><dd>{formatCount(stageSummary.rejectedRows)}</dd></div>
                    <div><dt>Duplicate</dt><dd>{formatCount(stageSummary.duplicateRows)}</dd></div>
                    <div><dt>Persistence failed</dt><dd>{formatCount(stageSummary.persistenceFailedRows)}</dd></div>
                    <div><dt>Quarantined</dt><dd>{formatCount(stageSummary.quarantinedRows)}</dd></div>
                  </dl>
                </div>

                <div className={styles.observabilitySubsection}>
                  <h4 className={styles.observabilitySubheading}>Batch timing</h4>
                  <dl className={styles.observabilityMetricGrid}>
                    {timingEntries(stageSummary.batchMetrics).map(([label, value]) => (
                      <div key={label}><dt>{label}</dt><dd>{formatDuration(value)}</dd></div>
                    ))}
                    <div><dt>DB writes</dt><dd>{formatCount(stageSummary.batchMetrics?.dbWriteCount)}</dd></div>
                  </dl>
                </div>

                <div className={styles.observabilitySubsection}>
                  <h4 className={styles.observabilitySubheading}>Quality and errors</h4>
                  <dl className={styles.recoveryMetaGrid}>
                    <div><dt>Quality decision</dt><dd>{stageSummary.quality?.decision || "—"}</dd></div>
                    <div><dt>Top rule codes</dt><dd>{stageSummary.quality?.topRuleCodes?.join(", ") || "—"}</dd></div>
                    <div className={styles.observabilityWideItem}><dt>Last error</dt><dd>{stageSummary.lastErrorCode ? `${stageSummary.lastErrorCode}${stageSummary.lastError ? ` · ${stageSummary.lastError}` : ""}` : stageSummary.lastError || "—"}</dd></div>
                  </dl>
                </div>
              </>
            )}
          </section>

          {recovery && <>
          <dl className={styles.recoveryMetaGrid}>
            <div><dt>Last completed</dt><dd>{recovery.lastCompletedUnitKey || "-"}</dd></div>
            <div><dt>Current unit</dt><dd>{recovery.currentUnitKey || "-"}</dd></div>
            <div><dt>Cursor before</dt><dd>{recovery.cursorBefore || "-"}</dd></div>
            <div><dt>Request attempt</dt><dd>{recovery.requestAttemptCount} / {recovery.maxAttempts}</dd></div>
            <div><dt>Next retry</dt><dd>{recovery.nextRetryAt ? <RecoveryCountdown target={recovery.nextRetryAt} /> : formatDateTime(null)}</dd></div>
            <div><dt>Fetched units</dt><dd>{recovery.fetchedUnitCount} of {recovery.totalUnitCount}</dd></div>
          </dl>

          <section className={styles.recoveryTimeline} aria-labelledby="recovery-timeline-title">
            <h3 id="recovery-timeline-title" className={styles.recoverySectionTitle}>Fetch unit timeline</h3>
            {recovery.units.length === 0 ? (
              <p className={styles.recoveryEmpty}>No source-unit timeline is available yet.</p>
            ) : (
              <ol className={styles.recoveryTimelineList}>
                {recovery.units.map((unit) => (
                  <li key={unit.unitKey} className={styles.recoveryTimelineItem}>
                    <span className={`${styles.recoveryTimelineMarker} ${styles[`marker${unit.status}`]}`} aria-hidden="true">
                      {unitSymbol(unit.status)}
                    </span>
                    <div className={styles.recoveryTimelineCopy}>
                      <strong>{unitLabel(unit)}</strong>
                      <span>{unit.status}{unit.errorCode ? ` · ${unit.errorCode}` : ""}</span>
                    </div>
                  </li>
                ))}
              </ol>
            )}
          </section>

          <section className={styles.recoveryEvents} aria-labelledby="recovery-events-title">
            <h3 id="recovery-events-title" className={styles.recoverySectionTitle}>Event timeline</h3>
            {recovery.events.length === 0 ? (
              <p className={styles.recoveryEmpty}>No persisted recovery events are available yet.</p>
            ) : (
              <ol className={styles.recoveryEventList}>
                {recovery.events.map((event) => {
                  const eventStatus = String(event.status || "UNKNOWN")
                    .toUpperCase()
                    .replace(/[^A-Z0-9_]/g, "_");
                  return (
                    <li key={event.eventId} className={`${styles.recoveryEventItem} ${styles[`event${eventStatus}`]}`}>
                      <span className={styles.recoveryEventMarker} aria-hidden="true">
                        {eventSymbol(eventStatus)}
                      </span>
                      <div className={styles.recoveryEventCopy}>
                        <strong>
                          {event.status}{event.action ? ` · ${event.action}` : ""}
                        </strong>
                        <span>
                          {event.unitKey || "stream"} · Request {event.requestAttempt || 1}/{recovery.maxAttempts} · {formatDateTime(event.timestamp)}
                          {event.actor ? ` · ${event.actor}` : ""}
                        </span>
                        {(event.errorCode || event.reason || event.message) && (
                          <small>{event.errorCode || event.reason || event.message}</small>
                        )}
                      </div>
                    </li>
                  );
                })}
              </ol>
            )}
          </section>

          {configurationReviewRequired && !configurationReviewResolved && (
            <section className={styles.recoveryReviewPanel} aria-labelledby="recovery-review-title">
              <h3 id="recovery-review-title" className={styles.recoverySectionTitle}>Review required</h3>
              <p>Configuration approval is required before ingestion can continue.</p>
            </section>
          )}

          {(recovery.errorCode || recovery.lastError) && !configurationReviewRequired && !configurationReviewResolved && (
            <section className={styles.recoveryErrorPanel} aria-labelledby="recovery-error-title">
              <h3 id="recovery-error-title" className={styles.recoverySectionTitle}>Active error</h3>
              {recovery.errorCode && <code>{recovery.errorCode}</code>}
              {recovery.lastError && <p>{recovery.lastError}</p>}
            </section>
          )}

          {onResolve && recovery.status === "BLOCKED" && (
            <section className={styles.recoveryResolution} aria-labelledby="recovery-resolution-title">
              <h3 id="recovery-resolution-title" className={styles.recoverySectionTitle}>Operator resolution</h3>
              <label htmlFor="recovery-resolution-reason">Reason</label>
              <textarea
                id="recovery-resolution-reason"
                value={resolutionReason}
                onChange={(event) => setResolutionDraft({ partner: job.partner, reason: event.target.value })}
                placeholder="Explain why this blocked unit may be retried or skipped."
                maxLength={500}
                disabled={resolving}
              />
              <div className={styles.recoveryActions}>
                <Button
                  variant="primary"
                  onClick={() => onResolve("RETRY", resolutionReason.trim())}
                  disabled={resolving || !resolutionReason.trim()}
                >
                  {resolving ? "Saving…" : "Resolve for retry"}
                </Button>
                <Button
                  variant="secondary"
                  onClick={() => onResolve("SKIP", resolutionReason.trim())}
                  disabled={resolving || !resolutionReason.trim()}
                >
                  Skip unit
                </Button>
              </div>
            </section>
          )}
          </>}

          <div className={styles.recoveryActions}>
            {recovery && onRetry && recovery.retryable && (
              <Button variant="primary" onClick={onRetry} disabled={retrying}>
                {retrying ? "Retrying…" : "Retry now"}
              </Button>
            )}
            {onRefresh && <Button variant="secondary" onClick={onRefresh}>Refresh</Button>}
          </div>
        </div>
      </aside>
    </div>
  );
}
