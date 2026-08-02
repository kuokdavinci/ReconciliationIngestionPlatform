"use client";

import { useState } from "react";
import { Dialog } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import type { ReviewRecord } from "@/types/reconciliation";
import * as api from "@/lib/api/reconciliation";
import { useToast } from "@/components/ui/toast";
import dialogStyles from "@/components/ui/dialog.module.css";
import styles from "./reconciliation.module.css";

interface Props {
  selectedIds: string[];
  partner: string;
  date: string;
  open: boolean;
  onClose: () => void;
  onRefresh: () => void;
  onLocalBatchUpdate?: (recordKeys: string[], updatedRecords: Record<string, ReviewRecord>) => void;
  actionType: "APPROVE" | "FLAG";
}

export function BatchReviewDialog({
  selectedIds,
  partner,
  date,
  open,
  onClose,
  onRefresh,
  onLocalBatchUpdate,
  actionType,
}: Props) {
  const { showToast } = useToast();
  const [noteText, setNoteText] = useState("");
  const [resolvedStatus, setResolvedStatus] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleConfirmBatch = async () => {
    if (selectedIds.length === 0) return;
    setIsSubmitting(true);
    let successCount = 0;
    let failCount = 0;
    const updatedRecords: Record<string, ReviewRecord> = {};

    try {
      for (const id of selectedIds) {
        try {
          let response;
          if (actionType === "APPROVE") {
            const statusToApply = resolvedStatus || "FORCE_MATCHED";
            response = await api.resolveReviewRecord(id, {
              partner,
              date,
              resolvedStatus: statusToApply,
              actor: "Operator",
              note: noteText.trim() ? `[Batch Resolve] ${noteText}` : undefined,
            });
          } else {
            // For FLAG actionType, just mark as Reviewed (with comment) without resolving
            const noteContent = noteText.trim() ? `[Batch Review] ${noteText}` : "Marked reviewed via bulk action.";
            response = await api.addReviewNote(id, {
              partner,
              date,
              note: noteContent,
              actor: "Operator",
            });
          }
          if (response && response.record) {
            updatedRecords[id] = response.record as unknown as ReviewRecord;
          }
          successCount++;
        } catch {
          failCount++;
        }
      }

      if (failCount > 0) {
        showToast(
          `Batch process completed: ${successCount} successful, ${failCount} failed.`,
          "error"
        );
      } else {
        showToast(`Successfully processed ${successCount} records.`, "success");
      }

      if (Object.keys(updatedRecords).length > 0 && onLocalBatchUpdate) {
        onLocalBatchUpdate(Object.keys(updatedRecords), updatedRecords);
      } else {
        onRefresh();
      }
      onClose();
      setNoteText("");
      setResolvedStatus("");
    } catch {
      showToast("Batch review failed.", "error");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={actionType === "APPROVE" ? "Batch Approve & Resolve" : "Batch Mark Reviewed"}
      panelClassName={dialogStyles.medium}
    >
      <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        <p style={{ margin: 0, fontSize: 13.5, color: "var(--text-secondary)", lineHeight: 1.5 }}>
          You have selected <strong>{selectedIds.length}</strong> items to review. 
          Confirming will apply this feedback and update the review state across all selected records.
        </p>

        {actionType === "APPROVE" && (
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <label style={{ fontSize: 12.5, fontWeight: 600, color: "var(--text-muted)" }}>
              Resolution Status
            </label>
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
              }}
            >
              <option value="">Select Resolution Status</option>
              <option value="EXPECTED_FEE">Expected Fee Discrepancy</option>
              <option value="TEMPORARY_LAG">Settlement/Timing Lag</option>
              <option value="FORCE_MATCHED">Manually Verified Match</option>
            </select>
          </div>
        )}

        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <label style={{ fontSize: 12.5, fontWeight: 600, color: "var(--text-muted)" }}>
            Review Commentary (Comment)
          </label>
          <textarea
            placeholder="Add batch feedback, reason for discrepancy, or verification findings..."
            value={noteText}
            onChange={(e) => setNoteText(e.target.value)}
            rows={3}
            className={styles.commentTextarea}
          />
        </div>

        <div style={{ display: "flex", justifyContent: "flex-end", gap: 12, marginTop: 8 }}>
          <Button variant="secondary" onClick={onClose} disabled={isSubmitting}>
            Cancel
          </Button>
          <Button variant="primary" onClick={handleConfirmBatch} disabled={isSubmitting}>
            {isSubmitting ? "Processing..." : "Confirm batch actions"}
          </Button>
        </div>
      </div>
    </Dialog>
  );
}
