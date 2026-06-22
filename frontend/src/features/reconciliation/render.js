import { formatDisplayDateTime } from "../../core/date.js";
import { formatAmount, formatNumber, escapeHtml } from "../../core/format.js";
import { badge } from "../../core/status.js";
import { table, renderEmptyState } from "../../core/dom.js";
import { renderInsightLoadingState, highlightInsightText } from "./insights.js";
import { renderEvidencePopup } from "./evidence.js";
import { renderPageFilters } from "../../shared/filters/render.js";

export function getFilteredReconItems(state, items) {
  const ef = state.explorerFilters || {};
  return items.filter(item => {
    if (state.reconStatus && item.reconciliationStatus !== state.reconStatus) return false;

    const pAmt = Number(item.partnerAmount || 0);
    const iAmt = Number(item.internalAmount || 0);
    const rowDelta = Math.abs(pAmt - iAmt);
    if (ef.amountMin && rowDelta < Number(ef.amountMin)) return false;
    if (ef.amountMax && rowDelta > Number(ef.amountMax)) return false;

    return true;
  });
}

export function renderVirtualReconRowsHtml(items, state) {
  return items.map(item => {
    const isMatched = item.reconciliationStatus === "MATCHED";
    const isMissing = /MISSING_/.test(item.reconciliationStatus);
    const sev = isMissing ? "HIGH" : (isMatched ? "LOW" : "MEDIUM");
    const rowId = item.partnerTxnId || item.internalTxnId || item.id;
    const delta = Math.abs(Number(item.partnerAmount || 0) - Number(item.internalAmount || 0));
    const direction = Number(delta) > 0 ? "up" : "down";
    const prefix = Number(delta) > 0 ? "+" : "-";
    const indicator = Number(delta) > 0 ? "▲" : "▼";
    const isSelected = !isMatched && state.selectedEvidenceRowId === rowId;
    const rowStyle = isSelected ? "background: rgba(240, 185, 11, 0.08); border-left: 3px solid var(--brand-primary);" : "";
    const isReviewed = state.reviewedRecords && state.reviewedRecords[rowId];
    const isBatchChecked = Boolean(state.selectedReconRows?.[rowId]);

    return `
      <tr style="${rowStyle}">
        <td style="text-align:center;">
          ${isMatched ? "" : `<input type="checkbox" data-action="toggle-recon-row" data-row-id="${escapeHtml(rowId)}" ${isBatchChecked ? "checked" : ""} />`}
        </td>
        <td><span class="badge severity-${sev.toLowerCase()}" style="font-size: 10px; padding: 1px 6px; border: none; font-weight: 600;">${sev}</span></td>
        <td>
          <span style="font-size: 11.5px; font-weight: 500;">${escapeHtml(item.reconciliationStatus || "MISMATCH")}</span>
          ${isReviewed ? `<span class="badge matched" style="font-size: 9px; padding: 1px 4px; border:none; margin-left: 6px; background: rgba(16, 185, 129, 0.15); color: #10b981;">Reviewed</span>` : ""}
        </td>
        <td><code>${escapeHtml(item.partnerTxnId || item.internalTxnId || "-")}</code></td>
        <td>${item.internalStatus ? `<span class="badge matched" style="font-size: 10px; padding: 1px 6px; border:none;">${escapeHtml(item.internalStatus)}</span>` : '<span class="badge warning" style="font-size:10px; padding:1px 6px; border:none;">MISSING</span>'}</td>
        <td>${item.partnerStatus ? `<span class="badge matched" style="font-size: 10px; padding: 1px 6px; border:none;">${escapeHtml(item.partnerStatus)}</span>` : '<span class="badge warning" style="font-size:10px; padding:1px 6px; border:none;">MISSING</span>'}</td>
        <td style="font-variant-numeric: tabular-nums;">${item.internalAmount ? formatAmount(item.internalAmount) : "-"}</td>
        <td style="font-variant-numeric: tabular-nums;">${item.partnerAmount ? formatAmount(item.partnerAmount) : "-"}</td>
        <td style="font-variant-numeric: tabular-nums; font-weight: 600; color: ${delta > 0 ? "#ef4444" : "var(--text-muted)"}">
          ${delta > 0 ? `<span class="diff-badge ${direction}"><span class="diff-badge-arrow">${indicator}</span>${prefix}${escapeHtml(formatNumber(Math.abs(Number(delta))))}</span>` : "-"}
        </td>
        <td style="text-align: center; width: 60px;">
          ${isMatched ? "-" : `<button class="button tertiary compact" data-action="open-evidence-detail" data-row-id="${escapeHtml(rowId)}" style="padding: 2px; min-width: unset; height: unset; display: inline-flex; align-items: center; justify-content: center; cursor: pointer; color: var(--brand-primary); background: transparent; border: none;"><span class="material-symbols-outlined" style="font-size: 18px;">visibility</span></button>`}
        </td>
      </tr>
    `;
  }).join("");
}

export function renderReconciliation(state, data) {
  function normalizeInsight(item = {}, fallbackCategory = "ANOMALY") {
    const category = String(item.category || item.type || fallbackCategory).toUpperCase();
    const severity = String(item.severity || "MEDIUM").toUpperCase();
    const affectedCount = Number(item.affectedCount ?? item.affected_count ?? item.evidence?.affectedRecords ?? 0);
    const partner = item.partner || state.partner || "";
    const metrics = Array.isArray(item.metrics) && item.metrics.length
      ? item.metrics.slice(0, 3)
      : [
          item.evidence?.deltaPerRecord ? { label: "delta each", value: formatAmount(item.evidence.deltaPerRecord) } : null,
          item.evidence?.sampleCoverage ? { label: "sample", value: `${item.evidence.sampleCoverage}%` } : null,
          partner ? { label: "partner", value: partner } : null
        ].filter(Boolean);
    return {
      id: item.id || `${category}_${item.title || "insight"}`,
      category,
      severity,
      title: item.title || "Insight",
      shortSummary: item.shortSummary || item.description || "Review this signal in detail.",
      affectedCount,
      partner,
      metrics,
      confidence: item.confidence,
      evidence: item.evidence || {},
      likelyCause: item.likelyCause || "Current evidence suggests a repeatable reconciliation issue that needs operator review.",
      recommendation: item.recommendation || {
        action: item.recommendation || "Review the affected records.",
        why: item.description || "This recommendation follows the observed evidence pattern.",
        owner: "Finance Operations",
        priority: severity,
        expectedOutcome: "Confirm whether the discrepancy is expected behavior or a true issue."
      },
      impact: item.impact || {
        currentImpact: affectedCount ? `${formatNumber(affectedCount)} records currently affected.` : "Observed impact is limited to the current sample.",
        potentialImpact: "",
        isEstimated: false,
      },
      samples: Array.isArray(item.samples) ? item.samples.slice(0, 3) : [],
      rawDescription: item.description || "",
    };
  }

  function renderDeltaBadge(deltaValue) {
    if (!deltaValue) return "";
    const direction = Number(deltaValue) > 0 ? "up" : "down";
    const prefix = Number(deltaValue) > 0 ? "+" : "-";
    const indicator = Number(deltaValue) > 0 ? "▲" : "▼";
    return `
      <span class="diff-badge ${direction}">
        <span class="diff-badge-arrow">${indicator}</span>
        ${prefix}${escapeHtml(formatNumber(Math.abs(Number(deltaValue))))}
      </span>
    `;
  }

  function getReconEmptyStateContent(status) {
    if (status === "MATCHED") {
      return {
        title: "All records matched perfectly for this period.",
        description: "There are no remaining discrepancies to review in the matched view.",
        icon: "task_alt",
      };
    }

    return {
      title: "No mismatches found with current filters.",
      description: "Try adjusting the status or amount filters to broaden the reconciliation view.",
      icon: "search_off",
    };
  }

  const items = data.results || [];
  const stats = state.insightsSummary || {};
  const byStatus = stats.byStatus || {};
  
  const totalAmountDiff = items.reduce((sum, item) => {
    const partnerAmount = Number(item.partnerAmount || 0);
    const internalAmount = Number(item.internalAmount || 0);
    return sum + Math.abs(partnerAmount - internalAmount);
  }, 0);
  const matchedCount = Number(byStatus.MATCHED || 0) + Number(byStatus.MATCHED_FAILED || 0) + Number(byStatus.MATCHED_REVERSED || 0);
  const mismatchRows =
    Number(byStatus.AMOUNT_MISMATCH || 0)
    + Number(byStatus.STATUS_MISMATCH || 0)
    + Number(byStatus.MULTIPLE_MISMATCH || 0)
    + Number(byStatus.UNMAPPED_SKIPPED || 0);
  const missingRows = Number(byStatus.MISSING_INTERNAL || 0) + Number(byStatus.MISSING_PARTNER || 0);
  const totalRows = Number(stats.total || data.total || items.length);
  const reviewedRowCount = Object.keys(state.reviewedRecords || {}).length;
  const allRowsLoaded = Number(data.offset || 0) === 0 && items.length >= totalRows;

  // Derived summary states
  const unreviewedMismatchRows = items.filter(item => {
    const isMatched = item.reconciliationStatus === "MATCHED";
    const isReviewed = state.reviewedRecords && state.reviewedRecords[item.partnerTxnId || item.internalTxnId || item.id];
    return !isMatched && !isReviewed && !/MISSING_/.test(item.reconciliationStatus || "");
  }).length;
  const unreviewedMissingRows = items.filter(item => {
    const isReviewed = state.reviewedRecords && state.reviewedRecords[item.partnerTxnId || item.internalTxnId || item.id];
    return /MISSING_/.test(item.reconciliationStatus || "") && !isReviewed;
  }).length;
  const pendingReviewCount = allRowsLoaded
    ? (unreviewedMismatchRows + unreviewedMissingRows)
    : Math.max((mismatchRows + missingRows) - reviewedRowCount, 0);
  const reviewStatus = pendingReviewCount > 0 ? "NEEDS_REVIEW" : "PASSED";
  const riskLevel = pendingReviewCount > 0 ? "HIGH" : "LOW";
  
  // 1. Improved Context Toolbar
  const toolbarHtml = renderPageFilters(state, { showDate: true, showClear: false, showReconActions: true });
  const run = state.reconciliationRun;
  const runStatus = String(run?.status || "IDLE").toUpperCase();
  const runStatusPanelHtml = `
    <section class="panel recon-section-panel">
      <div class="panel-header with-icon">
        <div>
          <h2 class="section-title">Reconciliation Run Status</h2>
          <p class="section-subtitle">Persisted runtime state for the selected partner and reconciliation date.</p>
        </div>
        <span class="material-symbols-outlined panel-header-icon">monitoring</span>
      </div>
      <div class="grid cols-4">
        <div class="metric compact">
          <span>Status</span>
          <strong>${badge(runStatus === "IDLE" ? "NO_ACTIVITY" : runStatus)}</strong>
          <small>${escapeHtml(run?.message || "No reconciliation run recorded yet.")}</small>
        </div>
        <div class="metric compact">
          <span>Started</span>
          <strong>${escapeHtml(run?.startedAt ? formatDisplayDateTime(run.startedAt) : "-")}</strong>
          <small>Runtime started time</small>
        </div>
        <div class="metric compact">
          <span>Finished</span>
          <strong>${escapeHtml(run?.finishedAt ? formatDisplayDateTime(run.finishedAt) : "-")}</strong>
          <small>Runtime finished time</small>
        </div>
        <div class="metric compact">
          <span>Results Written</span>
          <strong>${escapeHtml(String(run?.reconciliationCount ?? "-"))}</strong>
          <small>Persisted reconciliation results</small>
        </div>
      </div>
    </section>
  `;

  // 2. Semantic Risk Summary Strip
  const summaryStripHtml = `
    <div class="summary-strip recon-summary-strip">
      <div class="metric recon-summary-card">
        <span class="recon-summary-label">Review Status</span>
        <strong class="recon-summary-value ${reviewStatus === 'NEEDS_REVIEW' ? 'warning' : 'success'}">${reviewStatus === 'NEEDS_REVIEW' ? 'Needs Review' : 'Passed'}</strong>
      </div>
      <div class="metric recon-summary-card">
        <span class="recon-summary-label">Total Records</span>
        <strong class="recon-summary-value">${totalRows}</strong>
      </div>
      <div class="metric recon-summary-card">
        <span class="recon-summary-label">Missing Records</span>
        <strong class="recon-summary-value ${missingRows > 0 ? 'danger' : ''}">${missingRows}</strong>
      </div>
      <div class="metric recon-summary-card">
        <span class="recon-summary-label">Amount Delta</span>
        <strong class="recon-summary-value ${totalAmountDiff > 0 ? 'danger' : ''}">${formatAmount(totalAmountDiff)}</strong>
      </div>
    </div>
  `;

  // Compact Affected Records Preview
  const previewItems = items.filter(item => item.reconciliationStatus !== "MATCHED").slice(0, 3);
  const previewRows = previewItems.map(item => {
    const isMissing = /MISSING_/.test(item.reconciliationStatus);
    const sev = isMissing ? "HIGH" : "MEDIUM";
    const delta = Math.abs(Number(item.partnerAmount || 0) - Number(item.internalAmount || 0));
    const rowId = item.partnerTxnId || item.internalTxnId || item.id;
    const isSelected = state.selectedEvidenceRowId === rowId;
    const rowStyle = isSelected ? "background: rgba(240, 185, 11, 0.08); border-left: 3px solid var(--brand-primary);" : "";
    const isReviewed = state.reviewedRecords && state.reviewedRecords[rowId];

    return `
      <tr style="${rowStyle}">
        <td><span class="badge severity-${sev.toLowerCase()}" style="font-size: 10px; padding: 1px 6px; border: none; font-weight: 600;">${sev}</span></td>
        <td>
          <span style="font-size: 11.5px; font-weight: 500;">${escapeHtml(item.reconciliationStatus || "MISMATCH")}</span>
          ${isReviewed ? `<span class="badge matched" style="font-size: 9px; padding: 1px 4px; border:none; margin-left: 6px; background: rgba(16, 185, 129, 0.15); color: #10b981;">Reviewed</span>` : ""}
        </td>
        <td><code>${escapeHtml(item.partnerTxnId || item.internalTxnId || "-")}</code></td>
        <td>${item.internalStatus ? `<span class="badge matched" style="font-size: 10px; padding: 1px 6px; border:none;">${escapeHtml(item.internalStatus)}</span>` : '<span class="badge warning" style="font-size:10px; padding:1px 6px; border:none;">MISSING</span>'}</td>
        <td>${item.partnerStatus ? `<span class="badge matched" style="font-size: 10px; padding: 1px 6px; border:none;">${escapeHtml(item.partnerStatus)}</span>` : '<span class="badge warning" style="font-size:10px; padding:1px 6px; border:none;">MISSING</span>'}</td>
        <td style="font-variant-numeric: tabular-nums;">${item.internalAmount ? formatAmount(item.internalAmount) : "-"}</td>
        <td style="font-variant-numeric: tabular-nums;">${item.partnerAmount ? formatAmount(item.partnerAmount) : "-"}</td>
        <td style="font-variant-numeric: tabular-nums; font-weight: 600; color: ${delta > 0 ? '#ef4444' : 'var(--text-muted)'}">
          ${delta > 0 ? formatAmount(delta) : "-"}
        </td>
        <td style="text-align: center; width: 60px;">
          <button class="button tertiary compact" data-action="open-evidence-detail" data-row-id="${escapeHtml(rowId)}" style="padding: 2px; min-width: unset; height: unset; display: inline-flex; align-items: center; justify-content: center; cursor: pointer; color: var(--brand-primary); background: transparent; border: none;">
            <span class="material-symbols-outlined" style="font-size: 18px;">visibility</span>
          </button>
        </td>
      </tr>
    `;
  }).join("");

  const previewHeaders = ["Sev", "Issue Type", "Trace / TXN ID", "Internal Status", "Partner Status", "Internal Amount", "Partner Amount", "Delta", "Action"];

  const affectedPreviewHtml = `
    <div class="panel recon-preview-panel">
      <div class="recon-preview-header">
        <h4 class="recon-preview-title">Affected Records Preview</h4>
        <p class="recon-preview-subtitle">Records that caused the current verdict.</p>
      </div>
      ${previewRows.length ? table(previewHeaders, previewRows) : `
        <div class="empty-state-card recon-empty-card">
          <span class="material-symbols-outlined recon-empty-icon success">check_circle</span>
          <h3 class="recon-empty-title">Perfect Balance</h3>
          <p class="recon-empty-copy">All records are matched for this selection. No discrepancies found.</p>
        </div>
      `}
    </div>
  `;

  const insightSections = [
    { key: "anomalies", label: "Risk Signals" },
    { key: "patterns", label: "Trend Signals" },
    { key: "recommendations", label: "Operator Actions" }
  ];
  const renderInsightColumn = ({ key, label }) => {
    const sectionLoading = state.reconciliationInsightTabLoading === "all" && state.reconciliationInsightTabData?.[key] === null && !state.reconciliationInsightTabErrors?.[key];
    const sectionError = state.reconciliationInsightTabErrors?.[key];
    const sectionItems = Array.isArray(state.reconciliationInsightTabData?.[key]) ? state.reconciliationInsightTabData[key] : [];
    let bodyHtml = "";
    if (sectionLoading) {
      bodyHtml = renderInsightLoadingState(key);
    } else if (sectionError) {
      bodyHtml = `<div class="insight-content empty"><p class="muted">Unavailable.</p><p class="muted recon-insight-error">${escapeHtml(sectionError)}</p></div>`;
    } else if (!sectionItems.length) {
      bodyHtml = `<div class="insight-content empty"><p class="muted">No notable signals.</p></div>`;
    } else {
      bodyHtml = `
        <div class="recon-insight-column">
          ${sectionItems.slice(0, 2).map((rawItem, index) => {
            const item = normalizeInsight(rawItem, key.slice(0, -1));
            return `
            <div class="review-card recon-insight-card">
              ${index === 0 ? `<div class="recon-insight-label">${escapeHtml(label)}</div>` : ""}
              <div class="review-card-top recon-insight-top">
                <div class="recon-insight-title-row">
                  <span class="badge ${item.severity === 'CRITICAL' || item.severity === 'HIGH' ? 'failed' : item.severity === 'MEDIUM' ? 'warning' : 'matched'} recon-insight-severity">
                    ${escapeHtml(item.severity)}
                  </span>
                  <h3 class="recon-insight-title">${highlightInsightText(item.title)}</h3>
                </div>
                <span class="recon-insight-count">${formatNumber(item.affectedCount)} affected</span>
              </div>
              <div class="recon-insight-metrics">
                ${item.metrics.slice(0, 3).map(metric => `<span><strong style="color:white;">${escapeHtml(String(metric.value || "-"))}</strong>${metric.label ? ` ${escapeHtml(metric.label)}` : ""}</span>`).join('<span style="opacity:0.45;">·</span>')}
              </div>
              <p class="recon-insight-summary">${highlightInsightText(item.shortSummary)}</p>
              <div class="recon-insight-actions">
                <button class="button tertiary compact" data-action="open-copilot-explain" data-insight-payload="${escapeHtml(JSON.stringify(item))}">
                  Explain
                </button>
              </div>
            </div>
          `;}).join("")}
        </div>
      `;
    }
    return bodyHtml;
  };

  const tabsSectionHtml = `
    <div class="recon-insight-grid">
      ${insightSections.map(renderInsightColumn).join("")}
    </div>
  `;

  // 5. Evidence table markup
  const statusTabs = [
    ["", "All"],
    ["MATCHED", "Matched"],
    ["AMOUNT_MISMATCH", "Amount Mismatch"],
    ["STATUS_MISMATCH", "Status Mismatch"],
    ["MISSING_INTERNAL", "Missing Internal"],
    ["MISSING_PARTNER", "Missing Partner"]
  ].map(([value, label]) => `
    <button class="status-tab recon-status-tab ${state.reconStatus === value ? "active" : ""}" data-action="set-recon-status" data-status="${escapeHtml(value)}">
      ${escapeHtml(label)}
    </button>
  `).join("");

  const ef = state.explorerFilters || {};
  const filteredItems = items.filter(item => {
    if (state.reconStatus && item.reconciliationStatus !== state.reconStatus) return false;
    
    const pAmt = Number(item.partnerAmount || 0);
    const iAmt = Number(item.internalAmount || 0);
    const rowDelta = Math.abs(pAmt - iAmt);
    if (ef.amountMin && rowDelta < Number(ef.amountMin)) return false;
    if (ef.amountMax && rowDelta > Number(ef.amountMax)) return false;
    
    return true;
  });

  const selectedBatchKeys = Object.entries(state.selectedReconRows || {})
    .filter(([, selected]) => selected)
    .map(([key]) => key);
  
  const shouldVirtualize = filteredItems.length > 60;
  const virtualState = state.reconciliationVirtual || { startIndex: 0, rowHeight: 56, visibleCount: 40 };
  const virtualVisibleItems = shouldVirtualize
    ? filteredItems.slice(virtualState.startIndex, virtualState.startIndex + virtualState.visibleCount)
    : filteredItems;

  const headers = filteredItems.length > 0 
    ? ["<input type=\"checkbox\" data-action=\"toggle-recon-select-all\" />", "Sev", "Issue Type", "Trace / TXN ID", "Internal Status", "Partner Status", "Internal Amount", "Partner Amount", "Delta", "Action"]
    : ["Sev", "Issue Type", "Trace / TXN ID", "Internal Status", "Partner Status", "Internal Amount", "Partner Amount", "Delta", "Action"];

  const rows = virtualVisibleItems.map(item => {
    const isMatched = item.reconciliationStatus === "MATCHED";
    const isMissing = /MISSING_/.test(item.reconciliationStatus);
    const sev = isMissing ? "HIGH" : (isMatched ? "LOW" : "MEDIUM");

    const rowId = item.partnerTxnId || item.internalTxnId || item.id;
    const partnerAmtVal = Number(item.partnerAmount || 0);
    const internalAmtVal = Number(item.internalAmount || 0);
    const delta = Math.abs(partnerAmtVal - internalAmtVal);
    const isSelected = !isMatched && state.selectedEvidenceRowId === rowId;
    const rowStyle = isSelected ? "background: rgba(240, 185, 11, 0.08); border-left: 3px solid var(--brand-primary);" : "";
    const isReviewed = state.reviewedRecords && state.reviewedRecords[rowId];
    const isBatchChecked = Boolean(state.selectedReconRows?.[rowId]);

    let diffBadgeHtml = "";
    if (partnerAmtVal !== internalAmtVal) {
      const diffVal = partnerAmtVal - internalAmtVal;
      const arrow = diffVal > 0 ? "▲" : "▼";
      const formattedDiff = formatAmount(diffVal);
      const isPositive = diffVal > 0;
      const diffClass = isPositive ? "diff-positive" : "diff-negative";
      diffBadgeHtml = ` <span class="diff-badge ${diffClass}" style="margin-left:6px; font-variant-numeric: tabular-nums;">${arrow}${formattedDiff}</span>`;
    }

    return `
      <tr style="${rowStyle}">
        <td style="text-align:center;">
          ${isMatched ? "" : `<input type="checkbox" data-action="toggle-recon-row" data-row-id="${escapeHtml(rowId)}" ${isBatchChecked ? "checked" : ""} />`}
        </td>
        <td><span class="badge severity-${sev.toLowerCase()}" style="font-size: 10px; padding: 1px 6px; border: none; font-weight: 600;">${sev}</span></td>
        <td>
          <span style="font-size: 11.5px; font-weight: 500;">${escapeHtml(item.reconciliationStatus || "MISMATCH")}</span>
          ${isReviewed ? `<span class="badge matched" style="font-size: 9px; padding: 1px 4px; border:none; margin-left: 6px; background: rgba(16, 185, 129, 0.15); color: #10b981;">Reviewed</span>` : ""}
        </td>
        <td><code>${escapeHtml(item.partnerTxnId || item.internalTxnId || "-")}</code></td>
        <td>${item.internalStatus ? `<span class="badge matched" style="font-size: 10px; padding: 1px 6px; border:none;">${escapeHtml(item.internalStatus)}</span>` : '<span class="badge warning" style="font-size:10px; padding:1px 6px; border:none;">MISSING</span>'}</td>
        <td>${item.partnerStatus ? `<span class="badge matched" style="font-size: 10px; padding: 1px 6px; border:none;">${escapeHtml(item.partnerStatus)}</span>` : '<span class="badge warning" style="font-size:10px; padding:1px 6px; border:none;">MISSING</span>'}</td>
        <td style="font-variant-numeric: tabular-nums;">${item.internalAmount ? formatAmount(item.internalAmount) : "-"}</td>
        <td style="font-variant-numeric: tabular-nums;">${item.partnerAmount ? formatAmount(item.partnerAmount) : "-"}</td>
        <td style="font-variant-numeric: tabular-nums; font-weight: 600; color: ${delta > 0 ? '#ef4444' : 'var(--text-muted)'}">${delta > 0 ? formatAmount(delta) : "-"}${diffBadgeHtml}</td>
        <td style="text-align: center; width: 60px;">
          ${isMatched ? '-' : `
            <button class="button tertiary compact" data-action="open-evidence-detail" data-row-id="${escapeHtml(rowId)}" style="padding: 2px; min-width: unset; height: unset; display: inline-flex; align-items: center; justify-content: center; cursor: pointer; color: var(--brand-primary); background: transparent; border: none;">
              <span class="material-symbols-outlined" style="font-size: 18px;">visibility</span>
            </button>
          `}
        </td>
      </tr>
    `;
  }).join("");

  const mobileCardsHtml = filteredItems.map(item => {
    const isMatched = item.reconciliationStatus === "MATCHED";
    const isMissing = /MISSING_/.test(item.reconciliationStatus);
    const sev = isMissing ? "HIGH" : (isMatched ? "LOW" : "MEDIUM");
    const rowId = item.partnerTxnId || item.internalTxnId || item.id;
    const partnerAmtVal = Number(item.partnerAmount || 0);
    const internalAmtVal = Number(item.internalAmount || 0);
    const delta = Math.abs(partnerAmtVal - internalAmtVal);
    const isReviewed = state.reviewedRecords && state.reviewedRecords[rowId];
    const isBatchChecked = Boolean(state.selectedReconRows?.[rowId]);

    let diffBadgeHtml = "";
    if (partnerAmtVal !== internalAmtVal) {
      const diffVal = partnerAmtVal - internalAmtVal;
      const arrow = diffVal > 0 ? "▲" : "▼";
      const formattedDiff = formatAmount(diffVal);
      const isPositive = diffVal > 0;
      const diffClass = isPositive ? "diff-positive" : "diff-negative";
      diffBadgeHtml = ` <span class="diff-badge ${diffClass}" style="margin-left:6px; font-variant-numeric: tabular-nums;">${arrow}${formattedDiff}</span>`;
    }

    return `
      <div class="mobile-recon-card recon-mobile-card">
        <div class="recon-mobile-card-head">
          <div class="recon-mobile-card-head-left">
            ${isMatched ? "" : `<input type="checkbox" data-action="toggle-recon-row" data-row-id="${escapeHtml(rowId)}" ${isBatchChecked ? "checked" : ""} />`}
            <span class="badge severity-${sev.toLowerCase()} recon-mobile-severity">${sev}</span>
            <code class="recon-mobile-trace">${escapeHtml(rowId)}</code>
          </div>
          ${isMatched ? '-' : `
            <button class="button tertiary compact recon-icon-button recon-icon-button-lg" data-action="open-evidence-detail" data-row-id="${escapeHtml(rowId)}">
              <span class="material-symbols-outlined recon-icon-lg">visibility</span>
            </button>
          `}
        </div>
        <div class="recon-mobile-card-status-row">
          <span class="recon-mobile-status">
            ${escapeHtml(item.reconciliationStatus || "MISMATCH")}
            ${isReviewed ? `<span class="badge matched recon-reviewed-badge">Reviewed</span>` : ""}
          </span>
          <span class="recon-mobile-delta ${delta > 0 ? 'has-delta' : ''}">${delta > 0 ? `Δ ${formatAmount(delta)}` : "No Delta"}${diffBadgeHtml}</span>
        </div>
        <div class="recon-mobile-compare-grid">
          <div>
            <div class="recon-mobile-compare-label">Internal</div>
            <div>${item.internalStatus ? `<span class="badge matched recon-mobile-mini-badge">${escapeHtml(item.internalStatus)}</span>` : '<span class="badge warning recon-mobile-mini-badge">MISSING</span>'}</div>
            <div class="recon-mobile-amount">${item.internalAmount ? formatAmount(item.internalAmount) : "-"}</div>
          </div>
          <div>
            <div class="recon-mobile-compare-label">Partner</div>
            <div>${item.partnerStatus ? `<span class="badge matched recon-mobile-mini-badge">${escapeHtml(item.partnerStatus)}</span>` : '<span class="badge warning recon-mobile-mini-badge">MISSING</span>'}</div>
            <div class="recon-mobile-amount">${item.partnerAmount ? formatAmount(item.partnerAmount) : "-"}</div>
          </div>
        </div>
      </div>
    `;
  }).join("");

  const responsiveStyleHtml = `
    <style>
      @media (max-width: 768px) {
        .desktop-only-table { display: none !important; }
        .mobile-only-cards { display: block !important; }
      }
      @media (min-width: 769px) {
        .desktop-only-table { display: block !important; }
        .mobile-only-cards { display: none !important; }
      }
    </style>
  `;

  const tableFiltersHtml = `
    <div class="page-filters explorer-filters recon-filter-bar">
      <span class="recon-filter-label">Explorer Filters:</span>
      <input id="amount-min" class="recon-filter-input" type="text" placeholder="Min Delta" value="${escapeHtml(ef.amountMin || '')}">
      <input id="amount-max" class="recon-filter-input" type="text" placeholder="Max Delta" value="${escapeHtml(ef.amountMax || '')}">
      <button class="button primary recon-filter-button" data-action="apply-recon-filters">Apply</button>
      <button class="button secondary recon-filter-button" data-action="clear-recon-filters">Clear</button>
    </div>
  `;

  const isBulkBarVisible = selectedBatchKeys.length > 0;
  const bulkActionFloatingBarHtml = `
    <div id="bulk-action-bar" class="${isBulkBarVisible ? 'visible' : ''}">
      <div class="bulk-action-content">
        <div class="bulk-action-selected-text">
          <span class="material-symbols-outlined">ballot</span>
          <span><strong id="bulk-selected-count">${selectedBatchKeys.length}</strong> items selected</span>
        </div>
        <div class="bulk-action-buttons">
          <select id="recon-batch-status" style="height: 32px; background: var(--bg-input); border: 1px solid var(--border-color); color: var(--text-main); border-radius: 6px; padding: 2px 8px; font-size: 12px; outline: none; cursor: pointer; margin-right: 8px;">
            <option value="MATCHED">Resolve as MATCHED</option>
            <option value="MISSING_INTERNAL">Resolve as MISSING_INTERNAL</option>
            <option value="MISSING_PARTNER">Resolve as MISSING_PARTNER</option>
            <option value="STATUS_MISMATCH">Resolve as STATUS_MISMATCH</option>
          </select>
          <button class="button primary" data-action="batch-review-selected" style="height: 32px; font-size: 12px; padding: 4px 12px;">Apply Action</button>
          <button class="button secondary" data-action="clear-batch-selection" style="height: 32px; font-size: 12px; padding: 4px 12px; background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); margin-left: 8px;">Clear</button>
        </div>
      </div>
    </div>
  `;

  const batchReviewHtml = selectedBatchKeys.length > 0 ? bulkActionFloatingBarHtml : (filteredItems.some(item => item.reconciliationStatus !== "MATCHED") ? `
    <div class="page-filters explorer-filters" style="margin-top: 10px; margin-bottom: 12px; padding: 8px 12px; border-radius: 6px; background: rgba(0,0,0,0.15); display: flex; flex-wrap: wrap; gap: 8px; align-items: center; justify-content: space-between;">
      <div style="display:flex; gap:8px; align-items:center;">
        <label style="display:inline-flex; gap:6px; align-items:center; font-size:11px; color: var(--text-muted); cursor: pointer;">
          <input type="checkbox" data-action="toggle-recon-select-all" ${selectedBatchKeys.length && selectedBatchKeys.length === filteredItems.filter(item => item.reconciliationStatus !== "MATCHED").length ? "checked" : ""}/>
          Select visible mismatches
        </label>
        <span style="font-size:11px; color: var(--text-muted);">Select rows to trigger Bulk Actions</span>
      </div>
    </div>
    ${bulkActionFloatingBarHtml}
  ` : "");

  let emptyStateHtml = "";
  if (filteredItems.length === 0) {
    if (state.reconStatus === "MATCHED") {
      emptyStateHtml = `
        <div class="empty-state-card recon-empty-card recon-empty-card-lg">
          <span class="material-symbols-outlined recon-empty-icon success lg">task_alt</span>
          <h3 class="recon-empty-title recon-empty-title-lg">Perfect Match</h3>
          <p class="recon-empty-copy recon-empty-copy-lg">All records matched perfectly for this period.</p>
        </div>
      `;
    } else {
      emptyStateHtml = `
        <div class="empty-state-card recon-empty-card recon-empty-card-lg">
          <span class="material-symbols-outlined recon-empty-icon brand lg">search_off</span>
          <h3 class="recon-empty-title recon-empty-title-lg">No Mismatches Found</h3>
          <p class="recon-empty-copy recon-empty-copy-lg">No mismatch records found with current filters.</p>
        </div>
      `;
    }
  }

  const pageLimit = Number(data.limit || state.reconciliationPagination?.limit || 25);
  const pageOffset = Number(data.offset || state.reconciliationPagination?.offset || 0);
  const pageStart = totalRows ? pageOffset + 1 : 0;
  const pageEnd = Math.min(pageOffset + pageLimit, totalRows);
  const hasPrevPage = pageOffset > 0;
  const hasNextPage = pageOffset + pageLimit < totalRows;
  const currentPage = totalRows ? Math.floor(pageOffset / pageLimit) + 1 : 1;
  const totalPages = Math.max(1, Math.ceil(totalRows / pageLimit));
  const paginationHtml = `
    <div class="page-filters explorer-filters" style="margin-top: 12px; padding: 8px 12px; border-radius: 6px; background: rgba(0,0,0,0.15); display: flex; flex-wrap: wrap; gap: 10px; align-items: center; justify-content: space-between;">
      <div style="font-size: 11px; color: var(--text-muted);">
        Showing <strong>${formatNumber(pageStart)}</strong>-<strong>${formatNumber(pageEnd)}</strong> of <strong>${formatNumber(totalRows)}</strong> records
        <span style="margin-left:8px;">Page <strong>${formatNumber(currentPage)}</strong> of <strong>${formatNumber(totalPages)}</strong></span>
      </div>
      <div style="display:flex; gap:8px; align-items:center;">
        <label style="font-size:11px; color: var(--text-muted);">Page size</label>
        <select id="recon-page-size" style="height: 28px; background: var(--bg-input); border: 1px solid var(--border-color); color: var(--text-main); border-radius: 4px; padding: 2px 6px;">
          ${[25, 50].map(size => `<option value="${size}" ${size === pageLimit ? "selected" : ""}>${size}</option>`).join("")}
        </select>
        <button class="button secondary" data-action="recon-set-page-size" style="height: 28px; font-size: 11px; padding: 2px 8px;">Apply</button>
        <button class="button secondary" data-action="recon-prev-page" ${hasPrevPage ? "" : "disabled"} style="height: 28px; font-size: 11px; padding: 2px 8px;">Previous</button>
        <button class="button secondary" data-action="recon-next-page" ${hasNextPage ? "" : "disabled"} style="height: 28px; font-size: 11px; padding: 2px 8px;">Next</button>
      </div>
    </div>
  `;

  const emptyState = getReconEmptyStateContent(state.reconStatus);
  const topSpacerHeight = shouldVirtualize ? virtualState.startIndex * virtualState.rowHeight : 0;
  const bottomSpacerHeight = shouldVirtualize
    ? Math.max(0, (filteredItems.length - (virtualState.startIndex + virtualVisibleItems.length)) * virtualState.rowHeight)
    : 0;
  const evidenceTableHtml = `
    <section class="panel evidence-table-section">
      ${responsiveStyleHtml}
      <div class="recon-ledger-header">
        <div>
          <h2 class="section-title recon-ledger-title">Reconciliation Evidence Ledger</h2>
          <p class="section-subtitle recon-ledger-subtitle">Select a row to inspect full comparison detail and trigger adjustment options.</p>
        </div>
        <div class="recon-ledger-status-tabs">
          ${statusTabs}
        </div>
      </div>
      ${tableFiltersHtml}
      ${filteredItems.length ? `
        <div class="desktop-only-table">
          ${shouldVirtualize ? `
            <div class="table-wrap recon-virtual-scroll" data-virtualized="true" style="max-height: 720px; overflow-y: auto;" data-total-rows="${filteredItems.length}" data-row-height="${virtualState.rowHeight}">
              <table>
                <thead><tr>${headers.map(h => `<th>${h}</th>`).join("")}</tr></thead>
                <tbody>
                  <tr aria-hidden="true"><td colspan="${headers.length}" style="padding:0; border:none; height:${topSpacerHeight}px;"></td></tr>
                  ${rows}
                  <tr aria-hidden="true"><td colspan="${headers.length}" style="padding:0; border:none; height:${bottomSpacerHeight}px;"></td></tr>
                </tbody>
              </table>
            </div>
          ` : table(headers, rows)}
        </div>
        <div class="mobile-only-cards" style="display: none;">
          ${mobileCardsHtml}
        </div>
      ` : emptyStateHtml}
      ${paginationHtml}
    </section>
  `;

  // 6. Drawers and Modal layers
  const selectedRow = items.find(item => 
    (item.partnerTxnId || item.internalTxnId || item.id) === state.selectedEvidenceRowId
  );

  let modalHtml = "";
  if (state.adjustmentModalData) {
    modalHtml = `
      <div class="guided-review-overlay" style="position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.6); display: flex; align-items: center; justify-content: center; z-index: 1000;">
        <div class="brief-modal" style="padding: 24px; max-width: 500px; width: 100%;">
           <div class="brief-modal-header" style="margin-bottom: 16px; display: flex; justify-content: space-between; align-items: flex-start;">
              <div>
                 <span class="brief-eyebrow" style="color: var(--brand-primary); font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing:0.05em;">Create Manual Adjustment</span>
                 <h3 style="margin: 4px 0 0 0; color: white; font-size: 16px;">Prefilled Adjustment Form</h3>
              </div>
              <button class="button tertiary compact" data-action="close-adjustment-modal" style="padding: 4px; min-width: unset; height: unset;">
                 <span class="material-symbols-outlined" style="font-size: 18px;">close</span>
              </button>
           </div>
           <div style="padding: 10px 0 20px; color: var(--text-main); font-size: 13.5px;">
              <div style="margin-bottom: 12px;">
                 <label style="display: block; font-size: 11px; text-transform: uppercase; color: var(--text-muted); font-weight: 600; margin-bottom: 4px;">Transaction ID / Trace ID</label>
                 <input type="text" value="${escapeHtml(state.adjustmentModalData.txnId)}" readonly style="width: 100%; padding: 8px; background: var(--bg-input); border: 1px solid var(--border-color); color: var(--text-main); border-radius: 4px; font-family: monospace;">
              </div>
              <div style="margin-bottom: 12px;">
                 <label style="display: block; font-size: 11px; text-transform: uppercase; color: var(--text-muted); font-weight: 600; margin-bottom: 4px;">Adjustment Amount (VND)</label>
                 <input type="text" value="${escapeHtml(state.adjustmentModalData.amount)}" style="width: 100%; padding: 8px; background: var(--bg-input); border: 1px solid var(--border-color); color: var(--text-main); border-radius: 4px;">
              </div>
              <div style="margin-bottom: 12px;">
                 <label style="display: block; font-size: 11px; text-transform: uppercase; color: var(--text-muted); font-weight: 600; margin-bottom: 4px;">Reason for Adjustment</label>
                 <select style="width: 100%; padding: 8px; background: var(--bg-input); border: 1px solid var(--border-color); color: var(--text-main); border-radius: 4px; height: 34px;">
                    <option>Fee reconciliation drift</option>
                    <option>Late settlement batch processing</option>
                    <option>Manual system exception override</option>
                 </select>
              </div>
           </div>
           <div style="display: flex; justify-content: flex-end; gap: 12px;">
              <button class="button secondary" data-action="close-adjustment-modal">Cancel</button>
              <button class="button primary" data-action="submit-adjustment">Submit Adjustment</button>
           </div>
        </div>
      </div>
    `;
  }

  const explainPanelHtml = state.copilotExplainItem ? `
    <div class="guided-review-overlay" style="position: fixed; inset: 0; background: rgba(0,0,0,0.58); display: flex; align-items: center; justify-content: center; z-index: 1000; padding: 16px;">
      <div class="brief-modal" style="max-width: 860px; width: 100%; max-height: 88vh;">
        <div class="brief-modal-header">
          <div>
            <span class="brief-eyebrow">Explain</span>
            <h3 style="margin:4px 0 0 0; color:white;">${escapeHtml(state.copilotExplainItem.title || "Insight")}</h3>
          </div>
          <button class="button tertiary compact" data-action="close-copilot-explain"><span class="material-symbols-outlined">close</span></button>
        </div>
        <div class="brief-modal-content">
        <div class="copilot-explain-body" style="padding:0;">
          <div class="copilot-explain-chip-row" style="margin-bottom:16px;">
            <span class="badge neutral">${escapeHtml(String(state.copilotExplainItem.category || "ANOMALY"))}</span>
            <span class="badge ${["CRITICAL", "HIGH"].includes(String(state.copilotExplainItem.severity || "MEDIUM").toUpperCase()) ? "failed" : String(state.copilotExplainItem.severity || "MEDIUM").toUpperCase() === "MEDIUM" ? "warning" : "matched"}">${escapeHtml(String(state.copilotExplainItem.severity || "MEDIUM").toUpperCase())}</span>
            <span class="badge neutral">${formatNumber(state.copilotExplainItem.affectedCount || 0)} affected</span>
            ${state.copilotExplainItem.confidence ? `<span class="badge neutral">${escapeHtml(String(state.copilotExplainItem.confidence))} confidence</span>` : ""}
          </div>
          <section class="copilot-explain-section">
            <strong>Summary</strong>
            <p>${escapeHtml(state.copilotExplainItem.shortSummary || state.copilotExplainItem.rawDescription || "This insight summarizes the most relevant signal found in the current reconciliation set.")}</p>
          </section>
          <section class="copilot-explain-section">
            <strong>Evidence</strong>
            <div style="display:grid; grid-template-columns:1fr 1fr; gap:10px; font-size:12px; color:var(--text-muted);">
              <div>Affected records: <strong style="color:white;">${formatNumber(state.copilotExplainItem.evidence?.affectedRecords || state.copilotExplainItem.affectedCount || 0)}</strong></div>
              ${state.copilotExplainItem.evidence?.deltaPerRecord ? `<div>Delta per record: <strong style="color:white;">${formatAmount(state.copilotExplainItem.evidence.deltaPerRecord)}</strong></div>` : ""}
              ${state.copilotExplainItem.evidence?.totalObservedDelta ? `<div>Total observed delta: <strong style="color:white;">${formatAmount(state.copilotExplainItem.evidence.totalObservedDelta)}</strong></div>` : ""}
              <div>Pattern type: <strong style="color:white;">${escapeHtml(String(state.copilotExplainItem.evidence?.patternType || state.copilotExplainItem.category || "-").replace(/_/g, " "))}</strong></div>
              <div>Partner: <strong style="color:white;">${escapeHtml(state.copilotExplainItem.evidence?.partner || state.partner)}</strong></div>
              ${state.copilotExplainItem.evidence?.sampleCoverage ? `<div>Sample coverage: <strong style="color:white;">${escapeHtml(String(state.copilotExplainItem.evidence.sampleCoverage))}%</strong></div>` : ""}
            </div>
          </section>
          <section class="copilot-explain-section">
            <strong>Likely cause</strong>
            <p>${escapeHtml(state.copilotExplainItem.likelyCause || "Current evidence suggests a repeatable reconciliation issue that needs operator review.")}</p>
          </section>
          <section class="copilot-explain-section">
            <strong>Recommended action</strong>
            <div style="display:grid; gap:8px; font-size:12px; color:var(--text-muted);">
              <div>Action: <strong style="color:white;">${escapeHtml(state.copilotExplainItem.recommendation?.action || "Review the affected records.")}</strong></div>
              <div>Why: <strong style="color:white;">${escapeHtml(state.copilotExplainItem.recommendation?.why || "This recommendation follows the observed evidence pattern.")}</strong></div>
              <div>Owner: <strong style="color:white;">${escapeHtml(state.copilotExplainItem.recommendation?.owner || "Finance Operations")}</strong></div>
              <div>Priority: <strong style="color:white;">${escapeHtml(state.copilotExplainItem.recommendation?.priority || state.copilotExplainItem.severity || "MEDIUM")}</strong></div>
              <div>Expected outcome: <strong style="color:white;">${escapeHtml(state.copilotExplainItem.recommendation?.expectedOutcome || "Confirm whether the discrepancy is expected behavior or a true issue.")}</strong></div>
            </div>
          </section>
          <section class="copilot-explain-section">
            <strong>Impact</strong>
            <div style="display:grid; gap:8px; font-size:12px; color:var(--text-muted);">
              <div>Current impact: <strong style="color:white;">${escapeHtml(state.copilotExplainItem.impact?.currentImpact || "Observed impact is limited to the current sample.")}</strong></div>
              ${state.copilotExplainItem.impact?.potentialImpact ? `<div>Potential impact${state.copilotExplainItem.impact?.isEstimated ? " (estimate)" : ""}: <strong style="color:white;">${escapeHtml(state.copilotExplainItem.impact.potentialImpact)}</strong></div>` : ""}
            </div>
          </section>
          ${Array.isArray(state.copilotExplainItem.samples) && state.copilotExplainItem.samples.length ? `
            <section class="copilot-explain-section">
              <strong>Evidence samples</strong>
              <div class="table-wrap">
                <table style="width:100%; border-collapse:collapse; font-size:11.5px;">
                  <thead>
                    <tr>
                      <th style="text-align:left;">transactionId</th>
                      <th style="text-align:left;">internalAmount</th>
                      <th style="text-align:left;">partnerAmount</th>
                      <th style="text-align:left;">delta</th>
                      <th style="text-align:left;">status</th>
                      <th style="text-align:left;">timestamp</th>
                    </tr>
                  </thead>
                  <tbody>
                    ${state.copilotExplainItem.samples.slice(0, 3).map(sample => `
                      <tr>
                        <td><code>${escapeHtml(sample.transactionId || "-")}</code></td>
                        <td>${sample.internalAmount !== undefined ? formatAmount(sample.internalAmount) : "-"}</td>
                        <td>${sample.partnerAmount !== undefined ? formatAmount(sample.partnerAmount) : "-"}</td>
                        <td>${sample.delta !== undefined ? formatAmount(sample.delta) : "-"}</td>
                        <td>${escapeHtml(sample.status || "-")}</td>
                        <td>${escapeHtml(sample.timestamp || "-")}</td>
                      </tr>
                    `).join("")}
                  </tbody>
                </table>
              </div>
            </section>
          ` : ""}
          <div style="display:flex; justify-content:flex-end; gap:8px; margin-top:20px;">
            <button class="button secondary-action" data-action="close-copilot-explain">Close</button>
          </div>
        </div>
        </div>
      </div>
    </div>
  ` : "";

  // Render the popup outside the transform fade-in context (to document.body modal root)
  setTimeout(() => {
    let modalContainer = document.getElementById("modal-root");
    if (!modalContainer) {
      modalContainer = document.createElement("div");
      modalContainer.id = "modal-root";
      document.body.appendChild(modalContainer);
    }
    const modalParts = [];
    if (state.selectedEvidenceRowId && selectedRow) {
      modalParts.push(renderEvidencePopup(selectedRow, state));
    }
    if (state.copilotExplainItem) {
      modalParts.push(explainPanelHtml);
    }
    modalContainer.innerHTML = modalParts.join("");
  }, 0);

  // Wrap in grid layout
  return `
    ${toolbarHtml}
    ${runStatusPanelHtml}
    ${summaryStripHtml}
    <div class="reconciliation-container recon-layout">
      <div>
        ${state.reconciliationDeferredReady ? tabsSectionHtml : `
          <section class="panel recon-section-panel">
            <div class="empty-state-panel recon-deferred-panel">
              <span class="material-symbols-outlined recon-deferred-icon">hourglass_top</span>
              <h3 class="recon-deferred-title">Rendering non-critical widgets</h3>
              <p class="muted recon-deferred-copy">AI insights and analytical widgets are loading after the ledger for faster first paint.</p>
            </div>
          </section>
        `}
        ${affectedPreviewHtml}
        ${evidenceTableHtml}
      </div>
    </div>
    ${batchReviewHtml}
    ${modalHtml}
  `;
}
