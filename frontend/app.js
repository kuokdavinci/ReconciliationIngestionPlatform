(function () {
  const state = {
    route: "review-center",
    partner: "MOMO",
    partnerOptions: ["MOMO", "VNPAY", "ZALOPAY", "ACMEPAY"],
    date: new Date().toLocaleDateString('sv'),
    focus: "operational",
    reconStatus: "",
    explorerFilters: { amountMin: "", amountMax: "", dateFrom: "", dateTo: "" },
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
    reviewTab: "pending",
    reviewHistoryCache: null,
    reviewHistoryLoading: false,
    preservedScrollTop: null,
    briefOpen: false,
    localDraftMappingIds: {},
    guidedReviewAI: {
      loading: false,
      error: "",
      mapping: null,
      packetId: null
    }
  };

  const routes = [
    ["review-center", "Review Center", "fact_check"],
    ["reconciliation", "Reconciliation", "receipt_long"],
    ["automation", "Automation", "smart_toy"],
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
  let briefStep = 0;
  const BRIEF_STEPS = ["Brief", "Review", "Decision"];
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

  function init() {
    renderNav();
    window.addEventListener("hashchange", onRouteChange);
    onRouteChange();

    view.addEventListener("click", (e) => {
      const tab = e.target.closest(".segmented-tab");
      if (tab) {
        state.focus = tab.dataset.focus;
        view.innerHTML = renderCommandCenter();
        fetchPartners();
        bindFilters();
        bindViewActions();
      }
    });

    // Handle clicks inside the modal-root and global data-action elements (modal dialogs + table eye icon clicks)
    document.addEventListener("click", (e) => {
      // 1. Global delegation for open-evidence-detail (eye icon)
      const openDetailEl = e.target.closest("[data-action='open-evidence-detail']");
      if (openDetailEl) {
        const rowId = openDetailEl.dataset.rowId;
        state.selectedEvidenceRowId = rowId;
        render();
        return;
      }

      // 2. Modal actions delegation
      const modalActionEl = e.target.closest("#modal-root [data-action]");
      if (modalActionEl) {
        const action = modalActionEl.dataset.action;
        if (action === "close-evidence-drawer") {
          state.selectedEvidenceRowId = null;
          render();
          return;
        }
        if (action === "mark-exception") {
          showToast("Record marked as exception.");
          state.selectedEvidenceRowId = null;
          render();
          return;
        }
        if (action === "create-adjustment") {
          const txnId = modalActionEl.dataset.txnId || "";
          const amount = modalActionEl.dataset.amount || "";
          state.adjustmentModalData = { txnId, amount };
          state.selectedEvidenceRowId = null;
          render();
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
              showToast("Note saved and record marked as reviewed.");
              state.selectedEvidenceRowId = null;
              render();
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
      headers: { "Content-Type": "application/json" },
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
      headers: { "Content-Type": "application/json" },
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

  function getReviewPacketById(packetId) {
    return ([...(state.reviewCenterCache?.data?.packets || []), ...(state.reviewPackets || [])]
      .find(item => String(item._id) === String(packetId)) || null);
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

  function getPartnerOptions() {
    const base = state.partnerOptions && state.partnerOptions.length
      ? state.partnerOptions
      : ["MOMO", "VNPAY", "ZALOPAY", "ACMEPAY"];
    return Array.from(new Set([...(state.partner ? [state.partner] : []), ...base]));
  }

  function syncPartnerFilterOptions(container) {
    const partners = getPartnerOptions();
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

  function fetchPartners(container) {
    const requestToken = ++activePartnerFetchToken;
    fetch("/api/v1/data/stats?date=" + state.date)
      .then(r => r.json())
      .then(data => {
        if (requestToken !== activePartnerFetchToken) return;
        const found = Object.keys(data.by_partner || {});
        const defaultPartners = ["MOMO", "VNPAY", "ZALOPAY", "ACMEPAY"];
        const partners = Array.from(new Set([...found, ...defaultPartners]));
        state.partnerOptions = partners;
        if (!partners.includes(state.partner) && partners.length) {
          state.partner = partners[0];
          render();
          return;
        }
        syncPartnerFilterOptions(container);
      })
      .catch(() => {
        if (requestToken !== activePartnerFetchToken) return;
        state.partnerOptions = ["MOMO", "VNPAY", "ZALOPAY", "ACMEPAY"];
        if (!state.partnerOptions.includes(state.partner)) {
          state.partner = state.partnerOptions[0];
        }
        syncPartnerFilterOptions(container);
      });
  }

  function parseIsoDate(value) {
    const [year, month, day] = String(value || "").split("-").map(Number);
    if (!year || !month || !day) return null;
    const utcDate = new Date(Date.UTC(year, month - 1, day));
    return Number.isNaN(utcDate.getTime()) ? null : utcDate;
  }

  function formatIsoDate(date) {
    const year = date.getUTCFullYear();
    const month = String(date.getUTCMonth() + 1).padStart(2, "0");
    const day = String(date.getUTCDate()).padStart(2, "0");
    return `${year}-${month}-${day}`;
  }

  function formatDisplayDate(value) {
    const parsed = parseIsoDate(value);
    if (!parsed) return String(value || "-");
    const day = String(parsed.getUTCDate()).padStart(2, "0");
    const month = String(parsed.getUTCMonth() + 1).padStart(2, "0");
    const year = parsed.getUTCFullYear();
    return `${day}/${month}/${year}`;
  }

  function formatDisplayDateTime(value) {
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return value || "-";
    const day = String(parsed.getDate()).padStart(2, "0");
    const month = String(parsed.getMonth() + 1).padStart(2, "0");
    const year = parsed.getFullYear();
    const hours = String(parsed.getHours()).padStart(2, "0");
    const minutes = String(parsed.getMinutes()).padStart(2, "0");
    const seconds = String(parsed.getSeconds()).padStart(2, "0");
    return `${day}/${month}/${year} ${hours}:${minutes}:${seconds}`;
  }

  function shiftIsoDate(value, offsetDays) {
    const base = parseIsoDate(value) || new Date();
    const shifted = new Date(base.getTime());
    shifted.setUTCDate(shifted.getUTCDate() + offsetDays);
    return formatIsoDate(shifted);
  }

  function parseFlexibleDateInput(value, fallbackDate = state.date) {
    const raw = String(value || "").trim();
    if (!raw) return null;

    if (/^\d{4}-\d{2}-\d{2}$/.test(raw)) {
      return parseIsoDate(raw) ? raw : null;
    }

    const fallback = parseIsoDate(fallbackDate) || new Date();
    const fallbackYear = fallback.getUTCFullYear();
    let year;
    let month;
    let day;

    if (/^\d{4}$/.test(raw)) {
      month = Number(raw.slice(0, 2));
      day = Number(raw.slice(2, 4));
      year = fallbackYear;
    } else {
      const normalized = raw.replace(/[.\s-]+/g, "/");
      const parts = normalized.split("/").filter(Boolean);
      if (parts.length === 2) {
        [day, month] = parts.map(Number);
        year = fallbackYear;
      } else if (parts.length === 3) {
        [day, month, year] = parts.map(Number);
      } else {
        return null;
      }
    }

    if (!year || !month || !day) return null;
    const parsed = new Date(Date.UTC(year, month - 1, day));
    if (
      Number.isNaN(parsed.getTime()) ||
      parsed.getUTCFullYear() !== year ||
      parsed.getUTCMonth() !== month - 1 ||
      parsed.getUTCDate() !== day
    ) {
      return null;
    }

    return formatIsoDate(parsed);
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

  function bindFilters() {
    document.querySelectorAll("#partner-filter").forEach(pf => {
      pf.addEventListener("change", () => {
        state.partner = pf.value;
        render();
      });
    });

    const applyMainDateInput = (input) => {
      if (!input) return;
      const parsed = parseFlexibleDateInput(input.value, state.date);
      if (!parsed) {
        showToast("Ngay khong hop le. Dung dd/mm/yyyy, dd/mm, 0707 hoac yyyy-mm-dd.");
        input.value = formatDisplayDate(state.date);
        return;
      }
      state.date = parsed;
      render();
    };

    document.querySelectorAll("#date-filter").forEach(input => {
      input.addEventListener("change", () => applyMainDateInput(input));
      input.addEventListener("blur", () => applyMainDateInput(input));
      input.addEventListener("keydown", (event) => {
        if (event.key === "Enter") applyMainDateInput(input);
      });
    });

    document.querySelectorAll("#date-picker").forEach(input => {
      input.addEventListener("change", () => {
        if (!input.value) return;
        state.date = input.value;
        render();
      });
    });

    document.querySelectorAll("[data-action='open-date-picker']").forEach(button => {
      button.addEventListener("click", () => {
        const picker = button.parentElement?.querySelector("#date-picker");
        if (!picker) return;
        if (typeof picker.showPicker === "function") {
          picker.showPicker();
          return;
        }
        picker.focus();
        picker.click();
      });
    });

  }

  function onRouteChange() {
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
      if (!state.selectedReviewPacketId && selectableIds.length) {
        state.selectedReviewPacketId = selectableIds[0];
      }
      if (state.selectedReviewPacketId && !selectableIds.includes(state.selectedReviewPacketId)) {
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
      view.innerHTML = loadingPanel("Loading review center...");
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
    if (!isAlreadyOnRecon) {
      view.innerHTML = loadingPanel("Loading reconciliation results...");
    } else {
      state.preservedScrollTop = (document.scrollingElement || document.documentElement).scrollTop;
    }

    let url = `/api/v1/reconciliation/results?partner=${encodeURIComponent(state.partner)}&date=${encodeURIComponent(state.date)}&limit=100`;
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
    const [insightsSummary, anomalies, patterns, recommendations, copilot] = await Promise.all([
      fetchJson(`/api/v1/reconciliation/insights?type=summary&partner=${encodeURIComponent(state.partner)}&date=${encodeURIComponent(state.date)}`).catch(() => null),
      fetchJson(`/api/v1/reconciliation/insights?type=anomalies&partner=${encodeURIComponent(state.partner)}&date=${encodeURIComponent(state.date)}`).catch(() => null),
      fetchJson(`/api/v1/reconciliation/insights?type=patterns&partner=${encodeURIComponent(state.partner)}&date=${encodeURIComponent(state.date)}`).catch(() => null),
      fetchJson(`/api/v1/reconciliation/insights?type=recommendations&partner=${encodeURIComponent(state.partner)}&date=${encodeURIComponent(state.date)}`).catch(() => null),
      fetchJson(`/api/v1/copilot/context?partner=${encodeURIComponent(state.partner)}&date=${encodeURIComponent(state.date)}&screen=reconciliation`).catch(() => null)
    ]);
    if (
      renderToken !== activeRenderToken ||
      state.route !== routeAtStart ||
      state.partner !== partnerAtStart ||
      state.date !== dateAtStart
    ) return;
    state.insightsSummary = insightsSummary;
    state.insightsData = { anomalies, patterns, recommendations };
    state.copilotContext = copilot;
    if (!state.activeReconData || state.lastPartner !== state.partner || state.lastDate !== state.date) {
      state.activeReconData = data;
      state.lastPartner = state.partner;
      state.lastDate = state.date;
    }
    view.innerHTML = renderReconciliation(state.activeReconData);
    if (typeof state.preservedScrollTop === "number") {
      const viewport = document.scrollingElement || document.documentElement;
      viewport.scrollTop = state.preservedScrollTop;
      state.preservedScrollTop = null;
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
    view.innerHTML = renderAutomation(data);
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
      "mapping-studio": `Create a draft mapping, validate it, then send it to Review Center`
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

  }

  function renderCopilotBrief(copilot = state.copilotContext, pendingItems = []) {
    if (!copilot) return '';

    const rawStatus = String(copilot.status || "healthy");
    const riskLevel = copilot.riskLevel || "low";
    const headline = copilot.headline || "";
    const summary = copilot.summary || "";
    const evidence = copilot.evidence || {};
    const safeChecks = Array.isArray(evidence.safeChecks) ? evidence.safeChecks : [];
    const latestFile = evidence.latestFile || null;
    const runtime = evidence.runtime || {};
    const proposal = evidence.proposal || {};
    const primaryAction = copilot.primaryAction || null;
    const secondaryActions = Array.isArray(copilot.secondaryActions) ? copilot.secondaryActions : [];
    const decisionActions = Array.isArray(copilot.decisionActions) ? copilot.decisionActions : [];

    const runtimeVersion = runtime.version || null;
    const runtimeActive = runtime.state === "approved";
    const latestFileName = latestFile?.name || null;
    const latestFileFailed = latestFile && String(latestFile.status || "").toLowerCase() === "failed";
    const hasProposal = proposal.state && proposal.state !== "none";
    const hasDecision = decisionActions.length > 0;
    const proposalReason = proposal.reason || "";

    const verdictMap = {
      healthy: "No approval needed",
      monitor: "Monitor only",
      needs_review: "Review required before approving",
      blocked: "Blocked until mapping is fixed"
    };
    const verdict = verdictMap[rawStatus] || verdictMap.healthy;

    const statusColor = rawStatus === "healthy" ? "var(--success)"
      : rawStatus === "monitor" ? "var(--warning)"
      : "var(--danger)";

    const firstItem = pendingItems.length ? pendingItems[0] : null;

    // Step 1: Brief — status + risk + verdict + 3 compact facts
    const step1 = `
      <div class="brief-hero">
        <div class="brief-hero-badges">
          ${badge(rawStatus.toUpperCase())}
          ${severityBadge(riskLevel)}
        </div>
        <span class="brief-hero-verdict" style="color:${statusColor}">${escapeHtml(verdict)}</span>
        <p class="brief-hero-line">${escapeHtml(headline || summary || "No issues detected.")}</p>
      </div>
      <div class="brief-facts">
        <div class="brief-fact">
          <span class="brief-fact-label">Runtime</span>
          <span class="brief-fact-value">${escapeHtml(runtimeVersion || 'N/A')}${runtimeActive ? ' <span class="badge ok">active</span>' : ''}</span>
        </div>
        <div class="brief-fact${latestFileFailed ? ' fact-failed' : ''}">
          <span class="brief-fact-label">Latest file</span>
          <span class="brief-fact-value">${latestFileFailed ? 'Failed' : escapeHtml(latestFileName || 'None')}</span>
        </div>
        <div class="brief-fact${pendingItems.length ? ' fact-warn' : ''}">
          <span class="brief-fact-label">Review</span>
          <span class="brief-fact-value">${pendingItems.length ? `${pendingItems.length} item${pendingItems.length > 1 ? 's' : ''} waiting` : 'None'}</span>
        </div>
      </div>`;

    // Step 2: Review — review item summary or monitoring summary
    const step2 = firstItem ? `
      <div class="brief-review-item">
        <div class="brief-review-header">
          <span class="brief-review-kind badge ${firstItem.kind === 'REVIEW_PACKET' ? 'warning' : 'neutral'}">${escapeHtml(firstItem.kind === 'REVIEW_PACKET' ? 'Review' : 'Draft Mapping')}</span>
          <span class="badge ${firstItem.status === 'PENDING' ? 'warning' : 'neutral'}">${escapeHtml(firstItem.status || 'PENDING')}</span>
        </div>
        <h3 class="brief-review-title">${escapeHtml(firstItem.title || 'Review item')}</h3>
        ${firstItem.reason ? `<p class="brief-review-reason">${escapeHtml(firstItem.reason)}</p>` : ''}
        ${firstItem.fileName ? `<div class="brief-review-file"><span class="material-symbols-outlined">description</span> ${escapeHtml(firstItem.fileName)}</div>` : ''}
      </div>
      <div class="brief-review-impact">
        ${safeChecks.length ? safeChecks.map(check => {
          const label = check.label === "Latest file can continue" ? "Current runtime can continue"
            : check.label === "Draft ready" ? "Draft mapping available"
            : check.label;
          return `<div class="brief-check ${escapeHtml(check.status || 'warn')}">
            <span class="material-symbols-outlined">${check.status === "pass" ? "check_circle" : check.status === "fail" ? "cancel" : "warning"}</span>
            <span>${escapeHtml(label)}</span>
          </div>`;
        }).join('') : ''}
        ${summary ? `<p class="brief-review-impact-text">${escapeHtml(summary)}</p>` : ''}
      </div>
      <button class="button secondary-action brief-review-cta" data-action="go-mapping-studio"><span class="material-symbols-outlined">schema</span> Open Mapping Studio</button>` : `
      <div class="brief-monitoring">
        <div class="brief-monitoring-icon"><span class="material-symbols-outlined">visibility</span></div>
        <p class="brief-monitoring-text">No review item is waiting.</p>
        ${runtimeActive ? '<p class="brief-monitoring-text">Current runtime can continue.</p>' : ''}
        ${latestFileFailed ? '<p class="brief-monitoring-text">Latest file needs investigation.</p>' : '<p class="brief-monitoring-text">All systems operational.</p>'}
      </div>`;

    // Step 3: Decision — recommendation + primary CTA + secondary + decision actions
    const actionLabel = (key) => ({ review_proposal: "Open Review Center", approve_activate_next_runtime: "Approve & activate", approve_keep_current: "Keep current runtime", reject_proposal: "Reject change", open_mapping_details: "View mapping", refresh_context: "Refresh" })[key] || key.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
    const actionIcon = (key) => ({ review_proposal: "fact_check", approve_activate_next_runtime: "check_circle", approve_keep_current: "pause_circle", reject_proposal: "cancel", open_mapping_details: "schema", refresh_context: "refresh" })[key] || "play_arrow";

    const step3 = `
      <div class="brief-decision-recommendation">
        <span class="brief-rec-label">Recommendation</span>
        <p class="brief-rec-text">${escapeHtml(summary || verdict)}</p>
      </div>
      ${primaryAction ? `
      <div class="brief-decision-primary">
        <button class="button primary brief-decision-cta" data-action="copilot-action" data-copilot-action="${escapeHtml(primaryAction.key)}">
          <span class="material-symbols-outlined">${actionIcon(primaryAction.key)}</span>
          ${escapeHtml(actionLabel(primaryAction.key))}
        </button>
      </div>` : ''}
      <div class="brief-decision-links">
        <button class="button-link" data-action="go-review-center">Open full Review Center</button>
      </div>
      ${hasDecision ? `
      <div class="brief-decision-actions">
        <p class="brief-decision-hint">Decide on the proposed change:</p>
        <div class="brief-decision-buttons">
          ${decisionActions.map(a => `
            <button class="button brief-decision-btn ${a.key === 'reject_proposal' ? 'danger' : 'secondary-action'}" data-action="copilot-action" data-copilot-action="${escapeHtml(a.key)}">
              <span class="material-symbols-outlined">${actionIcon(a.key)}</span>
              ${escapeHtml(actionLabel(a.key))}
            </button>`).join('')}
        </div>
      </div>` : ''}`;

    const panes = [step1, step2, step3];

    return `
      <div class="brief-overlay" data-action="close-brief">
        <div class="brief-modal">
          <div class="brief-modal-header">
            <div>
              <span class="brief-eyebrow">COPILOT BRIEF</span>
              <div class="brief-header-badges">
                ${badge(rawStatus.toUpperCase())}
                ${severityBadge(riskLevel)}
              </div>
            </div>
            <button class="brief-close-btn" data-action="close-brief">&times;</button>
          </div>
          <div class="brief-steps-row">
            ${BRIEF_STEPS.map((s, i) => `
              <div class="brief-step ${i === briefStep ? 'active' : i < briefStep ? 'done' : ''}" data-index="${i}">
                <span class="brief-step-dot">${i < briefStep ? '✓' : i + 1}</span>
                <span class="brief-step-name">${s}</span>
              </div>`).join('')}
          </div>
          <div class="brief-pane-container">
            ${panes.map((p, i) => `<div class="brief-pane ${i === briefStep ? 'active' : ''}" data-pane="${i}">${p}</div>`).join('')}
          </div>
          <div class="brief-nav">
            <button class="button" data-action="brief-prev" ${briefStep === 0 ? 'disabled' : ''}>Back</button>
            <div class="brief-nav-right">
              <button class="button secondary-action" data-action="close-brief">Close</button>
              ${briefStep < BRIEF_STEPS.length - 1
                ? '<button class="button primary" data-action="brief-next">Next</button>'
                : `<button class="button primary" data-action="close-brief">Done</button>`}
            </div>
          </div>
      </div>`;
  }

  function getReviewCenterPendingItems(data) {
    const packets = (data.packets || []).filter(packet => !state.partner || packet.partner === state.partner);
    const mappings = (data.mappings || []).filter(item => item.partner === state.partner);
    const pendingPackets = packets.filter(item => String(item.status || "").toUpperCase() === "PENDING");
    const pendingMappings = mappings.filter(item => item.status === "PENDING_APPROVAL" && !pendingPackets.some(p => p.draftMappingId === item._id));
    const virtualPackets = pendingMappings.map(mapping => ({
      _id: mapping._id,
      partner: mapping.partner,
      fileName: mapping.sheetName || "Manual Configuration",
      fileTypeDetected: mapping.fileType || "SETTLEMENT",
      status: "PENDING",
      draftMappingId: mapping._id,
      recommendedAction: { actionType: "APPROVE_REQUIRED_BEFORE_RUNTIME", reason: mapping.configHealth?.reasoning || "Pending mapping review." },
      parseStrategy: { sheetName: mapping.sheetName, startRow: mapping.startRow, fieldMappingCount: (mapping.fieldMappings || []).length },
      validationGates: mapping.validationGates || [],
      samplePreview: [],
      riskSummary: { severity: "medium" },
      createdAt: mapping.createdAt,
      isVirtual: true
    }));

    return [...pendingPackets, ...virtualPackets].map(packet => {
      const localDraftMappingId = state.localDraftMappingIds ? state.localDraftMappingIds[packet._id] : null;
      if (state.localValidationGates && state.localValidationGates[packet._id]) {
        return {
          ...packet,
          validationGates: state.localValidationGates[packet._id],
          draftMappingId: localDraftMappingId || packet.draftMappingId || null
        };
      }
      if (localDraftMappingId) {
        return {
          ...packet,
          draftMappingId: localDraftMappingId
        };
      }
      return packet;
    });
  }

  function getSelectedReviewPacket(items) {
    return items.find(packet => packet._id === state.selectedReviewPacketId) || items[0] || null;
  }

  function summarizeReviewPacket(packet) {
    const gateSummary = (packet.validationGates || []).reduce((acc, gate) => {
      const status = String(gate.status || "").toLowerCase();
      acc[status] = (acc[status] || 0) + 1;
      return acc;
    }, {});
    const hasFailedGates = !!((gateSummary.fail || 0) + (gateSummary.failed || 0));
    const runtimeGate = (packet.validationGates || []).find(gate => gate.gateKey === "runtime_validation");
    const runtimeValidated = String(runtimeGate?.status || "").toLowerCase() === "pass";
    const mappingReady = !!packet.draftMappingId;
    return {
      gateSummary,
      hasFailedGates,
      runtimeGate,
      runtimeValidated,
      mappingReady,
      readyToActivate: mappingReady && runtimeValidated && !hasFailedGates
    };
  }

  function renderReviewCenterSummary(selectedPacket) {
    if (!selectedPacket) {
      return `
        <aside class="review-drawer empty">
          <div class="empty-state">
            <span class="material-symbols-outlined">smart_toy</span>
            <h3>No item selected</h3>
            <p class="muted">Select a pending item to view its review summary.</p>
          </div>
        </aside>
      `;
    }

    const reviewSummary = summarizeReviewPacket(selectedPacket);
    const shortTitle = selectedPacket.isVirtual ? "Draft mapping update" : "Format verification required";
    const shortReason = selectedPacket.recommendedAction?.reason || "Awaiting reviewer decision.";
    const risk = selectedPacket.riskSummary?.severity || "medium";

    return `
      <aside class="review-drawer review-summary-drawer" style="padding: 20px;">
        <div class="brief-section" style="border-bottom: none; margin-bottom: 0; padding-bottom: 0;">
          <div style="display:flex; gap:8px; align-items:center; flex-wrap:wrap;">
            <span class="badge ${risk === 'critical' || risk === 'high' ? 'failed' : 'warning'}">${escapeHtml(risk.toUpperCase())} RISK</span>
            ${reviewSummary.runtimeValidated ? '<span class="badge matched">Runtime validated</span>' : '<span class="badge warning">Runtime validate pending</span>'}
          </div>
          <h3 class="brief-title" style="font-size: 16px; margin: 10px 0 6px 0;">${escapeHtml(shortTitle)}</h3>
          <p class="brief-subtitle" style="font-size: 13px; margin-bottom: 12px;">${escapeHtml(shortReason)}</p>
        </div>
        <div class="review-summary-list">
          <div><strong>File:</strong> ${escapeHtml(selectedPacket.fileName || "-")}</div>
          <div><strong>Runtime:</strong> ${selectedPacket.activeRuntimeConfigId ? "Current runtime available" : "No active runtime"}</div>
          <div><strong>Draft mapping:</strong> ${reviewSummary.mappingReady ? "Ready" : "Missing"}</div>
        </div>
        <div style="margin-top: 16px; display:flex; gap:10px; flex-direction:column;">
          <button class="button primary" data-action="open-guided-review" style="width: 100%; justify-content: center;">
            <span class="material-symbols-outlined" style="font-size:18px; margin-right:4px;">quickreply</span> Open Review Panel
          </button>
          <button class="button secondary-action" data-action="go-mapping-studio" style="width: 100%; justify-content: center;">
            <span class="material-symbols-outlined" style="font-size:18px; margin-right:4px;">schema</span> Open Mapping Studio
          </button>
        </div>
      </aside>
    `;
  }

  const VALIDATION_SUGGESTIONS = {
    SOURCE_FIELD_NOT_FOUND: "Source field does not exist in sample data. Re-map this target to an existing partner field.",
    MISSING_REQUIRED_FIELD: "Required field '<field>' is missing. Map a partner field to this canonical field.",
    INVALID_DECIMAL: "Map the partner numeric amount field to 'amount' and ensure the sample value is numeric.",
    INVALID_DATE: "Check the source date field and ensure it matches a supported runtime date format.",
    UNMAPPED_VALUE: "Add a mapping rule for this partner value or configure a fallback rule.",
    INVALID_CANONICAL_STATUS: "Map the partner status into one of SUCCESS, FAILED, PENDING, REVERSED."
  };

  function getDraftMappingVersion(packet) {
    return packet?.draftMappingVersion
      || state.guidedReviewAI?.mapping?.draftMappingVersion
      || state.guidedReviewAI?.mapping?.configVersion
      || packet?.draftMappingId
      || null;
  }

  function getRuntimeValidationState(packet) {
    const runtimeGate = (packet?.validationGates || []).find(gate => gate.gateKey === "runtime_validation") || null;
    const details = runtimeGate?.details || {};
    const currentVersion = getDraftMappingVersion(packet);
    const validatedVersion = details.validatedMappingVersion || null;
    const hasValidation = !!runtimeGate;
    const isStale = !!(hasValidation && currentVersion && validatedVersion && currentVersion !== validatedVersion);
    const failedRows = Number(details.failedRows || 0);
    const status = String(runtimeGate?.status || "").toLowerCase();
    const summaryLabel = !hasValidation ? "Not run" : isStale ? "Stale" : status !== "pass" ? "Failed" : failedRows > 0 ? "Passed with warnings" : "Passed";
    return {
      runtimeGate,
      currentVersion,
      validatedVersion,
      validatedAt: details.validatedAt || null,
      hasValidation,
      isStale,
      failedRows,
      canProceed: !!(runtimeGate && !isStale && status === "pass"),
      summaryLabel
    };
  }

  function getValidationSuggestion(code, field) {
    const template = VALIDATION_SUGGESTIONS[code] || "Review this mapping rule and align the partner source field, transform, and canonical target before validating again.";
    return template.replace("<field>", field || "field");
  }

  function collectValidationIssues(runtimeGate) {
    const issues = [];
    const seen = new Set();
    const traceSamples = Array.isArray(runtimeGate?.details?.traceSamples) ? runtimeGate.details.traceSamples : [];
    traceSamples.forEach(sample => {
      (sample.fieldTraces || []).forEach(trace => {
        if (!trace.errorCode) return;
        const key = `${trace.errorCode}:${trace.path || ""}:${trace.errorMessage || ""}`;
        if (seen.has(key)) return;
        seen.add(key);
        issues.push({
          code: trace.errorCode,
          field: trace.path || trace.sourceField || "",
          row: sample.row,
          message: trace.errorMessage || trace.errorCode,
          suggestion: getValidationSuggestion(trace.errorCode, trace.path)
        });
      });
      (sample.buildErrors || []).forEach(err => {
        const key = `${err.errorCode || "CANONICAL_BUILD_FAILED"}:${err.field || ""}:${err.reason || ""}`;
        if (seen.has(key)) return;
        seen.add(key);
        issues.push({
          code: err.errorCode || "CANONICAL_BUILD_FAILED",
          field: err.field || "",
          row: err.row || sample.row,
          message: err.reason || err.errorCode || "Build failed",
          suggestion: getValidationSuggestion(err.errorCode || "CANONICAL_BUILD_FAILED", err.field)
        });
      });
    });
    return issues;
  }

  function collectRuntimeFieldStats(runtimeGate) {
    const stats = {};
    const traceSamples = Array.isArray(runtimeGate?.details?.traceSamples) ? runtimeGate.details.traceSamples : [];
    traceSamples.forEach(sample => {
      (sample.fieldTraces || []).forEach(trace => {
        const key = trace.path || trace.sourceField || "unknown";
        if (!stats[key]) {
          stats[key] = { field: key, ok: 0, warning: 0, error: 0 };
        }
        const status = trace.status || "ok";
        if (status === "warning") stats[key].warning += 1;
        else if (status === "error") stats[key].error += 1;
        else stats[key].ok += 1;
      });
    });
    return Object.values(stats).sort((a, b) => (b.error - a.error) || (b.warning - a.warning) || a.field.localeCompare(b.field));
  }

  function collectCandidateColumns(headers, sampleRows) {
    const maxCols = Math.max(headers.length, ...sampleRows.map(row => row.length), 0);
    const candidates = [];
    for (let index = 0; index < maxCols; index += 1) {
      const header = headers[index];
      const headerText = header === null || header === undefined ? "" : String(header).trim();
      const values = sampleRows.map(row => row[index]).filter(value => value !== null && value !== undefined && String(value).trim() !== "");
      if (!headerText && values.length === 0) continue;
      const meaningfulHeader = /[A-Za-zÀ-ỹ0-9]/.test(headerText);
      candidates.push({
        index,
        header: headerText || `Column ${index + 1}`,
        nonEmptyCount: values.length,
        sampleValues: values.slice(0, 2),
        priority: (meaningfulHeader ? 2 : 0) + Math.min(values.length, 3)
      });
    }
    return candidates.sort((a, b) => (b.priority - a.priority) || (b.nonEmptyCount - a.nonEmptyCount) || (a.index - b.index));
  }

  function renderRuntimeVisualSummary(runtimeGate, validationState) {
    const details = runtimeGate?.details || {};
    const sampledRows = Number(details.sampledRows || 0);
    const successRows = Number(details.successRows || 0);
    const failedRows = Number(details.failedRows || 0);
    const warningRows = validationState?.summaryLabel === "Passed with warnings" ? failedRows : 0;
    const hardFailedRows = validationState?.summaryLabel === "Failed" ? failedRows : 0;
    const okPercent = sampledRows ? (successRows / sampledRows) * 100 : 0;
    const warnPercent = sampledRows ? (warningRows / sampledRows) * 100 : 0;
    const failPercent = sampledRows ? (hardFailedRows / sampledRows) * 100 : 0;
    const fieldStats = collectRuntimeFieldStats(runtimeGate).slice(0, 6);
    const freshnessTone = validationState?.isStale ? "warning" : validationState?.hasValidation ? "matched" : "neutral";

    const heatmapHtml = fieldStats.length ? fieldStats.map(item => {
      const total = item.ok + item.warning + item.error;
      const okWidth = total ? (item.ok / total) * 100 : 0;
      const warningWidth = total ? (item.warning / total) * 100 : 0;
      const errorWidth = total ? (item.error / total) * 100 : 0;
      return `
        <div style="display:grid; grid-template-columns: 140px 1fr auto; gap:10px; align-items:center;">
          <div style="font-family:var(--font-mono); font-size:12px;">${escapeHtml(item.field)}</div>
          <div style="height:10px; border-radius:999px; overflow:hidden; background:rgba(255,255,255,0.06); display:flex;">
            <div style="width:${okWidth}%; background:#10B981;"></div>
            <div style="width:${warningWidth}%; background:#F59E0B;"></div>
            <div style="width:${errorWidth}%; background:#EF4444;"></div>
          </div>
          <div style="font-size:11px; color:var(--text-muted); min-width:72px; text-align:right;">${item.error} err / ${item.warning} warn</div>
        </div>
      `;
    }).join("") : `<div class="muted" style="font-size:12px;">No field-level runtime traces yet.</div>`;

    return `
      <section class="panel" style="margin:0; padding:16px; border-radius:10px;">
        <div style="display:grid; grid-template-columns: 1.2fr 0.8fr; gap:16px;">
          <div>
            <div style="font-size:12px; font-weight:700; text-transform:uppercase; color:var(--text-muted); margin-bottom:8px;">Runtime Coverage</div>
            <div style="height:14px; border-radius:999px; overflow:hidden; background:rgba(255,255,255,0.06); display:flex;">
              <div style="width:${okPercent}%; background:#10B981;"></div>
              <div style="width:${warnPercent}%; background:#F59E0B;"></div>
              <div style="width:${failPercent}%; background:#EF4444;"></div>
            </div>
            <div style="display:flex; gap:12px; flex-wrap:wrap; margin-top:8px; font-size:11px; color:var(--text-muted);">
              <span><strong style="color:#10B981;">${escapeHtml(String(successRows))}</strong> success</span>
              <span><strong style="color:#F59E0B;">${escapeHtml(String(warningRows))}</strong> warnings</span>
              <span><strong style="color:#EF4444;">${escapeHtml(String(hardFailedRows))}</strong> failed</span>
            </div>
          </div>
          <div>
            <div style="font-size:12px; font-weight:700; text-transform:uppercase; color:var(--text-muted); margin-bottom:8px;">Freshness</div>
            <div style="display:flex; gap:8px; flex-wrap:wrap; margin-bottom:8px;">
              <span class="badge ${freshnessTone}">${escapeHtml(validationState?.summaryLabel || "Not run")}</span>
              <span class="badge neutral">Draft ${escapeHtml(validationState?.currentVersion || "-")}</span>
            </div>
            <div style="font-size:11px; color:var(--text-muted);">Validated on <code>${escapeHtml(validationState?.validatedVersion || details.validatedMappingVersion || "-")}</code></div>
          </div>
        </div>
        <div style="margin-top:14px;">
          <div style="font-size:12px; font-weight:700; text-transform:uppercase; color:var(--text-muted); margin-bottom:8px;">Field Issue Heatmap</div>
          <div style="display:flex; flex-direction:column; gap:8px;">${heatmapHtml}</div>
        </div>
      </section>
    `;
  }

  function renderPartnerSampleRecord(packet, runtimeGate) {
    const headers = packet?.structureSignature?.headers || [];
    let rows = [];
    const hasDisplayValue = value => value !== null && value !== undefined && String(value).trim() !== "";
    const relevantTraceKeys = new Set(
      ((runtimeGate?.details?.traceSamples || [])[0]?.fieldTraces || [])
        .map(trace => trace.sourceField || (trace.column ? `Column ${trace.column}` : ""))
        .filter(Boolean)
    );

    if (Array.isArray(packet?.samplePreview) && packet.samplePreview.length > 0) {
      rows = packet.samplePreview.slice(0, 20).map(sample => ({
        rowIndex: sample?.rowIndex || null,
        cells: Array.isArray(sample?.values)
          ? sample.values.map((value, index) => ({
              key: headers[index] || `Column ${index + 1}`,
              value
            }))
          : []
      }));
    } else {
      rows = (runtimeGate?.details?.traceSamples || []).slice(0, 20).map(sample => ({
        rowIndex: sample?.row || null,
        cells: (sample?.fieldTraces || []).map(trace => ({
          key: trace.sourceField || (trace.column ? `Column ${trace.column}` : trace.path || "Field"),
          value: trace.sourceValue
        }))
      }));
    }

    const usableRows = rows
      .map(row => ({
        rowIndex: row.rowIndex,
        cells: (row.cells || []).filter(cell => cell.key)
      }))
      .filter(row => row.cells.length > 0)
      .slice(0, 20);

    if (!usableRows.length) {
      return `
        <section class="panel" style="margin:0; padding:16px; border-radius:10px;">
          <div style="font-size:12px; font-weight:700; text-transform:uppercase; color:var(--text-muted); margin-bottom:8px;">Partner Sample Rows</div>
          <div class="muted" style="font-size:12px;">No partner sample rows are attached to this review packet.</div>
        </section>
      `;
    }

    const derivedHeaders = headers.length
      ? headers.map((header, index) => ({ key: header || `Column ${index + 1}`, index }))
      : usableRows[0].cells.map((cell, index) => ({ key: cell.key || `Column ${index + 1}`, index }));

    const relevantHeaders = derivedHeaders.filter(header => relevantTraceKeys.has(header.key));
    const limitedHeaders = (relevantHeaders.length ? relevantHeaders : derivedHeaders)
      .filter(header => usableRows.some(row => hasDisplayValue(row.cells[header.index]?.value)))
      .slice(0, 8);

    return `
      <section class="panel" style="margin:0; padding:16px; border-radius:10px;">
        <div style="display:flex; justify-content:space-between; gap:12px; align-items:center; margin-bottom:10px; flex-wrap:wrap;">
          <div style="font-size:12px; font-weight:700; text-transform:uppercase; color:var(--text-muted);">Partner Sample Rows</div>
          <span class="badge neutral">${escapeHtml(String(usableRows.length))} records</span>
        </div>
        <div class="table-wrap">
          <table style="width:100%; border-collapse:collapse; font-size:11.5px;">
            <thead>
              <tr style="border-bottom:1px solid rgba(255,255,255,0.08); background:rgba(255,255,255,0.03);">
                <th style="padding:8px 10px; text-align:left; white-space:nowrap;">Row</th>
                ${limitedHeaders.map(header => `<th style="padding:8px 10px; text-align:left; white-space:nowrap;">${escapeHtml(String(header.key))}</th>`).join("")}
              </tr>
            </thead>
            <tbody>
              ${usableRows.map(row => `
                <tr style="border-bottom:1px solid rgba(255,255,255,0.05);">
                  <td style="padding:8px 10px; font-family:var(--font-mono); color:var(--brand-accent-blue); white-space:nowrap;">${escapeHtml(String(row.rowIndex ?? "-"))}</td>
                  ${limitedHeaders.map(header => {
                    const cell = row.cells[header.index];
                    return `<td style="padding:8px 10px; font-family:var(--font-mono); word-break:break-word;">${escapeHtml(String(cell?.value ?? "-"))}</td>`;
                  }).join("")}
                </tr>
              `).join("")}
            </tbody>
          </table>
        </div>
      </section>
    `;
  }

  function renderRuntimeTraceSamples(runtimeGate) {
    if (!runtimeGate?.details || !Array.isArray(runtimeGate.details.traceSamples) || runtimeGate.details.traceSamples.length === 0) {
      return `<div class="muted" style="font-size:12px;">No runtime trace samples are available yet.</div>`;
    }

    const hasDisplayValue = value => value !== null && value !== undefined && String(value).trim() !== "";

    const rowsHtml = runtimeGate.details.traceSamples.map((sample, index) => {
      const fieldTraces = Array.isArray(sample.fieldTraces)
        ? sample.fieldTraces.filter(trace =>
            hasDisplayValue(trace.sourceValue)
            || hasDisplayValue(trace.outputValue)
            || hasDisplayValue(trace.errorMessage)
            || hasDisplayValue(trace.path)
          )
        : [];
      const buildErrors = Array.isArray(sample.buildErrors) ? sample.buildErrors : [];
      const rowStatus = buildErrors.length > 0 || fieldTraces.some(trace => trace.status === "error")
        ? "Failed"
        : fieldTraces.some(trace => trace.status === "warning")
          ? "Warning"
          : "Passed";
      const rowTone = rowStatus === "Failed" ? "critical" : rowStatus === "Warning" ? "warning" : "matched";
      const sourcePreview = fieldTraces.map(trace => {
        const label = trace.sourceField || (trace.column ? `Column ${trace.column}` : trace.type === "CONSTANT" ? "Constant" : trace.path || "-");
        return `<div style="display:flex; justify-content:space-between; gap:12px; padding:7px 0; border-bottom:1px solid rgba(255,255,255,0.05);"><div style="font-family:var(--font-mono); color:var(--text-muted);">${escapeHtml(String(label))}</div><div style="font-family:var(--font-mono); text-align:right; word-break:break-word;">${escapeHtml(String(trace.sourceValue ?? "-"))}</div></div>`;
      }).join("");
      const normalizedPreview = Object.entries(sample.normalizedData || {})
        .filter(([, value]) => hasDisplayValue(value))
        .map(([key, value]) => `<div style="display:flex; justify-content:space-between; gap:12px; padding:7px 0; border-bottom:1px solid rgba(255,255,255,0.05);"><div style="font-family:var(--font-mono);">${escapeHtml(String(key))}</div><div style="font-family:var(--font-mono); text-align:right; word-break:break-word;">${escapeHtml(String(value ?? "-"))}</div></div>`)
        .join("");
      const traceRows = fieldTraces.map(trace => {
        const sourceField = trace.sourceField || (trace.column ? `Column ${trace.column}` : trace.type === "CONSTANT" ? "Constant" : "-");
        const toneColor = trace.status === "error" ? "#ef4444" : trace.status === "warning" ? "#f59e0b" : "#10B981";
        return `
          <tr style="border-bottom:1px solid rgba(255,255,255,0.05);">
            <td style="padding:8px;">${escapeHtml(String(sourceField))}</td>
            <td style="padding:8px; font-family:var(--font-mono);">${escapeHtml(String(trace.sourceValue ?? "-"))}</td>
            <td style="padding:8px; font-family:var(--font-mono);">${escapeHtml(String(trace.path || "-"))}</td>
            <td style="padding:8px;">${escapeHtml(String(trace.type || "-"))}</td>
            <td style="padding:8px; font-family:var(--font-mono);">${escapeHtml(String(trace.outputValue ?? "-"))}</td>
            <td style="padding:8px; color:${toneColor}; text-transform:capitalize;">${escapeHtml(String(trace.status || "ok"))}</td>
            <td style="padding:8px; color:var(--text-muted);">${escapeHtml(String(trace.errorMessage || "-"))}</td>
          </tr>
        `;
      }).join("");
      const buildErrorsHtml = buildErrors.length ? `<div style="margin-top:12px; padding:12px; border:1px solid rgba(239,68,68,0.18); border-radius:8px; background:rgba(239,68,68,0.05);"><div style="font-size:11px; font-weight:700; text-transform:uppercase; color:#fca5a5; margin-bottom:6px;">Canonical Build Errors</div>${buildErrors.map(err => `<div style="font-size:12px; margin-top:4px;"><strong>${escapeHtml(String(err.field || "-"))}</strong> · ${escapeHtml(String(err.errorCode || "CANONICAL_BUILD_FAILED"))} · ${escapeHtml(String(err.reason || "-"))}</div>`).join("")}</div>` : "";
      return `
        <details ${index === 0 ? "open" : ""} style="border:1px solid rgba(255,255,255,0.08); border-radius:10px; background:rgba(255,255,255,0.02); overflow:hidden;">
          <summary style="list-style:none; cursor:pointer; padding:14px 16px; display:flex; justify-content:space-between; gap:12px; align-items:center;">
            <div style="display:flex; gap:10px; flex-wrap:wrap; align-items:center;">
              <strong>Row ${escapeHtml(String(sample.row || "-"))}</strong>
              <span class="badge ${rowTone}">${escapeHtml(rowStatus)}</span>
              <span class="badge neutral">${escapeHtml(String(fieldTraces.length))} traces</span>
            </div>
            <span class="material-symbols-outlined" style="font-size:18px; color:var(--text-muted);">expand_more</span>
          </summary>
          <div style="padding:0 16px 16px 16px; border-top:1px solid rgba(255,255,255,0.06);">
            <div style="display:grid; grid-template-columns:repeat(2, minmax(0, 1fr)); gap:12px; margin-top:14px;">
              <div style="padding:12px; border:1px solid rgba(255,255,255,0.06); border-radius:8px; background:rgba(255,255,255,0.015);">
                <div style="font-size:11px; font-weight:700; color:var(--text-muted); text-transform:uppercase; margin-bottom:8px;">Raw Source Snapshot</div>
                ${sourcePreview || `<span class="muted">No source values</span>`}
              </div>
              <div style="padding:12px; border:1px solid rgba(255,255,255,0.06); border-radius:8px; background:rgba(255,255,255,0.015);">
                <div style="font-size:11px; font-weight:700; color:var(--text-muted); text-transform:uppercase; margin-bottom:8px;">Normalized Output</div>
                ${normalizedPreview || `<span class="muted">No normalized output</span>`}
              </div>
            </div>
            <div style="margin-top:12px;">
              <div style="font-size:11px; font-weight:700; color:var(--text-muted); text-transform:uppercase; margin-bottom:8px;">Field-Level Trace</div>
              <div class="table-wrap">
                <table style="width:100%; border-collapse:collapse; font-size:11.5px;">
                  <thead>
                    <tr style="border-bottom:1px solid rgba(255,255,255,0.08);">
                      <th style="padding:6px 8px; text-align:left;">Raw Partner Field</th>
                      <th style="padding:6px 8px; text-align:left;">Raw Partner Value</th>
                      <th style="padding:6px 8px; text-align:left;">Target Internal Field</th>
                      <th style="padding:6px 8px; text-align:left;">Transform</th>
                      <th style="padding:6px 8px; text-align:left;">Final Normalized Value</th>
                      <th style="padding:6px 8px; text-align:left;">Validation Status</th>
                      <th style="padding:6px 8px; text-align:left;">Failure Reason</th>
                    </tr>
                  </thead>
                  <tbody>${traceRows}</tbody>
                </table>
              </div>
              ${buildErrorsHtml}
            </div>
          </div>
        </details>
      `;
    }).join("");

    return `<div style="display:flex; flex-direction:column; gap:10px;">${rowsHtml}</div>`;
  }

  function renderReviewHistoryTab() {
    if (state.reviewHistoryLoading) {
      return loadingPanel("Loading decision history...");
    }
    const history = state.reviewHistoryCache || { decisions: [], reconNotes: [] };
    const decisionRows = history.decisions.length ? history.decisions.map(item => `
      <tr>
        <td><strong>${escapeHtml(item.fileName || "-")}</strong></td>
        <td>${badge(item.status || "-")}</td>
        <td>${escapeHtml(item.decisionMode || "-")}</td>
        <td>${escapeHtml(item.parseStrategy?.strategy || "-")}</td>
        <td>${escapeHtml(formatDisplayDateTime(item.reviewedAt || item.createdAt || "-"))}</td>
      </tr>
    `).join("") : `<tr><td colspan="5" style="text-align:center; padding: 24px 0;">No recent packet decisions for this partner.</td></tr>`;

    const noteRows = history.reconNotes.length ? history.reconNotes.map(item => `
      <tr>
        <td><code>${escapeHtml(item.rowId)}</code></td>
        <td><strong>${escapeHtml(item.event)}</strong></td>
        <td style="font-variant-numeric: tabular-nums;">${escapeHtml(item.time)}</td>
      </tr>
    `).join("") : `<tr><td colspan="3" style="text-align:center; padding: 24px 0; color: var(--text-muted);">No reconciliation reviews recorded yet.</td></tr>`;

    return `
      <section class="panel">
        <div class="panel-header" style="margin-bottom: 16px;">
          <div>
            <h2 style="margin: 0; font-size: 18px;">Recent Decisions</h2>
            <p class="section-subtitle">Outcomes of recently processed review packets.</p>
          </div>
        </div>
        ${table(["File", "Decision", "Decision Mode", "Parse Strategy", "Reviewed At"], decisionRows)}
      </section>
      <section class="panel" style="margin-top: 24px;">
        <div class="panel-header" style="margin-bottom: 16px;">
          <div>
            <h2 style="margin: 0; font-size: 18px;">Reconciliation Review History</h2>
            <p class="section-subtitle">Persisted notes and resolution events for reconciled records.</p>
          </div>
        </div>
        ${table(["Transaction ID", "Review Event / Note", "Recorded At"], noteRows)}
      </section>
    `;
  }

  function renderReviewConfigsTab(mappings) {
    const approvedConfigs = mappings.filter(item => item.status === "APPROVED");
    const configRows = approvedConfigs.length ? approvedConfigs.map(config => `
      <tr>
        <td><strong>v${escapeHtml(String(config.configVersion || "1.0"))}</strong></td>
        <td><code>${escapeHtml(config.sheetName || "Sheet1")}</code></td>
        <td>Row ${formatNumber(config.startRow || 1)}</td>
        <td>${formatNumber((config.fieldMappings || []).length)} fields</td>
        <td><span class="badge matched">Active</span></td>
        <td>${escapeHtml(formatDisplayDateTime(config.approvedAt || config.createdAt || "-"))}</td>
      </tr>
    `).join("") : `<tr><td colspan="6" style="text-align:center; padding: 24px 0;">No approved runtime configurations found for this partner.</td></tr>`;

    return `
      <section class="panel">
        <div class="panel-header" style="margin-bottom: 16px;">
          <div>
            <h2 style="margin: 0; font-size: 18px;">Active Runtime Configurations</h2>
            <p class="section-subtitle">Approved configurations currently available to the parser.</p>
          </div>
        </div>
        ${table(["Version", "Sheet / Target", "Start Row", "Mappings", "Status", "Approved At"], configRows)}
      </section>
    `;
  }

  function renderGuidedReviewModal(selectedPacket) {
    if (!state.guidedReviewOpen || !selectedPacket) {
      return "";
    }

    if (!state.guidedReviewStep) {
      state.guidedReviewStep = 1;
    }

    const step = state.guidedReviewStep;
    const stepsList = ["Scope", "Mapping", "Validation", "Decision"];

    const progressSteps = stepsList.map((s, i) => {
      const stepIdx = i + 1;
      const isActive = stepIdx === step;
      const isDone = stepIdx < step;
      return `
        <div class="brief-step ${isActive ? 'active' : isDone ? 'done' : ''}" style="flex: 1; text-align: center; padding: 10px;">
          <span class="brief-step-dot" style="display: block; margin: 0 auto 8px; width: 28px; height: 28px; line-height: 28px; border-radius: 50%; background: ${isDone ? '#10B981' : isActive ? 'var(--brand-accent-blue)' : 'rgba(255,255,255,0.1)'}; color: #000; font-weight: 700;">${isDone ? '✓' : stepIdx}</span>
          <span class="brief-step-name" style="font-size: 11px; display: block; color: ${isActive ? '#FFF' : 'var(--text-muted)'};">${s}</span>
        </div>
      `;
    }).join("");

    let stepBodyHtml = "";

    if (step === 1) {
      if (!state.guidedReviewScope || state.guidedReviewScope.packetId !== selectedPacket._id) {
        loadGuidedReviewScopeLLM(selectedPacket);
      }
      const scopeState = state.guidedReviewScope || { loading: true, error: "", data: null };
      
      if (scopeState.loading) {
        stepBodyHtml = `
          <div class="empty-state" style="padding: 48px 12px;">
            <span class="spinner" style="display:inline-block; width:36px; height:36px; border:3px solid rgba(255,255,255,0.1); border-top:3px solid var(--brand-accent-blue); border-radius:50%; animation:spin 1s linear infinite;"></span>
            <h3 style="margin-top: 16px;">Running LLM Scope Analysis</h3>
            <p class="muted">Analyzing file name hints, received record counts, and database status...</p>
          </div>
        `;
      } else if (scopeState.error) {
        stepBodyHtml = `
          <div class="empty-state" style="padding: 48px 12px;">
            <span class="material-symbols-outlined" style="color:var(--status-failed); font-size:48px;">error</span>
            <h3 style="margin-top: 16px;">LLM Scope Analysis Failed</h3>
            <p class="muted">${escapeHtml(scopeState.error)}</p>
            <button class="button" onclick="location.reload()" style="margin-top:16px;">Retry</button>
          </div>
        `;
      } else if (scopeState.data) {
        const scopeData = scopeState.data;
        const currentScope = selectedPacket.scopeType || scopeData.suggestedScope || "FULL_SNAPSHOT";
        stepBodyHtml = `
          <div style="display:grid; grid-template-columns: 1fr 1fr; gap:16px; margin-bottom:16px;">
            <div class="panel" style="margin:0; padding:16px; text-align:center; background:rgba(255,255,255,0.01); border:1px solid rgba(255,255,255,0.06); border-radius:10px;">
              <div style="font-size:11px; color:var(--text-muted); text-transform:uppercase; font-weight:700; letter-spacing:0.05em;">Internal DB Records</div>
              <div style="font-size:32px; font-weight:800; color:#FFF; margin-top:8px; font-family:var(--font-mono);">${formatNumber(scopeData.internalDbRecordCount)}</div>
              <div style="font-size:11px; color:var(--text-muted); margin-top:4px;">Transactions stored in system for same day</div>
            </div>
            <div class="panel" style="margin:0; padding:16px; text-align:center; background:rgba(255,255,255,0.01); border:1px solid rgba(255,255,255,0.06); border-radius:10px;">
              <div style="font-size:11px; color:var(--text-muted); text-transform:uppercase; font-weight:700; letter-spacing:0.05em;">Received Records</div>
              <div style="font-size:32px; font-weight:800; color:#FFF; margin-top:8px; font-family:var(--font-mono);">${formatNumber(scopeData.receivedRecordCount)}</div>
              <div style="font-size:11px; color:var(--text-muted); margin-top:4px;">Records read from the uploaded file</div>
            </div>
          </div>
          <section class="panel" style="margin:0; padding:20px; border-radius:10px;">
            <h4 style="margin:0 0 16px 0; font-size:15px; border-bottom:1px solid rgba(255,255,255,0.06); padding-bottom:8px; color:var(--brand-accent-blue);">AI Scope Classification Prediction</h4>
            <div style="display:flex; flex-direction:column; gap:14px; margin-bottom:20px;">
              <div>
                <div style="display:flex; justify-content:space-between; font-size:12.5px; margin-bottom:4px;">
                  <span><strong>Full Snapshot</strong> (Wipe old & load new for entire day)</span>
                  <span style="font-family:var(--font-mono); font-weight:700;">${Math.round((scopeData.probabilities.FULL_SNAPSHOT || 0) * 100)}%</span>
                </div>
                <div style="height:8px; border-radius:4px; background:rgba(255,255,255,0.06); overflow:hidden;">
                  <div style="width:${Math.round((scopeData.probabilities.FULL_SNAPSHOT || 0) * 100)}%; height:100%; background:var(--brand-accent-blue); border-radius:4px;"></div>
                </div>
              </div>
              <div>
                <div style="display:flex; justify-content:space-between; font-size:12.5px; margin-bottom:4px;">
                  <span><strong>Incremental Append</strong> (Add/append new records cumulatively)</span>
                  <span style="font-family:var(--font-mono); font-weight:700;">${Math.round((scopeData.probabilities.INCREMENTAL_APPEND || 0) * 100)}%</span>
                </div>
                <div style="height:8px; border-radius:4px; background:rgba(255,255,255,0.06); overflow:hidden;">
                  <div style="width:${Math.round((scopeData.probabilities.INCREMENTAL_APPEND || 0) * 100)}%; height:100%; background:#F59E0B; border-radius:4px;"></div>
                </div>
              </div>
              <div>
                <div style="display:flex; justify-content:space-between; font-size:12.5px; margin-bottom:4px;">
                  <span><strong>Replacement</strong> (Modify/update matching records)</span>
                  <span style="font-family:var(--font-mono); font-weight:700;">${Math.round((scopeData.probabilities.REPLACEMENT || 0) * 100)}%</span>
                </div>
                <div style="height:8px; border-radius:4px; background:rgba(255,255,255,0.06); overflow:hidden;">
                  <div style="width:${Math.round((scopeData.probabilities.REPLACEMENT || 0) * 100)}%; height:100%; background:#EF4444; border-radius:4px;"></div>
                </div>
              </div>
            </div>
            <div style="padding:12px 14px; background:rgba(255,255,255,0.02); border-left:3px solid var(--brand-accent-blue); border-radius:4px; font-size:13px; line-height:1.5; margin-bottom:20px; color:#E2E8F0;">
              <strong style="font-size:10px; text-transform:uppercase; color:var(--brand-accent-blue); display:block; margin-bottom:4px;">AI Reasoning</strong>
              ${escapeHtml(scopeData.reasoning)}
            </div>
            <div style="border-top:1px solid rgba(255,255,255,0.06); padding-top:16px;">
              <h4 style="margin:0 0 12px 0; font-size:14px;">Confirm your reconciliation file scope:</h4>
              <div style="display:grid; grid-template-columns:1fr 1fr 1fr; gap:12px; margin-bottom:20px;">
                <label class="scope-select-card" style="display:flex; flex-direction:column; gap:6px; padding:12px; border:1px solid rgba(255,255,255,0.1); border-radius:8px; background:rgba(255,255,255,0.02); cursor:pointer; text-align:center;">
                  <input type="radio" name="guided-scope-choice" value="FULL_SNAPSHOT" ${currentScope === 'FULL_SNAPSHOT' ? 'checked' : ''} style="margin:0 auto 6px auto;">
                  <strong style="font-size:12.5px; color:#FFF;">Full Snapshot</strong>
                  <span class="muted" style="font-size:11px;">Overwrite/wipe old and retrieve new for the whole day</span>
                </label>
                <label class="scope-select-card" style="display:flex; flex-direction:column; gap:6px; padding:12px; border:1px solid rgba(255,255,255,0.1); border-radius:8px; background:rgba(255,255,255,0.02); cursor:pointer; text-align:center;">
                  <input type="radio" name="guided-scope-choice" value="INCREMENTAL_APPEND" ${currentScope === 'INCREMENTAL_APPEND' ? 'checked' : ''} style="margin:0 auto 6px auto;">
                  <strong style="font-size:12.5px; color:#FFF;">Incremental Append</strong>
                  <span class="muted" style="font-size:11px;">Cumulative/Add additional records</span>
                </label>
                <label class="scope-select-card" style="display:flex; flex-direction:column; gap:6px; padding:12px; border:1px solid rgba(255,255,255,0.1); border-radius:8px; background:rgba(255,255,255,0.02); cursor:pointer; text-align:center;">
                  <input type="radio" name="guided-scope-choice" value="REPLACEMENT" ${currentScope === 'REPLACEMENT' ? 'checked' : ''} style="margin:0 auto 6px auto;">
                  <strong style="font-size:12.5px; color:#FFF;">Replacement</strong>
                  <span class="muted" style="font-size:11px;">Modify/Update records with matching key</span>
                </label>
              </div>
            </div>
          </section>
        `;
      }
    } else if (step === 2) {
      const sigHeaders = selectedPacket.structureSignature?.headers || [];
      const sampleRows = (selectedPacket.samplePreview || []).map(item => Array.isArray(item?.values) ? item.values : []).filter(row => row.length);
      const candidateColumns = collectCandidateColumns(sigHeaders, sampleRows);
      const aiMapping = state.guidedReviewAI.mapping;
      const aiConfidence = aiMapping?.configHealth?.confidence;
      const rawDraftFieldMappings = aiMapping?.fieldMappings || [];
      const idMapping = rawDraftFieldMappings.find(mapping => mapping.path === "id");
      const draftFieldMappings = rawDraftFieldMappings.filter(mapping => {
        if (mapping.path !== "trace") return true;
        if (!idMapping) return true;
        return Number(mapping.column || 0) !== Number(idMapping.column || 0);
      });
      const editableMappingRows = !state.guidedReviewAI.loading && !state.guidedReviewAI.error && aiMapping ? draftFieldMappings.map((mapping, index) => {
          const sourceColumn = Number(mapping.column || 0);
          const headerLabel = sourceColumn > 0 && sigHeaders[sourceColumn - 1] ? sigHeaders[sourceColumn - 1] : (mapping.sourceField || `Column ${sourceColumn || "?"}`);
          const currentMap = mapping.path || "";
          const confidence = typeof aiConfidence === "number" ? Math.round(aiConfidence * 100) : Math.max(70, 95 - (index * 3));
          const populateVia = mapping.type === "CONSTANT"
            ? `Constant${mapping.constant ? `: ${mapping.constant}` : ""}`
            : mapping.type === "MAPPING"
              ? "Rule / value mapping"
              : sourceColumn > 0
                ? `Source column ${sourceColumn}`
                : "Source column";
          
          const mappingStr = mapping.mapping ? escapeHtml(JSON.stringify(mapping.mapping)) : "";
          const originalRequired = mapping.required ? "true" : "false";
          const originalConstant = mapping.constant || "";

          return `
            <tr>
              <td><code style="font-size:11px;">${escapeHtml(headerLabel)}</code></td>
              <td style="color:var(--text-muted);">${escapeHtml(populateVia)}</td>
              <td>
                <select class="inline-field-select" 
                        data-source-column="${sourceColumn}" 
                        data-source-header="${escapeHtml(headerLabel)}" 
                        data-original-path="${escapeHtml(mapping.path || "")}"
                        data-original-type="${escapeHtml(mapping.type || "")}"
                        data-original-required="${originalRequired}"
                        data-original-constant="${escapeHtml(originalConstant)}"
                        data-original-mapping="${mappingStr}"
                        style="width: 100%; background: rgba(0,0,0,0.3); border: 1px solid #444; color: #fff; border-radius: 4px;">
                  <option value="" ${currentMap === "" ? "selected" : ""}>unmapped</option>
                  <option value="id" ${currentMap === "id" ? "selected" : ""}>partner_txn_id</option>
                  <option value="amount" ${currentMap === "amount" ? "selected" : ""}>amount</option>
                  <option value="currency" ${currentMap === "currency" ? "selected" : ""}>currency</option>
                  <option value="status" ${currentMap === "status" ? "selected" : ""}>status</option>
                  <option value="transDate" ${currentMap === "transDate" ? "selected" : ""}>transaction_time</option>
                </select>
              </td>
              <td style="text-align: center;">${confidence}%</td>
            </tr>
          `;
      }).join("") : "";
      const mappedFieldCount = draftFieldMappings.filter(mapping => !!mapping.path).length;
      const selectedSourceColumnCount = new Set(
        draftFieldMappings
          .map(mapping => mapping.column)
          .filter(column => column !== null && column !== undefined && column !== "")
          .map(column => String(column))
      ).size;
      const requiredCanonicalFields = ["id", "amount", "currency", "transDate", "status"];
      const requiredFromSourceCount = requiredCanonicalFields.filter(field =>
        draftFieldMappings.some(mapping => mapping.path === field && mapping.column !== null && mapping.column !== undefined && mapping.column !== "")
      ).length;
      const requiredFromConstantsCount = requiredCanonicalFields.filter(field =>
        draftFieldMappings.some(mapping => mapping.path === field && (mapping.type === "CONSTANT" || (mapping.mapping && mapping.type === "MAPPING" && (mapping.column === null || mapping.column === undefined || mapping.column === ""))))
      ).length;
      const requiredCoveredCount = requiredCanonicalFields.filter(field =>
        draftFieldMappings.some(mapping => mapping.path === field)
      ).length;
      const confidencePct = typeof aiConfidence === "number" ? Math.round(aiConfidence * 100) : null;
      const candidateColumnLabels = candidateColumns.slice(0, 5).map(item => item.header);
      let suggestionHtml = "";
      if (state.guidedReviewAI.loading) {
        suggestionHtml = `
          <div class="empty-state" style="padding: 48px 12px;">
            <span class="spinner" style="display:inline-block; width:36px; height:36px; border:3px solid rgba(255,255,255,0.1); border-top:3px solid var(--brand-accent-blue); border-radius:50%; animation:spin 1s linear infinite;"></span>
            <h3 style="margin-top: 16px;">Generating Draft Mapping</h3>
            <p class="muted">Building partner-to-canonical field suggestions from the current sample rows...</p>
          </div>
        `;
      } else if (state.guidedReviewAI.error) {
        suggestionHtml = `
          <div class="empty-state" style="padding: 48px 12px;">
            <span class="material-symbols-outlined" style="color:var(--status-failed); font-size:48px;">error</span>
            <h3 style="margin-top: 16px;">Draft Mapping Failed</h3>
            <p class="muted">${escapeHtml(state.guidedReviewAI.error)}</p>
          </div>
        `;
      } else {
        suggestionHtml = `
          <div style="display:grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap:16px; margin-bottom:16px;">
            <div class="panel" style="margin:0; padding:16px; text-align:center; background:rgba(255,255,255,0.01); border:1px solid rgba(255,255,255,0.06); border-radius:10px;">
              <div style="font-size:11px; color:var(--text-muted); text-transform:uppercase; font-weight:700; letter-spacing:0.05em;">Partner Columns Available</div>
              <div style="font-size:32px; font-weight:800; color:#FFF; margin-top:8px; font-family:var(--font-mono);">${formatNumber(sigHeaders.length)}</div>
              <div style="font-size:11px; color:var(--text-muted); margin-top:4px;">Columns detected in the incoming partner file</div>
            </div>
            <div class="panel" style="margin:0; padding:16px; text-align:center; background:rgba(255,255,255,0.01); border:1px solid rgba(255,255,255,0.06); border-radius:10px;">
              <div style="font-size:11px; color:var(--text-muted); text-transform:uppercase; font-weight:700; letter-spacing:0.05em;">Candidate Columns For Reconciliation</div>
              <div style="font-size:32px; font-weight:800; color:#FFF; margin-top:8px; font-family:var(--font-mono);">${formatNumber(selectedSourceColumnCount)}</div>
              <div style="font-size:11px; color:var(--text-muted); margin-top:4px;">Columns currently selected from the partner file</div>
            </div>
            <div class="panel" style="margin:0; padding:16px; text-align:center; background:rgba(255,255,255,0.01); border:1px solid rgba(255,255,255,0.06); border-radius:10px;">
              <div style="font-size:11px; color:var(--text-muted); text-transform:uppercase; font-weight:700; letter-spacing:0.05em;">Required Fields Covered</div>
              <div style="font-size:32px; font-weight:800; color:#FFF; margin-top:8px; font-family:var(--font-mono);">${requiredCoveredCount}/${requiredCanonicalFields.length}</div>
              <div style="font-size:11px; color:var(--text-muted); margin-top:4px;">${requiredFromSourceCount} from source columns, ${requiredFromConstantsCount} from constants/rules</div>
            </div>
          </div>
          <section class="panel" style="margin:0; padding:20px; border-radius:10px;">
            <h4 style="margin:0 0 16px 0; font-size:15px; border-bottom:1px solid rgba(255,255,255,0.06); padding-bottom:8px; color:var(--brand-accent-blue);">AI Suggestion / Draft Mapping</h4>
            <p class="muted" style="margin:0 0 12px 0;">Use the AI draft if it is good enough, or open Mapping Studio for a full edit.</p>
            <div style="margin:0 0 16px 0; padding:12px 14px; background:rgba(255,255,255,0.02); border-left:3px solid var(--brand-accent-blue); border-radius:4px; font-size:13px; line-height:1.5; color:#E2E8F0;">
              <strong style="font-size:10px; text-transform:uppercase; color:var(--brand-accent-blue); display:block; margin-bottom:4px;">Mapping Scope</strong>
              ${escapeHtml(`${sigHeaders.length} partner columns were detected, but only ${selectedSourceColumnCount} candidate columns are currently selected to populate ${mappedFieldCount} canonical mapping fields. Runtime processing only depends on relevant source columns, constants, and rules.`)}
              ${candidateColumnLabels.length ? `<div style="margin-top:8px; color:var(--text-muted);">Top candidate columns: ${escapeHtml(candidateColumnLabels.join(", "))}</div>` : ""}
              ${confidencePct !== null ? `<div style="margin-top:8px; color:var(--text-muted);">AI confidence: ${escapeHtml(String(confidencePct))}%</div>` : ""}
            </div>
            <div class="table-wrap"><table style="width:100%; border-collapse:collapse; font-size: 12px;">
              <thead><tr style="background:rgba(255,255,255,0.05)"><th>Partner Column</th><th>Populate Via</th><th>Canonical Field</th><th>AI Conf</th></tr></thead>
              <tbody>${editableMappingRows}</tbody>
            </table></div>
          </section>
        `;
      }
      stepBodyHtml = `
        <div class="guided-step-content" style="display:flex; flex-direction:column; gap:14px;">
          <div>
            <h4 style="margin:0;">Draft Mapping Review</h4>
            <p class="muted" style="margin:6px 0 0 0;">Review the AI proposal and adjust the partner field mapping before runtime validation.</p>
          </div>
          ${suggestionHtml}
          <div class="guided-action-bar" style="margin-top: 16px; display: flex; justify-content: space-between; align-items: center;">
            <button class="button-link" data-action="go-mapping-studio"><span class="material-symbols-outlined">open_in_new</span>Open full Mapping Studio</button>
            <button class="button primary" data-action="save-inline-mapping" data-packet-id="${escapeHtml(selectedPacket._id)}" ${state.guidedReviewAI.loading || state.guidedReviewAI.error ? "disabled" : ""}><span class="material-symbols-outlined">save</span> Save draft mapping</button>
          </div>
        </div>
      `;
    } else if (step === 3) {
      const validationState = getRuntimeValidationState(selectedPacket);
      const runtimeGate = validationState.runtimeGate;
      const details = runtimeGate?.details || {};
      const issues = collectValidationIssues(runtimeGate);
      const summaryTone = validationState.summaryLabel === "Failed" ? "critical" : validationState.summaryLabel === "Passed with warnings" ? "warning" : "matched";
      let bannerTone = "warning";
      let bannerTitle = "Runtime validation has not been run for the latest draft mapping.";
      let bannerText = "Run runtime validation before moving to the decision step.";
      if (validationState.isStale) {
        bannerTitle = "Runtime validation is stale for the current draft mapping.";
        bannerText = "The draft mapping changed after the last validation. Re-run runtime validation before continuing.";
      } else if (validationState.summaryLabel === "Passed with warnings") {
        bannerTone = "warning";
        bannerTitle = "Runtime validation passed with warnings.";
        bannerText = runtimeGate?.reason || "Some sampled rows still failed validation.";
      } else if (validationState.summaryLabel === "Failed") {
        bannerTone = "critical";
        bannerTitle = "Runtime validation failed.";
        bannerText = runtimeGate?.reason || "The current mapping did not validate successfully.";
      } else if (validationState.summaryLabel === "Passed") {
        bannerTone = "matched";
        bannerTitle = "Runtime validation is current for this draft mapping.";
        bannerText = runtimeGate?.reason || "All sampled rows validated successfully.";
      }
      const summaryCard = `
        <section class="panel" style="margin:0; padding:16px; border-radius:10px;">
          <div style="display:grid; grid-template-columns:repeat(4, minmax(0, 1fr)); gap:12px;">
            <div><div style="font-size:11px; color:var(--text-muted); text-transform:uppercase; font-weight:700;">Sampled Rows</div><div style="font-size:22px; font-weight:800;">${escapeHtml(String(details.sampledRows || 0))}</div></div>
            <div><div style="font-size:11px; color:var(--text-muted); text-transform:uppercase; font-weight:700;">Success Rows</div><div style="font-size:22px; font-weight:800;">${escapeHtml(String(details.successRows || 0))}</div></div>
            <div><div style="font-size:11px; color:var(--text-muted); text-transform:uppercase; font-weight:700;">Failed Rows</div><div style="font-size:22px; font-weight:800;">${escapeHtml(String(details.failedRows || 0))}</div></div>
            <div><div style="font-size:11px; color:var(--text-muted); text-transform:uppercase; font-weight:700;">Success Rate</div><div style="font-size:22px; font-weight:800;">${escapeHtml(`${details.successRows || 0}/${details.sampledRows || 0} (${Math.round((Number(details.successRate || 0)) * 100)}%)`)}</div></div>
          </div>
          <div style="display:flex; gap:10px; flex-wrap:wrap; margin-top:14px;">
            <span class="badge ${summaryTone}">${escapeHtml(validationState.summaryLabel)}</span>
            <span class="badge neutral">Gate ${escapeHtml(String(runtimeGate?.status || "pending").toUpperCase())}</span>
            <span class="badge ${String(details.riskLevel || "").toUpperCase() === "HIGH" ? "failed" : String(details.riskLevel || "").toUpperCase() === "MEDIUM" ? "warning" : "matched"}">Risk ${escapeHtml(String(details.riskLevel || "-"))}</span>
            <span class="badge neutral">${escapeHtml(formatDisplayDateTime(details.validatedAt || "-"))}</span>
          </div>
          <div style="margin-top:12px; font-size:12px; color:var(--text-muted);"><strong>Reason:</strong> ${escapeHtml(runtimeGate?.reason || "Run runtime validation on the latest draft mapping.")}</div>
        </section>
      `;
      const issuesHtml = issues.length ? `
        <section class="panel" style="margin:0; padding:16px; border-radius:10px;">
          <div style="font-size:12px; font-weight:700; text-transform:uppercase; color:var(--text-muted); margin-bottom:10px;">Validation Issues List</div>
          <div style="display:flex; flex-direction:column; gap:10px;">
            ${issues.map(issue => `
              <div style="padding:12px; border:1px solid rgba(255,255,255,0.08); border-radius:8px; background:rgba(255,255,255,0.02);">
                <div style="display:flex; gap:10px; flex-wrap:wrap; align-items:center;">
                  <strong>${escapeHtml(issue.code)}</strong>
                  <span class="badge warning">${escapeHtml(issue.field || "field")}</span>
                  <span class="muted" style="font-size:12px;">Row ${escapeHtml(String(issue.row || "-"))}</span>
                </div>
                <div style="margin-top:6px; font-size:12px;">${escapeHtml(issue.message)}</div>
                <div style="margin-top:6px; font-size:12px; color:var(--text-muted);">${escapeHtml(issue.suggestion)}</div>
              </div>
            `).join("")}
          </div>
        </section>
      ` : `
        <section class="panel" style="margin:0; padding:16px; border-radius:10px;">
          <div style="font-size:12px; font-weight:700; text-transform:uppercase; color:var(--text-muted); margin-bottom:6px;">Validation Issues List</div>
          <div class="muted" style="font-size:12px;">No deterministic validation issues were produced for the sampled rows.</div>
        </section>
      `;
      stepBodyHtml = `
        <div class="guided-step-content" style="display:flex; flex-direction:column; gap:14px;">
          <div style="display:flex; justify-content:space-between; gap:12px; align-items:flex-start; flex-wrap:wrap;">
            <div>
              <h4 style="margin:0;">Runtime Validation</h4>
              <p class="muted" style="margin:6px 0 0 0;">Inspect the latest runtime gate for the current draft mapping before approving.</p>
            </div>
            <button class="button primary" data-action="validate-runtime-packet" data-packet-id="${escapeHtml(selectedPacket._id)}">${validationState.hasValidation ? "Re-run runtime validation" : "Run runtime validation"}</button>
          </div>
          ${renderRuntimeVisualSummary(runtimeGate, validationState)}
          ${renderPartnerSampleRecord(selectedPacket, runtimeGate)}
          ${summaryCard}
          <section class="panel" style="margin:0; padding:16px; border-radius:10px; border:1px solid rgba(255,255,255,0.08); background:${bannerTone === "critical" ? "rgba(239,68,68,0.05)" : bannerTone === "warning" ? "rgba(245,158,11,0.06)" : "rgba(16,185,129,0.05)"};">
            <div style="display:flex; gap:10px; align-items:flex-start;">
              <span class="material-symbols-outlined" style="color:${bannerTone === "critical" ? "#ef4444" : bannerTone === "warning" ? "#f59e0b" : "#10B981"};">${bannerTone === "critical" ? "error" : bannerTone === "warning" ? "warning" : "check_circle"}</span>
              <div>
                <strong>${escapeHtml(bannerTitle)}</strong>
                <div style="font-size:12px; color:var(--text-muted); margin-top:4px;">${escapeHtml(bannerText)}</div>
              </div>
            </div>
          </section>
          ${issuesHtml}
          <section class="panel" style="margin:0; padding:16px; border-radius:10px;">
            <div style="font-size:12px; font-weight:700; text-transform:uppercase; color:var(--text-muted); margin-bottom:10px;">Runtime Mapping Preview</div>
            ${renderRuntimeTraceSamples(runtimeGate)}
          </section>
        </div>
      `;
    } else if (step === 4) {
      const validationState = getRuntimeValidationState(selectedPacket);
      const runtimeGate = validationState.runtimeGate;
      const isMappingReady = !!selectedPacket.draftMappingId;
      const isReady = isMappingReady && validationState.canProceed;
      const recommendation = isReady
        ? "The latest draft mapping is ready for approval and activation."
        : validationState.isStale
          ? "Validation is stale. Return to Step 3 and re-run runtime validation on the current draft mapping."
          : validationState.summaryLabel === "Failed"
            ? "Validation failed. Return to Step 3 and resolve the runtime mapping issues before approval."
            : "A current runtime validation is required before approval.";
      stepBodyHtml = `
        <div class="guided-step-content" style="display:flex; flex-direction:column; gap:14px;">
          <h4 style="margin:0;">Decision</h4>
          <section class="panel" style="margin:0; padding:16px; border-radius:10px;">
            <div style="display:flex; gap:10px; flex-wrap:wrap;">
              <span class="badge ${isMappingReady ? "matched" : "warning"}">Mapping ${isMappingReady ? "ready" : "missing"}</span>
              <span class="badge ${validationState.canProceed ? "matched" : validationState.isStale ? "warning" : "failed"}">Runtime validation ${escapeHtml(validationState.summaryLabel)}</span>
            </div>
            <div style="margin-top:12px; font-size:12px; color:var(--text-muted);"><strong>Gate summary:</strong> ${escapeHtml(runtimeGate?.reason || "Runtime validation has not been completed for the latest draft mapping.")}</div>
            <div style="margin-top:10px; font-size:13px;">${escapeHtml(recommendation)}</div>
          </section>
          ${(!validationState.canProceed || !isMappingReady) ? `<button class="button secondary-action" data-action="back-to-guided-step-3">Return to Step 3</button>` : ""}
          <div style="display:flex; flex-direction:column; gap:10px;">
            <button class="button primary ${isReady ? "success-cta" : ""}" data-action="approve-packet-activate" data-packet-id="${escapeHtml(selectedPacket._id)}" ${isReady ? "" : "disabled"}>Approve & Activate</button>
            <button class="button secondary-action" data-action="reject-packet" data-packet-id="${escapeHtml(selectedPacket._id)}">Reject change</button>
          </div>
        </div>
      `;
    }

    const step3State = step === 3 ? getRuntimeValidationState(selectedPacket) : null;
    const disableNext = step === 3 && !step3State?.canProceed;
    const footerHtml = `
      <div class="guided-review-footer" style="display:flex; justify-content:space-between; margin-top:20px; border-top: 1px solid rgba(255,255,255,0.08); padding-top: 16px;">
        <button class="button" data-action="guided-prev" ${step === 1 ? 'disabled' : ''}>Back</button>
        ${step < 4 ? `<button class="button primary" data-action="guided-next" data-packet-id="${escapeHtml(selectedPacket._id)}" ${disableNext ? "disabled" : ""}>Next</button>` : ""}
      </div>
    `;

    return `
      <div class="guided-review-backdrop" id="guided-review-backdrop">
        <div class="guided-review-modal" style="max-width: 800px; width: 100%; background: #111; padding: 24px; border-radius: 12px;">
          <div class="guided-review-header" style="display:flex; justify-content:space-between; margin-bottom:20px;">
            <div><h3 style="margin:0;">Guided Review</h3></div>
            <button class="button-link" data-action="close-guided-review"><span class="material-symbols-outlined">close</span></button>
          </div>
          <div class="guided-review-body">
            <div style="display:flex; margin-bottom:24px;">${progressSteps}</div>
            ${stepBodyHtml}
            ${footerHtml}
          </div>
        </div>
      </div>
    `;
  }

  function renderApprovals(data) {
    function middleTruncate(str, maxLen = 30) {
      if (!str) return "";
      if (str.length <= maxLen) return str;
      const half = Math.floor((maxLen - 3) / 2);
      return str.substring(0, half) + "..." + str.substring(str.length - half);
    }

    if (!state.reviewTab) {
      state.reviewTab = "pending";
    }

    const packets = (data.packets || []).filter(packet => !state.partner || packet.partner === state.partner);
    const mappings = (data.mappings || []).filter(item => item.partner === state.partner);
    const allPending = getReviewCenterPendingItems(data);
    const selectedPacket = getSelectedReviewPacket(allPending);

    // Intake info
    const intake = data.intake || {};
    const partners = intake.partners || [];
    const activePartnerInfo = partners.find(p => p.partner === state.partner) || {};

    // Header info computation
    const pendingCount = allPending.length;
    const latestFile = activePartnerInfo.latestFileSummary?.fileName || activePartnerInfo.latestFileSummary?.file_name || "-";
    const highestRisk = selectedPacket ? (selectedPacket.riskSummary?.severity || "medium") : "none";
    const riskLabel = highestRisk === "none" ? "No risk" : `${highestRisk.charAt(0).toUpperCase() + highestRisk.slice(1)} risk`;

    // 1. Compact Page Header
    const headerHtml = `
      <div class="compact-page-header">
        <div class="compact-header-info">
          <h2>Review Center</h2>
          <div class="compact-header-meta">
            <strong>${escapeHtml(state.partner)}</strong> · 
            <span>${pendingCount} pending review${pendingCount !== 1 ? 's' : ''}</span> · 
            <span class="badge ${highestRisk === 'critical' || highestRisk === 'high' ? 'failed' : 'warning'}" style="padding: 2px 6px; font-size: 11px;">${riskLabel.toUpperCase()}</span> · 
            <span>Latest file: <span title="${escapeHtml(latestFile)}">${escapeHtml(middleTruncate(latestFile, 30))}</span></span>
          </div>
        </div>
      </div>
    `;

    // Tabs navigation HTML
    const tabsNavHtml = `
      <div class="insights-tabs" style="margin-bottom: 20px;">
        <button class="insight-tab ${state.reviewTab === 'pending' ? 'active' : ''}" data-action="set-review-tab" data-tab="pending">Pending Reviews</button>
        <button class="insight-tab ${state.reviewTab === 'history' ? 'active' : ''}" data-action="set-review-tab" data-tab="history">Decision History</button>
        <button class="insight-tab ${state.reviewTab === 'configs' ? 'active' : ''}" data-action="set-review-tab" data-tab="configs">Runtime Configs</button>
      </div>
    `;

    // Build tabs content
    let tabContentHtml = "";
    if (state.reviewTab === "pending") {
      // Left Column: Pending reviews cards
      const needsReview = allPending.length ? allPending.map(packet => {
        const risk = packet.riskSummary?.severity || "medium";
        const title = packet.isVirtual ? "Draft mapping update" : "Format verification required";
        const shortReason = packet.recommendedAction?.reason || "Awaiting reviewer decision.";
        const dateStr = formatDisplayDateTime(packet.createdAt);
        const activeClass = selectedPacket && selectedPacket._id === packet._id ? "active" : "";

        return `
          <article class="review-card ${activeClass}" data-action="select-review-packet" data-packet-id="${escapeHtml(packet._id)}">
            <div class="review-card-top">
              <h4 class="review-card-title">${escapeHtml(title)}</h4>
              <span class="badge ${risk === 'critical' || risk === 'high' ? 'failed' : 'warning'}">${escapeHtml(risk.toUpperCase())} RISK</span>
            </div>
            <div class="review-card-meta">
              <strong>${escapeHtml(packet.partner)}</strong> · <span class="review-status-label">Pending</span> · <span class="review-time">${escapeHtml(dateStr)}</span>
            </div>
            <p class="review-card-reason">${escapeHtml(shortReason)}</p>
            <div style="font-size: 12px; color: var(--text-muted); margin-top: 8px; font-family: monospace;">
              File: ${escapeHtml(middleTruncate(packet.fileName || '-', 35))}
            </div>
          </article>
        `;
      }).join("") : `
        <div class="empty-state">
          <span class="material-symbols-outlined">task_alt</span>
          <h3>No reviews pending</h3>
          <p class="muted">Review queue is clear for ${escapeHtml(state.partner)}.</p>
        </div>
      `;

      // Right Column: Agent Brief Summary card
      tabContentHtml = `
        <div class="approval-desk-layout">
          <div class="review-card-grid">
            ${needsReview}
          </div>
          ${renderReviewCenterSummary(selectedPacket)}
        </div>
      `;
    } else if (state.reviewTab === "history") {
      tabContentHtml = renderReviewHistoryTab();
    } else if (state.reviewTab === "configs") {
      tabContentHtml = renderReviewConfigsTab(mappings);
    }

    return `
      ${headerHtml}
      ${tabsNavHtml}
      ${tabContentHtml}
      ${renderGuidedReviewModal(selectedPacket)}
    `;
  }

  function renderSubmitSamplePage() {
    return `
      <section class="panel studio-shell" style="margin-bottom: 24px;">
        <div class="panel-header" style="margin-bottom: 16px;">
          <div>
            <p class="eyebrow">Draft Workflow</p>
            <h2 style="margin: 0;">Mapping Studio</h2>
            <p class="section-subtitle">Select sample, review the draft mapping, validate output, then submit for review. Activation never happens here.</p>
          </div>
        </div>
        ${renderSettings(true)}
      </section>
    `;
  }

  function renderApprovalUploadEntry(copy) {
    return `
      <div class="panel handoff-panel" style="margin-top: 16px;">
        <div class="handoff-panel-header">
          <div>
            <h3 style="margin:0 0 8px 0;">Direct Intake Review</h3>
            <p class="muted" style="margin:0;">${escapeHtml(copy)}</p>
          </div>
          <div class="handoff-badges">
            <span class="badge neutral">${escapeHtml(state.partner)}</span>
            <span class="badge neutral">${escapeHtml(formatDisplayDate(state.date))}</span>
          </div>
        </div>
        <div class="handoff-actions">
          <input type="file" class="review-upload-input" accept=".xlsx,.xls,.csv" style="display:none;">
          <button class="button primary" data-action="open-review-upload">
            <span class="material-symbols-outlined" style="font-size:18px;">upload</span> Upload File For Review
          </button>
          <button class="button secondary-action" data-action="go-mapping-studio">Open Mapping Studio</button>
        </div>
      </div>
    `;
  }

  function renderAutomation(data) {
    const jobs = data.jobs || [];
    const recentPackets = jobs.flatMap(job => (job.recentPackets || []).map(packet => ({
      ...packet,
      partner: job.partner,
      fetchMethod: job.fetchMethod,
    }))).sort((a, b) => String(b.createdAt || "").localeCompare(String(a.createdAt || ""))).slice(0, 8);
    const rows = jobs.length ? jobs.map(job => `
      <tr>
        <td><strong>${escapeHtml(job.partner || "-")}</strong></td>
        <td>${escapeHtml(job.fetchMethod || "-")}</td>
        <td><code>${escapeHtml(job.schedule || "-")}</code></td>
        <td>${escapeHtml(job.destination || "-")}</td>
        <td>${job.enabled ? `<span class="badge matched">Enabled</span>` : `<span class="badge critical">Disabled</span>`}</td>
        <td>
          <div style="display:flex; gap:8px; align-items:center; flex-wrap:wrap;">
            <span class="badge neutral">${formatNumber(job.pendingReviewPackets || 0)} pending packets</span>
            <button class="button secondary-action" data-action="run-job-now" data-partner="${escapeHtml(job.partner || "")}">Run Now</button>
          </div>
        </td>
      </tr>
    `).join("") : `<tr><td colspan="6" style="text-align:center; padding: 24px 0;">No enabled automation jobs found.</td></tr>`;
    return `
      ${metrics([
        ["Enabled Jobs", formatNumber(jobs.filter(job => job.enabled).length), "Scheduler-connected fetch configs"],
        ["Pending Review Items", formatNumber(jobs.reduce((sum, job) => sum + Number(job.pendingReviewPackets || 0), 0)), "Review items waiting after automation runs"],
        ["Partners Covered", formatNumber(jobs.length), "Configured partner fetch routes"],
        ["Mode", "Recommend Only", "Automation recommends but does not auto-approve"]
      ])}
      <section class="panel" style="margin-bottom: 24px;">
        <div class="panel-header with-icon">
          <div>
            <h2 class="section-title">Scheduler Jobs</h2>
            <p class="section-subtitle">Visibility into configured fetch routes and how many review items they are creating.</p>
          </div>
          <span class="material-symbols-outlined panel-header-icon">schedule</span>
        </div>
        ${table(["Partner", "Method", "Schedule", "Destination", "Status", "Review Output"], rows)}
      </section>
      <section class="panel">
        <div class="panel-header with-icon">
          <div>
            <h2 class="section-title">Recent Automation Review Output</h2>
            <p class="section-subtitle">Latest packets generated by automation-backed file fetches and format-drift checks.</p>
          </div>
          <span class="material-symbols-outlined panel-header-icon">smart_toy</span>
        </div>
        <div class="review-card-grid">
          ${(recentPackets.length ? recentPackets : [{
            partner: "Automation",
            fileName: "No recent packets",
            recommendedAction: { reason: "No job-created review packets are available yet." },
            riskSummary: { severity: "low" },
            _id: "",
            status: "CLEAR",
            fetchMethod: "-"
          }]).map(packet => `
            <article class="review-card ${packet._id ? "" : "empty-card"}">
              <div class="review-card-top">
                <div>
                  <p class="eyebrow">${escapeHtml(packet.fetchMethod || packet.sourceType || "-")}</p>
                  <h3>${escapeHtml(packet.partner || "-")}</h3>
                </div>
                ${severityBadge(packet.riskSummary?.severity || "medium")}
              </div>
              <p class="review-reason">${escapeHtml(packet.fileName || "-")}</p>
              <div class="review-meta-row">
                ${badge(packet.status || "-")}
                ${packet.sourceType ? `<span class="badge neutral">${escapeHtml(packet.sourceType)}</span>` : ""}
                ${packet.decisionMode ? `<span class="badge neutral">${escapeHtml(packet.decisionMode)}</span>` : ""}
              </div>
              <div class="review-impact-box">
                <strong>Agent recommendation</strong>
                <p>${escapeHtml(packet.recommendedAction?.reason || packet.riskSummary?.summary || "-")}</p>
              </div>
              ${packet.reviewedAt ? `<div class="muted" style="font-size:12px;">Reviewed by ${escapeHtml(packet.reviewedBy || "Administrator")} on ${escapeHtml(formatDisplayDateTime(packet.reviewedAt))}</div>` : ""}
              ${packet._id ? `<button class="button" data-action="go-review-packet" data-packet-id="${escapeHtml(packet._id)}" data-partner="${escapeHtml(packet.partner)}" style="margin-top: 8px;">Open Approval Desk</button>` : ""}
            </article>
          `).join("")}
        </div>
      </section>
    `;
  }

  function renderCommandCenter() {
    const insights = state.insightsData ? state.insightsData.summary : null;
    if (!insights) return '<div class="empty-state">No dashboard data loaded.</div>';

    const m = insights.summary_metrics || {};
    const byStatus = m.by_status || {};
    const total = m.total_transactions || 0;
    const matched = m.matched || 0;
    const issueCount = Math.max(0, total - matched);
    const mismatchRate = m.mismatch_rate || 0;
    const mismatchAmount = m.total_amount_mismatch ? formatAmount(m.total_amount_mismatch) : "-";
    const matchedPct = total ? Math.round((matched / total) * 100) : 0;
    const obs = insights.ai_observation;

    const anomalyCount = (byStatus.AMOUNT_MISMATCH || 0) + (byStatus.STATUS_MISMATCH || 0) + (byStatus.MULTIPLE_MISMATCH || 0) + (byStatus.MISSING_INTERNAL || 0) + (byStatus.UNMAPPED_SKIPPED || 0);

    const data = state.insightsData;
    const focusData = {
      operational: data.operational || [],
      partner: data.partner || [],
      inconsistency: data.inconsistency || []
    };

    const activeFocus = state.focus;
    const items = focusData[activeFocus] || [];
    
    // Sort anomalies: critical > high > medium > low
    const severityWeight = { "critical": 4, "high": 3, "medium": 2, "low": 1 };
    const processedItems = items.map(item => {
      const copy = { ...item };
      if (!copy.severity) {
        copy.severity = (copy.affected_count > 100) ? "critical" : (copy.affected_count > 10) ? "medium" : "low";
      }
      return copy;
    });

    processedItems.sort((a, b) => {
      const wA = severityWeight[String(a.severity).toLowerCase()] || 0;
      const wB = severityWeight[String(b.severity).toLowerCase()] || 0;
      return wB - wA;
    });

    const cards = processedItems.length
      ? processedItems.slice(0, 3).map(item => insightCard(item)).join("")
      : `<div class="empty-state" style="grid-column: span 3; text-align: center; padding: 40px 0;">No active anomalies found for this focus dimension.</div>`;

    const actionQueueRows = processedItems.length
      ? processedItems.slice(0, 5).map(item => `
        <div class="action-queue-row">
          <div class="action-queue-main">
            <div class="action-queue-title-row">
              <strong>${boldNumbers(escapeHtml(item.title || "Untitled issue"))}</strong>
              ${severityBadge(item.severity || "medium")}
            </div>
            <p class="muted">${boldNumbers(escapeHtml(item.recommendation || item.description || "No recommendation available."))}</p>
          </div>
          <div class="action-queue-meta">
            <span class="badge neutral"><strong>${formatNumber(item.affected_count || 0)}</strong> records</span>
          </div>
        </div>
      `).join("")
      : `
        <div class="empty-state actionable">
          <span class="material-symbols-outlined">task_alt</span>
          <h3>No open action items</h3>
          <p class="muted">The current reconciliation run does not require operator intervention.</p>
        </div>
      `;

    const tabs = [
      { id: "operational", label: "Ingestion & Operations", icon: "dns", count: focusData.operational.length },
      { id: "partner", label: "Partner Trends", icon: "handshake", count: focusData.partner.length },
      { id: "inconsistency", label: "Data Inconsistencies", icon: "rule", count: focusData.inconsistency.length }
    ].map(tab => {
      const active = tab.id === activeFocus ? "active" : "";
      const badgeClass = tab.count > 0 ? "badge-has-anomalies" : "badge-clean";
      return `
        <button class="segmented-tab ${active}" data-focus="${tab.id}">
          <span class="material-symbols-outlined tab-icon">${tab.icon}</span>
          <span class="tab-label">${tab.label}</span>
          <span class="tab-badge ${badgeClass}">${tab.count}</span>
        </button>
      `;
    }).join("");

    return `
      ${metrics([
        ["Data Intake Today", formatNumber(total), `${state.partner} records observed today`],
        ["Needs Review", formatNumber(issueCount), `${matchedPct}% matched on current run`],
        ["Priority Actions", formatNumber(anomalyCount), anomalyCount ? "Start with Review Center and mismatches" : "No immediate blockers detected"],
        ["Financial Impact", mismatchAmount, "Amount exposed by visible mismatches"]
      ])}

      ${renderPageFilters({ showDate: true, showClear: false })}

      <div class="grid cols-2 command-center-grid">
        <section class="panel">
          <div class="panel-header with-icon">
            <div>
              <h2 class="section-title">Risk Insight</h2>
              <p class="section-subtitle">Switch the lens first, then interact with the resulting risk set.</p>
            </div>
            <span class="material-symbols-outlined panel-header-icon">troubleshoot</span>
          </div>
          <div class="segmented-tabs-container">
            ${tabs}
          </div>
          <div class="command-center-copy">
            <p class="muted">Severity stays above metadata. Use this to decide whether the next stop is Review Center, Data Intake, or Reconciliation.</p>
          </div>
        </section>

        <section class="panel">
          <div class="panel-header with-icon">
            <div>
              <h2 class="section-title">Partner Risk Snapshot</h2>
              <p class="section-subtitle">Scan partner-specific patterns and operational signals for the active lens.</p>
            </div>
            <span class="material-symbols-outlined panel-header-icon">partner_exchange</span>
          </div>
          <div class="grid cols-1">
            ${cards}
          </div>
        </section>
      </div>

      <section class="panel">
        <div class="panel-header with-icon">
          <div>
            <h2 class="section-title">Priority Action Queue</h2>
            <p class="section-subtitle">This screen only answers whether the system is healthy, which partner is at risk, and what to do next.</p>
          </div>
          <span class="material-symbols-outlined panel-header-icon">assignment_late</span>
        </div>
        <div class="action-queue">${actionQueueRows}</div>
      </section>

      <div class="grid cols-2">
        <section class="panel">
          <div class="panel-header with-icon">
            <div>
              <h2 class="section-title">Reconciliation Quality</h2>
              <p class="section-subtitle">Deterministic metrics stay primary; AI observations stay secondary.</p>
            </div>
            <span class="material-symbols-outlined panel-header-icon">monitoring</span>
          </div>
          ${bars([
            ["Matched Transactions", matchedPct, "green"],
            ["Total Mismatch Rate", Math.min(mismatchRate, 100), mismatchRate > 5 ? "red" : "amber"],
            ["Missing Internal Records", percent(byStatus.MISSING_INTERNAL || 0, total), "amber"],
            ["Missing Partner Records", percent(byStatus.MISSING_PARTNER || 0, total), "red"]
          ])}
        </section>

        <section class="panel chart-panel">
          <div class="panel-header with-icon">
            <div>
              <h2 class="section-title">Success Rate Distribution</h2>
              <p class="section-subtitle">Overall match quality for the current reconciliation window.</p>
            </div>
            <span class="material-symbols-outlined panel-header-icon">pie_chart</span>
          </div>
          ${donut(Math.max(0, 100 - mismatchRate), "Total Match Quality")}
        </section>
      </div>

      ${obs ? renderAiObservation(obs) : ''}
    `;
  }

  function renderScheduler() {
    return `
      <div class="grid cols-3" style="margin-bottom: 24px;">
        <div class="metric">
          <span>Daemon Status</span>
          <strong style="color: var(--green-primary);">ACTIVE</strong>
          <small>Reconciliation Daemon</small>
        </div>
        <div class="metric">
          <span>Job Trigger</span>
          <strong>daily_partner_fetch</strong>
          <small>Runs every day at midnight</small>
        </div>
        <div class="metric">
          <span>Target Schedule</span>
          <strong>0 0 * * * (Daily)</strong>
          <small>APScheduler Cron Trigger</small>
        </div>
      </div>

      <section class="panel" style="margin-bottom: 24px;">
        <h2>Active Fetch Schedulers</h2>
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Partner</th>
                <th>Method</th>
                <th>Schedule</th>
                <th>Destination</th>
                <th>Status</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td><strong>MOMO</strong></td>
                <td><code>SFTP</code></td>
                <td>Daily (00:00)</td>
                <td><code>./downloads/MOMO</code></td>
                <td><span class="badge matched">Enabled</span></td>
                <td><button class="button" data-action="run-job" data-partner="MOMO">Run Now</button></td>
              </tr>
              <tr>
                <td><strong>ZALOPAY</strong></td>
                <td><code>API</code></td>
                <td>Daily (00:05)</td>
                <td><code>./downloads/ZALOPAY</code></td>
                <td><span class="badge matched">Enabled</span></td>
                <td><button class="button" data-action="run-job" data-partner="ZALOPAY">Run Now</button></td>
              </tr>
              <tr>
                <td><strong>VIETTELPAY</strong></td>
                <td><code>FileDrop</code></td>
                <td>Watcher Active</td>
                <td><code>/drops/viettelpay</code></td>
                <td><span class="badge missing-internal">Paused</span></td>
                <td><button class="button" data-action="run-job" data-partner="VIETTELPAY">Run Now</button></td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section class="panel">
        <h2>Live Daemon Logs</h2>
        <div class="terminal">
00:00 scheduler started
00:00 fetch window opened for daily_partner_fetch
00:00 MOMO file received and validated
00:00 ingestion completed: 15,200 rows
00:05 ZALOPAY API fetch completed
00:05 no approval blockers detected
        </div>
      </section>
    `;
  }

  function renderReconciliation(data) {
    const items = data.results || [];
    
    // 1. Compact toolbar inputs & status mapping
    const totalAmountDiff = items.reduce((sum, item) => {
      const partnerAmount = Number(item.partnerAmount || 0);
      const internalAmount = Number(item.internalAmount || 0);
      return sum + Math.abs(partnerAmount - internalAmount);
    }, 0);
    const matchedCount = items.filter(item => item.reconciliationStatus === "MATCHED").length;
    const mismatchRows = items.filter(item => String(item.reconciliationStatus || "") !== "MATCHED" && !/MISSING_/.test(String(item.reconciliationStatus || ""))).length;
    const missingRows = items.filter(item => /MISSING_/.test(String(item.reconciliationStatus || ""))).length;
    const totalRows = data.total || items.length;

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
    const reviewStatus = (unreviewedMismatchRows > 0 || unreviewedMissingRows > 0) ? "NEEDS_REVIEW" : "PASSED";
    const riskLevel = (unreviewedMismatchRows > 0 || unreviewedMissingRows > 0) ? "HIGH" : "LOW";
    const summary = state.insightsSummary || {};
    
    // Fallback confidence clarification
    const aiSource = summary.llm_status || "Rule-based";
    const isLLM = aiSource === "LLM";
    const confidenceLabel = isLLM ? "AI Confidence" : "Rule Confidence";
    const aiConfidence = (mismatchRows > 0 || missingRows > 0) ? "82%" : "98%";
    const cacheStatus = summary.ai_observation?.cache_hit ? "HIT" : "MISS";

    // 1. Improved Context Toolbar
    const toolbarHtml = renderPageFilters({ showDate: true, showClear: false, showReconActions: true });

    // 2. Semantic Risk Summary Strip (Left-border semantic highlights)
    const riskBadgeClass = riskLevel === "HIGH" ? "failed" : "matched";

    const summaryStripHtml = `
      <div class="summary-strip" style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 20px;">
        <div class="metric" style="padding: 20px; border-radius: 4px; display: flex; flex-direction: column; justify-content: space-between; min-height: 100px; border: 1px solid var(--border-color); background: var(--bg-card);">
          <span style="font-size: 11px; text-transform: uppercase; color: var(--text-muted); font-weight: 700; letter-spacing: 0.05em;">Review Status</span>
          <strong style="font-size: 24px; font-weight: 800; margin-top: 8px; color: ${reviewStatus === 'NEEDS_REVIEW' ? '#f59e0b' : '#10b981'}">${reviewStatus === 'NEEDS_REVIEW' ? 'Needs Review' : 'Passed'}</strong>
        </div>
        <div class="metric" style="padding: 20px; border-radius: 4px; display: flex; flex-direction: column; justify-content: space-between; min-height: 100px; border: 1px solid var(--border-color); background: var(--bg-card);">
          <span style="font-size: 11px; text-transform: uppercase; color: var(--text-muted); font-weight: 700; letter-spacing: 0.05em;">Total Records</span>
          <strong style="font-size: 24px; font-weight: 800; margin-top: 8px;">${totalRows}</strong>
        </div>
        <div class="metric" style="padding: 20px; border-radius: 4px; display: flex; flex-direction: column; justify-content: space-between; min-height: 100px; border: 1px solid var(--border-color); background: var(--bg-card);">
          <span style="font-size: 11px; text-transform: uppercase; color: var(--text-muted); font-weight: 700; letter-spacing: 0.05em;">Missing Records</span>
          <strong style="font-size: 24px; font-weight: 800; margin-top: 8px; color: ${missingRows > 0 ? '#ef4444' : 'var(--text-main)'}">${missingRows}</strong>
        </div>
        <div class="metric" style="padding: 20px; border-radius: 4px; display: flex; flex-direction: column; justify-content: space-between; min-height: 100px; border: 1px solid var(--border-color); background: var(--bg-card);">
          <span style="font-size: 11px; text-transform: uppercase; color: var(--text-muted); font-weight: 700; letter-spacing: 0.05em;">Amount Delta</span>
          <strong style="font-size: 24px; font-weight: 800; margin-top: 8px; color: ${totalAmountDiff > 0 ? '#ef4444' : 'var(--text-main)'}">${formatAmount(totalAmountDiff)}</strong>
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
          <td style="font-variant-numeric: tabular-nums; font-weight: 600; color: ${delta > 0 ? '#ef4444' : 'var(--text-muted)'}">${delta > 0 ? formatAmount(delta) : "-"}</td>
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
      <div class="panel" style="margin-bottom: 12px; padding: 8px 12px;">
        <div style="margin-bottom: 8px;">
          <h4 style="margin: 0; font-size: 12.5px; font-weight: 700; color: white;">Affected Records Preview</h4>
          <p style="margin: 2px 0 0 0; font-size: 11px; color: var(--text-muted);">Records that caused the current verdict.</p>
        </div>
        ${previewRows.length ? table(previewHeaders, previewRows) : `<div style="text-align: center; padding: 16px; color: var(--text-muted); font-size: 11.5px; background: rgba(255,255,255,0.01); border: 1px solid rgba(255,255,255,0.04); border-radius: 4px;">No affected records found.</div>`}
      </div>
    `;

    // 4. Insight tabs markup
    const insightsData = state.insightsData;
    const insightTabs = ["Anomalies", "Patterns", "Recommendations"];
    let insightContent = '<div class="insight-content empty"><p class="muted">No insights available.</p></div>';
    if (insightsData) {
      const activeTabKey = ["anomalies", "patterns", "recommendations"][state.activeInsightTab || 0];
      const tabItems = Array.isArray(insightsData) ? insightsData : (insightsData[activeTabKey] || []);
      if (tabItems.length === 0) {
        insightContent = `<div class="insight-content empty"><p class="muted">No items found for this category.</p></div>`;
      } else {
        insightContent = `
          <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 12px; padding-top: 8px;">
            ${tabItems.map(item => `
              <div class="review-card" style="cursor: default; display: flex; flex-direction: column; gap: 10px;">
                <div class="review-card-top" style="display: flex; align-items: center; justify-content: space-between; gap: 8px;">
                  <span class="badge ${item.severity === 'critical' || item.severity === 'high' ? 'failed' : item.severity === 'medium' ? 'warning' : 'matched'}" style="font-size: 10px; padding: 2px 8px; border: none; border-radius: 4px; font-weight: 600;">
                    ${escapeHtml(item.severity || 'medium').toUpperCase()}
                  </span>
                  <span style="font-size: 11px; color: var(--text-muted); font-weight: 500;">Affected: ${formatNumber(item.affected_count || 0)}</span>
                </div>
                <h3 style="margin: 4px 0 0 0; font-size: 14px; font-weight: 700; color: white;">${highlightInsightText(item.title || '')}</h3>
                <p style="margin: 0; font-size: 12.5px; line-height: 1.5; color: var(--text-muted);">${highlightInsightText(item.description || '')}</p>
                ${item.recommendation ? `
                  <div class="review-impact-box" style="margin: 10px 0 0 0;">
                    <strong style="color: var(--brand-primary); font-size: 11.5px; display: flex; align-items: center; gap: 4px;">
                      <span class="material-symbols-outlined" style="font-size: 14px;">arrow_forward</span> Next step
                    </strong>
                    <p style="margin-top: 4px; font-size: 12px; line-height: 1.4; color: var(--text-main);">${highlightInsightText(item.recommendation)}</p>
                  </div>
                ` : ''}
              </div>
            `).join('')}
          </div>
        `;
      }
    }

    const tabsSectionHtml = `
      <div class="panel" style="margin-bottom: 12px; border: 1px solid var(--border-color); background: var(--bg-card); border-radius: 8px;">
        <div style="display: flex; align-items: center; justify-content: space-between; padding: 8px 12px; font-weight: 600; border-bottom: 1px solid rgba(255,255,255,0.06); cursor: default;">
          <div style="display: flex; align-items: center; gap: 6px;">
            <span class="material-symbols-outlined" style="font-size: 16px; color: var(--text-muted);">insights</span>
            <span style="font-size: 12px; color: white;">Deep Dive Insights</span>
            <span style="font-size: 11px; color: var(--text-muted); font-weight: normal; margin-left: 8px;">Structured AI findings, patterns, and recommendations.</span>
          </div>
        </div>
        <div style="padding: 12px; cursor: default;">
          <div class="insights-tabs" style="margin-top: 0; margin-bottom: 12px;">
            ${insightTabs.map((tab, i) => `
              <button class="insight-tab ${i === (state.activeInsightTab || 0) ? 'active' : ''}" data-action="set-insight-tab" data-tab-index="${i}">${tab}</button>
            `).join('')}
          </div>
          ${insightContent}
        </div>
      </div>
    `;

    // 5. Evidence table markup
    // Mismatch filters
    const statusTabs = [
      ["", "All"],
      ["MATCHED", "Matched"],
      ["AMOUNT_MISMATCH", "Amount Mismatch"],
      ["STATUS_MISMATCH", "Status Mismatch"],
      ["MISSING_INTERNAL", "Missing Internal"],
      ["MISSING_PARTNER", "Missing Partner"]
    ].map(([value, label]) => `
      <button class="status-tab ${state.reconStatus === value ? "active" : ""}" data-action="set-recon-status" data-status="${escapeHtml(value)}" style="padding: 4px 10px; font-size: 11.5px;">
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

    const headers = ["Sev", "Issue Type", "Trace / TXN ID", "Internal Status", "Partner Status", "Internal Amount", "Partner Amount", "Delta", "Action"];
    const rows = filteredItems.map(item => {
      const isMatched = item.reconciliationStatus === "MATCHED";
      const isMissing = /MISSING_/.test(item.reconciliationStatus);
      const sev = isMissing ? "HIGH" : (isMatched ? "LOW" : "MEDIUM");

      const rowId = item.partnerTxnId || item.internalTxnId || item.id;
      const delta = Math.abs(Number(item.partnerAmount || 0) - Number(item.internalAmount || 0));
      const isSelected = !isMatched && state.selectedEvidenceRowId === rowId;
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
          <td style="font-variant-numeric: tabular-nums; font-weight: 600; color: ${delta > 0 ? '#ef4444' : 'var(--text-muted)'}">${delta > 0 ? formatAmount(delta) : "-"}</td>
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

    const tableFiltersHtml = `
      <div class="page-filters explorer-filters" style="margin-top: 10px; margin-bottom: 12px; padding: 8px 12px; border-radius: 6px; background: rgba(0,0,0,0.15); display: flex; flex-wrap: wrap; gap: 8px; align-items: center;">
        <span style="font-size: 11px; font-weight: 600; text-transform: uppercase; color: var(--text-muted);">Explorer Filters:</span>
        <input id="amount-min" type="text" placeholder="Min Delta" value="${escapeHtml(ef.amountMin || '')}" style="width: 90px; height: 26px; font-size: 12px; background: var(--bg-input); border: 1px solid var(--border-color); color: var(--text-main); padding: 2px 6px; border-radius: 4px;">
        <input id="amount-max" type="text" placeholder="Max Delta" value="${escapeHtml(ef.amountMax || '')}" style="width: 90px; height: 26px; font-size: 12px; background: var(--bg-input); border: 1px solid var(--border-color); color: var(--text-main); padding: 2px 6px; border-radius: 4px;">
        <button class="button primary" data-action="apply-recon-filters" style="height: 26px; font-size: 11px; padding: 2px 8px;">Apply</button>
        <button class="button secondary" data-action="clear-recon-filters" style="height: 26px; font-size: 11px; padding: 2px 8px;">Clear</button>
      </div>
    `;

    const evidenceTableHtml = `
      <section class="panel evidence-table-section">
        <div style="display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid rgba(255,255,255,0.06); padding-bottom: 8px; margin-bottom: 8px;">
          <div>
            <h2 class="section-title" style="margin: 0; font-size: 14px;">Reconciliation Evidence Ledger</h2>
            <p class="section-subtitle" style="margin: 2px 0 0 0; font-size: 11px;">Select a row to inspect full comparison detail and trigger adjustment options.</p>
          </div>
          <div style="display: flex; gap: 6px;">
            ${statusTabs}
          </div>
        </div>
        ${tableFiltersHtml}
        ${table(headers, rows)}
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

    // Render the popup outside the transform fade-in context (to document.body modal root)
    setTimeout(() => {
      let modalContainer = document.getElementById("modal-root");
      if (!modalContainer) {
        modalContainer = document.createElement("div");
        modalContainer.id = "modal-root";
        document.body.appendChild(modalContainer);
      }
      if (state.selectedEvidenceRowId && selectedRow) {
        modalContainer.innerHTML = renderEvidencePopup(selectedRow);
      } else {
        modalContainer.innerHTML = "";
      }
    }, 0);

    // Wrap in grid layout
    return `
      ${toolbarHtml}
      ${summaryStripHtml}
      <div class="reconciliation-container" style="display: grid; grid-template-columns: 1fr; gap: 16px; align-items: start;">
        <div>
          ${tabsSectionHtml}
          ${affectedPreviewHtml}
          ${evidenceTableHtml}
        </div>
      </div>
      ${modalHtml}
    `;

    // Internal Popup Helper
    function renderEvidencePopup(item) {
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
      const sevColor = sev === "HIGH" ? "#ef4444" : (sev === "MEDIUM" ? "#f97316" : "#10b981");
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
  }

  function renderDataExplorer(txsData, filesData) {
    const transactions = txsData.transactions || [];
    const files = filesData.files || [];

    // Table rows for files
    const fileRows = files.length
      ? files.map(f => {
          const formattedDate = f.reconciliationDate ? formatDisplayDateTime(f.reconciliationDate) : "-";
          return `
            <tr>
              <td><strong>${escapeHtml(f.fileName || f.file_name || f.filename || "-")}</strong></td>
              <td><code>${escapeHtml(f.partner || "-")}</code></td>
              <td><span class="badge" style="background: rgba(240,185,11,.08); color: var(--brand-primary); border-color: rgba(240,185,11,.2);">${escapeHtml(f.fileType || "-")}</span></td>
              <td style="font-variant-numeric: tabular-nums;">${formatNumber(f.recordsCount || f.totalRows || 0)}</td>
              <td><span class="badge ${f.processingStatus === 'COMPLETED' ? 'matched' : f.processingStatus === 'PROCESSING' ? 'processing' : 'failed'}">${escapeHtml(f.processingStatus || "-")}</span></td>
              <td>${formattedDate}</td>
            </tr>
          `;
        }).join("")
      : `<tr><td colspan="6" style="text-align: center; padding: 24px 0;" class="text-muted">No ingested files found for this period.</td></tr>`;

    // Table rows for transactions
    const txnRows = transactions.length
      ? transactions.map(t => {
          const pd = t.partnerData || {};
          const trace = pd.trace || "-";
          const amount = pd.amount ? formatAmount(parseFloat(pd.amount)) : "-";
          const status = pd.status || "-";
          const formattedDate = t.reconciliationDate ? formatDisplayDateTime(t.reconciliationDate) : "-";
          return `
            <tr>
              <td><code>${escapeHtml(t.id || "-")}</code></td>
              <td><code>${escapeHtml(trace)}</code></td>
              <td style="font-variant-numeric: tabular-nums; font-weight: 600;">${amount}</td>
              <td><span class="badge matched">${escapeHtml(status)}</span></td>
              <td><code>${escapeHtml(t.identify || "-")}</code></td>
              <td>${formattedDate}</td>
            </tr>
          `;
        }).join("")
      : `<tr><td colspan="6" style="text-align: center; padding: 24px 0;" class="text-muted">No transaction logs found for this period.</td></tr>`;

    const ef = state.explorerFilters || {};
    return `
      ${renderPageFilters()}
      <div class="page-filters explorer-filters" style="margin-top: -16px;">
        <div class="filter-group">
          <span class="filter-label">AMOUNT MIN</span>
          <div class="filter-input-wrapper">
            <input id="amount-min" type="text" placeholder="0" value="${escapeHtml(ef.amountMin || '')}">
          </div>
        </div>
        <div class="filter-group">
          <span class="filter-label">AMOUNT MAX</span>
          <div class="filter-input-wrapper">
            <input id="amount-max" type="text" placeholder="∞" value="${escapeHtml(ef.amountMax || '')}">
          </div>
        </div>
        <div class="filter-group">
          <span class="filter-label">DATE FROM</span>
          <div class="filter-input-wrapper">
            <input id="date-from" type="text" placeholder="dd/mm/yyyy" value="${escapeHtml(ef.dateFrom ? formatDisplayDate(ef.dateFrom) : '')}">
          </div>
        </div>
        <div class="filter-group">
          <span class="filter-label">DATE TO</span>
          <div class="filter-input-wrapper">
            <input id="date-to" type="text" placeholder="dd/mm/yyyy" value="${escapeHtml(ef.dateTo ? formatDisplayDate(ef.dateTo) : '')}">
          </div>
        </div>
        <div class="filter-group" style="align-self: flex-end;">
          <button class="button primary" id="explorer-apply-btn" style="padding: 8px 20px; font-size: 12px;">
            <span class="material-symbols-outlined" style="font-size: 14px;">search</span>
            Apply
          </button>
        </div>
      </div>
      <div style="display: grid; gap: 32px;">
        <section class="panel">
          <div class="panel-header" style="margin-bottom: 20px; display: flex; align-items: center; gap: 8px;">
            <span class="material-symbols-outlined" style="color: var(--brand-primary);">cloud_done</span>
            <h2 style="margin: 0;">Ingested Reconciliation Files (${formatNumber(filesData.total || files.length)})</h2>
          </div>
          <div class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Filename</th>
                  <th>Partner</th>
                  <th>Type</th>
                  <th>Records</th>
                  <th>Status</th>
                  <th>Ingestion Date</th>
                </tr>
              </thead>
              <tbody>
                ${fileRows}
              </tbody>
            </table>
          </div>
        </section>

        <section class="panel">
          <div class="panel-header" style="margin-bottom: 20px; display: flex; align-items: center; gap: 8px;">
            <span class="material-symbols-outlined" style="color: var(--brand-primary);">receipt_long</span>
            <h2 style="margin: 0;">Raw Ingested Transactions (${formatNumber(txsData.total || transactions.length)})</h2>
          </div>
          <div class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>System ID</th>
                  <th>Trace ID</th>
                  <th>Amount</th>
                  <th>Status</th>
                  <th>Identify</th>
                  <th>Reconciliation Date</th>
                </tr>
              </thead>
              <tbody>
                ${txnRows}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    `;
  }


  function renderMappings(data, actionData, embedded = false) {
    const items = data.mappings || [];
    const actions = (actionData && actionData.actions) || state.copilotActions || [];
    const pendingActions = actions.filter(action => action.status === "PENDING_APPROVAL");

    const actionCards = pendingActions.length ? pendingActions.map(action => {
      const payload = action.payload || {};
      const confidence = typeof payload.confidence === "number" ? Math.round(payload.confidence * 100) : null;
      const mappingCount = Array.isArray(payload.proposedMappings) ? payload.proposedMappings.length : null;
      const draftMappingId = action.draftMappingId || "";
      return `
        <section class="panel review-center-panel">
          <div class="review-center-header">
            <div>
              <div class="review-center-title-row">
                <strong>${escapeHtml(action.title || "Action item")}</strong>
                ${action.status ? badge(action.status) : ""}
              </div>
              <p class="muted review-center-reason">${escapeHtml(action.reason || "Awaiting operator review.")}</p>
            </div>
            <div class="review-center-actions">
              ${draftMappingId ? `<button class="button" data-action="approve-config" data-config-id="${escapeHtml(draftMappingId)}">Approve Draft</button>` : ""}
              ${draftMappingId ? `<button class="button secondary-action" data-action="reject-config" data-config-id="${escapeHtml(draftMappingId)}">Reject Draft</button>` : ""}
            </div>
          </div>
          <div class="review-center-meta">
            <span class="badge neutral">${escapeHtml(action.partner || state.partner)}</span>
            ${action.workflowType ? `<span class="badge neutral">${escapeHtml(action.workflowType)}</span>` : ""}
            ${action.fileType ? `<span class="badge neutral">${escapeHtml(action.fileType)}</span>` : ""}
            ${confidence !== null ? `<span class="badge neutral">Confidence ${confidence}%</span>` : ""}
            ${mappingCount !== null ? `<span class="badge neutral">${mappingCount} field mappings</span>` : ""}
            ${payload.sheetName ? `<span class="badge neutral">Sheet ${escapeHtml(payload.sheetName)}</span>` : ""}
            ${payload.startRow ? `<span class="badge neutral">Start row ${escapeHtml(String(payload.startRow))}</span>` : ""}
          </div>
        </section>
      `;
    }).join("") : `
      <section class="panel">
        <div class="empty-state" style="text-align: center; padding: 32px 0;">
          <span class="material-symbols-outlined" style="font-size: 40px; color: var(--text-muted); margin-bottom: 12px;">fact_check</span>
          <h3>No Pending Review Items</h3>
          <p class="muted">No human approvals are waiting for ${state.partner}.</p>
        </div>
      </section>
    `;

    if (!items.length) {
      return `
        ${embedded ? "" : renderPageFilters({ showDate: false, showClear: false })}
        <section class="panel">
          <div class="panel-header" style="margin-bottom: 16px;">
            <h2 style="margin: 0;">Review Center</h2>
          </div>
          ${actionCards}
        </section>
        <section class="panel">
          <div class="empty-state" style="text-align: center; padding: 40px 0;">
            <span class="material-symbols-outlined" style="font-size: 48px; color: var(--text-muted); margin-bottom: 12px;">settings</span>
            <h3>No Mapping Versions</h3>
            <p class="muted">No mapping versions found for ${state.partner}.</p>
          </div>
        </section>
      `;
    }

    const cards = items.map(config => {
      const health = config.configHealth || {};
      const status = String(config.status || health.status || (health.stale ? "STALE" : "APPROVED"));
      const confidence = typeof health.confidence === "number" ? Math.round(health.confidence * 100) : null;
      const statusClass =
        status === "APPROVED" ? "matched" :
        status === "PENDING_APPROVAL" ? "warning" :
        status === "SUPERSEDED" ? "processing" :
        "critical";
      const mappingsHtml = (config.fieldMappings || []).map(fm => `
        <div class="mapping-grid" style="margin-bottom: 8px;">
          <div class="mapping-card" style="padding: 10px 16px;">
            <div><strong>${escapeHtml(fm.path)}</strong></div>
            <div style="font-size: 11px; color: var(--text-muted);">
              ${fm.column ? `Col: ${escapeHtml(fm.column)}` : fm.constant ? `Const: ${escapeHtml(fm.constant)}` : '-'}
            </div>
          </div>
          <div class="mapping-arrow"><span class="material-symbols-outlined" style="font-size: 18px;">arrow_forward</span></div>
          <div class="mapping-card" style="padding: 10px 16px;">
            <code style="font-size: 11px;">${escapeHtml(fm.type)}</code>
            <div style="font-size: 10px; color: var(--text-muted); margin-top: 2px;">
              ${fm.required ? '<span style="color: var(--status-unmatched);">Required</span>' : 'Optional'}
              ${fm.mapping ? `<span style="color: var(--brand-accent-blue); margin-left: 4px;">• ${Object.keys(fm.mapping).length} rules</span>` : ''}
            </div>
          </div>
        </div>
      `).join("");

      return `
        <section class="panel" style="margin-bottom: 24px;">
          <div class="grid cols-4" style="margin-bottom: 20px; align-items: stretch;">
            <div class="metric" style="padding: 16px;">
              <span>Partner</span>
              <strong style="font-size: 20px;">${escapeHtml(config.partner)}</strong>
            </div>
            <div class="metric" style="padding: 16px;">
              <span>Version</span>
              <strong style="font-size: 20px;">${escapeHtml(config.configVersion || 'latest')}</strong>
            </div>
            <div class="metric" style="padding: 16px;">
              <span>File Type</span>
              <strong style="font-size: 20px;">${escapeHtml(config.fileType || 'SETTLEMENT')}</strong>
            </div>
            <div class="metric" style="padding: 16px;">
              <span>Sheet / Row</span>
              <strong style="font-size: 20px;">${escapeHtml(config.sheetName || '-')} / ${config.startRow || 2}</strong>
            </div>
          </div>
          <div style="display:flex; gap:12px; align-items:center; flex-wrap:wrap; margin-bottom: 16px;">
            ${badge(status)}
            ${confidence !== null ? `<span class="badge neutral">Confidence ${confidence}%</span>` : ""}
            ${config.approvedAt ? `<span class="badge neutral">Approved ${escapeHtml(formatDisplayDateTime(config.approvedAt))}</span>` : ""}
            ${config.supersededByConfigId ? `<span class="badge neutral">Superseded by ${escapeHtml(config.supersededByConfigId)}</span>` : ""}
            ${health.reasoning ? `<span class="muted" style="font-size: 12px;">${escapeHtml(String(health.reasoning))}</span>` : ""}
            ${status === "PENDING_APPROVAL" ? `<button class="button" data-action="approve-config" data-config-id="${escapeHtml(config._id || "")}">Approve</button>` : ""}
            ${status === "PENDING_APPROVAL" ? `<button class="button secondary-action" data-action="reject-config" data-config-id="${escapeHtml(config._id || "")}">Reject</button>` : ""}
            ${status === "PENDING_APPROVAL" ? `<button class="button" data-action="refresh-config" data-config-id="${escapeHtml(config._id || "")}" style="background: transparent; border: 1px solid var(--border);">Re-run AI</button>` : ""}
          </div>
          <h3 style="font-size: 13px; font-weight: 700; color: var(--text-muted); letter-spacing: 0.05em; text-transform: uppercase; margin-bottom: 16px;">
            Field Mappings (${(config.fieldMappings || []).length})
          </h3>
          ${mappingsHtml}
        </section>
      `;
    }).join("");

    return `
      ${embedded ? "" : renderPageFilters({ showDate: false, showClear: false })}
      <section class="panel">
        <div class="panel-header" style="margin-bottom: 16px;">
          <h2 style="margin: 0;">Review Center</h2>
        </div>
        ${actionCards}
      </section>
      ${cards}
    `;
  }

  function renderSettings(embedded = false) {
    const s = state.studio;
    
    const stepsHeader = `
      <div class="studio-steps">
        <div class="studio-step-item ${s.step === 1 ? 'active' : ''}">
          <span class="studio-step-index">1</span>
          Select Sample
        </div>
        <div class="studio-step-item ${s.step === 2 ? 'active' : ''} ${s.step >= 2 ? 'enabled' : ''}">
          <span class="studio-step-index">2</span>
          Review Draft
        </div>
        <div class="studio-step-item ${s.step === 3 ? 'active' : ''} ${s.step >= 3 ? 'enabled' : ''}">
          <span class="studio-step-index">3</span>
          Validate Output
        </div>
      </div>
    `;

    // Step 1: Choose Source View
    if (s.step === 1) {
      return `
        <section class="panel" style="margin-bottom: 24px;">
          ${embedded ? "" : `<h2>Create Draft Mapping</h2>
          <p class="muted" style="margin-bottom: 24px;">Upload a partner sample, review the draft mapping, then send it to Review Center.</p>`}
          
          ${stepsHeader}

          <div class="grid cols-3 studio-validation-grid">
            <!-- Option A: Upload Spreadsheet -->
            <div class="option-card" style="border: 1px dashed var(--border); border-radius: 8px; padding: 24px; text-align: center; background: rgba(240, 185, 11, 0.02); display: flex; flex-direction: column; justify-content: space-between; transition: var(--transition-smooth);">
              <div>
                ${state.studio.loading ? `
                  <div style="display: flex; flex-direction: column; align-items: center; justify-content: center; min-height: 120px;">
                    <div class="spinner" style="margin-bottom: 16px;"></div>
                    <p style="font-size: 13px; font-weight: 600; color: var(--brand-primary); margin: 0;">AI is analyzing your file...</p>
                    <p class="muted" style="font-size: 11px; margin-top: 4px;">Mapping structure extraction in progress</p>
                  </div>
                ` : `
                  <span class="material-symbols-outlined" style="font-size: 48px; color: var(--brand-primary); margin-bottom: 12px;">psychology</span>
                  <h3 style="margin: 0 0 8px 0;">Upload Partner Sample</h3>
                  <p class="muted" style="font-size: 12px; margin-bottom: 16px;">Upload a spreadsheet (.xlsx, .xls, .csv) to generate a draft mapping.</p>
                  
                  <div style="margin-bottom: 16px; display: flex; gap: 8px; align-items: center; justify-content: center;">
                    <span style="font-size:11px; font-weight:700; color: var(--text-muted);">PARTNER:</span>
                    <select id="studio-partner-select" style="font-size: 11px; padding: 4px 18px 4px 8px; background: var(--bg-primary); border: 1px solid var(--border); border-radius: 4px; color: var(--text-primary); cursor: pointer; outline: none; height: 28px;">
                      <option value="VNPAY" ${state.partner === "VNPAY" ? "selected" : ""}>VNPAY</option>
                      <option value="MOMO" ${state.partner === "MOMO" ? "selected" : ""}>MOMO</option>
                      <option value="ZALOPAY" ${state.partner === "ZALOPAY" ? "selected" : ""}>ZALOPAY</option>
                      <option value="ACMEPAY" ${state.partner === "ACMEPAY" ? "selected" : ""}>ACMEPAY</option>
                    </select>
                  </div>
                `}
              </div>
              <div>
                <input type="file" id="studio-excel-upload" accept=".xlsx,.xls,.csv" style="display: none;">
                <button class="button primary" style="width: 100%;" onclick="document.getElementById('studio-excel-upload').click()" ${state.studio.loading ? "disabled" : ""}>
                  <span class="material-symbols-outlined" style="font-size:18px;">upload</span> ${state.studio.loading ? "Processing..." : "Generate Draft"}
                </button>
              </div>
            </div>

            <!-- Option B: Upload JSON -->
            <div class="option-card" style="border: 1px dashed var(--border); border-radius: 8px; padding: 24px; text-align: center; background: rgba(255,255,255,0.01); display: flex; flex-direction: column; justify-content: space-between; transition: var(--transition-smooth);">
              <div>
                <span class="material-symbols-outlined" style="font-size: 48px; color: var(--text-muted); margin-bottom: 12px;">upload_file</span>
                <h3 style="margin: 0 0 8px 0;">Upload Existing Schema</h3>
                <p class="muted" style="font-size: 12px; margin-bottom: 24px;">Start from an existing JSON schema and send a revised version for review.</p>
              </div>
              <div>
                <input type="file" id="studio-json-upload" accept=".json" style="display: none;">
                <button class="button" style="width: 100%;" onclick="document.getElementById('studio-json-upload').click()">
                  <span class="material-symbols-outlined" style="font-size:18px;">folder_open</span> Browse JSON File
                </button>
              </div>
            </div>

            <!-- Option C: Paste JSON -->
            <div class="option-card" style="border: 1px dashed var(--border); border-radius: 8px; padding: 24px; text-align: center; background: rgba(255,255,255,0.01); display: flex; flex-direction: column; justify-content: space-between; transition: var(--transition-smooth);">
              <div>
                <span class="material-symbols-outlined" style="font-size: 48px; color: var(--text-muted); margin-bottom: 12px;">edit_note</span>
                <h3 style="margin: 0 0 8px 0;">Manual Setup</h3>
                <p class="muted" style="font-size: 12px; margin-bottom: 24px;">Start configuration manually by pasting JSON mapping template.</p>
              </div>
              <div>
                <button class="button" style="width: 100%;" id="studio-paste-btn">
                  <span class="material-symbols-outlined" style="font-size:18px;">code</span> Paste Schema JSON
                </button>
              </div>
            </div>
          </div>
        </section>
      `;
    }

    // Step 2: Data Preview & AI Mapping
    if (s.step === 2) {
      // Build Excel Sheet preview if headers present
      let previewHtml = '';
      if (s.headers && s.headers.length) {
        const previewHeaders = s.headers.map(h => `<th style="text-align: left; padding: 10px;">${escapeHtml(h)}</th>`).join("");
        const previewRows = s.sampleRows.slice(0, 10).map((row, rIdx) => {
          const cells = row.map(c => `<td style="padding: 10px; border-top: 1px solid var(--border); font-size:12px;">${escapeHtml(String(c || ''))}</td>`).join("");
          return `<tr><td style="padding: 10px; border-top: 1px solid var(--border); font-size:12px; font-weight:700; color:var(--text-muted);">${rIdx + 1}</td>${cells}</tr>`;
        }).join("");
        
        previewHtml = `
          <div style="margin-bottom: 24px;">
            <h3 style="font-size: 13px; font-weight: 700; color: var(--text-muted); text-transform: uppercase; margin-bottom: 12px;">Detected File Structure Preview</h3>
            <div class="table-wrap" style="overflow-x: auto; max-height: 250px; background: rgba(0,0,0,0.15); border: 1px solid var(--border); border-radius: 6px;">
              <table style="width: 100%; border-collapse: collapse;">
                <thead>
                  <tr style="background: var(--bg-surface-hover);">
                    <th style="width: 40px; padding: 10px; text-align: left;">Row</th>
                    ${previewHeaders}
                  </tr>
                </thead>
                <tbody>
                  ${previewRows}
                </tbody>
              </table>
            </div>
          </div>
        `;
      }

      // Visual Field Mappings Table or JSON textarea
      const configJsonStr = s.config ? JSON.stringify(s.config, null, 2) : '';
      
      // AI Mapping review table (Step 3/4)
      const fieldMappings = (s.config?.fieldMappings || []).filter(fm => fm.path !== "currency");
      const mappingRows = fieldMappings.map((fm, idx) => {
        const path = fm.path || '';
        const col = fm.column !== undefined ? fm.column : '';
        const constVal = fm.constant !== undefined ? fm.constant : '';
        const type = fm.type || 'STRING';
        const isRequired = fm.required ? 'Yes' : 'No';
        
        // Confidence
        const confidenceVal = s.config?.configHealth?.confidence || 0.85;
        const confidencePct = Math.round(confidenceVal * 100);
        let badgeClass = 'neutral';
        let label = 'Medium';
        if (confidencePct >= 90) {
          badgeClass = 'matched';
          label = 'High';
        } else if (confidencePct < 80) {
          badgeClass = 'critical';
          label = 'Needs Review';
        }
        
        return `
          <tr>
            <td style="padding: 12px 16px; font-weight:600; color: var(--text-primary); border-top:1px solid var(--border);">${escapeHtml(path)}</td>
            <td style="padding: 12px 16px; border-top:1px solid var(--border);">
              <select class="studio-mapping-col-select" data-idx="${idx}" style="font-size:12px; padding: 4px 8px; background: var(--bg-primary); border: 1px solid var(--border); border-radius: 4px; outline:none; color:var(--text-primary);">
                <option value="">-- Constant Only --</option>
                ${s.headers.map((h, hIdx) => `<option value="${hIdx + 1}" ${col === (hIdx + 1) ? 'selected' : ''}>Col ${hIdx + 1}: ${h}</option>`).join("")}
              </select>
            </td>
            <td style="padding: 12px 16px; border-top:1px solid var(--border);">
              <input type="text" class="studio-mapping-const-input" data-idx="${idx}" value="${escapeHtml(String(constVal))}" style="font-size:12px; padding: 4px 8px; background: var(--bg-primary); border: 1px solid var(--border); border-radius: 4px; outline:none; color:var(--text-primary); width:100px;" placeholder="Constant...">
            </td>
            <td style="padding: 12px 16px; border-top:1px solid var(--border);">
              <select class="studio-mapping-type-select" data-idx="${idx}" style="font-size:12px; padding: 4px 8px; background: var(--bg-primary); border: 1px solid var(--border); border-radius: 4px; outline:none; color:var(--text-primary);">
                <option value="STRING" ${type === 'STRING' ? 'selected' : ''}>STRING</option>
                <option value="DECIMAL" ${type === 'DECIMAL' ? 'selected' : ''}>DECIMAL</option>
                <option value="DATE" ${type === 'DATE' ? 'selected' : ''}>DATE</option>
                <option value="CONSTANT" ${type === 'CONSTANT' ? 'selected' : ''}>CONSTANT</option>
              </select>
            </td>
            <td style="padding: 12px 16px; border-top:1px solid var(--border);"><span class="badge ${isRequired === 'Yes' ? 'warning' : 'neutral'}">${isRequired}</span></td>
            <td style="padding: 12px 16px; border-top:1px solid var(--border);"><span class="badge ${badgeClass}">${confidencePct}% (${label})</span></td>
          </tr>
        `;
      }).join("");

      return `
        <section class="panel" style="margin-bottom: 24px;">
          <h2>Review Draft Mapping</h2>
          <p class="muted" style="margin-bottom: 20px;">Inspect the detected file structure and adjust the draft before it moves through Review Center.</p>
          
          ${stepsHeader}
          ${s.draftMappingId ? `
            <div class="panel" style="margin-bottom: 20px; padding: 12px 16px; display: flex; align-items: center; gap: 12px; background: rgba(59, 130, 246, 0.05); border: 1px solid rgba(59, 130, 246, 0.18); border-radius: 6px;">
              <span class="material-symbols-outlined" style="color: var(--brand-accent-blue);">info</span>
              <div style="font-size: 13px; color: var(--text-primary); flex-grow: 1;">
                This draft is currently pending review. Runtime eligibility: <strong>${s.isRuntimeEligible ? "Yes" : "No"}</strong>.
              </div>
              <div style="margin-left: auto;">
                ${badge(s.configStatus || "PENDING_APPROVAL")}
              </div>
            </div>
          ` : ""}
          ${previewHtml}

          <!-- Tabs header -->
          <div class="studio-toolbar">
            <div class="studio-toolbar-tabs">
              <button class="button active studio-tab-button" id="studio-tab-visual">Visual Mapping</button>
              <button class="button studio-tab-button" id="studio-tab-json">Schema JSON</button>
            </div>
            
            <div>
              <button class="button button-ghost" id="studio-add-field-btn" style="height:32px; padding:0 12px; font-size:12px;">+ Add Mapping Row</button>
            </div>
          </div>

          <!-- Tab Content 1: Visual Mapper -->
          <div id="studio-tab-visual-content" style="margin-bottom: 24px; border:1px solid var(--border); border-radius:6px; background:var(--bg-surface);">
            <table style="width:100%; border-collapse:collapse; text-align:left;">
              <thead>
                <tr style="background:var(--bg-surface-hover);">
                  <th style="padding:12px 16px;">Canonical Field</th>
                  <th style="padding:12px 16px;">Source Column</th>
                  <th style="padding:12px 16px;">Constant Value</th>
                  <th style="padding:12px 16px;">Data Type</th>
                  <th style="padding:12px 16px;">Required</th>
                  <th style="padding:12px 16px;">AI Confidence</th>
                </tr>
              </thead>
              <tbody>
                ${mappingRows}
              </tbody>
            </table>
          </div>

          <!-- Tab Content 2: Raw JSON -->
          <div id="studio-tab-json-content" style="display:none; margin-bottom: 24px; display:flex; flex-direction:column; gap:10px;">
            <textarea id="studio-json-textarea" style="width:100%; min-height: 280px; font-family: monospace; background: var(--bg-primary); border: 1px solid var(--border); padding: 12px; border-radius: 6px; color: #a8ffb2; outline: none; line-height: 1.4; font-size: 13px;" placeholder="Schema JSON...">${configJsonStr}</textarea>
            <div style="text-align:right;">
              <button class="button" id="studio-copy-json-btn" style="height:32px; padding:0 16px; font-size:12px;">Copy JSON Schema</button>
            </div>
          </div>



          <div style="display: flex; gap: 12px;">
            <button class="button" id="studio-back-to-1-btn">Back to Step 1</button>
            <button class="button primary" id="studio-to-3-btn">
              <span class="material-symbols-outlined" style="font-size:18px;">rule</span> Validate & Test Mapping Schema
            </button>
          </div>
        </section>
      `;
    }

    // Step 3: Validate, Test & Submit
    if (s.step === 3) {
      // Quality score details
      const score = s.validation?.score || 100;
      let scoreClass = 'matched';
      let scoreLabel = 'Excellent';
      if (score < 75) {
        scoreClass = 'critical';
        scoreLabel = 'Review Needed';
      } else if (score < 90) {
        scoreClass = 'warning';
        scoreLabel = 'Good';
      }

      // Checklists
      const errors = s.validation?.errors || [];
      const warnings = s.validation?.warnings || [];
      const passedChecks = [
        errors.some(e => e.includes("required")) ? null : "Required fields are mapped for the canonical output.",
        warnings.some(w => w.includes("multiple")) ? null : "Duplicate mapping check passed.",
        warnings.some(w => w.includes("neither")) ? null : "Each field has either a source column or a constant."
      ].filter(Boolean);

      const renderValidationItems = (items, tone, icon) => items.length
        ? items.map(item => `
          <div class="validation-item ${tone}">
            <span class="material-symbols-outlined">${icon}</span>
            <span>${escapeHtml(item)}</span>
          </div>
        `).join("")
        : `<div class="validation-empty ${tone}">None</div>`;

      // Test output transformed JSON representation
      let testOutputHtml = `<div class="empty-state" style="padding: 24px; text-align:center;">Click "Run Transformation Test" to verify output layout.</div>`;
      if (s.testOutput) {
        testOutputHtml = `
          <textarea readonly style="width:100%; min-height: 180px; font-family: monospace; background: var(--bg-primary); border: 1px solid var(--border); padding: 12px; border-radius: 6px; color: #5bc0be; outline: none; line-height: 1.4; font-size: 13px;">${JSON.stringify(s.testOutput, null, 2)}</textarea>
        `;
      }

      // Versions history listing
      const versionRows = (s.versions || []).map(v => `
        <tr style="border-top:1px solid var(--border);">
          <td style="padding:10px 12px; font-weight:700;">${escapeHtml(v.configVersion || 'latest')}</td>
          <td style="padding:10px 12px; color:var(--text-muted);">${escapeHtml(v.publishedAt ? formatDisplayDateTime(v.publishedAt) : 'N/A')}</td>
          <td style="padding:10px 12px; text-align:right;">
            <button class="button studio-restore-version-btn" data-id="${v._id}" style="height:26px; padding:0 10px; font-size:11px;">Restore</button>
          </td>
        </tr>
      `).join("");
      
      const versionsTable = versionRows ? `
        <table style="width:100%; border-collapse:collapse; text-align:left; font-size:12px;">
          <thead>
            <tr style="background:var(--bg-surface-hover);">
              <th style="padding:10px 12px;">Version</th>
              <th style="padding:10px 12px;">Published Date</th>
              <th style="padding:10px 12px; text-align:right;">Action</th>
            </tr>
          </thead>
          <tbody>
            ${versionRows}
          </tbody>
        </table>
      ` : `<div style="font-size:12px; color:var(--text-muted); padding:10px; text-align:center;">No previous versions.</div>`;

      return `
        <section class="panel" style="margin-bottom: 24px;">
          <h2>Validate & Prepare Review Handoff</h2>
          <p class="muted" style="margin-bottom: 20px;">Resolve blocking issues, inspect warnings, test the transformed output, and then hand the draft to Review Center.</p>
          ${s.draftMappingId ? `
            <div class="panel" style="margin-bottom: 20px; padding: 12px 16px; display: flex; align-items: center; gap: 16px; background: rgba(59, 130, 246, 0.05); border: 1px solid rgba(59, 130, 246, 0.18); border-radius: 6px; flex-wrap: wrap;">
              <span class="material-symbols-outlined" style="color: var(--brand-accent-blue);">fact_check</span>
              <div style="font-size: 13px; color: var(--text-primary); flex-grow: 1;">
                This draft requires Review Center action before activation.
              </div>
              <div style="display: flex; gap: 8px; align-items: center; margin-left: auto;">
                ${badge(s.configStatus || "PENDING_APPROVAL")}
                <button class="button ${s.handoffConfirmed ? "secondary-action" : "primary"}" id="studio-confirm-handoff-btn" style="height: 32px; padding: 0 12px; font-size: 12px;">
                  ${s.handoffConfirmed ? "Handoff Confirmed" : "Confirm Ready"}
                </button>
                <button class="button" id="studio-open-review-center-btn" style="height: 32px; padding: 0 12px; font-size: 12px;">
                  Open Review Center
                </button>
              </div>
            </div>
          ` : ""}
          
          ${stepsHeader}

          <div class="grid cols-3" style="gap: 20px; align-items: stretch; margin-bottom: 24px;">
            <!-- Score & Validation Status -->
            <div class="panel studio-validation-card">
              <div>
                <h3 style="margin: 0 0 16px 0; font-size:14px; text-transform:uppercase; letter-spacing:0.05em; color:var(--text-muted);">Mapping Quality Score</h3>
                <div style="display:flex; align-items:baseline; gap:8px; margin-bottom:8px;">
                  <strong style="font-size:36px; color:${score < 75 ? 'var(--status-unmatched)' : 'var(--brand-primary)'};">${score}</strong>
                  <span style="font-size:14px; color:var(--text-muted);">/ 100</span>
                </div>
                <span class="badge ${scoreClass}" style="margin-bottom:16px;">${scoreLabel}</span>
                <div class="validation-group">
                  <div class="validation-group-title">Passed Checks</div>
                  ${renderValidationItems(passedChecks, "matched", "check_circle")}
                </div>
              </div>
            </div>

            <div class="panel studio-validation-card">
              <div>
                <h3 style="margin:0 0 16px 0; font-size:14px; text-transform:uppercase; letter-spacing:0.05em; color:var(--text-muted);">Validation Results</h3>
                <div class="validation-group">
                  <div class="validation-group-title critical">Blocking Errors</div>
                  ${renderValidationItems(errors, "critical", "cancel")}
                </div>
                <div class="validation-group">
                  <div class="validation-group-title warning">Warnings</div>
                  ${renderValidationItems(warnings, "warning", "warning")}
                </div>
              </div>
            </div>

            <!-- Version Management history (Step 9) -->
            <div class="panel studio-validation-card studio-version-card">
              <div>
                <h3 style="margin:0 0 12px 0; font-size:14px; text-transform:uppercase; letter-spacing:0.05em; color:var(--text-muted);">Schema Versions</h3>
                <div class="table-wrap" style="max-height:160px; overflow-y:auto; border:1px solid var(--border); border-radius:4px;">
                  ${versionsTable}
                </div>
              </div>
            </div>
          </div>

          <!-- Section 2: Test Mapping Output console -->
          <div class="panel studio-output-panel">
            <div class="studio-output-header">
              <h3 style="margin:0; font-size:15px; font-weight:700;">Test Mapping Transformation Result</h3>
              <button class="button primary studio-tab-button" id="studio-run-test-btn">Run Transformation Test</button>
            </div>
            ${testOutputHtml}
          </div>

          <div style="display: flex; gap: 12px;">
            <button class="button" id="studio-back-to-2-btn">Back to Step 2</button>
            ${!s.draftMappingId ? `
              <button class="button primary" id="studio-confirm-handoff-btn">Mark Ready for Review</button>
            ` : ""}
          </div>
        </section>
      `;
    }
  }

  function renderAiObservation(obs) {
    const resolutionLabel = {
      "llm": "Primary LLM",
      "llm_fallback": "Fallback LLM",
      "schema_fallback": "Schema Fallback",
      "rule_based": "Rule-based",
    }[obs.resolution] || obs.resolution;

    const isLlm = obs.resolution === "llm";
    const providerModel = (obs.provider || '-') + (obs.model ? ` / ${obs.model}` : '');
    const gr = obs.guardrail_result;

    // Build the visual blueprint checklist of guardrails
    let guardrailChecklistHtml = '';
    if (gr && gr.findings) {
      // Map standard checks:
      // Check 1: Record Count Integrity
      const hasCountHallucination = gr.findings.some(f => f.field === 'affected_count');
      const countCheck = {
        title: "Record Count Verification",
        status: hasCountHallucination ? "fail" : "pass",
        desc: hasCountHallucination 
          ? "Discrepancy detected: LLM affected counts deviate from actual database records."
          : "Verified. LLM anomaly counts match underlying database metrics."
      };

      // Check 2: Severity Calibration
      const hasSeverityMismatch = gr.findings.some(f => f.field === 'severity');
      const severityCheck = {
        title: "Severity Level Calibration",
        status: hasSeverityMismatch ? "warn" : "pass",
        desc: hasSeverityMismatch
          ? "Deviation flagged: LLM severity level is slightly misaligned with threshold rules."
          : "Verified. Anomaly severity corresponds correctly to operational rules."
      };

      // Check 3: Scope Alignment
      const hasScopeMismatch = gr.findings.some(f => f.field === 'type');
      const scopeCheck = {
        title: "Analysis Scope Check",
        status: hasScopeMismatch ? "warn" : "pass",
        desc: hasScopeMismatch
          ? "Scope alert: Insights contain findings outside of the requested category focus."
          : "Verified. AI findings are 100% focused on the requested analysis dimension."
      };

      const checks = [countCheck, severityCheck, scopeCheck];
      guardrailChecklistHtml = `
        <div style="margin-top: 16px;">
          <h4 style="font-size: 11px; font-weight: 800; color: var(--text-muted); letter-spacing: 0.05em; text-transform: uppercase; margin-bottom: 12px;">AI Confidence & Integrity Guardrails</h4>
          <div class="guardrail-integrity-grid">
            ${checks.map(c => {
              const icon = c.status === 'pass' ? 'check_circle' : c.status === 'fail' ? 'cancel' : 'warning';
              return `
                <div class="guardrail-check-card ${c.status}">
                  <span class="material-symbols-outlined guardrail-check-icon ${c.status}">${icon}</span>
                  <div class="guardrail-check-body">
                    <span class="guardrail-check-title">${c.title}</span>
                    <span class="guardrail-check-desc">${c.desc}</span>
                  </div>
                </div>
              `;
            }).join("")}
          </div>
        </div>
      `;
    }

    const flowStatus = gr ? (gr.is_valid ? 'completed' : 'failed') : 'completed';
    const flowIcon = gr ? (gr.is_valid ? 'verified_user' : 'report') : 'verified_user';

    return `
      <details class="ai-obs-accordion">
        <summary class="ai-obs-summary">
          <div class="ai-obs-summary-left">
            <span class="material-symbols-outlined ai-obs-glow-icon">psychology</span>
            <span class="ai-obs-summary-title">AI Blueprint & Audit telemetry</span>
            <span class="ai-obs-summary-subtext">(${resolutionLabel} • ${providerModel} • Latency: ${obs.latency_ms ? obs.latency_ms.toFixed(0) + 'ms' : '-'})</span>
          </div>
          <div class="ai-obs-summary-right">
            <span class="ai-badge ${isLlm ? 'ai-badge-llm' : 'ai-badge-fallback'}">${isLlm ? 'LLM' : 'FALLBACK'}</span>
            ${obs.cache_hit ? '<span class="ai-badge ai-badge-hit">CACHED</span>' : ''}
            ${gr ? `<span class="ai-badge ai-badge-${gr.risk_level}">${gr.is_valid ? 'VALIDATED' : 'WARNING'}</span>` : ''}
            <span class="material-symbols-outlined accordion-arrow">expand_more</span>
          </div>
        </summary>
        <div class="ai-obs-details-grid" style="padding-top: 20px;">
          <div class="pipeline-flow" style="margin-bottom: 20px;">
            <div class="flow-step completed">
              <span class="material-symbols-outlined">database</span>
              <span>Source Ledger Data</span>
            </div>
            <div class="flow-arrow">➔</div>
            <div class="flow-step completed">
              <span class="material-symbols-outlined">cognition</span>
              <span>LLM Generator (${obs.model || 'rule-engine'})</span>
            </div>
            <div class="flow-arrow">➔</div>
            <div class="flow-step ${flowStatus}">
              <span class="material-symbols-outlined">${flowIcon}</span>
              <span>Integrity Guardrails</span>
            </div>
          </div>

          <div class="grid cols-3" style="gap: 12px; margin: 0;">
            <div class="ai-group">
              <div class="ai-group-title">PIPELINE METADATA</div>
              <div class="ai-group-body">
                <div class="ai-row">
                  <span class="ai-label">Resolution</span>
                  <span class="ai-value">${resolutionLabel}</span>
                </div>
                <div class="ai-row">
                  <span class="ai-label">Provider</span>
                  <span class="ai-value mono">${providerModel}</span>
                </div>
                <div class="ai-row">
                  <span class="ai-label">Cache</span>
                  <span class="ai-value">${obs.cache_hit ? 'Hit' : 'Miss'}</span>
                </div>
              </div>
            </div>
            <div class="ai-group">
              <div class="ai-group-title">PERFORMANCE METRICS</div>
              <div class="ai-group-body">
                <div class="ai-row">
                  <span class="ai-label">Latency</span>
                  <span class="ai-value mono">${obs.latency_ms ? obs.latency_ms.toFixed(0) + 'ms' : '-'}</span>
                </div>
                <div class="ai-row">
                  <span class="ai-label">Tokens</span>
                  <span class="ai-value mono">${formatNumber(obs.total_tokens || 0)} <small style="color: var(--text-muted); font-weight: 400;">(p:${formatNumber(obs.prompt_tokens || 0)} / c:${formatNumber(obs.completion_tokens || 0)})</small></span>
                </div>
                <div class="ai-row">
                  <span class="ai-label">Cost</span>
                  <span class="ai-value mono">${obs.estimated_cost_usd ? '$' + obs.estimated_cost_usd.toFixed(6) : '-'}</span>
                </div>
              </div>
            </div>
            <div class="ai-group">
              <div class="ai-group-title">QUALITY COMPLIANCE</div>
              <div class="ai-group-body">
                <div class="ai-row">
                  <span class="ai-label">Schema Validation</span>
                  <span class="ai-value">${obs.schema_valid ? 'PASSED' : 'FAILED'}</span>
                </div>
                <div class="ai-row">
                  <span class="ai-label">Data Integrity</span>
                  <span class="ai-value" style="color: ${gr && !gr.is_valid ? 'var(--status-failed)' : 'var(--status-matched)'};">${gr ? (gr.is_valid ? 'VERIFIED' : 'WARNING') : 'VERIFIED'}</span>
                </div>
              </div>
            </div>
          </div>
          
          ${guardrailChecklistHtml}
        </div>
      </details>
    `;
  }

  function renderError(err) {
    return `
      <section class="panel" style="border-color: var(--red); background: var(--red-bg); display: flex; align-items: center; gap: 12px;">
        <span class="material-symbols-outlined" style="color: var(--red);">error</span>
        <div>
          <strong style="color: var(--red);">Service API error</strong>
          <p class="muted" style="margin: 2px 0 0 0;">${escapeHtml(err.message || String(err))}</p>
        </div>
      </section>
    `;
  }

  function boldNumbers(text) {
    if (!text) return "";
    return text.replace(/\b(\d+(?:\.\d+)?%|\b\d+(?:,\d{3})*(?:\.\d+)?(?:[MKmk])?\s*VND|\b\d+(?:,\d{3})*(?:\.\d+)?(?:[MKmk])?)\b/gi, "<strong>$1</strong>");
  }

  function insightCard(item) {
    const sev = String(item.severity || "low").toLowerCase();
    
    // Select visual color and icon based on severity
    let statusColor = "var(--text-muted)";
    if (sev === "critical") {
      statusColor = "var(--critical)";
    } else if (sev === "high") {
      statusColor = "var(--status-warning)";
    } else if (sev === "medium") {
      statusColor = "#fb923c";
    } else if (sev === "low") {
      statusColor = "var(--status-matched)";
    }

    const typeLabel = (item.type || state.focus).replace(/_/g, ' ');
    const descriptionText = item.description || "";

    return `
      <div class="insight-card-flex" style="display: flex; gap: 16px; padding: 18px; border-radius: 14px; background: linear-gradient(180deg, rgba(255,255,255,0.03), rgba(255,255,255,0.015)); border: 1px solid rgba(255,255,255,0.07); align-items: flex-start; box-shadow: var(--shadow);">
        <div style="flex-shrink: 0; width: 68px; height: 68px; border-radius: 12px; background: ${sev === 'critical' ? 'rgba(235, 87, 87, 0.12)' : sev === 'high' ? 'rgba(240, 185, 11, 0.12)' : 'rgba(255,255,255,0.04)'}; display: flex; flex-direction: column; align-items: center; justify-content: center; border: 1.5px solid ${statusColor}; text-align: center; box-shadow: 0 4px 10px rgba(0,0,0,0.15);">
          <span style="font-size: 26px; font-weight: 800; color: ${statusColor}; line-height: 1.1; font-family: monospace;">${formatNumber(item.affected_count || 0)}</span>
          <span style="font-size: 9px; font-weight: 800; color: var(--text-muted); text-transform: uppercase; margin-top: 3px; letter-spacing: 0.05em;">Record</span>
        </div>
        <div style="flex-grow: 1; min-width: 0;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; gap: 8px;">
            <span class="insight-type-badge" style="margin: 0; font-size: 10px; padding: 2px 8px; text-transform: uppercase; font-weight: 700; background: rgba(255,255,255,0.05); color: var(--text-muted); border-radius: 4px;">${typeLabel}</span>
            ${severityBadge(sev)}
          </div>
          <h3 style="margin: 0 0 6px; font-size: 15px; font-weight: 700; color: #FFFFFF; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${boldNumbers(escapeHtml(item.title))}</h3>
          <p style="margin: 0 0 10px; font-size: 13px; color: var(--text-muted); line-height: 1.45;">${boldNumbers(escapeHtml(descriptionText))}</p>
          ${item.recommendation ? `
            <div style="padding: 10px 12px; border-radius: 8px; background: rgba(0,0,0,0.2); border-left: 3px solid ${statusColor}; font-size: 12px; box-shadow: inset 0 1px 3px rgba(0,0,0,0.2);">
              <strong style="color: ${statusColor}; font-size: 9px; text-transform: uppercase; letter-spacing: 0.06em; display: block; margin-bottom: 3px; font-weight: 800;">Action</strong>
              <span style="color: #E2E8F0; line-height: 1.4;">${boldNumbers(escapeHtml(item.recommendation))}</span>
            </div>
          ` : ""}
        </div>
      </div>
    `;
  }

  function bindViewActions() {
    const reconStatus = document.getElementById("recon-status-filter");
    if (reconStatus) {
      reconStatus.addEventListener("change", () => {
        state.reconStatus = reconStatus.value;
        render();
      });
    }

    const scopeSelect = document.getElementById("scope-override-select");
    if (scopeSelect) {
      scopeSelect.addEventListener("change", () => {
        const packetId = scopeSelect.dataset.packetId;
        if (!state.overrideScopes) {
          state.overrideScopes = {};
        }
        state.overrideScopes[packetId] = scopeSelect.value;
        renderPreserveScroll();
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
        render();
      });
    }

    // Actions triggers
    document.querySelectorAll("[data-action]").forEach(el => {
      el.addEventListener("click", (e) => {
        const action = el.dataset.action;
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
                briefStep = 0;
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
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({}),
          })
            .then(r => r.json().then(body => ({ ok: r.ok, body })))
            .then(({ ok, body }) => {
              el.disabled = false;
              el.style.opacity = "";
              el.style.cursor = "";
              el.innerHTML = originalText;
              if (!ok) throw new Error(body.detail || "Run now failed");
              showToast(`Automation job completed for ${partner}.`);
              render();
            })
            .catch(err => {
              el.disabled = false;
              el.style.opacity = "";
              el.style.cursor = "";
              el.innerHTML = originalText;
              showToast(err.message || "Run now failed");
            });
          return;
        }
        if (action === "select-partner") {
          const partner = el.dataset.partner;
          if (!partner) return;
          state.partner = partner;
          render();
          return;
        }
        if (action === "select-review-packet") {
          const packetId = el.dataset.packetId;
          if (!packetId) return;
          state.selectedReviewPacketId = packetId;
          renderPreserveScroll();
          return;
        }
        if (action === "go-review-center") {
          const partner = el.dataset.partner;
          if (partner) state.partner = partner;
          location.hash = "review-center";
          return;
        }
        if (action === "go-review-packet") {
          const packetId = el.dataset.packetId;
          const partner = el.dataset.partner;
          if (partner) state.partner = partner;
          if (packetId) state.selectedReviewPacketId = packetId;
          location.hash = "review-center";
          return;
        }
        if (action === "open-review-upload") {
          const uploadInput = el.parentElement?.querySelector(".review-upload-input")
            || el.closest(".panel")?.querySelector(".review-upload-input")
            || document.querySelector(".review-upload-input");
          uploadInput?.click();
          return;
        }
        if (action === "go-mapping-studio") {
          const partner = el.dataset.partner;
          if (partner) state.partner = partner;
          // Fresh studio open — clear pre-loaded IDs
          state.studio.handoffConfirmed = false;
          state.studio.step = 1;
          location.hash = "mapping-studio";
          return;
        }
        if (action === "clear-filters") {
          state.reconStatus = "";
          state.explorerFilters = { amountMin: "", amountMax: "", dateFrom: "", dateTo: "" };
          render();
          return;
        }
        if (action === "go-reconciliation") {
          location.hash = "reconciliation";
          return;
        }
        if (action === "set-recon-status") {
          state.reconStatus = el.dataset.status || "";
          render();
          return;
        }
        if (action === "reset-recon-status") {
          state.reconStatus = "";
          render();
          return;
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
            return;
          }
          if (dateToRaw && !parsedDateTo) {
            showToast("DATE TO khong hop le. Dung dd/mm/yyyy hoac yyyy-mm-dd.");
            return;
          }

          state.explorerFilters = {
            amountMin,
            amountMax,
            dateFrom: parsedDateFrom,
            dateTo: parsedDateTo
          };
          render();
          return;
        }
        if (action === "clear-recon-filters") {
          state.explorerFilters = { amountMin: "", amountMax: "", dateFrom: "", dateTo: "" };
          render();
          return;
        }
        if (action === "set-insight-tab") {
          const tabIndex = parseInt(el.dataset.tabIndex || "0", 10);
          state.activeInsightTab = tabIndex;
          render();
          return;
        }
        if (action === "approve-config") {
          const configId = el.dataset.configId;
          if (!configId) return;
          fetch(`/api/v1/mappings/${encodeURIComponent(configId)}/approve`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({}),
          })
            .then(r => r.json().then(body => ({ ok: r.ok, body })))
            .then(({ ok, body }) => {
              if (!ok) throw new Error(body.detail || "Approve failed");
              if (state.selectedReviewPacketId === configId) {
                state.selectedReviewPacketId = null;
              }
              showToast("Mapping config approved.");
              render();
            })
            .catch(err => showToast(err.message || "Approve failed"));
          return;
        }
        if (action === "reject-config") {
          const configId = el.dataset.configId;
          if (!configId) return;
          fetch(`/api/v1/mappings/${encodeURIComponent(configId)}/reject`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({}),
          })
            .then(r => r.json().then(body => ({ ok: r.ok, body })))
            .then(({ ok, body }) => {
              if (!ok) throw new Error(body.detail || "Reject failed");
              if (state.selectedReviewPacketId === configId) {
                state.selectedReviewPacketId = null;
              }
              showToast("Draft mapping rejected.");
              render();
            })
            .catch(err => showToast(err.message || "Reject failed"));
          return;
        }
        if (action === "refresh-config") {
          showToast("Re-run AI is triggered from the next fetch cycle.");
          return;
        }
        if (action === "approve-packet-activate" || action === "approve-packet-keep-current" || action === "reject-packet" || action === "send-packet-to-studio") {
          const packetId = el.dataset.packetId;
          if (!packetId) return;

          let actionLabel = "";
          if (action === "approve-packet-activate") actionLabel = "approve and activate this configuration";
          if (action === "approve-packet-keep-current") actionLabel = "approve this file but keep the current runtime configuration";
          if (action === "reject-packet") actionLabel = "reject this proposed change";
          if (action === "send-packet-to-studio") actionLabel = "send this item to Mapping Studio for adjustments";

          const originalText = el.innerHTML;
          el.disabled = true;
          el.style.opacity = "0.6";
          el.style.cursor = "not-allowed";
          if (action === "approve-packet-activate") {
            el.innerHTML = `<span class="spinner-mini" style="display:inline-block; width:12px; height:12px; border:2px solid #000; border-top:2px solid transparent; border-radius:50%; animation:spin 1s linear infinite; margin-right:6px; vertical-align:middle;"></span>Reconciling...`;
          } else if (action === "approve-packet-keep-current") {
            el.innerHTML = `Approving...`;
          } else if (action === "reject-packet") {
            el.innerHTML = `Rejecting...`;
          } else {
            el.innerHTML = `Processing...`;
          }

          const isVirtual = !state.reviewPackets.some(p => p._id === packetId);
          if (isVirtual) {
            if (action === "send-packet-to-studio") {
              el.disabled = false;
              el.style.opacity = "";
              el.style.cursor = "";
              el.innerHTML = originalText;
              state.studio.reviewItemId = null;
              state.studio.draftMappingId = packetId;
              state.studio.step = 2;
              location.hash = "mapping-studio";
              return;
            }
            const endpoint = action === "reject-packet" ? "reject" : "approve";
            fetch(`/api/v1/mappings/${encodeURIComponent(packetId)}/${endpoint}`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ reviewed_by: "Administrator" }),
            })
              .then(r => r.json().then(body => ({ ok: r.ok, body })))
              .then(({ ok, body }) => {
                el.disabled = false;
                el.style.opacity = "";
                el.style.cursor = "";
                el.innerHTML = originalText;
                if (!ok) throw new Error(body.detail || "Action failed");
                if (state.selectedReviewPacketId === packetId) {
                  state.selectedReviewPacketId = null;
                }
                showToast("Mapping config updated successfully.");
                render();
              })
              .catch(err => {
                el.disabled = false;
                el.style.opacity = "";
                el.style.cursor = "";
                el.innerHTML = originalText;
                showToast(err.message || "Action failed");
              });
            return;
          }

          const endpointMap = {
            "approve-packet-activate": "approve-activate",
            "approve-packet-keep-current": "approve-keep-current",
            "reject-packet": "reject",
            "send-packet-to-studio": "send-to-studio",
          };
          const payload = {};
          if (action === "approve-packet-activate" || action === "approve-packet-keep-current") {
            const scopeSelectEl = document.getElementById("scope-override-select");
            if (scopeSelectEl) {
              payload.scopeType = scopeSelectEl.value;
            } else if (state.overrideScopes && state.overrideScopes[packetId]) {
              payload.scopeType = state.overrideScopes[packetId];
            }
          }
          fetch(`/api/v1/review-packets/${encodeURIComponent(packetId)}/${endpointMap[action]}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
          })
            .then(r => r.json().then(body => ({ ok: r.ok, body })))
            .then(async ({ ok, body }) => {
              el.disabled = false;
              el.style.opacity = "";
              el.style.cursor = "";
              el.innerHTML = originalText;
              if (!ok) throw new Error(body.detail || "Review packet action failed");
              if (action === "send-packet-to-studio") {
                showToast("Opening Mapping Studio with this review item.");
                await openPacketInStudio(packetId);
                return;
              }
              if (state.selectedReviewPacketId === packetId) {
                state.selectedReviewPacketId = null;
              }
              if (action === "approve-packet-activate") {
                const runInfo = body.postApproveRun;
                if (runInfo?.partner) state.partner = runInfo.partner;
                if (runInfo?.date) state.date = runInfo.date;
                if (runInfo?.ok) {
                  showToast(`Approve xong va da chay doi soat ngay. ${runInfo.reconciliationCount || 0} ket qua duoc cap nhat.`);
                } else if (body.warning) {
                  showToast(body.warning);
                } else {
                  showToast("Review packet updated.");
                }
              } else {
                showToast("Review packet updated.");
              }
              state.guidedReviewOpen = false;
              render();
            })
            .catch(err => {
              el.disabled = false;
              el.style.opacity = "";
              el.style.cursor = "";
              el.innerHTML = originalText;
              showToast(err.message || "Review packet action failed");
            });
        }

        if (action === "validate-runtime-packet") {
          const packetId = el.dataset.packetId;
          if (!packetId) {
            showToast("Missing review packet id for runtime validation.");
            return;
          }
          const originalText = el.innerHTML;
          el.disabled = true;
          el.style.opacity = "0.65";
          el.innerHTML = `<span class="spinner-mini" style="display:inline-block; width:12px; height:12px; border:2px solid #fff; border-top:2px solid transparent; border-radius:50%; animation:spin 1s linear infinite; margin-right:6px; vertical-align:middle;"></span>Validating...`;
          fetch(`/api/v1/review-packets/${encodeURIComponent(packetId)}/validate-runtime`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
          })
            .then(r => r.json().then(body => ({ ok: r.ok, body })))
            .then(({ ok, body }) => {
              el.disabled = false;
              el.style.opacity = "";
              el.innerHTML = originalText;
              if (!ok) throw new Error(body.detail || "Runtime validation failed");
              const currentPacket = ([...(state.reviewCenterCache?.data?.packets || []), ...(state.reviewPackets || [])].find(packet => String(packet._id) === String(packetId)) || {});
              const gates = Array.isArray(currentPacket.validationGates) ? currentPacket.validationGates.filter(gate => gate.gateKey !== body.gate.gateKey) : [];
              gates.push(body.gate);
              syncLocalReviewPacket(packetId, {
                draftMappingId: currentPacket.draftMappingId || null,
                draftMappingVersion: currentPacket.draftMappingVersion || body.gate?.details?.validatedMappingVersion || currentPacket.draftMappingId || null,
                validationGates: gates,
                parseStrategy: currentPacket.parseStrategy || {}
              });
              state.reviewCenterCache = null;
              showToast(body.gate?.reason || "Runtime validation completed.");
              renderPreserveScroll();
            })
            .catch(err => {
              el.disabled = false;
              el.style.opacity = "";
              el.innerHTML = originalText;
              showToast(err.message || "Runtime validation failed");
            });
          return;
        }
        if (action === "set-review-tab") {
          const tab = el.dataset.tab;
          if (tab) {
            state.reviewTab = tab;
            render();
            if (tab === "history" && (!state.reviewHistoryCache || state.reviewHistoryCache.key !== `${state.partner}:${state.date}`)) {
              loadReviewHistoryData().catch(() => {
                showToast("Failed to load review history.");
              });
            }
          }
          return;
        }
        if (action === "open-guided-review") {
          state.guidedReviewOpen = true;
          state.guidedReviewStep = 1;
          state.guidedReviewScope = { loading: false, error: "", data: null, packetId: null };
          state.guidedReviewAI = { loading: false, error: "", mapping: null, packetId: null };
          render();
          const packet = getSelectedReviewPacket(getReviewCenterPendingItems(state.reviewCenterCache?.data || { packets: state.reviewPackets, mappings: [], intake: {} }));
          if (packet) {
            loadGuidedReviewScopeLLM(packet);
          }
          return;
        }
        if (action === "guided-next") {
          const packetId = el.dataset.packetId;
          if (!packetId) return;

          const step = state.guidedReviewStep || 1;
          if (step === 1) {
            const choice = document.querySelector('input[name="guided-scope-choice"]:checked');
            if (!choice) {
              showToast("Please select a file scope.");
              return;
            }
            const scopeType = choice.value;
            const originalText = el.innerHTML;
            el.disabled = true;
            el.style.opacity = "0.6";
            el.innerHTML = "Saving...";
            
            fetch(`/api/v1/review-packets/${encodeURIComponent(packetId)}/scope`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ scopeType }),
            })
              .then(r => r.json().then(body => ({ ok: r.ok, body })))
              .then(({ ok, body }) => {
                el.disabled = false;
                el.style.opacity = "";
                el.innerHTML = originalText;
                if (!ok) throw new Error(body.detail || "Failed to update scope.");
                
                updateReviewPacketLocally(packetId, currentPacket => {
                  currentPacket.scopeType = scopeType;
                });
                
                state.guidedReviewStep = 2;
                render();
                
                const currentPacket = [
                  ...(state.reviewPackets || []),
                  ...((state.reviewCenterCache && state.reviewCenterCache.data && state.reviewCenterCache.data.packets) || [])
                ].find(packet => String(packet._id) === String(packetId)) || null;
                if (currentPacket) {
                  loadGuidedReviewAIMapping(currentPacket);
                }
              })
              .catch(err => {
                el.disabled = false;
                el.style.opacity = "";
                el.innerHTML = originalText;
                showToast(err.message || "Failed to save scope.");
              });
            return;
          } else if (step === 2) {
            if (state.guidedReviewAI.loading || state.guidedReviewAI.error) {
              showToast("Wait for the AI mapping proposal to finish loading before saving.");
              return;
            }
            const originalText = el.innerHTML;
            const currentPacket = [
              ...(state.reviewPackets || []),
              ...((state.reviewCenterCache && state.reviewCenterCache.data && state.reviewCenterCache.data.packets) || [])
            ].find(packet => String(packet._id) === String(packetId)) || null;
            const rows = Array.from(document.querySelectorAll(".inline-field-select"));
            const fieldMappings = rows.map((select, index) => {
              const path = select.value;
              if (!path) return null;
              const sourceHeader = select.dataset.sourceHeader || `Column ${index + 1}`;
              const rawSourceColumn = select.dataset.sourceColumn;
              const sourceColumn = rawSourceColumn ? Number(rawSourceColumn) : null;
              const originalPath = select.dataset.originalPath || "";
              const originalType = select.dataset.originalType || "";
              const originalRequired = select.dataset.originalRequired === "true";
              const originalConstant = select.dataset.originalConstant || null;
              let originalMapping = null;
              if (select.dataset.originalMapping) {
                try {
                  originalMapping = JSON.parse(select.dataset.originalMapping);
                } catch (err) {
                  originalMapping = null;
                }
              }

              if (path === originalPath) {
                return {
                  path,
                  column: sourceColumn,
                  sourceField: sourceHeader,
                  type: originalType || INLINE_FIELD_TYPES[path] || "STRING",
                  required: originalRequired,
                  constant: originalConstant,
                  mapping: originalMapping
                };
              }

              return {
                path,
                column: sourceColumn,
                sourceField: sourceHeader,
                type: INLINE_FIELD_TYPES[path] || "STRING",
                required: ["id", "amount", "transDate"].includes(path)
              };
            }).filter(Boolean);

            el.disabled = true;
            el.style.opacity = "0.65";
            el.innerHTML = `<span class="spinner-mini" style="display:inline-block; width:12px; height:12px; border:2px solid #fff; border-top:2px solid transparent; border-radius:50%; animation:spin 1s linear infinite; margin-right:6px; vertical-align:middle;"></span>Saving...`;
            fetch(`/api/v1/review-packets/${encodeURIComponent(packetId)}/save-draft-mapping`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                sheetName: currentPacket?.parseStrategy?.sheetName || "Sheet1",
                startRow: currentPacket?.parseStrategy?.startRow || 2,
                fieldMappings
              }),
            })
              .then(r => r.json().then(body => ({ ok: r.ok, body })))
              .then(({ ok, body }) => {
                el.disabled = false;
                el.style.opacity = "";
                el.innerHTML = originalText;
                if (!ok) {
                  const detail = body.detail;
                  if (detail && typeof detail === "object") {
                    const msg = [detail.message, ...(detail.errors || []), ...(detail.warnings || [])]
                      .filter(Boolean)
                      .join(" ");
                    throw new Error(msg || "Save mapping failed");
                  }
                  throw new Error(detail || "Save mapping failed");
                }
                
                state.guidedReviewAI = {
                  loading: false,
                  error: "",
                  mapping: {
                    ...(state.guidedReviewAI.mapping || {}),
                    _id: body.draftMappingId,
                    configVersion: body.draftMappingVersion || state.guidedReviewAI.mapping?.configVersion || body.draftMappingId,
                    draftMappingVersion: body.draftMappingVersion || body.draftMappingId,
                    fieldMappings,
                    sheetName: body.sheetName,
                    startRow: body.startRow,
                  },
                  packetId
                };
                syncLocalReviewPacket(packetId, {
                  draftMappingId: body.draftMappingId,
                  draftMappingVersion: body.draftMappingVersion || body.draftMappingId,
                  validationGates: Array.isArray(body.validationGates) ? body.validationGates : [],
                  parseStrategy: {
                    ...(currentPacket?.parseStrategy || {}),
                    sheetName: body.sheetName,
                    startRow: body.startRow,
                    fieldMappingCount: body.fieldMappingCount
                  }
                });
                state.reviewCenterCache = null;
                showToast("Draft mapping saved.");
                state.guidedReviewStep = 3;
                render();
              })
              .catch(err => {
                el.disabled = false;
                el.style.opacity = "";
                el.innerHTML = originalText;
                showToast(err.message || "Save mapping failed");
              });
            return;
          } else if (step === 3) {
            const currentPacket = getReviewPacketById(packetId);
            if (!getRuntimeValidationState(currentPacket || {}).canProceed) {
              showToast("Run current runtime validation before moving to the decision step.");
              return;
            }
            state.guidedReviewStep = 4;
            render();
            return;
          }
        }
        if (action === "guided-prev") {
          if (state.guidedReviewStep && state.guidedReviewStep > 1) {
            state.guidedReviewStep -= 1;
            render();
          }
          return;
        }
        if (action === "back-to-guided-step-1") {
          state.guidedReviewStep = 1;
          render();
          return;
        }
        if (action === "back-to-guided-step-3") {
          state.guidedReviewStep = 3;
          render();
          return;
        }
        if (action === "close-guided-review") {
          state.guidedReviewOpen = false;
          state.guidedReviewAI = { loading: false, error: "", mapping: null, packetId: null };
          render();
          return;
        }
        if (action === "save-inline-mapping") {
          const packetId = el.dataset.packetId;
          if (!packetId) return;
          if (state.guidedReviewAI.loading || state.guidedReviewAI.error) {
            showToast("Wait for the AI mapping proposal to finish loading before saving.");
            return;
          }
          const originalText = el.innerHTML;
          const currentPacket = [
            ...(state.reviewPackets || []),
            ...((state.reviewCenterCache && state.reviewCenterCache.data && state.reviewCenterCache.data.packets) || [])
          ].find(packet => String(packet._id) === String(packetId)) || null;
          const rows = Array.from(document.querySelectorAll(".inline-field-select"));
          const fieldMappings = rows.map((select, index) => {
            const path = select.value;
            if (!path) return null;
            const sourceHeader = select.dataset.sourceHeader || `Column ${index + 1}`;
            const rawSourceColumn = select.dataset.sourceColumn;
            const sourceColumn = rawSourceColumn ? Number(rawSourceColumn) : null;
            const originalPath = select.dataset.originalPath || "";
            const originalType = select.dataset.originalType || "";
            const originalRequired = select.dataset.originalRequired === "true";
            const originalConstant = select.dataset.originalConstant || null;
            let originalMapping = null;
            if (select.dataset.originalMapping) {
              try {
                originalMapping = JSON.parse(select.dataset.originalMapping);
              } catch (err) {
                originalMapping = null;
              }
            }

            if (path === originalPath) {
              return {
                path,
                column: sourceColumn,
                sourceField: sourceHeader,
                type: originalType || INLINE_FIELD_TYPES[path] || "STRING",
                required: originalRequired,
                constant: originalConstant,
                mapping: originalMapping
              };
            }

            return {
              path,
              column: sourceColumn,
              sourceField: sourceHeader,
              type: INLINE_FIELD_TYPES[path] || "STRING",
              required: ["id", "amount", "transDate"].includes(path)
            };
          }).filter(Boolean);

          el.disabled = true;
          el.style.opacity = "0.65";
          el.innerHTML = `<span class="spinner-mini" style="display:inline-block; width:12px; height:12px; border:2px solid #fff; border-top:2px solid transparent; border-radius:50%; animation:spin 1s linear infinite; margin-right:6px; vertical-align:middle;"></span>Saving...`;
          fetch(`/api/v1/review-packets/${encodeURIComponent(packetId)}/save-draft-mapping`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              sheetName: currentPacket?.parseStrategy?.sheetName || "Sheet1",
              startRow: currentPacket?.parseStrategy?.startRow || 2,
              fieldMappings
            }),
          })
            .then(r => r.json().then(body => ({ ok: r.ok, body })))
            .then(({ ok, body }) => {
              el.disabled = false;
              el.style.opacity = "";
              el.innerHTML = originalText;
              if (!ok) {
                const detail = body.detail;
                if (detail && typeof detail === "object") {
                  const msg = [detail.message, ...(detail.errors || []), ...(detail.warnings || [])]
                    .filter(Boolean)
                    .join(" ");
                  throw new Error(msg || "Save mapping failed");
                }
                throw new Error(detail || "Save mapping failed");
              }
              state.guidedReviewAI = {
                loading: false,
                error: "",
                mapping: {
                  ...(state.guidedReviewAI.mapping || {}),
                  _id: body.draftMappingId,
                  configVersion: body.draftMappingVersion || state.guidedReviewAI.mapping?.configVersion || body.draftMappingId,
                  draftMappingVersion: body.draftMappingVersion || body.draftMappingId,
                  fieldMappings,
                  sheetName: body.sheetName,
                  startRow: body.startRow,
                },
                packetId
              };
              syncLocalReviewPacket(packetId, {
                draftMappingId: body.draftMappingId,
                draftMappingVersion: body.draftMappingVersion || body.draftMappingId,
                validationGates: Array.isArray(body.validationGates) ? body.validationGates : [],
                parseStrategy: {
                  ...(currentPacket?.parseStrategy || {}),
                  sheetName: body.sheetName,
                  startRow: body.startRow,
                  fieldMappingCount: body.fieldMappingCount
                }
              });
              state.reviewCenterCache = null;
              showToast("Draft mapping saved.");
              state.guidedReviewStep = 3;
              render();
            })
            .catch(err => {
              el.disabled = false;
              el.style.opacity = "";
              el.innerHTML = originalText;
              showToast(err.message || "Save mapping failed");
            });
          return;
        }
        if (action === "refresh-recon") {
          state.activeReconData = null;
          render();
          return;
        }
        if (action === "export-recon") {
          showToast("Reconciliation report exported successfully.");
          return;
        }
        if (action === "scroll-to-evidence") {
          document.querySelector(".evidence-table-section")?.scrollIntoView({ behavior: "smooth" });
          return;
        }
        if (action === "open-mapping-studio-context") {
          state.studio.step = 1;
          location.hash = "mapping-studio";
          return;
        }
        if (action === "create-adjustment") {
          const txnId = el.dataset.txnId || "";
          const amount = el.dataset.amount || "";
          state.adjustmentModalData = { txnId, amount };
          render();
          return;
        }
        if (action === "close-adjustment-modal") {
          state.adjustmentModalData = null;
          render();
          return;
        }
        if (action === "submit-adjustment") {
          showToast(`Adjustment of ${state.adjustmentModalData?.amount} VND for ${state.adjustmentModalData?.txnId} submitted successfully.`);
          state.adjustmentModalData = null;
          render();
          return;
        }
        if (action === "open-evidence-detail") {
          const rowId = el.dataset.rowId;
          state.selectedEvidenceRowId = rowId;
          render();
          return;
        }
        if (action === "close-evidence-drawer") {
          state.selectedEvidenceRowId = null;
          render();
          return;
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
              showToast(`Record ${rowId} marked as resolved.`);
              state.selectedEvidenceRowId = null;
              render();
            })
            .catch(() => {
              showToast("Failed to persist resolved record.");
            });
          return;
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
              showToast("Reconciliation run approved. All anomalies marked as resolved.");
              state.selectedEvidenceRowId = null;
              render();
            })
            .catch(() => {
              showToast("Failed to persist one or more resolved records.");
            });
          return;
        }
        if (action === "mark-exception") {
          showToast("Record marked as exception.");
          state.selectedEvidenceRowId = null;
          render();
          return;
        }
        if (action === "open-copilot-brief") {
          state.briefOpen = true;
          briefStep = 0;
          render();
          return;
        }
        if (action === "close-brief") {
          if (e.target !== el) return;
          state.briefOpen = false;
          briefStep = 0;
          render();
          return;
        }
        if (action === "brief-next") {
          if (briefStep < BRIEF_STEPS.length - 1) {
            briefStep++;
            render();
          }
          return;
        }
        if (action === "brief-prev") {
          if (briefStep > 0) {
            briefStep--;
            render();
          }
          return;
        }
      });
    });

    document.querySelectorAll(".review-upload-input").forEach(input => {
      input.addEventListener("change", (event) => {
        const file = event.target.files && event.target.files[0];
        if (!file) return;
        showToast("Analyzing uploaded file and preparing a review item...");
        const formData = new FormData();
        formData.append("file", file);

        fetch(`/api/v1/mapping/ai-generate?partner=${encodeURIComponent(state.partner)}`, {
          method: "POST",
          body: formData
        })
          .then(r => r.json().then(body => ({ ok: r.ok, body })))
          .then(({ ok, body }) => {
            if (!ok) throw new Error(body.detail || "Upload analysis failed");
            state.studio.fileName = file.name;
            state.studio.headers = body.headers || [];
            state.studio.sampleRows = body.sample_rows || [];
            state.studio.config = body.config;
            state.studio.draftMappingId = body.draftMappingId || null;
            state.studio.reviewItemId = body.reviewItemId || null;
            state.studio.configStatus = body.configStatus || null;
            state.studio.isRuntimeEligible = body.isRuntimeEligible || false;
            state.studio.handoffConfirmed = false;
            if (body.reviewItemId) {
              state.selectedReviewPacketId = body.reviewItemId;
            }
            showToast("Review item created. Opening Review Center.");
            location.hash = "review-center";
            if (input) input.value = "";
          })
          .catch(err => {
            showToast(err.message || "Upload analysis failed");
            if (input) input.value = "";
          });
      });
    });

    // Step 1: Upload Excel File for AI auto-generation
    const studioExcelUpload = document.getElementById("studio-excel-upload");
    if (studioExcelUpload) {
      studioExcelUpload.addEventListener("change", (e) => {
        const file = e.target.files[0];
        if (!file) return;
        const partner = document.getElementById("studio-partner-select")?.value || "VNPAY";
        
        showToast("Uploading sample and generating a draft mapping...");
        state.studio.loading = true;
        render();

        const formData = new FormData();
        formData.append("file", file);
        
        fetch(`/api/v1/mapping/ai-generate?partner=${encodeURIComponent(partner)}`, {
          method: "POST",
          body: formData
        })
          .then(r => r.json().then(body => ({ ok: r.ok, body })))
          .then(({ ok, body }) => {
            state.studio.loading = false;
            if (!ok) throw new Error(body.detail || "AI gen failed");
            
            state.studio.fileName = file.name;
            state.studio.headers = body.headers || [];
            state.studio.sampleRows = body.sample_rows || [];
            state.studio.config = body.config;
            state.studio.draftMappingId = body.draftMappingId || null;
            state.studio.reviewItemId = body.reviewItemId || null;
            state.studio.configStatus = body.configStatus || null;
            state.studio.isRuntimeEligible = body.isRuntimeEligible || false;
            state.studio.handoffConfirmed = false;
            state.studio.step = 2;
            if (body.reviewItemId) {
              state.selectedReviewPacketId = body.reviewItemId;
              showToast("Draft created. Opening Review Center with the review drawer.");
              location.hash = "review-center";
              return;
            }

            showToast("Draft created. Review now continues in the Review Center.");
            render();
          })
          .catch(err => {
            state.studio.loading = false;
            showToast("AI Gen failed: " + err.message);
            render();
          });
      });
    }

    // Step 1: Upload Existing Mapping JSON
    const studioJsonUpload = document.getElementById("studio-json-upload");
    if (studioJsonUpload) {
      studioJsonUpload.addEventListener("change", (e) => {
        const file = e.target.files[0];
        if (!file) return;
        
        const reader = new FileReader();
        reader.onload = (event) => {
          try {
            const json = JSON.parse(event.target.result);
            state.studio.config = json;
            state.studio.fileName = file.name;
            state.studio.step = 2;
            state.studio.handoffConfirmed = false;
            state.studio.headers = (json.fieldMappings || []).map(fm => fm.path); // fallback headers
            state.studio.sampleRows = [];
            
            showToast("Existing mapping JSON schema loaded.");
            render();
          } catch (err) {
            showToast("Invalid JSON file schema structure.");
          }
        };
        reader.readAsText(file);
      });
    }

    // Step 1: Paste JSON Button click
    const studioPasteBtn = document.getElementById("studio-paste-btn");
    if (studioPasteBtn) {
      studioPasteBtn.addEventListener("click", () => {
        const template = {
          "partner": "VNPAY",
          "workflowType": "UPC",
          "fileType": "SETTLEMENT",
          "sheetName": "Sheet1",
          "startRow": 2,
          "configVersion": "v_manual",
          "fieldMappings": [
            { "path": "id", "column": 1, "type": "STRING", "required": true },
            { "path": "amount", "column": 2, "type": "DECIMAL", "required": true },
            { "path": "transDate", "column": 3, "type": "DATE", "required": true }
          ]
        };
        state.studio.config = template;
        state.studio.step = 2;
        state.studio.handoffConfirmed = false;
        state.studio.headers = ["id", "amount", "transDate"];
        state.studio.sampleRows = [];
        
        showToast("Starting manual setup with default template.");
        render();
      });
    }

    // Tab Switches
    const tabVisual = document.getElementById("studio-tab-visual");
    const tabJson = document.getElementById("studio-tab-json");
    if (tabVisual && tabJson) {
      tabVisual.addEventListener("click", () => {
        tabVisual.classList.add("active");
        tabJson.classList.remove("active");
        document.getElementById("studio-tab-visual-content").style.display = "block";
        document.getElementById("studio-tab-json-content").style.display = "none";
      });
      tabJson.addEventListener("click", () => {
        tabJson.classList.add("active");
        tabVisual.classList.remove("active");
        document.getElementById("studio-tab-json-content").style.display = "flex";
        document.getElementById("studio-tab-visual-content").style.display = "none";
      });
    }

    // Add field mapping row
    const addFieldBtn = document.getElementById("studio-add-field-btn");
    if (addFieldBtn) {
      addFieldBtn.addEventListener("click", () => {
        if (!state.studio.config) return;
        state.studio.config.fieldMappings.push({
          "path": "custom_field_" + (state.studio.config.fieldMappings.length + 1),
          "column": null,
          "type": "STRING",
          "required": false
        });
        render();
      });
    }

    // Listeners for dropdown/input mapping edits
    document.querySelectorAll(".studio-mapping-col-select").forEach(el => {
      el.addEventListener("change", () => {
        const idx = parseInt(el.dataset.idx);
        const val = el.value ? parseInt(el.value) : null;
        if (state.studio.config && state.studio.config.fieldMappings[idx]) {
          state.studio.config.fieldMappings[idx].column = val;
          if (val !== null) delete state.studio.config.fieldMappings[idx].constant;
        }
      });
    });

    document.querySelectorAll(".studio-mapping-const-input").forEach(el => {
      el.addEventListener("change", () => {
        const idx = parseInt(el.dataset.idx);
        const val = el.value;
        if (state.studio.config && state.studio.config.fieldMappings[idx]) {
          state.studio.config.fieldMappings[idx].constant = val;
          if (val !== "") delete state.studio.config.fieldMappings[idx].column;
        }
      });
    });

    document.querySelectorAll(".studio-mapping-type-select").forEach(el => {
      el.addEventListener("change", () => {
        const idx = parseInt(el.dataset.idx);
        const val = el.value;
        if (state.studio.config && state.studio.config.fieldMappings[idx]) {
          state.studio.config.fieldMappings[idx].type = val;
        }
      });
    });

    // Accept AI Suggestions (Step 8)
    const acceptSuggestionBtn = document.getElementById("studio-accept-suggestion-btn");
    if (acceptSuggestionBtn) {
      acceptSuggestionBtn.addEventListener("click", () => {
        if (!state.studio.config) return;
        const hasCurrency = state.studio.config.fieldMappings.some(fm => fm.path === "currency");
        if (!hasCurrency) {
          state.studio.config.fieldMappings.push({
            "path": "currency",
            "constant": "VND",
            "type": "CONSTANT"
          });
        }
        showToast("AI Currency suggestion accepted.");
        render();
      });
    }

    // Back to Step 1
    const backTo1Btn = document.getElementById("studio-back-to-1-btn");
    if (backTo1Btn) {
      backTo1Btn.addEventListener("click", () => {
        state.studio.step = 1;
        state.studio.handoffConfirmed = false;
        render();
      });
    }

    // Proceed to Step 3 (Validate & Test Mapping Schema)
    const to3Btn = document.getElementById("studio-to-3-btn");
    if (to3Btn) {
      to3Btn.addEventListener("click", () => {
        const jsonTextarea = document.getElementById("studio-json-textarea");
        if (jsonTextarea && document.getElementById("studio-tab-json-content").style.display === "flex") {
          try {
            state.studio.config = JSON.parse(jsonTextarea.value);
          } catch (err) {
            showToast("Failed to parse schema JSON before proceeding.");
            return;
          }
        }

        if (!state.studio.config) return;

        // Ensure currency defaults to VND in config payload sent to backend validator
        const configCopy = JSON.parse(JSON.stringify(state.studio.config));
        if (configCopy.fieldMappings && !configCopy.fieldMappings.some(fm => fm.path === "currency")) {
          configCopy.fieldMappings.push({
            path: "currency",
            type: "CONSTANT",
            constant: "VND",
            required: true
          });
        }

        showToast("Running validation rules engine...");
        
        fetch("/api/v1/mapping/validate", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(configCopy)
        })
          .then(r => r.json())
          .then(data => {
            state.studio.validation = data;
            state.studio.step = 3;
            state.studio.handoffConfirmed = false;
            
            return fetch(`/api/v1/mapping/versions?partner=${encodeURIComponent(state.studio.config.partner)}`);
          })
          .then(r => r ? r.json() : null)
          .then(vData => {
            if (vData) state.studio.versions = vData.versions || [];
            render();
          })
          .catch(err => showToast("Validation fetch error: " + err.message));
      });
    }

    // Step 3 Back to Step 2
    const backTo2Btn = document.getElementById("studio-back-to-2-btn");
    if (backTo2Btn) {
      backTo2Btn.addEventListener("click", () => {
        state.studio.step = 2;
        render();
      });
    }

    // Step 3 Transformation test run
    const runTestBtn = document.getElementById("studio-run-test-btn");
    if (runTestBtn) {
      runTestBtn.addEventListener("click", () => {
        if (!state.studio.config) return;
        const row = state.studio.sampleRows[0] || ["TXN001", "150000", "SUCCESS"];
        
        showToast("Testing layout transformation output...");
        
        fetch("/api/v1/mapping/test", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            "mapping": state.studio.config,
            "sampleRow": row
          })
        })
          .then(r => r.json())
          .then(data => {
            state.studio.testOutput = data.output;
            showToast("Transformation test completed.");
            render();
          })
          .catch(err => showToast("Transformation test failed: " + err.message));
      });
    }

    const openReviewCenterBtn = document.getElementById("studio-open-review-center-btn");
    if (openReviewCenterBtn) {
      openReviewCenterBtn.addEventListener("click", () => {
        if (state.studio.reviewItemId) {
          state.selectedReviewPacketId = state.studio.reviewItemId;
        }
        location.hash = "review-center";
      });
    }

    const confirmHandoffBtn = document.getElementById("studio-confirm-handoff-btn");
    if (confirmHandoffBtn) {
      confirmHandoffBtn.addEventListener("click", () => {
        const draftId = state.studio.draftMappingId;
        if (!draftId) {
          showToast("No draft mapping to hand off. Save the draft mapping first.");
          return;
        }
        confirmHandoffBtn.disabled = true;
        confirmHandoffBtn.innerHTML = `<span class="spinner small"></span> Handing off...`;
        fetch(`/api/v1/review-packets/from-mapping/${encodeURIComponent(draftId)}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
        })
          .then(r => r.json().then(body => ({ ok: r.ok, body })))
          .then(({ ok, body }) => {
            confirmHandoffBtn.disabled = false;
            confirmHandoffBtn.innerHTML = "Confirm Ready";
            if (!ok) throw new Error(body.detail || "Handoff failed");
            showToast("Mapping submitted for review.");
            state.studio.handoffConfirmed = false;
            location.hash = "review-center";
          })
          .catch(err => {
            confirmHandoffBtn.disabled = false;
            confirmHandoffBtn.innerHTML = "Confirm Ready";
            showToast(err.message || "Handoff failed");
          });
      });
    }

    // Step 3 Restore Version
    document.querySelectorAll(".studio-restore-version-btn").forEach(el => {
      el.addEventListener("click", () => {
        const vId = el.dataset.id;
        showToast("Restoring schema version...");
        
        fetch(`/api/v1/mapping/version/${encodeURIComponent(vId)}`)
          .then(r => r.json())
          .then(data => {
            state.studio.config = data;
            state.studio.step = 2;
            showToast(`Restored schema version: ${data.configVersion}`);
            render();
          })
          .catch(err => showToast("Restore failed: " + err.message));
      });
    });
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

  function renderPageFilters(options = {}) {
    const { showDate = true, showClear = true, showReconActions = false } = options;
    return `
      <div class="page-filters" style="align-items: center;">
        <div class="filter-group">
          <span class="filter-label">PARTNER</span>
          <div class="filter-input-wrapper">
            <span class="material-symbols-outlined input-icon">store</span>
            <select id="partner-filter">
              ${getPartnerOptions().map(partner => `<option value="${partner}" ${partner === state.partner ? "selected" : ""}>${partner}</option>`).join("")}
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
            <div style="display: flex; align-items: center; gap: 6px;">
              <span class="badge matched" style="padding: 4px 8px; font-size: 11px; font-weight: 600; border-radius: 4px; border: none; background: rgba(16, 185, 129, 0.08); color: rgba(16, 185, 129, 0.8); text-transform: none; display: inline-flex; align-items: center; gap: 4px; height: 26px;">
                <span style="display: inline-block; width: 4px; height: 4px; border-radius: 50%; background: #10b981; opacity: 0.7;"></span>Completed
              </span>
              <span style="font-size: 11px; color: var(--text-muted);">Last run 10:42</span>
            </div>
            <button class="button primary compact" data-action="approve-all-recon" style="padding: 4px 12px; font-size: 12px; display: inline-flex; align-items: center; gap: 4px; height: 32px; border-radius: 6px; background: var(--brand-primary); color: black; font-weight: 600; border: none; cursor: pointer; box-shadow: var(--shadow);">
              <span class="material-symbols-outlined" style="font-size: 15px;">check_circle</span> Approve Run
            </button>
          </div>
        ` : ""}
      </div>
    `;
  }

  function loadingPanel(message) {
    return `
      <section class="panel">
        <div class="loading-row">
          <div class="spinner"></div>
          <div>
            <h2 style="margin: 0;">Loading Workspace</h2>
            <p class="muted" style="margin: 4px 0 0 0;">${message}</p>
          </div>
        </div>
      </section>
    `;
  }

  function fetchJson(path) {
    return fetch(path, { headers: { Accept: "application/json" } }).then(r => {
      if (!r.ok) return r.text().then(t => { throw new Error("HTTP " + r.status + ": " + t.slice(0, 180)); });
      return r.json();
    });
  }

  function executeCopilotAction(actionKey) {
    return fetch(`/api/v1/copilot/actions/${encodeURIComponent(actionKey)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({
        partner: state.partner,
        date: state.date,
        reviewedBy: "Administrator",
      }),
    }).then(r => r.json().then(body => {
      if (!r.ok) throw new Error(body.detail || "Copilot action failed");
      return body;
    }));
  }

  function metrics(items) {
    return `<div class="grid cols-4">${items.map(([label, value, hint]) => `
      <div class="metric compact">
        <span>${label}</span>
        <strong>${value}</strong>
        <small>${hint}</small>
      </div>
    `).join("")}</div>`;
  }

  function table(headers, rows) {
    return `
      <div class="table-wrap">
        <table>
          <thead><tr>${headers.map(h => `<th>${h}</th>`).join("")}</tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    `;
  }

  function badge(value) {
    const text = statusLabel(value);
    const cls = text.toLowerCase().replace(/_/g, "-");
    const raw = String(value || "").toUpperCase();
    const toneMap = {
      "MATCHED": "matched",
      "MATCHED_FAILED": "warning",
      "MATCHED_REVERSED": "processing",
      "AMOUNT_MISMATCH": "critical",
      "STATUS_MISMATCH": "warning",
      "MULTIPLE_MISMATCH": "critical",
      "MISSING_INTERNAL": "warning",
      "MISSING_PARTNER": "critical",
      "UNMAPPED_SKIPPED": "neutral",
      "APPROVED": "matched",
      "PENDING_APPROVAL": "warning",
      "REJECTED": "critical",
      "SUPERSEDED": "processing",
      "PROCESSING": "processing",
      "COMPLETED": "matched",
      "FAILED": "critical",
      "ACTIVE": "matched",
      "NEEDS_REVIEW": "warning",
      "BLOCKED": "critical",
      "NO_ACTIVITY": "neutral",
      "STALE": "warning",
      "ENABLED": "matched",
      "DISABLED": "critical",
      "PAUSED": "warning",
      "PENDING": "warning",
      "HEALTHY": "matched",
      "MONITOR": "warning",
      "LOW": "matched",
      "MEDIUM": "warning",
      "HIGH": "critical"
    };
    const tone = toneMap[raw] || "neutral";
    return `<span class="badge ${tone}">${text}</span>`;
  }

  function statusLabel(value) {
    const raw = String(value || "");
    const labels = {
      MATCHED: "Matched",
      MATCHED_FAILED: "Matched with Failure",
      MATCHED_REVERSED: "Matched and Reversed",
      AMOUNT_MISMATCH: "Amount Mismatch",
      STATUS_MISMATCH: "Status Mismatch",
      MULTIPLE_MISMATCH: "Multiple Mismatch",
      MISSING_INTERNAL: "Missing Internal",
      MISSING_PARTNER: "Missing Partner",
      UNMAPPED_SKIPPED: "Unmapped",
      APPROVED: "Approved",
      PENDING_APPROVAL: "Pending Review",
      REJECTED: "Rejected",
      SUPERSEDED: "Superseded",
      PROCESSING: "Processing",
      COMPLETED: "Completed",
      FAILED: "Failed",
      ACTIVE: "Active",
      NEEDS_REVIEW: "Needs Review",
      BLOCKED: "Blocked",
      NO_ACTIVITY: "No Activity",
      STALE: "Stale",
      ENABLED: "Enabled",
      DISABLED: "Disabled",
      PAUSED: "Paused",
      PENDING: "Pending",
      HEALTHY: "Healthy",
      MONITOR: "Monitor",
      LOW: "Low",
      MEDIUM: "Medium",
      HIGH: "High"
    };
    return labels[raw] || raw.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
  }

  function severityBadge(value) {
    const level = String(value || "medium").toLowerCase();
    const label = level.toUpperCase();
    return `<span class="badge severity-${level}">${label}</span>`;
  }

  function reconciliationRowClass(status) {
    const normalized = String(status || "").toUpperCase();
    if (!normalized || normalized === "MATCHED") return "recon-row-neutral";
    if (normalized.includes("MISSING")) return "recon-row-critical";
    if (normalized.includes("AMOUNT") || normalized.includes("MULTIPLE")) return "recon-row-critical";
    if (normalized.includes("STATUS") || normalized.includes("UNMAPPED")) return "recon-row-warning";
    return "recon-row-warning";
  }

  function bars(items) {
    return `<div class="bars">${items.map(([label, value, tone]) => `
      <div class="bar-row">
        <strong>${label}</strong>
        <div class="bar-track"><div class="bar-fill ${tone || ""}" style="width:${Math.min(100, Number(value) || 0)}%"></div></div>
        <span style="font-weight: 600; text-align: right; display: block;">${Math.round(Number(value) || 0)}%</span>
      </div>
    `).join("")}</div>`;
  }

  function donut(value, label) {
    return `
      <div class="donut" style="--value:${Math.round(value)}">
        <div class="donut-inner">${Math.round(value)}%</div>
      </div>
      <p style="text-align:center; margin-top:14px; font-weight: 600; color: var(--green-primary); letter-spacing: 0.02em;">${label}</p>
    `;
  }

  function percent(value, total) {
    if (!total) return 0;
    return Math.round((value / total) * 1000) / 10;
  }

  function formatNumber(value) {
    return Number(value || 0).toLocaleString("en-US");
  }

  function formatAmount(value) {
    if (value === null || value === undefined || value === "") return "-";
    if (typeof value === "string" && Number.isNaN(Number(value))) return value;
    return formatNumber(value) + " VND";
  }

  function escapeHtml(value) {
    return String(value).replace(/[&<>"']/g, ch => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#039;"
    }[ch]));
  }

  function highlightInsightText(text) {
    if (!text) return "";
    let html = escapeHtml(text);

    // Color severity markers
    html = html.replace(/\[CRITICAL\]/gi, '<span class="badge failed" style="padding: 2px 6px; font-size: 10px; font-weight: 700; margin-right: 4px; background-color: #ef4444; color: white; border-radius: 4px; border: none;">CRITICAL</span>');
    html = html.replace(/\[HIGH\]/gi, '<span class="badge failed" style="padding: 2px 6px; font-size: 10px; font-weight: 700; margin-right: 4px; background-color: #f97316; color: white; border-radius: 4px; border: none;">HIGH</span>');
    html = html.replace(/\[MEDIUM\]/gi, '<span class="badge warning" style="padding: 2px 6px; font-size: 10px; font-weight: 700; margin-right: 4px; background-color: #eab308; color: black; border-radius: 4px; border: none;">MEDIUM</span>');
    html = html.replace(/\[LOW\]/gi, '<span class="badge neutral" style="padding: 2px 6px; font-size: 10px; font-weight: 700; margin-right: 4px; background-color: #6b7280; color: white; border-radius: 4px; border: none;">LOW</span>');

    // Bold transaction IDs
    html = html.replace(/(MOMO_TXN_\w+)/g, '<strong>$1</strong>');
    
    // Bold numbers with currency (VND, đ, USD)
    html = html.replace(/(\b\d{1,3}(,\d{3})+(\.\d+)?\s*(VND|đ|USD)?\b)/gi, '<strong>$1</strong>');

    const boldTerms = [
      "matched", "mismatch", "amount discrepancy", "missing partner", "missing internal", "mismatches", 
      "discrepancy", "anomaly", "anomalies", "recommendation", "wave", "wave1", "wave2", 
      "difference", "delta", "unmatched", "single-source variance",
      "msTotalAmount", "Mapping Studio", "SFTP delivery status", "float mapping", "recalibrate float mapping"
    ];
    
    boldTerms.forEach(term => {
      const regex = new RegExp(`\\b(${term.replace(/[-\/\\^$*+?.()|[\]{}]/g, '\\$&')})\\b`, "gi");
      html = html.replace(regex, "<strong>$1</strong>");
    });

    html = html.replace(/\b(MATCHED)\b/g, '<span class="badge matched" style="padding: 2px 6px; font-size: 10px; font-weight: 600; margin-left: 2px; border: none;">$1</span>');
    html = html.replace(/\b(AMOUNT_MISMATCH|AMOUNT MISMATCH)\b/gi, '<span class="badge failed" style="padding: 2px 6px; font-size: 10px; font-weight: 600; margin-left: 2px; border: none;">$1</span>');
    html = html.replace(/\b(STATUS_MISMATCH|STATUS MISMATCH)\b/gi, '<span class="badge failed" style="padding: 2px 6px; font-size: 10px; font-weight: 600; margin-left: 2px; border: none;">$1</span>');
    html = html.replace(/\b(MISSING_INTERNAL|MISSING INTERNAL)\b/gi, '<span class="badge warning" style="padding: 2px 6px; font-size: 10px; font-weight: 600; margin-left: 2px; border: none;">$1</span>');
    html = html.replace(/\b(MISSING_PARTNER|MISSING PARTNER)\b/gi, '<span class="badge warning" style="padding: 2px 6px; font-size: 10px; font-weight: 600; margin-left: 2px; border: none;">$1</span>');
    
    return html;
  }

  function showToast(message) {
    toast.textContent = message;
    toast.classList.add("show");
    clearTimeout(showToast.timer);
    showToast.timer = setTimeout(() => toast.classList.remove("show"), 2400);
  }

  function loadGuidedReviewAIMapping(packet) {
    if (!packet || !packet.partner) {
      state.guidedReviewAI = {
        loading: false,
        error: "No review item is available for AI mapping.",
        mapping: null,
        packetId: packet?._id || null
      };
      render();
      return;
    }
    if (
      state.guidedReviewAI &&
      state.guidedReviewAI.packetId === packet._id &&
      (state.guidedReviewAI.loading || state.guidedReviewAI.mapping || state.guidedReviewAI.error)
    ) {
      return;
    }
    state.guidedReviewAI = {
      loading: true,
      error: "",
      mapping: null,
      packetId: packet._id
    };
    render();
    fetch(`/api/v1/review-packets/${encodeURIComponent(packet._id)}/generate-ai-mapping`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    })
      .then(r => r.json().then(body => ({ ok: r.ok, body })))
      .then(({ ok, body }) => {
        if (!ok) {
          throw new Error(body.detail || "Failed to generate AI mapping proposal.");
        }
        const mapping = body.mapping || null;
        if (body.draftMappingId) {
          syncLocalReviewPacket(packet._id, {
            draftMappingId: body.draftMappingId,
            draftMappingVersion: body.draftMappingVersion || mapping?.draftMappingVersion || mapping?.configVersion || body.draftMappingId,
            validationGates: Array.isArray(body.validationGates) ? body.validationGates : [],
            parseStrategy: {
              ...(packet.parseStrategy || {}),
              sheetName: mapping?.sheetName || packet?.parseStrategy?.sheetName || "Sheet1",
              startRow: mapping?.startRow || packet?.parseStrategy?.startRow || 2,
              fieldMappingCount: (mapping?.fieldMappings || []).length,
            }
          });
        }
        state.guidedReviewAI = {
          loading: false,
          error: mapping ? "" : "AI draft mapping was not found for this review item.",
          mapping,
          packetId: packet._id
        };
        render();
      })
      .catch(err => {
        state.guidedReviewAI = {
          loading: false,
          error: err.message || "Failed to load AI mapping proposal.",
          mapping: null,
          packetId: packet._id
        };
        render();
      });
  }

  function loadGuidedReviewScopeLLM(packet) {
    if (!packet || !packet._id) return;
    if (state.guidedReviewScope && state.guidedReviewScope.packetId === packet._id && (state.guidedReviewScope.loading || state.guidedReviewScope.data)) {
      return;
    }
    state.guidedReviewScope = {
      loading: true,
      error: "",
      data: null,
      packetId: packet._id
    };
    renderPreserveScroll();
    fetch(`/api/v1/review-packets/${encodeURIComponent(packet._id)}/classify-scope-llm`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    })
      .then(r => r.json().then(body => ({ ok: r.ok, body })))
      .then(({ ok, body }) => {
        if (!ok) {
          throw new Error(body.detail || "Failed to classify scope.");
        }
        state.guidedReviewScope.loading = false;
        state.guidedReviewScope.data = body;
        renderPreserveScroll();
      })
      .catch(err => {
        state.guidedReviewScope.loading = false;
        state.guidedReviewScope.error = err.message || "Failed to load scope classification.";
        renderPreserveScroll();
      });
  }

  function syncLocalReviewPacket(packetId, updates = {}) {
    if (updates.draftMappingId) {
      state.localDraftMappingIds = state.localDraftMappingIds || {};
      state.localDraftMappingIds[packetId] = updates.draftMappingId;
    }
    updateReviewPacketLocally(packetId, currentPacket => {
      if (Object.prototype.hasOwnProperty.call(updates, "draftMappingId")) {
        currentPacket.draftMappingId = updates.draftMappingId;
      }
      if (Object.prototype.hasOwnProperty.call(updates, "draftMappingVersion")) {
        currentPacket.draftMappingVersion = updates.draftMappingVersion;
      }
      if (Object.prototype.hasOwnProperty.call(updates, "validationGates")) {
        currentPacket.validationGates = updates.validationGates || [];
      }
      if (Object.prototype.hasOwnProperty.call(updates, "parseStrategy")) {
        currentPacket.parseStrategy = updates.parseStrategy;
      }
    });
  }

  function updateReviewPacketLocally(packetId, updater) {
    state.reviewPackets = (state.reviewPackets || []).map(packet => {
      if (String(packet._id) !== String(packetId)) return packet;
      const nextPacket = { ...packet };
      updater(nextPacket);
      return nextPacket;
    });
    if (state.reviewCenterCache && state.reviewCenterCache.data && Array.isArray(state.reviewCenterCache.data.packets)) {
      state.reviewCenterCache.data.packets = state.reviewCenterCache.data.packets.map(packet => {
        if (String(packet._id) !== String(packetId)) return packet;
        const nextPacket = { ...packet };
        updater(nextPacket);
        return nextPacket;
      });
    }
  }

  function renderPreserveScroll() {
    const viewport = document.scrollingElement || document.documentElement;
    state.preservedScrollTop = viewport ? viewport.scrollTop : 0;
    render();
  }

  init();
})();
