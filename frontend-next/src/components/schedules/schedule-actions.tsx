"use client";

import { useState, useRef, useEffect } from "react";
import { Button } from "@/components/ui/button";
import type { ScheduleJob } from "@/types/schedules";
import styles from "./schedules.module.css";

interface Props {
  job: ScheduleJob;
  running: boolean;
  retrying: boolean;
  dropup?: boolean;
  onRun: () => void;
  onBackfill: () => void;
  onRetry?: () => void;
  onViewRecovery?: () => void;
  onOpenReview?: () => void;
}

export function ScheduleActions({
  job,
  running,
  retrying,
  dropup = false,
  onRun,
  onBackfill,
  onRetry,
  onViewRecovery,
  onOpenReview,
}: Props) {
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        setMenuOpen(false);
      }
    }
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setMenuOpen(false);
      }
    }

    if (menuOpen) {
      document.addEventListener("mousedown", handleClickOutside);
      document.addEventListener("keydown", handleKeyDown);
    }
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [menuOpen]);

  const runtimeActive = Boolean(job.activeRuntimeRun);
  const isFailedOrBlocked = job.status === "FAILED"
    || job.status === "BLOCKED"
    || job.recovery?.status === "FAILED"
    || job.recovery?.status === "BLOCKED";
  const isRetryable = Boolean(onRetry && (job.recovery?.retryable === true || isFailedOrBlocked));
  const backfillActive = Boolean(job.activeBackfill);

  // Determine Primary Action
  // 1. If retryable / failed: Primary action is Retry
  // 2. If running / active: Primary action is Running...
  // 3. Otherwise: Primary action is Run
  const showRetryAsPrimary = isRetryable && Boolean(onRetry);

  const runDisabled = running || runtimeActive || job.recovery?.status === "WAITING_REVIEW";
  const runBlockedByBackfill = backfillActive && !runDisabled;
  const retryDisabled = retrying || (
    Boolean(job.activeRuntimeRun)
    && job.status !== "RETRYING"
    && job.latestRuntimeRun?.orchestration?.taskState !== "up_for_retry"
  );

  return (
    <div className={styles.scheduleActionsGroup}>
      {/* Primary Action Button */}
      {showRetryAsPrimary && onRetry ? (
        <Button
          variant="primary"
          className={styles.primaryActionButton}
          onClick={onRetry}
          disabled={retryDisabled}
          title="Retry failed operation"
        >
          <span className="material-symbols-outlined" style={{ fontSize: 14 }}>refresh</span>
          <span>{retrying ? "Retrying…" : "Retry"}</span>
        </Button>
      ) : runtimeActive || running ? (
        <Button
          variant="secondary"
          className={styles.primaryActionButton}
          disabled
          title="Execution in progress"
        >
          <span className="material-symbols-outlined" style={{ fontSize: 14 }}>sync</span>
          <span>Running…</span>
        </Button>
      ) : (
        <Button
          variant="primary"
          className={`${styles.primaryActionButton} ${runBlockedByBackfill ? styles.blockedActionButton : ""}`}
          onClick={onRun}
          disabled={runDisabled}
          aria-disabled={runBlockedByBackfill || undefined}
          title={backfillActive ? "Backfill is active; continue from Backfill" : "Run schedule now"}
        >
          <span className="material-symbols-outlined" style={{ fontSize: 14 }}>play_arrow</span>
          <span>Run</span>
        </Button>
      )}

      {/* Overflow Menu (⋯) */}
      <div className={styles.overflowMenuContainer} ref={menuRef}>
        <button
          type="button"
          className={`${styles.overflowMenuButton} ${menuOpen ? styles.overflowMenuButtonActive : ""}`}
          onClick={() => setMenuOpen((prev) => !prev)}
          aria-haspopup="menu"
          aria-expanded={menuOpen}
          aria-label={`More options for ${job.partner}`}
          title="More options"
        >
          <span className="material-symbols-outlined" style={{ fontSize: 18 }}>more_horiz</span>
        </button>

        {menuOpen && (
          <div className={`${styles.dropdownMenu} ${dropup ? styles.dropdownMenuUp : ""}`} role="menu">
            {showRetryAsPrimary ? (
              <button
                type="button"
                role="menuitem"
                className={styles.dropdownMenuItem}
                onClick={() => { setMenuOpen(false); onRun(); }}
                disabled={runDisabled}
                aria-disabled={runBlockedByBackfill || undefined}
                title={backfillActive ? "Backfill is active; continue from Backfill" : undefined}
              >
                <span className="material-symbols-outlined" style={{ fontSize: 15 }}>play_arrow</span>
                <span>Run schedule now</span>
              </button>
            ) : isRetryable && onRetry ? (
              <button
                type="button"
                role="menuitem"
                className={styles.dropdownMenuItem}
                onClick={() => { setMenuOpen(false); onRetry(); }}
                disabled={retryDisabled}
              >
                <span className="material-symbols-outlined" style={{ fontSize: 15 }}>refresh</span>
                <span>Retry failed recovery</span>
              </button>
            ) : null}

            {onOpenReview && (
              <button
                type="button"
                role="menuitem"
                className={styles.dropdownMenuItem}
                onClick={() => { setMenuOpen(false); onOpenReview(); }}
              >
                <span className="material-symbols-outlined" style={{ fontSize: 15 }}>rate_review</span>
                <span>Open pending review</span>
              </button>
            )}

            <button
              type="button"
              role="menuitem"
              className={styles.dropdownMenuItem}
              onClick={() => { setMenuOpen(false); onBackfill(); }}
              disabled={running || runtimeActive}
            >
              <span className="material-symbols-outlined" style={{ fontSize: 15 }}>calendar_month</span>
              <span>Backfill date range…</span>
            </button>

            {onViewRecovery && (
              <button
                type="button"
                role="menuitem"
                className={styles.dropdownMenuItem}
                onClick={() => { setMenuOpen(false); onViewRecovery(); }}
              >
                <span className="material-symbols-outlined" style={{ fontSize: 15 }}>analytics</span>
                <span>View runtime details</span>
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
