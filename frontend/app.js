import {
  formatDisplayDate,
  formatDisplayDateTime,
  parseFlexibleDateInput,
} from "./src/core/date.js";
import {
  getActorName as _getActorName,
  withActorHeaders as _withActorHeaders,
  fetchJson,
  executeCopilotAction as _executeCopilotAction,
} from "./src/core/api.js";
import {
  percent,
  formatNumber,
  formatAmount,
  escapeHtml,
  boldNumbers,
} from "./src/core/format.js";
import {
  statusLabel,
  badge,
  severityBadge,
  reconciliationRowClass,
} from "./src/core/status.js";
import {
  loadingPanel,
  renderSkeletonMetrics,
  renderError,
  metrics,
  table,
  bars,
  donut,
  showToast,
} from "./src/core/dom.js";
import { renderAuditLog } from "./src/features/audit/render.js";
import { renderAutomation } from "./src/features/automation/render.js";
import { bindMappingStudioViewActions } from "./src/features/mapping-studio/bind.js";
import { createMappingStudioRenderer } from "./src/features/mapping-studio/render.js";
import { createReviewCenterRenderer } from "./src/features/review-center/render.js";
import { createReviewRuntimeHelpers } from "./src/features/review-runtime/render.js";
import {
  getReviewCenterPendingItems as _getReviewCenterPendingItems,
  getSelectedReviewPacket as _getSelectedReviewPacket,
  getTrackedReviewPacket as _getTrackedReviewPacket,
  getReviewPacketById as _getReviewPacketById,
  summarizeReviewPacket,
} from "./src/features/review-center/selectors.js";
import { handleReviewCenterAction } from "./src/features/review-center/bind.js";
import {
  handleGuidedReviewAction,
  loadGuidedReviewAIMapping as _loadGuidedReviewAIMapping,
  loadGuidedReviewScopeLLM as _loadGuidedReviewScopeLLM,
} from "./src/features/review-center/guided-review.js";
import { renderReconciliation } from "./src/features/reconciliation/render.js";
import {
  renderAiObservation,
  insightCard,
  highlightInsightText,
  renderInsightLoadingState,
} from "./src/features/reconciliation/insights.js";
import { renderEvidencePopup } from "./src/features/reconciliation/evidence.js";
import { bindReconciliationFilters, bindReconciliationEnhancedUi, handleReconciliationAction } from "./src/features/reconciliation/bind.js";
import {
  bindFilters as _bindFilters,
  fetchPartners as _fetchPartners,
} from "./src/shared/filters/bind.js";
import {
  pollAutomationOverview as _pollAutomationOverview,
  pollReconciliationRun as _pollReconciliationRun,
  pollPostApprovalRun as _pollPostApprovalRun,
} from "./src/core/polling.js";
import {
  renderPageFilters,
  getPartnerOptions,
  syncPartnerFilterOptions,
} from "./src/shared/filters/render.js";
import {
  isActiveRuntimeStatus,
  isTerminalPostApprovalRun,
  isTerminalReconciliationRun,
  isLiveReconciliationRunStatus,
  getActivePostApprovalRunForContext,
  getPostApprovalRunForPacket,
  hasMeaningfulRunChange,
  updateReviewPacketLocally as _updateReviewPacketLocally,
  syncLocalReviewPacket as _syncLocalReviewPacket,
  upsertPostApprovalRun as _upsertPostApprovalRun,
} from "./src/core/state-helpers.js";





(function () {
  // Pure JavaScript typeWriter helper function
  window.typeWriter = function (element, text, speed = 15) {
    if (!element) return;
    element.innerHTML = "";
    let i = 0;
    function type() {
      if (i < text.length) {
        element.innerHTML += text.charAt(i);
        i++;
        setTimeout(type, speed);
      }
    }
    type();
  };

  const state = {
    route: "review-center",
    partner: "MOMO",
    partnerOptions: ["MOMO", "VNPAY", "ZALOPAY", "ACMEPAY"],
    date: new Date().toLocaleDateString('sv'),
    focus: "operational",
    reconStatus: "",
    explorerFilters: { amountMin: "", amountMax: "", dateFrom: "", dateTo: "" },
    reconciliationPagination: { limit: 25, offset: 0 },
    evidenceHistory: {},
    reviewedRecords: {},
    resolvedReconStatuses: {},
    studio: {
      step: 1,
      sourceType: null,
      fileName: "",
      sheetNames: [],
      selectedSheet: "",
      headers: [],
      sampleRows: [],
      config: null,
      draftMappingId: null,
      reviewItemId: null,
      configStatus: null,
      isRuntimeEligible: null,
      validation: null,
      testOutput: null,
      versions: [],
      aiSuggestions: [],
      handoffConfirmed: false
    },
    copilotActions: [],
    copilotContext: null,
    selectedReviewPacketId: null,
    reviewPackets: [],
    postApprovalRuns: {},
    automationRunningPartners: {},
    automationNewPacketIds: [],
    automationKnownPacketIds: [],
    reconciliationRun: null,
    reconciliationInsightsLoading: false,
    reconciliationInsightsError: "",
    reconciliationInsightTabData: {
      anomalies: null,
      patterns: null,
      recommendations: null
    },
    reconciliationInsightTabLoading: "",
    reconciliationInsightTabErrors: {},
    selectedReconRows: {},
    reconciliationVirtual: {
      startIndex: 0,
      rowHeight: 56,
      visibleCount: 40,
    },
    reconciliationDeferredReady: false,
    copilotExplainItem: null,
    reviewTab: "pending",
    reviewHistoryCache: null,
    reviewHistoryLoading: false,
    preservedScrollTop: null,
    briefOpen: false,
    briefStep: 0,
    shortcutHelpOpen: false,
    guidedReviewScopeChoice: "",
    localDraftMappingIds: {},
    guidedReviewAI: {
      loading: false,
      error: "",
      mapping: null,
      packetId: null
    },
    guidedReviewTraceModal: {
      open: false,
      sampleIndex: null
    },
    audit: {
      events: [],
      entityType: "",
      action: "",
      lastLoadedAt: "",
      selectedEventId: null,
    }
  };
  state.actor = "Administrator";

  window.updateGuidedScopeChoice = function (value) {
    state.guidedReviewScopeChoice = value;
    document.querySelectorAll(".scope-select-card").forEach(card => {
      card.classList.toggle("selected", card.dataset.scopeValue === value);
      const input = card.querySelector('input[name="guided-scope-choice"]');
      if (input) {
        input.checked = input.value === value;
      }
    });
    const summary = document.getElementById("guided-scope-summary");
    if (!summary) return;
    let probabilities = {};
    try {
      probabilities = JSON.parse(summary.dataset.probabilities || "{}");
    } catch (_) {
      probabilities = {};
    }
    const confidence = Math.round(Number(probabilities[value] || 0) * 100);
    const tone = confidence >= 85 ? {
      border: "#10B981",
      bg: "rgba(16,185,129,0.10)",
      badge: "matched",
      label: "High confidence"
    } : confidence >= 60 ? {
      border: "#F59E0B",
      bg: "rgba(245,158,11,0.10)",
      badge: "warning",
      label: "Medium confidence"
    } : {
      border: "#EF4444",
      bg: "rgba(239,68,68,0.10)",
      badge: "failed",
      label: "Low confidence"
    };
    const scopeOptionMeta = {
      FULL_SNAPSHOT: "File covers the full day, so the safest action is to replace the existing day snapshot with the uploaded partner file.",
      INCREMENTAL_APPEND: "File looks like a delta feed, so new rows should be appended without wiping previously ingested data.",
      REPLACEMENT: "File appears to contain correction/update rows, so matching records should be updated instead of appended.",
    };
    summary.style.borderColor = tone.border;
    summary.style.background = tone.bg;
    const labelEl = document.getElementById("guided-scope-summary-label");
    const titleEl = document.getElementById("guided-scope-summary-title");
    const badgeEl = document.getElementById("guided-scope-summary-badge");
    const confidenceEl = document.getElementById("guided-scope-summary-confidence");
    const metaEl = document.getElementById("guided-scope-summary-meta");
    const reasoningEl = document.getElementById("guided-scope-summary-reasoning");
    if (labelEl) labelEl.style.color = tone.border;
    if (titleEl) titleEl.textContent = value.replace(/_/g, " ");
    if (badgeEl) {
      badgeEl.className = `badge ${tone.badge}`;
      badgeEl.textContent = tone.label;
    }
    if (confidenceEl) {
      confidenceEl.textContent = `${confidence}%`;
      confidenceEl.style.color = tone.border;
    }
    if (metaEl) metaEl.textContent = scopeOptionMeta[value] || "This is the suggested operating mode for the uploaded file based on record shape and count alignment.";
    if (reasoningEl) reasoningEl.textContent = summary.dataset.reasoning || "";
  };

  const getActorName = () => _getActorName(state);
  const withActorHeaders = (headers) => _withActorHeaders(state, headers);
  const executeCopilotAction = (actionKey) => _executeCopilotAction(state, actionKey);
  const getReviewCenterPendingItems = (data) => _getReviewCenterPendingItems(state, data);
  const getSelectedReviewPacket = (items) => _getSelectedReviewPacket(state, items);
  const getTrackedReviewPacket = (data) => _getTrackedReviewPacket(state, data);
  const getReviewPacketById = (packetId) => _getReviewPacketById(state, packetId);
  const loadGuidedReviewAIMapping = (packet) => _loadGuidedReviewAIMapping(state, packet, fetchJson, withActorHeaders, syncLocalReviewPacket, render);
  const loadGuidedReviewScopeLLM = (packet) => _loadGuidedReviewScopeLLM(state, packet, withActorHeaders, renderPreserveScroll);
  const syncLocalReviewPacket = (packetId, updates) => _syncLocalReviewPacket(state, packetId, updates);
  const updateReviewPacketLocally = (packetId, updater) => _updateReviewPacketLocally(state, packetId, updater);
  const upsertPostApprovalRun = (run) => _upsertPostApprovalRun(state, run);
  const bindFilters = () => _bindFilters({ state, render, showToast });
  const fetchPartners = (container) => _fetchPartners({ state, render, container });
  const pollAutomationOverview = () => _pollAutomationOverview({
    state,
    view,
    fetchJson,
    renderAutomation,
    bindViewActions,
    isActiveRuntimeStatus,
    pollers,
    badge,
    escapeHtml,
    formatDisplayDateTime,
    formatNumber,
    metrics,
    severityBadge,
    table
  });
  const pollReconciliationRun = () => _pollReconciliationRun({
    state,
    render,
    hasMeaningfulRunChange,
    isLiveReconciliationRunStatus,
    isTerminalReconciliationRun,
    pollers
  });
  const pollPostApprovalRun = (packetId) => _pollPostApprovalRun({
    state,
    render,
    packetId,
    upsertPostApprovalRun,
    isTerminalPostApprovalRun,
    syncLocalReviewPacket,
    pollers
  });

  const routes = [
    ["review-center", "Review Center", "fact_check"],
    ["reconciliation", "Reconciliation", "receipt_long"],
    ["automation", "Schedules", "smart_toy"],
    ["audit-log", "Audit Log", "history"],
  ];
  const utilityRoutes = {
    "mapping-studio": { title: "Mapping Studio", icon: "schema" }
  };

  const view = document.getElementById("view");
  const title = document.getElementById("page-title");
  const subtitle = document.getElementById("page-subtitle");
  const nav = document.getElementById("nav");
  const toast = document.getElementById("toast");
  let activeRenderToken = 0;
  let activePartnerFetchToken = 0;
  const pollers = { automation: null, reconciliation: null, postApproval: {} };

  const INLINE_FIELD_LABELS = {
    id: "partner_txn_id",
    amount: "amount",
    transDate: "transaction_time",
    status: "transaction_status",
    trace: "trace",
    extra_data: "extra_data",
    currency: "currency",
    description: "description"
  };
  const INLINE_FIELD_TYPES = {
    id: "STRING",
    amount: "DECIMAL",
    transDate: "DATE",
    status: "STRING",
    trace: "STRING",
    extra_data: "STRING",
    currency: "STRING",
    description: "STRING"
  };
  const {
    collectCandidateColumns,
    collectValidationIssues,
    getRuntimeValidationState,
    renderGuidedRuntimeDetailModal,
    renderGuidedSampleRuntimePanel,
    renderRuntimeVisualSummary,
  } = createReviewRuntimeHelpers({ state, escapeHtml });
  const { renderApprovals } = createReviewCenterRenderer({
    state,
    badge,
    escapeHtml,
    formatDisplayDateTime,
    formatNumber,
    getReviewCenterPendingItems,
    getSelectedReviewPacket,
    getTrackedReviewPacket,
    getRuntimeValidationState,
    loadingPanel,
    loadGuidedReviewScopeLLM,
    renderGuidedRuntimeDetailModal,
    renderGuidedSampleRuntimePanel,
    renderRuntimeVisualSummary,
    collectCandidateColumns,
    collectValidationIssues,
    getPostApprovalRunForPacket,
    isTerminalPostApprovalRun,
    statusLabel,
    summarizeReviewPacket,
    table,
  });

  const {
    renderApprovalUploadEntry,
    renderMappings,
    renderSettings,
    renderSubmitSamplePage,
  } = createMappingStudioRenderer({
    state,
    badge,
    escapeHtml,
    formatDisplayDate,
    formatDisplayDateTime,
    renderPageFilters,
  });


  function init() {
    renderNav();
    window.addEventListener("hashchange", onRouteChange);
    onRouteChange();

    // Responsive sidebar collapse & toggle events
    const sidebarToggle = document.getElementById("sidebar-toggle");
    const sidebar = document.querySelector(".sidebar");
    const appShell = document.querySelector(".app-shell");
    const collapseBtn = document.getElementById("sidebar-collapse-btn");

    // Initialize sidebar state from localStorage
    const isCollapsed = localStorage.getItem("sidebarCollapsed") === "true";
    if (isCollapsed && appShell && collapseBtn) {
      appShell.classList.add("sidebar-collapsed");
      const icon = collapseBtn.querySelector(".material-symbols-outlined");
      if (icon) icon.textContent = "chevron_right";
    }
    
    if (sidebarToggle && sidebar) {
      sidebarToggle.addEventListener("click", (e) => {
        e.stopPropagation();
        sidebar.classList.toggle("sidebar-open");
      });

      // Close sidebar when clicking outside on mobile
      document.addEventListener("click", (e) => {
        if (sidebar.classList.contains("sidebar-open") && !sidebar.contains(e.target) && e.target !== sidebarToggle) {
          sidebar.classList.remove("sidebar-open");
        }
      });
    }

    // Toggle collapse on desktop button click
    if (collapseBtn && appShell) {
      collapseBtn.addEventListener("click", () => {
        const collapsing = appShell.classList.toggle("sidebar-collapsed");
        localStorage.setItem("sidebarCollapsed", collapsing ? "true" : "false");
        const icon = collapseBtn.querySelector(".material-symbols-outlined");
        if (icon) {
          icon.textContent = collapsing ? "chevron_right" : "chevron_left";
        }
      });
    }

    // Toggle shortcut (Cmd/Ctrl + B)
    document.addEventListener("keydown", (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "b") {
        e.preventDefault();
        if (collapseBtn) collapseBtn.click();
      }
    });

    // Mobile swipe actions delegation on dynamically rendered cards
    let swipeStartX = 0;
    let swipeActiveCard = null;

    document.addEventListener("touchstart", (e) => {
      const card = e.target.closest(".mobile-recon-card");
      if (!card) return;
      swipeStartX = e.touches[0].clientX;
      swipeActiveCard = card;
      card.style.transition = "none";
    }, { passive: true });

    document.addEventListener("touchmove", (e) => {
      if (!swipeActiveCard) return;
      const currentX = e.touches[0].clientX;
      const diffX = currentX - swipeStartX;
      
      // Allow minor vertical scroll wiggle room
      if (Math.abs(diffX) > 10) {
        // Clamp swipe movement visually
        const visualTranslate = Math.max(-120, Math.min(120, diffX));
        swipeActiveCard.style.transform = `translateX(${visualTranslate}px)`;
        if (diffX > 40) {
          swipeActiveCard.style.background = "rgba(14, 203, 129, 0.15)";
        } else if (diffX < -40) {
          swipeActiveCard.style.background = "rgba(180, 67, 67, 0.15)";
        } else {
          swipeActiveCard.style.background = "";
        }
      }
    }, { passive: true });

    document.addEventListener("touchend", (e) => {
      if (!swipeActiveCard) return;
      swipeActiveCard.style.transition = "transform 0.3s cubic-bezier(0.16, 1, 0.3, 1), background 0.3s ease";
      
      const currentX = e.changedTouches[0].clientX;
      const diffX = currentX - swipeStartX;
      const rowId = swipeActiveCard.querySelector("input[type='checkbox']")?.dataset.rowId;

      if (diffX > 80 && rowId) {
        // Swipe Right -> Resolve as MATCHED
        showToast(`Resolving ${rowId} as MATCHED via swipe...`);
        resolveReviewRecord(rowId, "MATCHED")
          .then(async () => {
            if (state.activeReconData && state.activeReconData.results) {
              const item = state.activeReconData.results.find(r => (r.partnerTxnId || r.internalTxnId || r.id) === rowId);
              if (item) item.reconciliationStatus = "MATCHED";
            }
            await loadReconciliationReviewRecords();
            showToast(`Record ${rowId} matched successfully.`);
            render();
          })
          .catch(() => {
            showToast("Failed to match transaction.");
            swipeActiveCard.style.transform = "";
            swipeActiveCard.style.background = "";
          });
      } else if (diffX < -80 && rowId) {
        // Swipe Left -> Flag/Mark as exception
        showToast(`Marking ${rowId} as Exception via swipe...`);
        swipeActiveCard.style.transform = "";
        swipeActiveCard.style.background = "";
        const triggerBtn = swipeActiveCard.querySelector("[data-action='open-evidence-detail']");
        if (triggerBtn) triggerBtn.click();
      } else {
        // Reset card visually if swipe threshold not met
        swipeActiveCard.style.transform = "";
        swipeActiveCard.style.background = "";
      }
      
      swipeActiveCard = null;
    });

    // Command Center implementation
    const commandCenterModal = document.getElementById("command-center-modal");
    const commandInput = document.getElementById("command-center-input");
    const commandResults = document.getElementById("command-center-results");
    const shortcutHelpModal = document.getElementById("shortcut-help-modal");
    const shortcutHelpClose = document.getElementById("shortcut-help-close");

    const availableCommands = [
      { key: "/review", title: "Go to Review Center", subtitle: "Review pending ingestion changes", icon: "fact_check", route: "review-center" },
      { key: "/recon", title: "Go to Reconciliation Ledger", subtitle: "Deterministic reconciliation mismatch ledger", icon: "receipt_long", route: "reconciliation" },
      { key: "/auto", title: "Go to Automation Visibility", subtitle: "Job queues and automation logs", icon: "smart_toy", route: "automation" },
      { key: "/mapping", title: "Go to Mapping Studio", subtitle: "Create and validate partner mappings", icon: "schema", route: "mapping-studio" },
      { key: "/audit", title: "Go to Audit Trail", subtitle: "Activity trail and operational logs", icon: "history", route: "audit-log" }
    ];

    function toggleCommandCenter(show) {
      if (!commandCenterModal) return;
      if (show) {
        commandCenterModal.style.display = "flex";
        commandInput.value = "";
        commandInput.focus();
        renderCommandResults("");
      } else {
        commandCenterModal.style.display = "none";
      }
    }

    function toggleShortcutHelp(show) {
      if (!shortcutHelpModal) return;
      state.shortcutHelpOpen = Boolean(show);
      shortcutHelpModal.style.display = show ? "flex" : "none";
    }

    function renderCommandResults(query) {
      if (!commandResults) return;
      const cleanQuery = query.trim().toLowerCase();
      let html = "";

      // Filter default commands
      const filteredCommands = availableCommands.filter(cmd => 
        cmd.key.includes(cleanQuery) || 
        cmd.title.toLowerCase().includes(cleanQuery) ||
        cmd.subtitle.toLowerCase().includes(cleanQuery)
      );

      filteredCommands.forEach((cmd, idx) => {
        html += `
          <div class="command-center-item ${idx === 0 ? 'selected' : ''}" data-type="route" data-route="${cmd.route}">
            <span class="material-symbols-outlined item-icon">${cmd.icon}</span>
            <div class="item-info">
              <span class="item-title">${cmd.title}</span>
              <span class="item-subtitle">${cmd.subtitle}</span>
            </div>
            <span class="item-shortcut">${cmd.key}</span>
          </div>
        `;
      });

      // Search Transaction ID in reconciliation results if on reconciliation screen or query looks like a txn/trace
      const results = (state.activeReconData && state.activeReconData.results) || [];
      if (cleanQuery.length > 2 && results.length) {
        const matches = results.filter(item => {
          const rowId = (item.partnerTxnId || item.internalTxnId || item.id || "").toLowerCase();
          return rowId.includes(cleanQuery);
        }).slice(0, 5);

        matches.forEach((item, idx) => {
          const rowId = item.partnerTxnId || item.internalTxnId || item.id;
          const isMatched = item.reconciliationStatus === "MATCHED";
          const offsetIdx = filteredCommands.length + idx;
          html += `
            <div class="command-center-item ${offsetIdx === 0 ? 'selected' : ''}" data-type="evidence" data-row-id="${escapeHtml(rowId)}">
              <span class="material-symbols-outlined item-icon">visibility</span>
              <div class="item-info">
                <span class="item-title">Inspect TXN ID: ${escapeHtml(rowId)}</span>
                <span class="item-subtitle">Status: ${escapeHtml(item.reconciliationStatus)} | Delta: ${formatAmount(Math.abs((item.partnerAmount || 0) - (item.internalAmount || 0)))}</span>
              </div>
              <span class="item-shortcut" style="background: rgba(240, 185, 11, 0.15); color: var(--brand-primary);">Ledger Row</span>
            </div>
          `;
        });
      }

      if (!html) {
        html = `<div style="padding: 16px; text-align: center; color: var(--text-muted); font-size: 13px;">No commands or transactions found.</div>`;
      }
      commandResults.innerHTML = html;
      bindCommandItems();
    }

    function bindCommandItems() {
      commandResults.querySelectorAll(".command-center-item").forEach(item => {
        item.addEventListener("click", () => {
          executeCommandItem(item);
        });
      });
    }

    function executeCommandItem(item) {
      if (item.dataset.type === "route") {
        location.hash = item.dataset.route;
      } else if (item.dataset.type === "evidence") {
        state.selectedEvidenceRowId = item.dataset.rowId;
        render();
      }
      toggleCommandCenter(false);
    }

    if (commandInput) {
      commandInput.addEventListener("input", (e) => {
        renderCommandResults(e.target.value);
      });

      commandInput.addEventListener("keydown", (e) => {
        const items = commandResults.querySelectorAll(".command-center-item");
        let activeIdx = Array.from(items).findIndex(item => item.classList.contains("selected"));

        if (e.key === "ArrowDown") {
          e.preventDefault();
          if (items.length) {
            if (activeIdx !== -1) items[activeIdx].classList.remove("selected");
            activeIdx = (activeIdx + 1) % items.length;
            items[activeIdx].classList.add("selected");
            items[activeIdx].scrollIntoView({ block: "nearest" });
          }
        } else if (e.key === "ArrowUp") {
          e.preventDefault();
          if (items.length) {
            if (activeIdx !== -1) items[activeIdx].classList.remove("selected");
            activeIdx = (activeIdx - 1 + items.length) % items.length;
            items[activeIdx].classList.add("selected");
            items[activeIdx].scrollIntoView({ block: "nearest" });
          }
        } else if (e.key === "Enter") {
          e.preventDefault();
          if (activeIdx !== -1 && items[activeIdx]) {
            executeCommandItem(items[activeIdx]);
          }
        }
      });
    }

    document.addEventListener("keydown", (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        const isOpen = commandCenterModal && commandCenterModal.style.display === "flex";
        toggleCommandCenter(!isOpen);
      } else if ((e.ctrlKey || e.metaKey) && e.key === "/") {
        e.preventDefault();
        toggleShortcutHelp(!state.shortcutHelpOpen);
      } else if (e.key === "Escape") {
        toggleCommandCenter(false);
        toggleShortcutHelp(false);
      }
    });

    if (commandCenterModal) {
      commandCenterModal.addEventListener("click", (e) => {
        if (e.target === commandCenterModal) {
          toggleCommandCenter(false);
        }
      });
    }

    if (shortcutHelpModal) {
      shortcutHelpModal.addEventListener("click", (e) => {
        if (e.target === shortcutHelpModal) {
          toggleShortcutHelp(false);
        }
      });
    }

    if (shortcutHelpClose) {
      shortcutHelpClose.addEventListener("click", () => toggleShortcutHelp(false));
    }

    // Handle clicks inside the modal-root and global data-action elements (modal dialogs + table eye icon clicks)
    document.addEventListener("click", (e) => {
      // 1. Global delegation for open-evidence-detail (eye icon)
      const openDetailEl = e.target.closest("[data-action='open-evidence-detail']");
      if (openDetailEl) {
        const rowId = openDetailEl.dataset.rowId;
        state.selectedEvidenceRowId = rowId;
        rerenderReconciliationLocally();
        return;
      }

      const openAuditDetailEl = e.target.closest("[data-action='open-audit-detail']");
      if (openAuditDetailEl) {
        state.audit.selectedEventId = openAuditDetailEl.dataset.eventId || null;
        render();
        return;
      }

      // 2. Modal actions delegation
      const modalActionEl = e.target.closest("#modal-root [data-action]");
      if (modalActionEl) {
        const action = modalActionEl.dataset.action;
        if (action === "close-copilot-explain") {
          state.copilotExplainItem = null;
          rerenderReconciliationLocally();
          return;
        }
        if (action === "close-evidence-drawer") {
          state.selectedEvidenceRowId = null;
          rerenderReconciliationLocally();
          return;
        }
        if (action === "close-audit-detail") {
          state.audit.selectedEventId = null;
          render();
          return;
        }
        if (action === "mark-exception") {
          showToast("Record marked as exception.");
          state.selectedEvidenceRowId = null;
          rerenderReconciliationLocally();
          return;
        }
        if (action === "create-adjustment") {
          const txnId = modalActionEl.dataset.txnId || "";
          const amount = modalActionEl.dataset.amount || "";
          state.adjustmentModalData = { txnId, amount };
          state.selectedEvidenceRowId = null;
          rerenderReconciliationLocally();
          return;
        }
        if (action === "submit-anomaly-note") {
          const rowId = modalActionEl.dataset.rowId;
          const noteText = document.getElementById("evidence-note-input")?.value || "";
          if (!noteText.trim()) {
            showToast("Please type a note first.");
            return;
          }
          saveReviewNote(rowId, noteText.trim())
            .then(async () => {
              await loadReconciliationReviewRecords();
              await refreshAuditLogIfVisible();
              showToast("Note saved and record marked as reviewed.");
              state.selectedEvidenceRowId = null;
              rerenderReconciliationLocally();
            })
            .catch(() => {
              showToast("Failed to save review note.");
            });
          return;
        }
      }
    });
  }

  async function loadReconciliationReviewRecords() {
    const data = await fetchJson(`/api/v1/reconciliation/review-records?partner=${encodeURIComponent(state.partner)}&date=${encodeURIComponent(state.date)}`);
    const evidenceHistory = {};
    const reviewedRecords = {};
    const resolvedReconStatuses = {};
    (data.records || []).forEach(record => {
      const key = record.recordKey;
      if (!key) return;
      evidenceHistory[key] = Array.isArray(record.notes) ? record.notes : [];
      if (record.reviewed) reviewedRecords[key] = true;
      if (record.resolvedStatus) resolvedReconStatuses[key] = record.resolvedStatus;
    });
    state.evidenceHistory = evidenceHistory;
    state.reviewedRecords = reviewedRecords;
    state.resolvedReconStatuses = resolvedReconStatuses;
  }

  async function loadReviewHistoryData(force = false) {
    const cacheKey = `${state.partner}:${state.date}`;
    if (!force && state.reviewHistoryCache && state.reviewHistoryCache.key === cacheKey) {
      return state.reviewHistoryCache;
    }

    state.reviewHistoryLoading = true;
    render();
    try {
      await loadReconciliationReviewRecords();
      const decisions = (state.reviewPackets || [])
        .filter(item => ["APPROVED", "REJECTED", "SUPERSEDED"].includes(String(item.status || "").toUpperCase()))
        .slice(0, 20);
      const reconNotes = [];
      Object.entries(state.evidenceHistory || {}).forEach(([rowId, historyList]) => {
        historyList.forEach(entry => {
          reconNotes.push({
            rowId,
            time: entry.time,
            event: entry.event
          });
        });
      });
      reconNotes.sort((a, b) => new Date(String(b.time || "").replace(/-/g, "/")) - new Date(String(a.time || "").replace(/-/g, "/")));
      state.reviewHistoryCache = { key: cacheKey, decisions, reconNotes };
      return state.reviewHistoryCache;
    } finally {
      state.reviewHistoryLoading = false;
      render();
    }
  }

  async function saveReviewNote(rowId, noteText) {
    const response = await fetch(`/api/v1/reconciliation/review-records/${encodeURIComponent(rowId)}/note`, {
      method: "POST",
      headers: withActorHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({
        partner: state.partner,
        date: state.date,
        note: noteText
      })
    });
    if (!response.ok) {
      throw new Error("Failed to save review note.");
    }
    return response.json();
  }

  async function resolveReviewRecord(rowId, resolvedStatus = "MATCHED") {
    const response = await fetch(`/api/v1/reconciliation/review-records/${encodeURIComponent(rowId)}/resolve`, {
      method: "POST",
      headers: withActorHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({
        partner: state.partner,
        date: state.date,
        resolvedStatus
      })
    });
    if (!response.ok) {
      throw new Error("Failed to persist resolved status.");
    }
    return response.json();
  }


  async function openPacketInStudio(packetId) {
    const packet = getReviewPacketById(packetId);
    if (!packet) {
      state.studio.reviewItemId = packetId || null;
      location.hash = "mapping-studio";
      return;
    }

    if (packet.partner) {
      state.partner = packet.partner;
    }
    state.studio.reviewItemId = packetId;
    state.studio.fileName = packet.fileName || "";
    state.studio.headers = packet.structureSignature?.headers || [];
    state.studio.sampleRows = (packet.samplePreview || []).map(row => row.values || []);
    state.studio.draftMappingId = packet.draftMappingId || null;
    state.studio.configStatus = packet.status || null;
    state.studio.handoffConfirmed = packet.decisionMode === "SEND_TO_MAPPING_STUDIO";

    const draftMappingId = packet.draftMappingId;
    if (draftMappingId) {
      try {
        const response = await fetchJson(`/api/v1/mappings?partner=${encodeURIComponent(packet.partner || state.partner)}`);
        const mapping = (response.mappings || []).find(item => item._id === draftMappingId);
        if (mapping) {
          state.studio.config = mapping;
          state.studio.step = 2;
        } else {
          state.studio.step = 1;
        }
      } catch (err) {
        showToast("Could not preload the draft mapping in Mapping Studio.");
        state.studio.step = 1;
      }
    } else {
      state.studio.step = 1;
    }

    location.hash = "mapping-studio";
  }



  function renderNav() {
    const primary = routes.map(([key, label, icon]) => `
      <button class="nav-item ${key === state.route ? 'active' : ''}" data-route="${key}">
        <span class="material-symbols-outlined">${icon}</span>
        <span>${label}</span>
      </button>
    `).join("");
    const utility = Object.entries(utilityRoutes).map(([key, meta]) => `
      <button class="nav-item nav-item-utility ${key === state.route ? 'active' : ''}" data-route="${key}">
        <span class="material-symbols-outlined">${meta.icon}</span>
        <span>${meta.title}</span>
      </button>
    `).join("");
    nav.innerHTML = `${primary}${utility ? `<div class="nav-divider"></div><div class="nav-subgroup-label">Tools</div>${utility}` : ""}`;
    
    nav.querySelectorAll("[data-route]").forEach(button => {
      button.addEventListener("click", () => {
        location.hash = button.dataset.route;
      });
    });
  }



  function onRouteChange() {
    if (pollers.automation) {
      clearInterval(pollers.automation);
      pollers.automation = null;
    }
    const key = location.hash.replace("#", "") || "review-center";
    const aliases = {
      "review-queue": "review-center",
      "reconcilliation": "reconciliation",
      "reconcillation": "reconciliation",
      "reconcilation": "reconciliation"
    };
    const normalized = aliases[key] || key;
    state.route = (routes.some(([route]) => route === normalized) || utilityRoutes[normalized]) ? normalized : "review-center";
    
    document.querySelectorAll(".nav-item").forEach(item => {
      const active = item.dataset.route === state.route;
      item.classList.toggle("active", active);
      const icon = item.querySelector(".material-symbols-outlined");
      if (icon) {
        icon.style.fontVariationSettings = active ? "'FILL' 1" : "'FILL' 0";
      }
    });

    // Close mobile sidebar on navigate
    document.querySelector(".sidebar")?.classList.remove("sidebar-open");
    
    render();
  }

  async function renderReviewCenterPage(renderToken, routeAtStart, partnerAtStart, dateAtStart) {
    const cachedReviewCenter = state.reviewCenterCache
      && state.reviewCenterCache.partner === state.partner
      && state.reviewCenterCache.date === state.date;

    const applyReviewCenterData = (data, copilot = state.copilotContext) => {
      state.copilotContext = copilot;
      state.reviewPackets = data.packets || [];
      const historyKey = `${state.partner}:${state.date}`;
      if (!state.reviewHistoryCache || state.reviewHistoryCache.key !== historyKey) {
        state.reviewHistoryCache = null;
      }
      const pendingPacketIds = (data.packets || [])
        .filter(packet => String(packet.status || "").toUpperCase() === "PENDING")
        .map(packet => packet._id);
      const pendingMappingIds = (data.mappings || [])
        .filter(mapping => String(mapping.status || "").toUpperCase() === "PENDING_APPROVAL")
        .map(mapping => mapping._id);
      const selectableIds = [...pendingPacketIds, ...pendingMappingIds];
      const trackedPostApprovalRun = state.selectedReviewPacketId
        ? state.postApprovalRuns?.[String(state.selectedReviewPacketId)] || null
        : null;
      const preserveTrackedGuidedReview = Boolean(
        state.guidedReviewOpen &&
        state.selectedReviewPacketId &&
        trackedPostApprovalRun &&
        !isTerminalPostApprovalRun(trackedPostApprovalRun)
      );
      if (!state.selectedReviewPacketId && selectableIds.length) {
        state.selectedReviewPacketId = selectableIds[0];
      }
      if (
        state.selectedReviewPacketId &&
        !selectableIds.includes(state.selectedReviewPacketId) &&
        !preserveTrackedGuidedReview
      ) {
        state.selectedReviewPacketId = selectableIds[0] || null;
      }
      view.innerHTML = renderApprovals(data);
      if (typeof state.preservedScrollTop === "number") {
        const viewport = document.scrollingElement || document.documentElement;
        viewport.scrollTop = state.preservedScrollTop;
        state.preservedScrollTop = null;
      }
    };

    if (!cachedReviewCenter) {
      view.innerHTML = `
        ${renderSkeletonMetrics(3)}
        ${loadingPanel("Loading review center data...")}
      `;
      const [packets, mappings, intake, copilot] = await Promise.all([
        fetchJson(`/api/v1/review-packets?partner=${encodeURIComponent(state.partner)}`),
        fetchJson(`/api/v1/mappings?partner=${encodeURIComponent(state.partner)}`),
        fetchJson(`/api/v1/operations/intake?partner=${encodeURIComponent(state.partner)}&date=${encodeURIComponent(state.date)}`),
        fetchJson(`/api/v1/copilot/context?partner=${encodeURIComponent(state.partner)}&screen=review`).catch(() => null)
      ]);
      if (
        renderToken !== activeRenderToken ||
        state.route !== routeAtStart ||
        state.partner !== partnerAtStart ||
        state.date !== dateAtStart
      ) return;
      const data = {
        packets: packets.packets || [],
        mappings: mappings.mappings || [],
        intake: intake
      };
      state.reviewCenterCache = {
        partner: state.partner,
        date: state.date,
        data
      };
      applyReviewCenterData(data, copilot);
      return;
    }

    applyReviewCenterData(state.reviewCenterCache.data, state.copilotContext);
  }

  async function renderReconciliationPage(renderToken, routeAtStart, partnerAtStart, dateAtStart) {
    const isAlreadyOnRecon = view.querySelector(".summary-strip") !== null;
    const contextChanged = state.lastPartner !== state.partner || state.lastDate !== state.date || !state.activeReconData;
    if (!isAlreadyOnRecon || contextChanged) {
      view.innerHTML = `
        ${renderSkeletonMetrics(4)}
        ${loadingPanel("Loading reconciliation results...")}
      `;
    } else {
      state.preservedScrollTop = (document.scrollingElement || document.documentElement).scrollTop;
    }

    const pageState = state.reconciliationPagination || { limit: 25, offset: 0 };
    let url = `/api/v1/reconciliation/results?partner=${encodeURIComponent(state.partner)}&date=${encodeURIComponent(state.date)}&limit=${encodeURIComponent(pageState.limit || 25)}&offset=${encodeURIComponent(pageState.offset || 0)}`;
    if (state.reconStatus) {
      url += `&status=${encodeURIComponent(state.reconStatus)}`;
    }
    const ef = state.explorerFilters || {};
    if (ef.amountMin) url += `&amountMin=${encodeURIComponent(ef.amountMin)}`;
    if (ef.amountMax) url += `&amountMax=${encodeURIComponent(ef.amountMax)}`;
    if (ef.dateFrom) url += `&dateFrom=${encodeURIComponent(ef.dateFrom)}`;
    if (ef.dateTo) url += `&dateTo=${encodeURIComponent(ef.dateTo)}`;
    const data = await fetchJson(url);
    await loadReconciliationReviewRecords();
    if (data && data.results) {
      data.results.forEach(item => {
        const key = item.partnerTxnId || item.internalTxnId || item.id;
        if (state.resolvedReconStatuses && state.resolvedReconStatuses[key]) {
          item.reconciliationStatus = state.resolvedReconStatuses[key];
        }
      });
    }
    const [statsResponse, reconRunResponse] = await Promise.all([
      fetchJson(`/api/v1/reconciliation/stats?partner=${encodeURIComponent(state.partner)}&date=${encodeURIComponent(state.date)}`).catch(() => null),
      fetchJson(`/api/v1/reconciliation/run-status?partner=${encodeURIComponent(state.partner)}&date=${encodeURIComponent(state.date)}`).catch(() => null)
    ]);
    if (
      renderToken !== activeRenderToken ||
      state.route !== routeAtStart ||
      state.partner !== partnerAtStart ||
      state.date !== dateAtStart
    ) return;
    state.insightsSummary = statsResponse;
    state.reconciliationInsightsLoading = true;
    state.reconciliationInsightsError = "";
    state.reconciliationInsightTabData = {
      anomalies: null,
      patterns: null,
      recommendations: null
    };
    state.reconciliationInsightTabLoading = "all";
    state.reconciliationInsightTabErrors = {};
    state.selectedReconRows = {};
    state.reconciliationVirtual.startIndex = 0;
    state.reconciliationDeferredReady = true;
    state.copilotExplainItem = null;
    state.reconciliationRun = reconRunResponse?.run || null;
    state.activeReconData = data;
    state.lastPartner = state.partner;
    state.lastDate = state.date;
    view.innerHTML = renderReconciliation(state, data);
    if (state.reconciliationRun && !isTerminalReconciliationRun(state.reconciliationRun)) {
      pollReconciliationRun();
    }
    if (typeof state.preservedScrollTop === "number") {
      const viewport = document.scrollingElement || document.documentElement;
      viewport.scrollTop = state.preservedScrollTop;
      state.preservedScrollTop = null;
    }
    loadReconciliationCopilot(renderToken, routeAtStart, partnerAtStart, dateAtStart);
    loadReconciliationInsights(renderToken, routeAtStart, partnerAtStart, dateAtStart);
  }

  async function loadReconciliationCopilot(renderToken, routeAtStart, partnerAtStart, dateAtStart) {
    try {
      const copilot = await fetchJson(`/api/v1/copilot/context?partner=${encodeURIComponent(partnerAtStart)}&date=${encodeURIComponent(dateAtStart)}&screen=reconciliation`).catch(() => null);
      if (
        renderToken !== activeRenderToken ||
        state.route !== routeAtStart ||
        state.partner !== partnerAtStart ||
        state.date !== dateAtStart
      ) return;
      state.copilotContext = copilot;
    } catch (err) {
      return;
    }
  }

  async function loadReconciliationInsights(renderToken, routeAtStart, partnerAtStart, dateAtStart) {
    const tabKeys = ["anomalies", "patterns", "recommendations"];
    state.reconciliationInsightsLoading = true;
    await Promise.all(tabKeys.map(async (tabKey) => {
      state.reconciliationInsightTabErrors = {
        ...(state.reconciliationInsightTabErrors || {}),
        [tabKey]: ""
      };
      try {
        const tabData = await fetchJson(`/api/v1/reconciliation/insights?type=${encodeURIComponent(tabKey)}&partner=${encodeURIComponent(partnerAtStart)}&date=${encodeURIComponent(dateAtStart)}`);
        if (
          renderToken !== activeRenderToken ||
          state.route !== routeAtStart ||
          state.partner !== partnerAtStart ||
          state.date !== dateAtStart
        ) return;
        state.reconciliationInsightTabData = {
          ...(state.reconciliationInsightTabData || {}),
          [tabKey]: Array.isArray(tabData) ? tabData : []
        };
        state.reconciliationInsightsError = "";
      } catch (err) {
        if (
          renderToken !== activeRenderToken ||
          state.route !== routeAtStart ||
          state.partner !== partnerAtStart ||
          state.date !== dateAtStart
        ) return;
        const message = err.message || "AI insights are unavailable right now.";
        state.reconciliationInsightsError = message;
        state.reconciliationInsightTabErrors = {
          ...(state.reconciliationInsightTabErrors || {}),
          [tabKey]: message
        };
      } finally {
        if (
          renderToken !== activeRenderToken ||
          state.route !== routeAtStart ||
          state.partner !== partnerAtStart ||
          state.date !== dateAtStart
        ) return;
        rerenderReconciliationLocally();
      }
    }));
    if (
      renderToken !== activeRenderToken ||
      state.route !== routeAtStart ||
      state.partner !== partnerAtStart ||
      state.date !== dateAtStart
    ) return;
    state.reconciliationInsightTabLoading = "";
    state.reconciliationInsightsLoading = false;
    rerenderReconciliationLocally();
  }

  function rerenderReconciliationLocally() {
    if (state.route !== "reconciliation") {
      render();
      return;
    }
    const viewport = document.scrollingElement || document.documentElement;
    const currentScrollTop = viewport ? viewport.scrollTop : 0;
    view.innerHTML = renderReconciliation(state, state.activeReconData || { results: [] });
    bindFilters();
    bindViewActions();
    if (viewport) {
      viewport.scrollTop = currentScrollTop;
    }
  }

  function renderMappingStudioPage() {
    view.innerHTML = renderSubmitSamplePage();
    bindViewActions();
  }

  async function renderAutomationPage(renderToken, routeAtStart) {
    view.innerHTML = loadingPanel("Loading automation visibility...");
    const [data, copilot] = await Promise.all([
      fetchJson(`/api/v1/automation/jobs`),
      fetchJson(`/api/v1/copilot/context?partner=${encodeURIComponent(state.partner)}&screen=automation`).catch(() => null)
    ]);
    if (renderToken !== activeRenderToken || state.route !== routeAtStart) return;
    state.copilotContext = copilot;
    view.innerHTML = renderAutomation({
      state,
      data,
      badge,
      escapeHtml,
      formatDisplayDateTime,
      formatNumber,
      metrics,
      severityBadge,
      table,
    });
    pollAutomationOverview();
    bindViewActions();
  }

  async function renderAuditPage(renderToken, routeAtStart, partnerAtStart, dateAtStart) {
    view.innerHTML = loadingPanel("Loading audit log...");
    const qs = new URLSearchParams({
      limit: "200",
      partner: partnerAtStart,
      date: dateAtStart
    });
    if (state.audit.entityType) qs.set("entityType", state.audit.entityType);
    if (state.audit.action) qs.set("action", state.audit.action);
    const data = await fetchJson(`/api/v1/audit/events?${qs.toString()}`);
    if (
      renderToken !== activeRenderToken ||
      state.route !== routeAtStart ||
      state.partner !== partnerAtStart ||
      state.date !== dateAtStart
    ) return;
    state.audit.events = Array.isArray(data.events) ? data.events : [];
    state.audit.lastLoadedAt = new Date().toISOString();
    view.innerHTML = renderAuditLog({
      state,
      badge,
      escapeHtml,
      formatDisplayDateTime,
      formatNumber,
      renderPageFilters,
      table,
    });
    bindFilters();
    bindViewActions();
  }

  async function render() {
    const modalContainer = document.getElementById("modal-root");
    if (modalContainer) {
      modalContainer.innerHTML = "";
    }
    const renderToken = ++activeRenderToken;
    const routeAtStart = state.route;
    const partnerAtStart = state.partner;
    const dateAtStart = state.date;
    const route = routes.find(([key]) => key === state.route);
    const utility = utilityRoutes[state.route];
    title.textContent = route ? route[1] : utility ? utility.title : "Command Center";
    const routeSubtitle = {
      "review-center": `Review pending runtime changes for ${state.partner}`,
      reconciliation: `Deterministic reconciliation outcomes for ${state.partner} on ${formatDisplayDate(state.date)}`,
      automation: `Scheduler, job visibility, and automation context`,
      "mapping-studio": `Create a draft mapping, validate it, then send it to Review Center`,
      "audit-log": `Append-only activity trail for ${state.partner} on ${formatDisplayDate(state.date)}`
    };
    subtitle.textContent = routeSubtitle[state.route] || `Operations Console - ${state.partner}`;

    // Smooth tab fade-in transition
    view.classList.remove("fade-in");
    void view.offsetWidth;
    view.classList.add("fade-in");

    if (state.route === "review-center") {
      try {
        await renderReviewCenterPage(renderToken, routeAtStart, partnerAtStart, dateAtStart);
      } catch (err) {
        if (renderToken !== activeRenderToken || state.route !== routeAtStart) return;
        view.innerHTML = renderError(err);
      }
      fetchPartners();
      bindFilters();
      bindViewActions();
      return;
    }

    if (state.route === "reconciliation") {
      try {
        await renderReconciliationPage(renderToken, routeAtStart, partnerAtStart, dateAtStart);
      } catch (err) {
        if (renderToken !== activeRenderToken || state.route !== routeAtStart) return;
        view.innerHTML = renderError(err);
      }
      fetchPartners();
      bindFilters();
      bindViewActions();
      return;
    }

    if (state.route === "mapping-studio") {
      renderMappingStudioPage();
      return;
    }

    if (state.route === "automation") {
      try {
        await renderAutomationPage(renderToken, routeAtStart);
      } catch (err) {
        if (renderToken !== activeRenderToken || state.route !== routeAtStart) return;
        view.innerHTML = renderError(err);
      }
      return;
    }

    if (state.route === "audit-log") {
      try {
        await renderAuditPage(renderToken, routeAtStart, partnerAtStart, dateAtStart);
      } catch (err) {
        if (renderToken !== activeRenderToken || state.route !== routeAtStart) return;
        view.innerHTML = renderError(err);
      }
      fetchPartners();
      bindFilters();
      bindViewActions();
    }
  }

  async function refreshAuditLogIfVisible() {
    if (state.route !== "audit-log") return;
    await render();
  }








  function bindViewActions() {
    const auditEntityFilter = document.getElementById("audit-entity-filter");
    if (auditEntityFilter) {
      auditEntityFilter.addEventListener("change", () => {
        state.audit.entityType = auditEntityFilter.value || "";
        render();
      });
    }

    const auditActionFilter = document.getElementById("audit-action-filter");
    if (auditActionFilter) {
      auditActionFilter.addEventListener("change", () => {
        state.audit.action = auditActionFilter.value || "";
        render();
      });
    }

    bindReconciliationFilters({ state, render, localRender: rerenderReconciliationLocally, showToast });

    // Actions triggers
    document.querySelectorAll("[data-action]").forEach(el => {
      el.addEventListener("click", (e) => {
        const action = el.dataset.action;
        const handled = handleReviewCenterAction({
          action,
          el,
          state,
          render,
          renderPreserveScroll,
          showToast,
          getActorName,
          withActorHeaders,
          getReviewPacketById,
          openPacketInStudio,
          syncLocalReviewPacket,
          upsertPostApprovalRun,
          pollPostApprovalRun,
          loadReviewHistoryData,
          getReviewCenterPendingItems,
          getSelectedReviewPacket,
          getTrackedReviewPacket,
          getRuntimeValidationState,
          updateReviewPacketLocally,
          loadGuidedReviewScopeLLM
        });
        if (handled) return;

        const guidedHandled = handleGuidedReviewAction({
          action,
          el,
          state,
          render,
          renderPreserveScroll,
          showToast,
          withActorHeaders,
          getReviewPacketById,
          syncLocalReviewPacket,
          updateReviewPacketLocally,
          getReviewCenterPendingItems,
          getSelectedReviewPacket,
          getTrackedReviewPacket,
          getRuntimeValidationState,
          pollPostApprovalRun,
          loadGuidedReviewScopeLLM,
          loadGuidedReviewAIMapping
        });
        if (guidedHandled) return;

        const reconHandled = handleReconciliationAction({
          action,
          el,
          state,
          render,
          localRender: rerenderReconciliationLocally,
          renderPreserveScroll,
          showToast,
          withActorHeaders,
          getActorName,
          getActivePostApprovalRunForContext,
          pollReconciliationRun,
          resolveReviewRecord,
          loadReconciliationReviewRecords,
          refreshAuditLogIfVisible,
          getActiveRenderToken: () => activeRenderToken
        });
        if (reconHandled) {
          // Sync floating bar state in case of reconciliation actions
          const bar = document.getElementById("bulk-action-bar");
          if (bar) {
            const selectedKeys = Object.entries(state.selectedReconRows || {})
              .filter(([, selected]) => selected)
              .map(([key]) => key);
            if (selectedKeys.length > 0) {
              bar.classList.add("visible");
              const countEl = document.getElementById("bulk-selected-count");
              if (countEl) countEl.textContent = selectedKeys.length;
            } else {
              bar.classList.remove("visible");
            }
          }
          return;
        }

        if (action === "run-job") {
          showToast(`Manual triggers active for partner: ${el.dataset.partner}`);
          return;
        }
        if (action === "copilot-action") {
          const actionKey = el.dataset.copilotAction;
          if (!actionKey) return;
          const originalText = el.innerHTML;
          el.disabled = true;
          el.style.opacity = "0.65";
          el.innerHTML = `<span class="spinner small"></span> Working...`;
          executeCopilotAction(actionKey)
            .then(body => {
              el.disabled = false;
              el.style.opacity = "";
              el.innerHTML = originalText;
              if (body.context) {
                state.copilotContext = body.context;
              }
              const target = body.target || {};
              if (target.type === "review_drawer") {
                if (target.reviewItemId) state.selectedReviewPacketId = target.reviewItemId;
                showToast("Opening review drawer.");
                location.hash = "review-center";
                return;
              }
              if (target.type === "review_queue") {
                showToast("Opening Review Center.");
                location.hash = "review-center";
                return;
              }
              if (target.type === "mapping_studio") {
                state.studio.reviewItemId = target.reviewItemId || null;
                state.studio.draftMappingId = target.draftMappingId || null;
                showToast("Opening Mapping Studio.");
                location.hash = "mapping-studio";
                return;
              }
              const runInfo = body.result?.postApproveRun;
              if (runInfo?.partner) state.partner = runInfo.partner;
              if (runInfo?.date) state.date = runInfo.date;
              const decisionActions = ["reject_proposal", "approve_activate_next_runtime", "approve_keep_current"];
              if (decisionActions.includes(actionKey)) {
                state.briefOpen = false;
                state.briefStep = 0;
                showToast(actionKey === "reject_proposal" ? "Proposal rejected." : "Proposal approved.");
              } else {
                showToast(actionKey === "refresh_context" ? "Recommendation refreshed." : "Copilot action completed.");
              }
              render();
            })
            .catch(err => {
              el.disabled = false;
              el.style.opacity = "";
              el.innerHTML = originalText;
              showToast(err.message || "Copilot action failed");
            });
          return;
        }
        if (action === "run-job-now") {
          const partner = el.dataset.partner;
          if (!partner) return;
          const originalText = el.innerHTML;
          el.disabled = true;
          el.style.opacity = "0.6";
          el.style.cursor = "not-allowed";
          el.innerHTML = `<span class="spinner-mini" style="display:inline-block; width:12px; height:12px; border:2px solid #000; border-top:2px solid transparent; border-radius:50%; animation:spin 1s linear infinite; margin-right:6px; vertical-align:middle;"></span>Running...`;
          showToast(`Running automation job for ${partner}...`);
          fetch(`/api/v1/automation/jobs/${encodeURIComponent(partner)}/run`, {
            method: "POST",
            headers: withActorHeaders({ "Content-Type": "application/json" }),
            body: JSON.stringify({}),
          })
            .then(r => r.json().then(body => ({ ok: r.ok, body })))
            .then(({ ok, body }) => {
              if (!ok) throw new Error(body.detail || "Run now failed");
              state.automationRunningPartners = {
                ...(state.automationRunningPartners || {}),
                [partner]: true,
              };
              showToast(body.message || `Automation job queued for ${partner}.`);
              pollAutomationOverview();
            })
            .catch(err => {
              state.automationRunningPartners = {
                ...(state.automationRunningPartners || {}),
                [partner]: false,
              };
              el.disabled = false;
              el.style.opacity = "";
              el.style.cursor = "";
              el.innerHTML = originalText;
              showToast(err.message || "Run now failed");
            });
          return;
        }

      });
    });

    bindMappingStudioViewActions({
      state,
      render,
      showToast,
      withActorHeaders,
    });
    bindReconciliationEnhancedUi({
      state,
      render,
      localRender: rerenderReconciliationLocally,
    });

    const bulkActionBar = document.getElementById("bulk-action-bar");
    if (bulkActionBar) {
      const syncBulkActionBar = () => {
        const selectedCount = Object.values(state.selectedReconRows || {}).filter(Boolean).length;
        bulkActionBar.classList.toggle("visible", selectedCount > 0);
        bulkActionBar.dataset.selectedCount = String(selectedCount);
        const countLabel = document.getElementById("bulk-action-count");
        if (countLabel) {
          countLabel.textContent = `${selectedCount.toLocaleString("en-US")} items selected`;
        }
      };

      document.querySelectorAll('[data-action="toggle-recon-row"], [data-action="toggle-recon-select-all"]').forEach(input => {
        input.addEventListener("change", syncBulkActionBar);
      });

      syncBulkActionBar();
    }
  }

  function handleConfigParse(json) {
    const previewPanel = document.getElementById("config-preview-panel");
    const previewContent = document.getElementById("config-preview-content");
    if (!previewPanel || !previewContent) return;

    if (!json.partner || !json.fieldMappings) {
      previewContent.innerHTML = `<span style="color: var(--red);">Invalid config: Missing required fields 'partner' or 'fieldMappings'.</span>`;
      previewPanel.style.display = "block";
      return;
    }

    const mappingsHtml = json.fieldMappings.map(m => `
      <div class="mapping-grid">
        <div class="mapping-card">
          <span><strong>Source (Col: ${m.column || 'Constant'})</strong></span>
          <code>${m.path}</code>
        </div>
        <div class="mapping-arrow"><span class="material-symbols-outlined">arrow_forward</span></div>
        <div class="mapping-card">
          <span><strong>Type Mapping</strong></span>
          <code>${m.type} ${m.required ? '(Required)' : ''}</code>
        </div>
      </div>
    `).join("");

    previewContent.innerHTML = `
      <div class="grid cols-3" style="margin-bottom: 20px;">
        <div class="metric">
          <span>Partner</span>
          <strong>${json.partner}</strong>
          <small>Workflow: ${json.workflowType || 'UPC'}</small>
        </div>
        <div class="metric">
          <span>File Type</span>
          <strong>${json.fileType || 'SETTLEMENT'}</strong>
          <small>Sheet: ${json.sheetName || 'N/A'}</small>
        </div>
        <div class="metric">
          <span>Config Version</span>
          <strong>${json.configVersion || 'latest'}</strong>
          <small>Start row: ${json.startRow || 2}</small>
        </div>
      </div>
      
      <h3>Field Mappings Details</h3>
      ${mappingsHtml}
    `;

    previewPanel.style.display = "block";
  }











  function renderPreserveScroll() {
    const viewport = document.scrollingElement || document.documentElement;
    state.preservedScrollTop = viewport ? viewport.scrollTop : 0;
    render();
  }

  init();
})();
