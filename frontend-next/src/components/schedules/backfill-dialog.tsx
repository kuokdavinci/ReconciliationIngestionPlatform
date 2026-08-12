"use client";

import { useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import styles from "./backfill.module.css";

interface Props {
  partner: string | null;
  open: boolean;
  submitting?: boolean;
  onClose: () => void;
  onSubmit: (fromDate: string, toDate: string) => Promise<void>;
}

function isoDate(date: Date) {
  return date.toISOString().slice(0, 10);
}

export function BackfillDialog({ partner, open, submitting = false, onClose, onSubmit }: Props) {
  const today = useMemo(() => new Date(), []);
  const [fromDate, setFromDate] = useState(() => isoDate(new Date(today.getTime() - 3 * 86_400_000)));
  const [toDate, setToDate] = useState(() => isoDate(today));
  const invalidRange = Boolean(fromDate && toDate && fromDate > toDate);
  const dayCount = (() => {
    if (!fromDate || !toDate || invalidRange) return 0;
    const start = new Date(`${fromDate}T00:00:00`);
    const end = new Date(`${toDate}T00:00:00`);
    let count = 0;
    for (const cursor = new Date(start); cursor <= end; cursor.setDate(cursor.getDate() + 1)) {
      if (cursor.getDay() !== 0 && cursor.getDay() !== 6) count += 1;
    }
    return count;
  })();

  return (
    <Dialog open={open} onClose={onClose} title={`Backfill ${partner || "partner"}`} panelClassName={styles.dialogPanel}>
      <form className={styles.form} onSubmit={(event) => {
        event.preventDefault();
        if (!invalidRange && fromDate && toDate) void onSubmit(fromDate, toDate);
      }}>
        <p className={styles.description}>Run this FileDrop stream through Airflow in ascending business-date order.</p>
        <div className={styles.dateGrid}>
          <label className={styles.field}>
            From date
            <input type="date" value={fromDate} onChange={(event) => setFromDate(event.target.value)} required />
          </label>
          <label className={styles.field}>
            To date
            <input type="date" value={toDate} onChange={(event) => setToDate(event.target.value)} required />
          </label>
        </div>
        {invalidRange && <p className={styles.error} role="alert">From date must be on or before to date.</p>}
        <div className={styles.preview}>
          <strong>{dayCount} business day{dayCount === 1 ? "" : "s"}</strong>
          <span>Sequential execution · scheduled checkpoint isolated</span>
        </div>
        <div className={styles.footer}>
          <Button type="button" variant="tertiary" onClick={onClose}>Cancel</Button>
          <Button type="submit" variant="primary" disabled={submitting || invalidRange || !fromDate || !toDate}>
            {submitting ? "Starting…" : "Start Backfill"}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
