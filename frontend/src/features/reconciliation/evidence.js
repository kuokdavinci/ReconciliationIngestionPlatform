import { escapeHtml, formatAmount } from "../../core/format.js";
import { highlightInsightText } from "./insights.js";

export function renderEvidencePopup(item, state) {
  if (!item) return "";
  const fallbackId = item.partnerTxnId || item.internalTxnId || item.id || "";
  
  const mockEvidenceRows = [
    {
      id: "MOMO_TXN_90_MISSING_PARTNER",
      aiExplanation: "The transaction is successfully registered on the internal ledger, but the partner settlement file contains no record of this Trace ID. This typically indicates a settlement lag or transaction drop on the partner side.",
      auditTrail: [
        { time: "2026-06-10 10:00", event: "Internal ledger created" },
        { time: "2026-06-10 10:42", event: "Reconciliation run: MISSING_PARTNER anomaly flag set" }
      ]
    },
    {
      id: "MOMO_TXN_9005",
      aiExplanation: "The transaction has matching identifiers on both sides, but the amount differs. Partner reports 999,999 VND while Internal DB reports 125,000 VND, leaving an absolute delta of 874,999 VND. This points to a mismatch in float mapping or commission configuration.",
      auditTrail: [
        { time: "2026-06-10 09:30", event: "Internal ledger created" },
        { time: "2026-06-10 09:35", event: "Partner transaction ingested" },
        { time: "2026-06-10 10:42", event: "Reconciliation run: AMOUNT_MISMATCH anomaly flag set" }
      ]
    },
    {
      id: "MOMO_TXN_9019",
      aiExplanation: "The partner settlement file records a transaction of 125,000 VND, but no corresponding transaction could be located on the internal ledger. This suggests a failure in the transaction sync pipeline or SFTP file processing latency.",
      auditTrail: [
        { time: "2026-06-10 09:40", event: "Partner transaction ingested" },
        { time: "2026-06-10 10:42", event: "Reconciliation run: MISSING_INTERNAL anomaly flag set" }
      ]
    }
  ];

  const detailFallback = mockEvidenceRows.find(r => r.id === fallbackId) || {
    aiExplanation: "Discrepancy detected during the latest reconciliation sweep. Please review the values on both sides.",
    auditTrail: [
      { time: "2026-06-10 10:42", event: "Reconciliation run: anomaly flag set" }
    ]
  };

  const statusBadge = (s) => {
    if (!s || s === "MISSING") return `<span class="badge warning" style="padding: 1px 4px; font-size:10px; border:none; margin-left: 2px;">MISSING</span>`;
    return `<span class="badge matched" style="padding: 1px 4px; font-size:10px; border:none; margin-left: 2px;">${escapeHtml(s)}</span>`;
  };

  const isMissing = /MISSING_/.test(item.reconciliationStatus);
  const sev = isMissing ? "HIGH" : (item.reconciliationStatus === "MATCHED" ? "LOW" : "MEDIUM");
  const deltaVal = Math.abs(Number(item.internalAmount || 0) - Number(item.partnerAmount || 0));

  return `
    <div class="evidence-detail-overlay" style="position: fixed; top: 0; left: 0; width: 100vw; height: 100vh; background: rgba(15, 23, 42, 0.45); backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px); display: flex; align-items: center; justify-content: center; z-index: 9999;">
      <div class="brief-modal" style="margin: 0; max-width: 550px; width: 100%; max-height: 90vh; overflow-y: auto; padding: 24px; border: 1px solid var(--border-color); border-radius: 12px; background: rgba(30, 41, 59, 0.95); color: white; box-shadow: var(--shadow);">
        <div class="review-drawer-header" style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 16px;">
          <div>
            <h4 style="margin: 0; font-size: 10px; text-transform: uppercase; color: var(--text-muted); letter-spacing: 0.05em;">Evidence Detail</h4>
            <h3 style="margin: 4px 0 0 0; font-size: 16px; font-weight: 700; color: white;">${escapeHtml(fallbackId)}</h3>
          </div>
          <button class="button tertiary compact" data-action="close-evidence-drawer" style="padding: 4px; min-width: unset; height: unset;">
            <span class="material-symbols-outlined" style="font-size: 20px;">close</span>
          </button>
        </div>

        <div style="margin-bottom: 16px; display: flex; gap: 6px; align-items: center;">
          <span class="badge severity-${sev.toLowerCase()}" style="font-size: 10px; padding: 2px 6px; font-weight: 700; border-radius: 4px;">${sev} RISK</span>
          <span class="badge neutral" style="font-size: 10px; padding: 2px 6px; border: none;">${escapeHtml(item.reconciliationStatus || "MISMATCH")}</span>
        </div>

        <div class="drawer-section" style="margin-bottom: 16px; border-bottom: 1px solid rgba(255,255,255,0.06); padding-bottom: 12px;">
          <h4 style="margin: 0 0 6px 0; font-size: 11px; text-transform: uppercase; color: var(--brand-primary); font-weight: 700; letter-spacing: 0.05em;">AI Explanation</h4>
          <p style="margin: 0; font-size: 12.5px; line-height: 1.45; color: var(--text-muted);">${highlightInsightText(detailFallback.aiExplanation)}</p>
        </div>

        <div class="drawer-section" style="margin-bottom: 16px; border-bottom: 1px solid rgba(255,255,255,0.06); padding-bottom: 12px;">
          <h4 style="margin: 0 0 6px 0; font-size: 11px; text-transform: uppercase; color: var(--brand-primary); font-weight: 700; letter-spacing: 0.05em;">Field-by-Field Compare</h4>
          <div style="background: rgba(0,0,0,0.25); border-radius: 6px; padding: 12px; font-family: var(--font-mono); font-size: 12px;">
            <div style="display: grid; grid-template-columns: 1fr 1fr; border-bottom: 1px solid rgba(255,255,255,0.05); padding-bottom: 6px; margin-bottom: 6px; font-weight: bold; color: var(--text-muted);">
              <span>Internal</span>
              <span>Partner</span>
            </div>
            <div style="display: grid; grid-template-columns: 1fr 1fr; margin-bottom: 6px;">
              <span style="color: ${item.internalAmount ? 'white' : 'var(--text-muted)'}; font-variant-numeric: tabular-nums;">Amt: ${item.internalAmount ? formatAmount(item.internalAmount) : '-'}</span>
              <span style="color: ${item.partnerAmount ? 'white' : 'var(--text-muted)'}; font-variant-numeric: tabular-nums;">Amt: ${item.partnerAmount ? formatAmount(item.partnerAmount) : '-'}</span>
            </div>
            <div style="display: grid; grid-template-columns: 1fr 1fr; margin-bottom: 6px;">
              <span>Status: ${statusBadge(item.internalStatus)}</span>
              <span>Status: ${statusBadge(item.partnerStatus)}</span>
            </div>
            <div style="margin-top: 8px; padding-top: 6px; border-top: 1px solid rgba(255,255,255,0.05); color: #ef4444; font-weight: 600;">
              <span>Delta: ${formatAmount(deltaVal)}</span>
            </div>
          </div>
        </div>

        <div class="drawer-section" style="margin-bottom: 16px; border-bottom: 1px solid rgba(255,255,255,0.06); padding-bottom: 12px;">
          <h4 style="margin: 0 0 6px 0; font-size: 11px; text-transform: uppercase; color: var(--brand-primary); font-weight: 700; letter-spacing: 0.05em;">Review Notes & Comments</h4>
          <textarea id="evidence-note-input" placeholder="Type your investigation findings, note, or comment for this mismatch..." style="width: 100%; height: 54px; background: rgba(0, 0, 0, 0.25); border: 1px solid var(--border-color); color: white; padding: 6px 10px; border-radius: 6px; font-size: 12px; resize: none; font-family: inherit; outline: none; margin-bottom: 8px;"></textarea>
        </div>

        <div class="drawer-section" style="margin-bottom: 20px;">
          <h4 style="margin: 0 0 6px 0; font-size: 11px; text-transform: uppercase; color: var(--brand-primary); font-weight: 700; letter-spacing: 0.05em;">Audit Trail & History</h4>
          <ul style="margin: 0; padding-left: 14px; font-size: 11px; color: var(--text-muted); line-height: 1.45;">
            ${(() => {
              const customNotes = (state.evidenceHistory && state.evidenceHistory[fallbackId]) || [];
              const combinedAuditTrail = [...detailFallback.auditTrail, ...customNotes];
              return combinedAuditTrail.map(t => `
                <li style="margin-bottom: 4px;">
                  <strong>${escapeHtml(t.time)}</strong>: ${escapeHtml(t.event)}
                </li>
              `).join("");
            })()}
          </ul>
        </div>

        <div style="display: flex; justify-content: flex-end; gap: 12px;">
          <button class="button secondary" data-action="close-evidence-drawer">Cancel</button>
          <button class="button primary" data-action="submit-anomaly-note" data-row-id="${escapeHtml(fallbackId)}" style="background: var(--brand-primary); color: black; font-weight: 600; border: none; cursor: pointer; display: inline-flex; align-items: center; gap: 4px; box-shadow: var(--shadow);">
            <span class="material-symbols-outlined" style="font-size: 16px;">bookmark_added</span> Save Note & Mark Reviewed
          </button>
        </div>
      </div>
    </div>
  `;
}
