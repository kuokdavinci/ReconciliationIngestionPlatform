import { parseFlexibleDateInput } from "../../core/date.js";
import { getFilteredReconItems, renderVirtualReconRowsHtml } from "./render.js";

function rerenderReconciliationView(state, render, localRender) {
  if (state.route === "reconciliation" && typeof localRender === "function") {
    localRender();
    return;
  }
  render();
}

export function bindReconciliationFilters({ state, render, localRender, showToast }) {
  const reconStatus = document.getElementById("recon-status-filter");
  if (reconStatus) {
    reconStatus.addEventListener("change", () => {
      state.reconStatus = reconStatus.value;
      rerenderReconciliationView(state, render, localRender);
    });
  }

  // Explorer apply filter
  const explorerBtn = document.getElementById("explorer-apply-btn");
  if (explorerBtn) {
    explorerBtn.addEventListener("click", () => {
      const dateFromRaw = document.getElementById("date-from")?.value || "";
      const dateToRaw = document.getElementById("date-to")?.value || "";
      const parsedDateFrom = dateFromRaw ? parseFlexibleDateInput(dateFromRaw, state.date) : "";
      const parsedDateTo = dateToRaw ? parseFlexibleDateInput(dateToRaw, state.date) : "";

      if (dateFromRaw && !parsedDateFrom) {
        showToast("DATE FROM khong hop le. Dung dd/mm/yyyy hoac yyyy-mm-dd.");
        return;
      }
      if (dateToRaw && !parsedDateTo) {
        showToast("DATE TO khong hop le. Dung dd/mm/yyyy hoac yyyy-mm-dd.");
        return;
      }

      state.explorerFilters = {
        amountMin: document.getElementById("amount-min")?.value || "",
        amountMax: document.getElementById("amount-max")?.value || "",
        dateFrom: parsedDateFrom,
        dateTo: parsedDateTo,
      };
      rerenderReconciliationView(state, render, localRender);
    });
  }
}

export function bindReconciliationEnhancedUi({ state, render, localRender }) {
  const virtualScroller = document.querySelector(".recon-virtual-scroll[data-virtualized='true']");
  if (virtualScroller) {
    virtualScroller.addEventListener("scroll", () => {
      const rowHeight = Number(virtualScroller.dataset.rowHeight || state.reconciliationVirtual?.rowHeight || 56);
      const visibleCount = state.reconciliationVirtual?.visibleCount || 40;
      const nextStartIndex = Math.max(0, Math.floor(virtualScroller.scrollTop / rowHeight) - 5);
      if (nextStartIndex !== (state.reconciliationVirtual?.startIndex || 0)) {
        state.reconciliationVirtual = {
          ...(state.reconciliationVirtual || {}),
          startIndex: nextStartIndex,
          rowHeight,
          visibleCount,
        };
        const filteredItems = getFilteredReconItems(state, (state.activeReconData && state.activeReconData.results) || []);
        const visibleItems = filteredItems.slice(nextStartIndex, nextStartIndex + visibleCount);
        const tbody = virtualScroller.querySelector("tbody");
        if (tbody) {
          tbody.innerHTML = `
            <tr aria-hidden="true"><td colspan="10" style="padding:0; border:none; height:${nextStartIndex * rowHeight}px;"></td></tr>
            ${renderVirtualReconRowsHtml(visibleItems, state)}
            <tr aria-hidden="true"><td colspan="10" style="padding:0; border:none; height:${Math.max(0, (filteredItems.length - (nextStartIndex + visibleItems.length)) * rowHeight)}px;"></td></tr>
          `;
        }
      }
    }, { passive: true });
  }

  const selectionContainer = document.querySelector(".evidence-table-section");
  if (selectionContainer) {
    selectionContainer.addEventListener("change", (event) => {
      const rowToggle = event.target.closest('[data-action="toggle-recon-row"]');
      if (rowToggle) {
        const rowId = rowToggle.dataset.rowId;
        if (!rowId) return;
        state.selectedReconRows = {
          ...(state.selectedReconRows || {}),
          [rowId]: Boolean(rowToggle.checked),
        };
        rerenderReconciliationView(state, render, localRender);
        return;
      }

      const selectAll = event.target.closest('[data-action="toggle-recon-select-all"]');
      if (selectAll) {
        const shouldSelect = Boolean(selectAll.checked);
        const results = getFilteredReconItems(state, (state.activeReconData && state.activeReconData.results) || []);
        const nextSelection = { ...(state.selectedReconRows || {}) };
        results
          .filter(item => item.reconciliationStatus !== "MATCHED")
          .forEach(item => {
            const rowId = item.partnerTxnId || item.internalTxnId || item.id;
            nextSelection[rowId] = shouldSelect;
          });
        state.selectedReconRows = nextSelection;
        rerenderReconciliationView(state, render, localRender);
      }
    });
  }
}

export function handleReconciliationAction({
  action,
  el,
  state,
  render,
  localRender,
  renderPreserveScroll,
  showToast,
  withActorHeaders,
  getActorName,
  getActivePostApprovalRunForContext,
  pollReconciliationRun,
  resolveReviewRecord,
  loadReconciliationReviewRecords,
  refreshAuditLogIfVisible,
  getActiveRenderToken
}) {
  if (action === "run-reconciliation-now") {
    const activePostApprovalRun = getActivePostApprovalRunForContext();
    if (activePostApprovalRun) {
      showToast(activePostApprovalRun.message || "Approved file is still being ingested. Wait for post-approval processing to finish.");
      return true;
    }
    const originalText = el.innerHTML;
    el.disabled = true;
    el.style.opacity = "0.6";
    el.style.cursor = "not-allowed";
    el.innerHTML = `<span class="spinner-mini" style="display:inline-block; width:12px; height:12px; border:2px solid #000; border-top:2px solid transparent; border-radius:50%; animation:spin 1s linear infinite; margin-right:6px; vertical-align:middle;"></span>Running...`;
    showToast(`Running reconciliation for ${state.partner} on ${state.date}...`);
    fetch(`/api/v1/reconciliation/run`, {
      method: "POST",
      headers: withActorHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({
        partner: state.partner,
        date: state.date,
        triggeredBy: getActorName(),
      }),
    })
      .then(r => r.json().then(body => ({ ok: r.ok, body })))
      .then(({ ok, body }) => {
        el.disabled = false;
        el.style.opacity = "";
        el.style.cursor = "";
        el.innerHTML = originalText;
        if (!ok) throw new Error(body.detail || "Run reconciliation failed");
        state.reconciliationRun = body.run || null;
        pollReconciliationRun();
        showToast("Reconciliation queued. Status will update automatically.");
      })
      .catch(err => {
        el.disabled = false;
        el.style.opacity = "";
        el.style.cursor = "";
        el.innerHTML = originalText;
        showToast(err.message || "Run reconciliation failed");
      });
    return true;
  }

  if (action === "open-reconciliation-from-automation") {
    const partner = el.dataset.partner;
    const date = el.dataset.date;
    if (partner) state.partner = partner;
    if (date) state.date = date;
    state.activeReconData = null;
    state.reconciliationRun = null;
    showToast(`Opening reconciliation for ${state.partner}${state.date ? ` on ${state.date}` : ""}.`);
    location.hash = "reconciliation";
    return true;
  }

  if (action === "select-partner") {
    const partner = el.dataset.partner;
    if (!partner) return true;
    state.partner = partner;
    render();
    return true;
  }

  if (action === "go-review-center") {
    const partner = el.dataset.partner;
    if (partner) state.partner = partner;
    location.hash = "review-center";
    return true;
  }

  if (action === "go-review-packet") {
    const packetId = el.dataset.packetId;
    const partner = el.dataset.partner;
    if (partner) state.partner = partner;
    if (packetId) state.selectedReviewPacketId = packetId;
    location.hash = "review-center";
    return true;
  }

  if (action === "clear-filters") {
    state.reconStatus = "";
    state.explorerFilters = { amountMin: "", amountMax: "", dateFrom: "", dateTo: "" };
    state.reconciliationPagination = { ...(state.reconciliationPagination || {}), offset: 0 };
    render();
    return true;
  }

  if (action === "go-reconciliation") {
    location.hash = "reconciliation";
    return true;
  }

  if (action === "set-recon-status") {
    state.reconStatus = el.dataset.status || "";
    state.reconciliationPagination = { ...(state.reconciliationPagination || {}), offset: 0 };
    rerenderReconciliationView(state, render, localRender);
    return true;
  }

  if (action === "reset-recon-status") {
    state.reconStatus = "";
    state.reconciliationPagination = { ...(state.reconciliationPagination || {}), offset: 0 };
    rerenderReconciliationView(state, render, localRender);
    return true;
  }

  if (action === "apply-recon-filters") {
    const amountMin = document.getElementById("amount-min")?.value || "";
    const amountMax = document.getElementById("amount-max")?.value || "";
    const dateFromRaw = document.getElementById("date-from")?.value || "";
    const dateToRaw = document.getElementById("date-to")?.value || "";
    const parsedDateFrom = dateFromRaw ? parseFlexibleDateInput(dateFromRaw, state.date) : "";
    const parsedDateTo = dateToRaw ? parseFlexibleDateInput(dateToRaw, state.date) : "";

    if (dateFromRaw && !parsedDateFrom) {
      showToast("DATE FROM khong hop le. Dung dd/mm/yyyy hoac yyyy-mm-dd.");
      return true;
    }
    if (dateToRaw && !parsedDateTo) {
      showToast("DATE TO khong hop le. Dung dd/mm/yyyy hoac yyyy-mm-dd.");
      return true;
    }

    state.explorerFilters = {
      amountMin,
      amountMax,
      dateFrom: parsedDateFrom,
      dateTo: parsedDateTo
    };
    state.reconciliationPagination = { ...(state.reconciliationPagination || {}), offset: 0 };
    rerenderReconciliationView(state, render, localRender);
    return true;
  }

  if (action === "clear-recon-filters") {
    state.explorerFilters = { amountMin: "", amountMax: "", dateFrom: "", dateTo: "" };
    state.reconciliationPagination = { ...(state.reconciliationPagination || {}), offset: 0 };
    rerenderReconciliationView(state, render, localRender);
    return true;
  }

  if (action === "recon-prev-page") {
    const current = state.reconciliationPagination || { limit: 100, offset: 0 };
    state.reconciliationPagination = {
      ...current,
      offset: Math.max(0, (current.offset || 0) - (current.limit || 100)),
    };
    state.activeReconData = null;
    render();
    return true;
  }

  if (action === "recon-next-page") {
    const current = state.reconciliationPagination || { limit: 100, offset: 0 };
    state.reconciliationPagination = {
      ...current,
      offset: (current.offset || 0) + (current.limit || 100),
    };
    state.activeReconData = null;
    render();
    return true;
  }

  if (action === "recon-set-page-size") {
    const select = document.getElementById("recon-page-size");
    const nextLimit = Number(select?.value || 100);
    state.reconciliationPagination = { limit: nextLimit, offset: 0 };
    state.activeReconData = null;
    render();
    return true;
  }

  if (action === "refresh-recon") {
    state.activeReconData = null;
    render();
    return true;
  }

  if (action === "export-recon") {
    showToast("Reconciliation report exported successfully.");
    return true;
  }

  if (action === "scroll-to-evidence") {
    document.querySelector(".evidence-table-section")?.scrollIntoView({ behavior: "smooth" });
    return true;
  }

  if (action === "create-adjustment") {
    const txnId = el.dataset.txnId || "";
    const amount = el.dataset.amount || "";
    state.adjustmentModalData = { txnId, amount };
    rerenderReconciliationView(state, render, localRender);
    return true;
  }

  if (action === "close-adjustment-modal") {
    state.adjustmentModalData = null;
    rerenderReconciliationView(state, render, localRender);
    return true;
  }

  if (action === "submit-adjustment") {
    showToast(`Adjustment of ${state.adjustmentModalData?.amount} VND for ${state.adjustmentModalData?.txnId} submitted successfully.`);
    state.adjustmentModalData = null;
    rerenderReconciliationView(state, render, localRender);
    return true;
  }

  if (action === "open-evidence-detail") {
    const rowId = el.dataset.rowId;
    state.selectedEvidenceRowId = rowId;
    rerenderReconciliationView(state, render, localRender);
    return true;
  }

  if (action === "open-copilot-explain") {
    if (el.dataset.insightPayload) {
      try {
        state.copilotExplainItem = JSON.parse(el.dataset.insightPayload);
      } catch (_) {
        state.copilotExplainItem = null;
      }
    } else {
      state.copilotExplainItem = {
        type: el.dataset.insightType || "",
        title: el.dataset.insightTitle || "",
        description: el.dataset.insightDescription || "",
        recommendation: el.dataset.insightRecommendation || "",
        severity: el.dataset.insightSeverity || "medium",
        affected_count: Number(el.dataset.insightAffected || 0),
      };
    }
    rerenderReconciliationView(state, render, localRender);
    return true;
  }

  if (action === "close-copilot-explain") {
    state.copilotExplainItem = null;
    rerenderReconciliationView(state, render, localRender);
    return true;
  }

  if (action === "close-evidence-drawer") {
    state.selectedEvidenceRowId = null;
    rerenderReconciliationView(state, render, localRender);
    return true;
  }

  if (action === "resolve-single-anomaly") {
    const rowId = el.dataset.rowId;
    resolveReviewRecord(rowId, "MATCHED")
      .then(async () => {
        if (state.activeReconData && state.activeReconData.results) {
          const item = state.activeReconData.results.find(r => (r.partnerTxnId || r.internalTxnId || r.id) === rowId);
          if (item) {
            item.reconciliationStatus = "MATCHED";
          }
        }
        await loadReconciliationReviewRecords();
        await refreshAuditLogIfVisible();
        showToast(`Record ${rowId} marked as resolved.`);
        state.selectedEvidenceRowId = null;
        rerenderReconciliationView(state, render, localRender);
      })
      .catch(() => {
        showToast("Failed to persist resolved record.");
      });
    return true;
  }

  if (action === "approve-all-recon") {
    const results = (state.activeReconData && state.activeReconData.results) || [];
    Promise.all(results.map(item => {
      const key = item.partnerTxnId || item.internalTxnId || item.id;
      item.reconciliationStatus = "MATCHED";
      return resolveReviewRecord(key, "MATCHED");
    }))
      .then(async () => {
        await loadReconciliationReviewRecords();
        await refreshAuditLogIfVisible();
        showToast("Reconciliation run approved. All anomalies marked as resolved.");
        state.selectedEvidenceRowId = null;
        rerenderReconciliationView(state, render, localRender);
      })
      .catch(() => {
        showToast("Failed to persist one or more resolved records.");
      });
    return true;
  }

  if (action === "batch-review-selected") {
    const selectedKeys = Object.entries(state.selectedReconRows || {})
      .filter(([, selected]) => selected)
      .map(([key]) => key);
    if (!selectedKeys.length) {
      showToast("Select at least one reconciliation row.");
      return true;
    }
    const resolvedStatus = document.getElementById("recon-batch-status")?.value || "MATCHED";
    Promise.all(selectedKeys.map(key => resolveReviewRecord(key, resolvedStatus)))
      .then(async () => {
        if (state.activeReconData && state.activeReconData.results) {
          state.activeReconData.results.forEach(item => {
            const key = item.partnerTxnId || item.internalTxnId || item.id;
            if (selectedKeys.includes(key)) {
              item.reconciliationStatus = resolvedStatus;
            }
          });
        }
        await loadReconciliationReviewRecords();
        await refreshAuditLogIfVisible();
        state.selectedReconRows = {};
        showToast(`Batch reviewed ${selectedKeys.length} records.`);
        rerenderReconciliationView(state, render, localRender);
      })
      .catch(() => {
        showToast("Batch review failed.");
      });
    return true;
  }

  if (action === "mark-selected-for-review") {
    const selectedKeys = Object.entries(state.selectedReconRows || {})
      .filter(([, selected]) => selected)
      .map(([key]) => key);
    if (!selectedKeys.length) {
      showToast("Select at least one reconciliation row.");
      return true;
    }
    Promise.all(selectedKeys.map(key => resolveReviewRecord(key, "STATUS_MISMATCH")))
      .then(async () => {
        if (state.activeReconData && state.activeReconData.results) {
          state.activeReconData.results.forEach(item => {
            const key = item.partnerTxnId || item.internalTxnId || item.id;
            if (selectedKeys.includes(key)) {
              item.reconciliationStatus = "STATUS_MISMATCH";
            }
          });
        }
        await loadReconciliationReviewRecords();
        await refreshAuditLogIfVisible();
        state.selectedReconRows = {};
        showToast(`Flagged ${selectedKeys.length} items for review.`);
        rerenderReconciliationView(state, render, localRender);
      })
      .catch(() => {
        showToast("Flag for review failed.");
      });
    return true;
  }

  if (action === "clear-batch-selection") {
    state.selectedReconRows = {};
    rerenderReconciliationView(state, render, localRender);
    return true;
  }

  if (action === "mark-exception") {
    showToast("Record marked as exception.");
    state.selectedEvidenceRowId = null;
    rerenderReconciliationView(state, render, localRender);
    return true;
  }

  return false;
}
