"use client";

import { useEffect, useRef, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { RecoveryStatus, RecoveryUnitSummary, ScheduleJob } from "@/types/schedules";
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
  if (status === "COMPLETED" || status === "REPLAYED") return "low" as const;
  return "neutral" as const;
}

function unitSymbol(status: RecoveryUnitSummary["status"]) {
  if (status === "COMPLETED" || status === "SKIPPED" || status === "REPLAYED") return "✓";
  if (status === "FAILED" || status === "BLOCKED" || status === "WAITING_REVIEW") return "!";
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
  const isOpen = Boolean(job?.recovery);
  const recovery = job?.recovery;
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

  if (!job || !recovery) return null;

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
            <p className={styles.recoveryPanelEyebrow}>{job.fetchMethod} · {recovery.mode || "SCHEDULED"}</p>
            <h2 id="recovery-details-title" className={styles.recoveryPanelTitle}>{job.partner}</h2>
          </div>
          <button ref={closeButtonRef} type="button" className={styles.recoveryClose} onClick={onClose} aria-label="Close recovery details">
            <span className="material-symbols-outlined" aria-hidden="true">close</span>
          </button>
        </div>

        <div className={styles.recoveryPanelBody}>
          <div className={styles.recoveryStatusHeader}>
            <Badge severity={statusSeverity(recovery.status)}>{recovery.status}</Badge>
            <span className={styles.recoveryStreamKey}>{recovery.streamKey || "No stream identity"}</span>
          </div>

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
                {recovery.events.map((event) => (
                  <li key={event.eventId} className={styles.recoveryEventItem}>
                    <strong>
                      Request {event.requestAttempt || 1}/{recovery.maxAttempts} · {event.status}{event.action ? ` · ${event.action}` : ""}
                    </strong>
                    <span>
                      {event.unitKey || "stream"} · {formatDateTime(event.timestamp)}
                      {event.actor ? ` · ${event.actor}` : ""}
                    </span>
                    {(event.errorCode || event.reason || event.message) && (
                      <small>{event.errorCode || event.reason || event.message}</small>
                    )}
                  </li>
                ))}
              </ol>
            )}
          </section>

          {(recovery.errorCode || recovery.lastError) && (
            <section className={styles.recoveryErrorPanel} aria-labelledby="recovery-error-title">
              <h3 id="recovery-error-title" className={styles.recoverySectionTitle}>Error</h3>
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

          <div className={styles.recoveryActions}>
            {onRetry && recovery.retryable && (
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
