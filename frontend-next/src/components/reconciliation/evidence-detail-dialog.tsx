"use client";

import { Dialog } from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import type { ReconciliationRow } from "@/types/reconciliation";
import dialogStyles from "@/components/ui/dialog.module.css";
import styles from "./reconciliation.module.css";

interface Props {
  row: ReconciliationRow | null;
  open: boolean;
  onClose: () => void;
}

export function EvidenceDetailDialog({ row, open, onClose }: Props) {
  if (!row) return null;

  const isMissing = /MISSING_/.test(row.reconciliationStatus);
  const sev = isMissing ? "high" : row.reconciliationStatus === "MATCHED" ? "low" : "medium" as const;
  const delta = row.delta ?? Math.abs(Number(row.internalAmount ?? 0) - Number(row.partnerAmount ?? 0));
  const traceId = row.partnerTxnId || row.internalTxnId || row.id;
  const deltaDirection = Number((row.partnerAmount ?? 0) - (row.internalAmount ?? 0)) > 0 ? "Partner higher" : "Internal higher";

  return (
    <Dialog open={open} onClose={onClose} title="Evidence Detail" panelClassName={dialogStyles.wide}>
      <div className={styles.dialogBadgeRow}>
        <Badge severity={sev}>{sev.toUpperCase()} RISK</Badge>
        <Badge severity={row.reconciliationStatus === "MATCHED" ? "low" : row.reconciliationStatus.startsWith("MISSING") ? "high" : "medium"}>{row.reconciliationStatus}</Badge>
        <Badge severity="neutral">Trace {traceId}</Badge>
      </div>

      <div className={styles.dialogBodyGrid}>
        <section className={styles.dialogSection}>
          <strong className={styles.dialogHeading}>Summary</strong>
          <p style={{ margin: 0, fontSize: 13, lineHeight: 1.55, color: "var(--text-primary)" }}>
            {isMissing
              ? "This transaction exists on only one side of the ledger and needs review before the batch can be considered complete."
              : `A monetary discrepancy was detected for this transaction. ${deltaDirection} by ${delta.toLocaleString()}.`}
          </p>
        </section>

        <section className={styles.dialogSection}>
          <strong className={styles.dialogHeading}>Evidence</strong>
          <div className={styles.evidenceCompareBox}>
            <div className={styles.evidenceCompareHead}>
              <span>Internal</span>
              <span>Partner</span>
            </div>
            <div className={styles.evidenceCompareRow}>
              <span>{row.internalAmount != null ? `${row.internalAmount.toLocaleString()}` : "—"}</span>
              <span>{row.partnerAmount != null ? `${row.partnerAmount.toLocaleString()}` : "—"}</span>
            </div>
            <div className={styles.evidenceCompareRow}>
              <span>{row.internalStatus ?? "—"}</span>
              <span>{row.partnerStatus ?? "—"}</span>
            </div>
            {delta > 0 && (
              <div className={styles.evidenceDelta}>Delta: {delta.toLocaleString()}</div>
            )}
          </div>
        </section>

        <section className={styles.dialogSection}>
          <strong className={styles.dialogHeading}>Operator Guidance</strong>
          <p style={{ margin: 0, fontSize: 12.5, lineHeight: 1.5, color: "var(--text-muted)" }}>
            {isMissing
              ? "Check whether the missing side is a settlement lag, a file omission, or a true synchronization issue before resolving the record."
              : "Review the source values and determine whether this delta is expected fee behavior or a real reconciliation discrepancy."}
          </p>
        </section>

        <section className={styles.dialogSection}>
          <strong className={styles.dialogHeading}>Audit Trail</strong>
          <div className={styles.auditTrail}>
            {[
              { time: "2026-06-10 10:00", event: "Internal ledger created" },
              { time: "2026-06-10 10:42", event: "Reconciliation run completed" },
            ].map((entry, i) => (
              <div key={i} className={styles.auditTrailRow}>
                <span className={styles.auditTrailTime}>{entry.time}</span>
                <span>{entry.event}</span>
              </div>
            ))}
          </div>
        </section>
      </div>
    </Dialog>
  );
}
