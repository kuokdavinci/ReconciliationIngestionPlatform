import { formatDisplayDate, formatDisplayDateTime } from "../../core/date.js";
import { escapeHtml } from "../../core/format.js";
import { statusLabel } from "../../core/status.js";
import { getActivePostApprovalRunForContext, isActiveRuntimeStatus } from "../../core/state-helpers.js";

export function getPartnerOptions(state) {
  const base = state.partnerOptions && state.partnerOptions.length
    ? state.partnerOptions
    : ["MOMO", "VNPAY", "ZALOPAY", "ACMEPAY"];
  return Array.from(new Set([...(state.partner ? [state.partner] : []), ...base]));
}

export function syncPartnerFilterOptions(state, container) {
  const partners = getPartnerOptions(state);
  const elements = (container || document).querySelectorAll("#partner-filter");
  elements.forEach(el => {
    const currentValue = state.partner && partners.includes(state.partner)
      ? state.partner
      : partners[0] || "";
    el.innerHTML = partners.map(p =>
      `<option value="${p}" ${p === currentValue ? "selected" : ""}>${p}</option>`
    ).join("");
    el.value = currentValue;
  });
}

export function renderPageFilters(state, options = {}) {
  const { showDate = true, showClear = true, showReconActions = false } = options;
  const reconRun = state.reconciliationRun;
  const reconStatus = String(reconRun?.status || "IDLE").toUpperCase();
  const postApprovalRun = getActivePostApprovalRunForContext(state);
  const reconBlockedByPostApproval = Boolean(postApprovalRun);
  const reconActionLabel = reconBlockedByPostApproval ? "Waiting for Approved Ingestion" : "Run Reconciliation";
  const reconStatusClass = reconStatus === "COMPLETED" ? "matched" : reconStatus === "FAILED" ? "failed" : isActiveRuntimeStatus(reconStatus) ? "warning" : "neutral";
  const reconStatusLabel = reconStatus === "IDLE" ? "No run" : statusLabel(reconStatus);
  const reconStatusDetail = reconBlockedByPostApproval
    ? (postApprovalRun.message || "Approved file is still being ingested before reconciliation can run.")
    : (reconRun?.message || (reconRun?.updatedAt ? `Updated ${formatDisplayDateTime(reconRun.updatedAt)}` : "No reconciliation run recorded"));
  return `
    <div class="page-filters" style="align-items: center;">
      <div class="filter-group">
        <span class="filter-label">PARTNER</span>
        <div class="filter-input-wrapper">
          <span class="material-symbols-outlined input-icon">store</span>
          <select id="partner-filter">
            ${getPartnerOptions(state).map(partner => `<option value="${partner}" ${partner === state.partner ? "selected" : ""}>${partner}</option>`).join("")}
          </select>
        </div>
      </div>
      ${showDate ? `
      <div class="filter-group">
        <span class="filter-label">DATE</span>
        <div class="date-inline-row">
          <div class="filter-input-wrapper date-current-input">
            <span class="material-symbols-outlined input-icon" style="color: #f8d76a;">edit_calendar</span>
            <input id="date-filter" type="text" value="${formatDisplayDate(state.date)}" placeholder="dd/mm/yyyy">
          </div>
          <div class="date-picker-trigger" data-action="open-date-picker" aria-label="Open date picker" style="cursor: pointer;">
            <span class="material-symbols-outlined">calendar_month</span>
            <input id="date-picker" type="date" value="${state.date}">
          </div>
        </div>
      </div>` : ""}
      ${showClear ? `
        <div class="filter-actions">
          <button class="button tertiary-action" data-action="clear-filters">Clear Filters</button>
        </div>
      ` : ""}
      ${showReconActions ? `
        <div style="margin-left: auto; display: flex; align-items: center; gap: 12px; height: 44px; margin-top: auto;">
          <button class="button primary compact" data-action="run-reconciliation-now" ${reconBlockedByPostApproval ? "disabled" : ""} style="padding: 4px 12px; font-size: 12px; display: inline-flex; align-items: center; gap: 4px; height: 32px; border-radius: 6px; background: var(--brand-accent-blue); color: black; font-weight: 600; border: none; ${reconBlockedByPostApproval ? "cursor:not-allowed; opacity:0.55;" : "cursor:pointer;"} box-shadow: var(--shadow);">
            <span class="material-symbols-outlined" style="font-size: 15px;">sync</span> ${reconActionLabel}
          </button>
          <div style="display: flex; align-items: center; gap: 6px;">
            <span class="badge ${reconStatusClass}" style="padding: 4px 8px; font-size: 11px; font-weight: 600; border-radius: 4px; border: none; text-transform: none; display: inline-flex; align-items: center; gap: 4px; height: 26px;">
              <span style="display: inline-block; width: 4px; height: 4px; border-radius: 50%; background: currentColor; opacity: 0.7;"></span>${escapeHtml(reconStatusLabel)}
            </span>
            <span style="font-size: 11px; color: var(--text-muted);">${escapeHtml(reconStatusDetail)}</span>
          </div>
          <button class="button primary compact" data-action="approve-all-recon" style="padding: 4px 12px; font-size: 12px; display: inline-flex; align-items: center; gap: 4px; height: 32px; border-radius: 6px; background: var(--brand-primary); color: black; font-weight: 600; border: none; cursor: pointer; box-shadow: var(--shadow);">
            <span class="material-symbols-outlined" style="font-size: 15px;">check_circle</span> Approve Run
          </button>
        </div>
      ` : ""}
    </div>
  `;
}
