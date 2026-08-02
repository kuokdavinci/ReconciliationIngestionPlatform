import { useState } from "react";
import { Dialog } from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { ReconciliationRow, ReviewRecord } from "@/types/reconciliation";
import * as api from "@/lib/api/reconciliation";
import { useToast } from "@/components/ui/toast";
import dialogStyles from "@/components/ui/dialog.module.css";
import styles from "./reconciliation.module.css";

interface Props {
  row: ReconciliationRow | null;
  partner: string;
  date: string;
  open: boolean;
  onClose: () => void;
  onRefresh: () => void;
  onLocalUpdate?: (recordKey: string, updatedRecord: ReviewRecord) => void;
}

export function EvidenceDetailDialog({ row, partner, date, open, onClose, onRefresh, onLocalUpdate }: Props) {
  const { showToast } = useToast();
  const [noteText, setNoteText] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [resolvedStatus, setResolvedStatus] = useState("");

  if (!row) return null;

  const isMissing = /MISSING_/.test(row.reconciliationStatus);
  const sev = isMissing ? "high" : row.reconciliationStatus === "MATCHED" ? "low" : "medium" as const;
  const delta = row.delta ?? Math.abs(Number(row.internalAmount ?? 0) - Number(row.partnerAmount ?? 0));
  const traceId = row.partnerTxnId || row.internalTxnId || row.id;
  const deltaDirection = Number((row.partnerAmount ?? 0) - (row.internalAmount ?? 0)) > 0 ? "Partner higher" : "Internal higher";

  const handleAddNote = async () => {
    if (!noteText.trim()) return;
    setIsSubmitting(true);
    try {
      const response = await api.addReviewNote(traceId, {
        partner,
        date,
        note: noteText,
        actor: "Operator",
      });
      showToast("Feedback note added.", "success");
      setNoteText("");
      if (response && response.record && onLocalUpdate) {
        onLocalUpdate(traceId, response.record as unknown as ReviewRecord);
      } else {
        onRefresh();
      }
    } catch {
      showToast("Failed to add note.", "error");
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleResolve = async (status: string) => {
    setIsSubmitting(true);
    try {
      const response = await api.resolveReviewRecord(traceId, {
        partner,
        date,
        resolvedStatus: status,
        actor: "Operator",
        note: noteText.trim() ? noteText.trim() : undefined,
      });
      showToast(`Record marked resolved: ${status}`, "success");
      setNoteText("");
      if (response && response.record && onLocalUpdate) {
        onLocalUpdate(traceId, response.record as unknown as ReviewRecord);
      } else {
        onRefresh();
      }
    } catch {
      showToast("Failed to resolve record.", "error");
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleMarkReviewed = async () => {
    setIsSubmitting(true);
    const comment = noteText.trim() || "Marked as reviewed by Operator.";
    try {
      const response = await api.addReviewNote(traceId, {
        partner,
        date,
        note: comment,
        actor: "Operator",
      });
      showToast("Record marked as reviewed.", "success");
      setNoteText("");
      if (response && response.record && onLocalUpdate) {
        onLocalUpdate(traceId, response.record as unknown as ReviewRecord);
      } else {
        onRefresh();
      }
    } catch {
      showToast("Failed to mark as reviewed.", "error");
    } finally {
      setIsSubmitting(false);
    }
  };

  // Get notes from database record or fallback to basic audit timeline
  const notes = row.reviewState?.notes ?? [];
  const resolvedState = row.reviewState?.resolvedStatus;

  return (
    <Dialog open={open} onClose={onClose} title="Evidence Detail" panelClassName={dialogStyles.wide}>
      <div className={styles.dialogBadgeRow}>
        <Badge severity={sev}>{sev.toUpperCase()} RISK</Badge>
        <Badge severity={row.reconciliationStatus === "MATCHED" ? "low" : row.reconciliationStatus.startsWith("MISSING") ? "high" : "medium"}>{row.reconciliationStatus}</Badge>
        {resolvedState ? (
          <Badge severity="low">RESOLVED: {resolvedState}</Badge>
        ) : (
          <Badge severity="high">PENDING REVIEW</Badge>
        )}
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

        {row.reconciliationStatus !== "MATCHED" && (
          <section className={styles.dialogSection} style={{ gridColumn: "1 / -1", borderTop: "1px solid var(--border-subtle)", paddingTop: 16 }}>
            <strong className={styles.dialogHeading}>Discrepancy Actions</strong>
            <div style={{ display: "flex", gap: 12, alignItems: "center", marginTop: 8, flexWrap: "wrap" }}>
              <select
                value={resolvedStatus}
                onChange={(e) => setResolvedStatus(e.target.value)}
                style={{
                  background: "var(--bg-card)",
                  border: "1px solid var(--border-muted)",
                  padding: "8px 12px",
                  borderRadius: 6,
                  color: "#fff",
                  fontSize: 13,
                  width: 240,
                }}
              >
                <option value="">Select Resolution Status</option>
                <option value="EXPECTED_FEE">Expected Fee Discrepancy</option>
                <option value="TEMPORARY_LAG">Settlement/Timing Lag</option>
                <option value="FORCE_MATCHED">Manually Verified Match</option>
                <option value="OMITTED_PARTNER">Omitted by Partner (Flagged)</option>
              </select>
              <Button
                variant="primary"
                disabled={!resolvedStatus || isSubmitting}
                onClick={() => handleResolve(resolvedStatus)}
              >
                Resolve
              </Button>
              <span style={{ color: "var(--text-muted)", fontSize: 13 }}>or</span>
              <Button
                variant="secondary"
                disabled={isSubmitting}
                onClick={handleMarkReviewed}
              >
                Mark Reviewed
              </Button>
            </div>
          </section>
        )}

        <section className={styles.dialogSection} style={{ gridColumn: "1 / -1" }}>
          <strong className={styles.dialogHeading}>Operator Feedback Notes</strong>
          <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
            <textarea
              placeholder="Add review notes, confirmation findings or lag details..."
              value={noteText}
              onChange={(e) => setNoteText(e.target.value)}
              rows={2}
              className={styles.commentTextarea}
            />
            <Button
              variant="secondary"
              onClick={handleAddNote}
              disabled={!noteText.trim() || isSubmitting}
            >
              Add Comment
            </Button>
          </div>
        </section>

        <section className={styles.dialogSection} style={{ gridColumn: "1 / -1" }}>
          <strong className={styles.dialogHeading}>History & Feedback Logs</strong>
          <div className={styles.auditTrail} style={{ maxHeight: 180, overflowY: "auto" }}>
            {notes.length === 0 ? (
              <div style={{ padding: "8px 0", fontSize: 12.5, color: "var(--text-muted)", fontStyle: "italic" }}>
                No operator notes found. Audit trace shows record initial load.
              </div>
            ) : (
              notes.map((entry, i) => (
                <div key={i} className={styles.auditTrailRow}>
                  <span className={styles.auditTrailTime}>{entry.time}</span>
                  <span>{entry.event}</span>
                </div>
              ))
            )}
          </div>
        </section>
      </div>
    </Dialog>
  );
}
