(function () {
  const state = {
    route: "data-intake",
    partner: "MOMO",
    partnerOptions: ["MOMO", "VNPAY", "ZALOPAY", "ACMEPAY"],
    date: "2026-06-05",
    focus: "operational",
    reconStatus: "",
    explorerFilters: { amountMin: "", amountMax: "", dateFrom: "", dateTo: "" },
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
    utilityRoute: "submit-sample",
    preservedScrollTop: null,
    briefOpen: false
  };

  const routes = [
    ["data-intake", "Data Intake", "inbox"],
    ["review-queue", "Review Queue", "fact_check"],
    ["reconciliation", "Reconciliation", "receipt_long"],
    ["mapping-studio", "Mapping Studio", "schema"],
  ];
  const utilityRoutes = {
    automation: { title: "Automation", icon: "smart_toy" }
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
  }

  async function openPacketInStudio(packetId) {
    const packet = state.reviewPackets.find(item => item._id === packetId);
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
    nav.innerHTML = `${primary}${utility ? `<div class="nav-divider"></div>${utility}` : ""}`;
    
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
    const key = location.hash.replace("#", "") || "data-intake";
    const aliases = {
      overview: "data-intake",
      "command-center": "data-intake",
      intake: "data-intake",
      approvals: "review-queue",
      "submit-sample": "mapping-studio"
    };
    const normalized = aliases[key] || key;
    state.route = (routes.some(([route]) => route === normalized) || utilityRoutes[normalized]) ? normalized : "data-intake";
    
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

  async function render() {
    const renderToken = ++activeRenderToken;
    const routeAtStart = state.route;
    const partnerAtStart = state.partner;
    const dateAtStart = state.date;
    const route = routes.find(([key]) => key === state.route);
    const utility = utilityRoutes[state.route];
    title.textContent = route ? route[1] : utility ? utility.title : "Command Center";
    const routeSubtitle = {
      "data-intake": `Track arrivals, processing state, and runtime readiness for ${state.partner}`,
      "review-queue": `Review pending runtime changes for ${state.partner}`,
      reconciliation: `Deterministic reconciliation outcomes for ${state.partner} on ${formatDisplayDate(state.date)}`,
      "mapping-studio": `Create a draft mapping, validate it, then send it to Review Queue`,
      automation: `Scheduler, job visibility, and automation context`
    };
    subtitle.textContent = routeSubtitle[state.route] || `Operations Console - ${state.partner}`;

    // Smooth tab fade-in transition
    view.classList.remove("fade-in");
    void view.offsetWidth;
    view.classList.add("fade-in");

    if (state.route === "command-center") {
      view.innerHTML = loadingPanel("Loading command center...");
      try {
        const [summary, operational, partner, inconsistency] = await Promise.all([
          fetchJson(`/api/v1/insights/summary?partner=${encodeURIComponent(state.partner)}&date=${encodeURIComponent(state.date)}`),
          fetchJson(`/api/v1/insights/discrepancies?partner=${encodeURIComponent(state.partner)}&date=${encodeURIComponent(state.date)}&focus=operational`),
          fetchJson(`/api/v1/insights/discrepancies?partner=${encodeURIComponent(state.partner)}&date=${encodeURIComponent(state.date)}&focus=partner`),
          fetchJson(`/api/v1/insights/discrepancies?partner=${encodeURIComponent(state.partner)}&date=${encodeURIComponent(state.date)}&focus=inconsistency`),
        ]);
        if (
          renderToken !== activeRenderToken ||
          state.route !== routeAtStart ||
          state.partner !== partnerAtStart ||
          state.date !== dateAtStart
        ) return;
        state.insightsData = { summary, operational, partner, inconsistency };
        view.innerHTML = renderCommandCenter();
      } catch (err) {
        if (renderToken !== activeRenderToken || state.route !== routeAtStart) return;
        view.innerHTML = renderError(err);
      }
      fetchPartners();
      bindFilters();
      bindViewActions();
      return;
    }

    if (state.route === "data-intake") {
      view.innerHTML = loadingPanel("Loading data intake...");
      try {
        const [data, copilot] = await Promise.all([
          fetchJson(`/api/v1/operations/intake?partner=${encodeURIComponent(state.partner)}&date=${encodeURIComponent(state.date)}`),
          fetchJson(`/api/v1/copilot/context?partner=${encodeURIComponent(state.partner)}&date=${encodeURIComponent(state.date)}`)
        ]);
        if (
          renderToken !== activeRenderToken ||
          state.route !== routeAtStart ||
          state.partner !== partnerAtStart ||
          state.date !== dateAtStart
        ) return;
        state.copilotContext = copilot;
        view.innerHTML = renderPartnerIntake(data, copilot);
      } catch (err) {
        if (renderToken !== activeRenderToken || state.route !== routeAtStart) return;
        view.innerHTML = renderError(err);
      }
      fetchPartners();
      bindFilters();
      bindViewActions();
      return;
    }

    if (state.route === "review-queue") {
      view.innerHTML = loadingPanel("Loading review queue...");
      try {
        const [packets, mappings] = await Promise.all([
          fetchJson(`/api/v1/review-packets?partner=${encodeURIComponent(state.partner)}`),
          fetchJson(`/api/v1/mappings?partner=${encodeURIComponent(state.partner)}`)
        ]);
        if (
          renderToken !== activeRenderToken ||
          state.route !== routeAtStart ||
          state.partner !== partnerAtStart
        ) return;
        const data = { packets: packets.packets || [], mappings: mappings.mappings || [] };
        state.reviewPackets = data.packets;
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
      const alreadyOnRecon = !!view.querySelector(".status-tabs");
      if (!alreadyOnRecon) {
        view.innerHTML = loadingPanel("Loading reconciliation results...");
      }
      try {
        let url = `/api/v1/reconciliation/results?partner=${encodeURIComponent(state.partner)}&date=${encodeURIComponent(state.date)}&limit=100`;
        if (state.reconStatus) {
          url += `&status=${encodeURIComponent(state.reconStatus)}`;
        }
        const data = await fetchJson(url);
        if (
          renderToken !== activeRenderToken ||
          state.route !== routeAtStart ||
          state.partner !== partnerAtStart ||
          state.date !== dateAtStart
        ) return;
        view.innerHTML = renderReconciliation(data);
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
      view.innerHTML = renderSubmitSamplePage();
      bindViewActions();
      return;
    }

    if (state.route === "automation") {
      view.innerHTML = loadingPanel("Loading automation visibility...");
      try {
        const data = await fetchJson(`/api/v1/automation/jobs`);
        if (renderToken !== activeRenderToken || state.route !== routeAtStart) return;
        view.innerHTML = renderAutomation(data);
      } catch (err) {
        if (renderToken !== activeRenderToken || state.route !== routeAtStart) return;
        view.innerHTML = renderError(err);
      }
      bindViewActions();
      return;
    }

  }

  function renderPartnerIntake(data, copilot) {
    const partners = data.partners || [];
    const detail = data.detail || {};
    const pendingItems = detail.pendingItems || [];
    const runtime = detail.currentRuntimeConfigSummary || {};
    const latestFile = detail.latestFileSummary || null;
    const header = detail.statusHeader || {};

    const summaryCards = partners.map(item => {
      const stateLabel = item.overallState || "NO_ACTIVITY";
      const latest = item.latestFileSummary;
      return `
        <button class="panel intake-partner-card ${item.partner === state.partner ? "active" : ""}" data-action="select-partner" data-partner="${escapeHtml(item.partner)}">
          <div class="intake-card-top">
            <div>
              <h3>${escapeHtml(item.partner)}</h3>
              <p class="muted">${escapeHtml(item.primaryReason || "No current partner activity")}</p>
            </div>
            ${badge(stateLabel)}
          </div>
          <div class="intake-card-meta">
            ${latest ? `<span class="badge neutral">${escapeHtml(latest.fileName || latest.file_name || "Latest file")}</span>` : ""}
            <span class="badge neutral">Files ${formatNumber(item.fileCount || 0)}</span>
            <span class="badge neutral">Pending changes ${formatNumber(item.pendingProposalCount || 0)}</span>
          </div>
        </button>
      `;
    }).join("");

    const overallState = header.overallState || "";
    const latestFileName = latestFile?.fileName || latestFile?.file_name || null;
    const latestFileFailed = latestFile && String(latestFile.processingStatus || "").toUpperCase() === "FAILED";

    const runtimeLabel = runtime.configVersion ? `Active (${escapeHtml(runtime.configVersion)})` : 'N/A';
    const fileLabel = latestFileFailed ? 'Failed' : (latestFileName ? 'OK' : 'None');
    const reviewLabel = pendingItems.length > 0 ? `${pendingItems.length} waiting` : 'None';

    const copilotStatusText = copilot ? (() => {
      const m = { healthy: "No approval needed", monitor: "Monitor only", needs_review: "Review required", blocked: "Blocked" };
      return m[String(copilot.status || "healthy")] || "No approval needed";
    })() : '';

    return `
      ${renderPageFilters({ showDate: true, showClear: false })}
      <section class="page-section">
        <div class="section-heading">
          <div>
            <p class="eyebrow">Partner Snapshot</p>
            <h2 class="section-title">Which partner stream needs attention</h2>
          </div>
        </div>
        <div class="intake-partner-grid">
          ${summaryCards || `<div class="empty-state">No partner intake data available.</div>`}
        </div>
      </section>

      <div class="intake-dashboard-card">
        <div class="intake-dash-top">
          <h2>${escapeHtml(detail.partner || state.partner)}</h2>
          ${badge(overallState)}
        </div>
        <div class="intake-dash-facts">
          <div class="intake-dash-fact">
            <span class="dash-fact-label">Runtime</span>
            <span class="dash-fact-value ${!runtime.configVersion ? 'muted' : ''}">${runtimeLabel}</span>
          </div>
          <div class="intake-dash-fact${latestFileFailed ? ' fact-failed' : ''}">
            <span class="dash-fact-label">Latest file</span>
            <span class="dash-fact-value">${escapeHtml(fileLabel)}</span>
          </div>
          <div class="intake-dash-fact${pendingItems.length ? ' fact-warn' : ''}">
            <span class="dash-fact-label">Review</span>
            <span class="dash-fact-value">${escapeHtml(reviewLabel)}</span>
          </div>
        </div>
        <div class="intake-dash-copilot">
          <span class="dash-copilot-text">Copilot: ${escapeHtml(copilotStatusText)}</span>
          <button class="button primary" data-action="open-copilot-brief">Open Brief</button>
        </div>
        <div class="intake-dash-utility">
          <input type="file" class="review-upload-input" accept=".xlsx,.xls,.csv" style="display:none;">
          <button class="button-link" data-action="open-review-upload">Upload file</button>
        </div>
      </div>
      ${state.briefOpen ? renderCopilotBrief(copilot, pendingItems) : ''}
    `;
  }

  function renderCopilotSummaryCard(copilot) {
    if (!copilot) return '';

    const rawStatus = String(copilot.status || "healthy");
    const riskLevel = copilot.riskLevel || "low";
    const evidence = copilot.evidence || {};
    const runtime = evidence.runtime || {};
    const latestFile = evidence.latestFile || null;
    const proposal = evidence.proposal || {};

    const verdictMap = {
      healthy: "No approval needed",
      monitor: "Monitor only",
      needs_review: "Review required before approving",
      blocked: "Blocked until mapping is fixed"
    };
    const verdict = verdictMap[rawStatus] || verdictMap.healthy;

    const parts = [];
    if (runtime.version) parts.push("Runtime active");
    if (latestFile && String(latestFile.status || "").toLowerCase() === "failed") parts.push("Latest file failed");
    if (proposal.state && proposal.state !== "none") parts.push("1 review item");

    return `
      <aside class="copilot-summary-card">
        <div class="copilot-summary-top">
          <span class="copilot-summary-eyebrow">COPILOT BRIEF</span>
          ${severityBadge(riskLevel)}
        </div>
        <div class="copilot-summary-verdict verdict-${escapeHtml(rawStatus)}">${escapeHtml(verdict)}</div>
        <div class="copilot-summary-condensed">${parts.length ? escapeHtml(parts.join(' · ')) : 'No issues detected'}</div>
        <button class="button primary copilot-summary-cta" data-action="open-copilot-brief">Open full brief</button>
      </aside>
    `;
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

    const runtimeVersion = runtime.version || null;
    const runtimeActive = runtime.state === "approved";
    const latestFileName = latestFile?.name || null;
    const latestFileFailed = latestFile && String(latestFile.status || "").toLowerCase() === "failed";
    const hasProposal = proposal.state && proposal.state !== "none";
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
    const decisionKeys = ["approve_activate_next_runtime", "approve_keep_current", "reject_proposal"];
    const actionLabel = (key) => ({ review_proposal: "Open Review Queue", approve_activate_next_runtime: "Approve & activate", approve_keep_current: "Keep current runtime", reject_proposal: "Reject change", open_mapping_details: "View mapping", refresh_context: "Refresh" })[key] || key.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
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
        <button class="button-link" data-action="go-review-queue">Open full Review Queue</button>
      </div>
      ${hasProposal ? `
      <div class="brief-decision-actions">
        <p class="brief-decision-hint">Decide on the proposed change:</p>
        <div class="brief-decision-buttons">
          ${secondaryActions.filter(a => decisionKeys.includes(a.key)).map(a => `
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
        </div>
      </div>`;
  }

  function renderApprovals(data) {
    const packets = (data.packets || []).filter(packet => !state.partner || packet.partner === state.partner);
    const mappings = (data.mappings || []).filter(item => item.partner === state.partner);
    const pendingPackets = packets.filter(item => String(item.status || "").toUpperCase() === "PENDING");
    
    // Synthesize pending mapping configurations as virtual packets
    const pendingMappings = mappings.filter(item => item.status === "PENDING_APPROVAL" && !pendingPackets.some(p => p.draftMappingId === item._id));
    const virtualPackets = pendingMappings.map(m => ({
      _id: m._id,
      partner: m.partner,
      fileName: m.sheetName || "Manual Configuration",
      fileTypeDetected: m.fileType || "SETTLEMENT",
      status: "PENDING",
      draftMappingId: m._id,
      recommendedAction: { actionType: "APPROVE_REQUIRED_BEFORE_RUNTIME", reason: m.configHealth?.reasoning || "Pending mapping review." },
      parseStrategy: { sheetName: m.sheetName, startRow: m.startRow, fieldMappingCount: (m.fieldMappings || []).length },
      validationGates: [],
      samplePreview: [],
      riskSummary: { severity: "medium" },
      createdAt: m.createdAt,
      isVirtual: true
    }));

    const allPending = [...pendingPackets, ...virtualPackets];

    const recentDecisions = packets
      .filter(item => ["APPROVED", "REJECTED", "SUPERSEDED"].includes(String(item.status || "").toUpperCase()))
      .slice(0, 8);
    const approvedConfigs = mappings.filter(item => item.status === "APPROVED").length;
    const selectedPacket = allPending.find(packet => packet._id === state.selectedReviewPacketId) || allPending[0] || null;
    const summary = [
      ["Pending Reviews", formatNumber(allPending.length), allPending.length ? "Items waiting for reviewer action" : "Queue is clear"],
      ["Approved Configs", formatNumber(approvedConfigs), "Runtime continues on approved config"],
      ["Closed Decisions", formatNumber(recentDecisions.length), "Recent reviewer outcomes"],
      ["Current Focus", state.partner, "Filtered partner review workspace"]
    ];

    const needsReview = allPending.length ? allPending.map(packet => {
      const fieldCount = Number(packet.parseStrategy?.fieldMappingCount || 0);
      const gateSummary = (packet.validationGates || []).reduce((acc, gate) => {
        const status = String(gate.status || "").toLowerCase();
        acc[status] = (acc[status] || 0) + 1;
        return acc;
      }, {});
      return `
        <article class="review-card ${selectedPacket && selectedPacket._id === packet._id ? "active" : ""}" data-action="select-review-packet" data-packet-id="${escapeHtml(packet._id)}">
          <div class="review-card-top">
            <div>
              <p class="eyebrow">Review Readiness</p>
              <h3>${escapeHtml(packet.partner || "-")}</h3>
            </div>
            ${severityBadge(packet.riskSummary?.severity || "medium")}
          </div>
          <p class="review-reason">${escapeHtml(packet.recommendedAction?.reason || "Awaiting reviewer decision.")}</p>
          <div class="review-meta-row">
            <span class="badge neutral">${escapeHtml(packet.sourceType || "UPLOAD")}</span>
            <span class="badge neutral">${escapeHtml(packet.fileName || "-")}</span>
            <span class="badge neutral">${escapeHtml(packet.fileTypeDetected || "-")}</span>
            ${fieldCount ? `<span class="badge neutral">${fieldCount} mapped fields</span>` : ""}
          </div>
          <div class="review-impact-box">
            <strong>Gates</strong>
            <p>${formatNumber(gateSummary.pass || 0)} pass · ${formatNumber(gateSummary.warn || 0)} warn · ${formatNumber(gateSummary.fail || 0)} fail</p>
          </div>
        </article>
      `;
    }).join("") : `
      <section class="panel">
        <div class="empty-state actionable">
          <span class="material-symbols-outlined">task_alt</span>
          <h3>No reviews waiting</h3>
          <p class="muted">The review queue is clear for ${state.partner}. New format changes will appear here.</p>
          <button class="button" data-action="go-mapping-studio">Create Draft</button>
        </div>
      </section>
    `;

    const runtimeGate = selectedPacket
      ? (selectedPacket.validationGates || []).find(gate => gate.gateKey === "runtime_validation")
      : null;
    const runtimeGateStatus = String(runtimeGate?.status || "").toLowerCase();
    const runtimeVerified = runtimeGateStatus === "pass";
    const runtimeGateTone = runtimeVerified ? "matched" : runtimeGateStatus === "fail" ? "critical" : runtimeGateStatus === "warn" ? "warning" : "neutral";
    const runtimeGateLabel = "Validate";

    const drawerGates = selectedPacket ? (selectedPacket.validationGates || [])
      .filter(gate => gate.gateKey !== "runtime_safety")
      .map(gate => `
      <div class="gate-row ${escapeHtml(String(gate.status || "").toLowerCase())}">
        <div>
          <strong>${escapeHtml(gate.label || "-")}</strong>
          <div class="muted">${escapeHtml(gate.reason || "-")}</div>
          ${gate.details?.failedExamples?.length ? `<div class="muted" style="margin-top: 4px;">Example: row ${escapeHtml(String(gate.details.failedExamples[0].row || "-"))} · ${escapeHtml(gate.details.failedExamples[0].field || "-")} · ${escapeHtml(gate.details.failedExamples[0].reason || "-")}</div>` : ""}
          ${gate.gateKey === "runtime_validation" && gate.details ? `<div class="muted" style="margin-top: 4px;">${formatNumber(gate.details.successRows || 0)}/${formatNumber(gate.details.sampledRows || 0)} sampled rows passed</div>` : ""}
        </div>
        <div style="display:flex; align-items:center; gap:8px;">
          ${gate.gateKey === "runtime_validation" ? `
            <button class="button ${runtimeVerified ? "secondary-action" : "primary"}" data-action="validate-runtime-packet" data-packet-id="${escapeHtml(selectedPacket._id)}" style="justify-content:center; min-width: 148px;">
              ${runtimeGateLabel}
            </button>
          ` : ""}
          <span class="badge ${String(gate.status || "").toLowerCase() === "fail" ? "critical" : String(gate.status || "").toLowerCase() === "warn" ? "warning" : "matched"}">${escapeHtml(gate.status || "-")}</span>
        </div>
      </div>
    `).join("") : "";

    const runtimeGateMissing = selectedPacket && !runtimeGate ? `
      <div class="gate-row neutral">
        <div>
          <strong>Runtime validation</strong>
          <div class="muted">No executable validation has been run on this packet yet.</div>
        </div>
        <div style="display:flex; align-items:center; gap:8px;">
          <button class="button primary" data-action="validate-runtime-packet" data-packet-id="${escapeHtml(selectedPacket._id)}" style="justify-content:center; min-width: 148px;">
            Validate
          </button>
          <span class="badge neutral">required</span>
        </div>
      </div>
    ` : "";
    
    const proposalConfig = selectedPacket ? (data.mappings || []).find(m => String(m._id) === String(selectedPacket.draftMappingId)) : null;
    let proposalMappingsHtml = "";
    if (proposalConfig && proposalConfig.fieldMappings && proposalConfig.fieldMappings.length) {
      const rows = proposalConfig.fieldMappings.map(fm => {
        let colDetail = fm.column || "-";
        if (fm.sourceField) {
          colDetail += ` (<code>${escapeHtml(fm.sourceField)}</code>)`;
        }
        let normDetail = "-";
        if (fm.constant) {
          normDetail = `Constant: <code>${escapeHtml(fm.constant)}</code>`;
        } else if (fm.mapping) {
          normDetail = `Mapped: <pre style="margin:2px 0; font-size:10px; background: rgba(0,0,0,0.2); padding: 4px; border-radius: 4px;">${escapeHtml(JSON.stringify(fm.mapping, null, 2))}</pre>`;
        }
        return `
          <tr>
            <td style="padding: 8px 12px; font-size: 13px;"><strong>${escapeHtml(fm.path)}</strong></td>
            <td style="padding: 8px 12px; font-size: 13px;">${escapeHtml(String(colDetail))}</td>
            <td style="padding: 8px 12px; font-size: 13px;"><span class="badge neutral">${escapeHtml(fm.type)}</span></td>
            <td style="padding: 8px 12px; font-size: 13px;">${normDetail}</td>
          </tr>
        `;
      }).join("");
      proposalMappingsHtml = `
        <div class="table-wrap" style="margin-top: 10px; border-color: rgba(255,255,255,0.08);">
          <table style="width: 100%; border-collapse: collapse;">
            <thead>
              <tr style="background: rgba(255,255,255,0.02);">
                <th style="padding: 8px 12px; font-size: 11px;">Field Path</th>
                <th style="padding: 8px 12px; font-size: 11px;">Col / Header</th>
                <th style="padding: 8px 12px; font-size: 11px;">Type</th>
                <th style="padding: 8px 12px; font-size: 11px;">Rule / Value</th>
              </tr>
            </thead>
            <tbody>
              ${rows}
            </tbody>
          </table>
        </div>
      `;
    } else {
      proposalMappingsHtml = `<div class="muted" style="padding: 10px 0;">No draft mapping details available.</div>`;
    }

    let previewTableHtml = "";
    if (selectedPacket && selectedPacket.samplePreview && selectedPacket.samplePreview.length) {
      const maxCols = Math.max(...selectedPacket.samplePreview.map(row => (row.values || []).length));
      const headers = Array.from({ length: maxCols }, (_, idx) => {
        let letter = "";
        let i = idx;
        while (i >= 0) {
          letter = String.fromCharCode((i % 26) + 65) + letter;
          i = Math.floor(i / 26) - 1;
        }
        const sigHeaders = selectedPacket.structureSignature?.headers || [];
        if (sigHeaders[idx]) {
          return sigHeaders[idx];
        }
        if (proposalConfig && proposalConfig.fieldMappings) {
          const fm = proposalConfig.fieldMappings.find(f => {
            if (typeof f.column === "number" && f.column === idx + 1) return true;
            if (typeof f.column === "string" && f.column === letter) return true;
            return false;
          });
          if (fm && fm.sourceField) {
            return fm.sourceField;
          }
        }
        return letter;
      });
      const headerRow = `<tr><th style="padding: 8px 12px; font-size: 11px;">Row</th>${headers.map(h => `<th style="padding: 8px 12px; font-size: 11px; white-space: nowrap;">${h}</th>`).join("")}</tr>`;
      const bodyRows = selectedPacket.samplePreview.map(row => {
        const cells = (row.values || []).map(val => `<td style="padding: 8px 12px; font-size: 12px; white-space: nowrap;">${escapeHtml(String(val !== null ? val : ""))}</td>`).join("");
        return `<tr><td style="padding: 8px 12px; font-size: 12px;"><strong>${row.rowIndex}</strong></td>${cells}</tr>`;
      }).join("");
      previewTableHtml = `
        <div class="table-wrap" style="margin-top: 10px; max-height: 250px; overflow: auto; border-color: rgba(255,255,255,0.08);">
          <table style="width: 100%; border-collapse: collapse;">
            <thead>
              <tr style="background: rgba(255,255,255,0.02);">${headerRow}</tr>
            </thead>
            <tbody>
              ${bodyRows}
            </tbody>
          </table>
        </div>
      `;
    } else {
      previewTableHtml = `<div class="muted" style="padding: 10px 0;">No preview rows available.</div>`;
    }

    // Render Scope section
    let scopeSectionHtml = "";
    if (selectedPacket) {
      const scopeType = selectedPacket.scopeType || "UNCONFIRMED";
      const confidence = typeof selectedPacket.scopeConfidence === "number" ? `${(selectedPacket.scopeConfidence * 100).toFixed(0)}%` : "N/A";
      const reasons = selectedPacket.scopeReason || [];
      const signals = selectedPacket.scopeSignals || {};

      if (!state.overrideScopes) {
        state.overrideScopes = {};
      }
      const activeScope = state.overrideScopes[selectedPacket._id] || scopeType;

      const signalsHtml = (signals && Object.keys(signals).length)
        ? `<div class="scope-signals" style="font-size: 11px; background: rgba(0, 0, 0, 0.2); padding: 8px; border-radius: 4px; margin-top: 6px; border: 1px solid rgba(255,255,255,0.05);">
            <strong class="muted" style="display:block; margin-bottom: 4px; font-size: 10px; text-transform: uppercase; letter-spacing: 0.5px;">Signals</strong>
            ${Object.entries(signals).map(([key, val]) => `
              <div style="display:flex; justify-content:space-between; margin-bottom: 2px;">
                <span class="muted" style="margin-right: 8px;">${escapeHtml(key)}:</span>
                <span style="font-family: monospace; word-break: break-all; text-align: right;">${escapeHtml(typeof val === 'object' ? JSON.stringify(val) : String(val))}</span>
              </div>
            `).join("")}
          </div>`
        : "";

      const reasonList = (reasons && reasons.length)
        ? `<ul style="margin: 4px 0 0 16px; padding: 0; font-size: 12px; color: var(--text-muted);">
            ${reasons.map(r => `<li>${escapeHtml(r)}</li>`).join("")}
          </ul>`
        : `<p class="muted" style="margin: 4px 0 0 0; font-size: 12px; font-style: italic;">No specific reasons provided.</p>`;

      scopeSectionHtml = `
        <section class="drawer-section">
          <h4>Reconciliation Scope</h4>
          <p class="section-subtitle" style="font-size: 12px; margin: 4px 0 8px; color: var(--text-muted);">
            Define the boundaries of data matching for this file to ensure proper reconciliation flow.
          </p>
          <div class="scope-info-box" style="background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.06); border-radius: 6px; padding: 12px; margin-bottom: 12px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
              <span style="font-size: 12px;" class="muted">Suggested scope:</span>
              <span class="badge ${scopeType === 'UNCONFIRMED' ? 'neutral' : 'matched'}" style="font-weight: 600; font-size: 11px;">
                ${escapeHtml(scopeType)}
              </span>
            </div>
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
              <span style="font-size: 12px;" class="muted">Confidence Score:</span>
              <span style="font-size: 12px; font-weight: 600; color: ${typeof selectedPacket.scopeConfidence === 'number' && selectedPacket.scopeConfidence >= 0.8 ? '#4caf50' : typeof selectedPacket.scopeConfidence === 'number' && selectedPacket.scopeConfidence >= 0.5 ? '#ff9800' : 'var(--text-muted)'};">
                ${confidence}
              </span>
            </div>
            <div style="margin-top: 8px;">
              <span style="font-size: 12px; display: block;" class="muted">Why this scope:</span>
              ${reasonList}
            </div>
            ${signalsHtml}
          </div>

          <div style="margin-top: 10px;">
            <label for="scope-override-select" style="font-size: 12px; font-weight: 500; display: block; margin-bottom: 6px;" class="muted">
              Confirm scope or override:
            </label>
            <select id="scope-override-select" class="input-select" data-packet-id="${escapeHtml(selectedPacket._id)}" style="width: 100%; font-size: 12px; padding: 8px; border-radius: 4px; background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.12); color: var(--text);">
              <option value="UNCONFIRMED" ${activeScope === 'UNCONFIRMED' ? 'selected' : ''}>UNCONFIRMED (Review required)</option>
              <option value="FULL_SNAPSHOT" ${activeScope === 'FULL_SNAPSHOT' ? 'selected' : ''}>FULL_SNAPSHOT (Complete database snapshot)</option>
              <option value="INCREMENTAL_APPEND" ${activeScope === 'INCREMENTAL_APPEND' ? 'selected' : ''}>INCREMENTAL_APPEND (Add new records only)</option>
              <option value="REPLACEMENT" ${activeScope === 'REPLACEMENT' ? 'selected' : ''}>REPLACEMENT (Replace matching period data)</option>
            </select>
          </div>
        </section>
      `;
    }

    const drawer = selectedPacket ? `
      <aside class="review-drawer">
        <div class="review-drawer-header">
          <div>
            <p class="eyebrow">Review Item</p>
            <h3>${escapeHtml(selectedPacket.fileName || "-")}</h3>
            <p class="muted">${escapeHtml(selectedPacket.partner || "-")} · ${escapeHtml(selectedPacket.fileTypeDetected || "-")}</p>
          </div>
          ${severityBadge(selectedPacket.riskSummary?.severity || "medium")}
        </div>

        <section class="drawer-section">
          <h4>Current Context</h4>
          <div class="drawer-meta-grid">
            <div><span class="muted">Active runtime</span><strong>${selectedPacket.activeRuntimeConfigId ? "Available" : "No approved config"}</strong></div>
            <div><span class="muted">Draft mapping</span><strong>${selectedPacket.draftMappingId ? "Ready for review" : "-"}</strong></div>
            <div><span class="muted">Recommended next step</span><strong>${escapeHtml(selectedPacket.recommendedAction?.reason || "-")}</strong></div>
            <div><span class="muted">Runtime behavior</span><strong>${selectedPacket.runtimeDecisionHint === "KEEP_CURRENT_RUNTIME_UNTIL_APPROVED" ? "Keep current runtime until approved" : selectedPacket.runtimeDecisionHint === "BLOCK_UNTIL_APPROVED" ? "Block until approved" : "-"}</strong></div>
          </div>
        </section>

        <section class="drawer-section">
          <h4>Draft Mapping Preview</h4>
          <p class="section-subtitle" style="font-size: 12px; margin: 4px 0 8px; color: var(--text-muted);">This draft mapping shows how the file columns would be interpreted.</p>
          ${proposalMappingsHtml}
        </section>

        <section class="drawer-section">
          <h4>Sample Preview Grid</h4>
          <p class="section-subtitle" style="font-size: 12px; margin: 4px 0 8px; color: var(--text-muted);">Direct columns and row cells parsed from the dropped partner file.</p>
          ${previewTableHtml}
        </section>

        <section class="drawer-section">
          <h4>Validation Gates</h4>
          <p class="section-subtitle" style="font-size: 12px; margin: 4px 0 8px; color: var(--text-muted);">Automated verification rules checking the file structure and integrity. Failed gates block automatic ingestion.</p>
          <div class="gate-list">${drawerGates || runtimeGateMissing ? `${drawerGates}${runtimeGateMissing || ""}` : `<div class="muted">No gates available.</div>`}</div>
        </section>

        ${scopeSectionHtml}

        <section class="drawer-section">
          <h4>Decision</h4>
          <p class="section-subtitle" style="font-size: 12px; margin: 4px 0 8px; color: var(--text-muted);">Choose how to handle this runtime change.</p>
          <div class="review-actions" style="display: flex; flex-direction: column; gap: 8px;">
            <button class="button primary" data-action="approve-packet-activate" data-packet-id="${escapeHtml(selectedPacket._id)}" style="width: 100%; justify-content: center;">
              Approve and activate for future files
            </button>
            <div style="display: flex; gap: 8px; width: 100%;">
              <button class="button secondary-action" data-action="approve-packet-keep-current" data-packet-id="${escapeHtml(selectedPacket._id)}" style="flex: 1; justify-content: center; font-size: 12px; padding: 0 8px;">
                Keep current runtime
              </button>
              <button class="button secondary-action" data-action="reject-packet" data-packet-id="${escapeHtml(selectedPacket._id)}" style="flex: 1; justify-content: center; font-size: 12px; padding: 0 8px;">
                Reject change
              </button>
            </div>
            <button class="button tertiary-action" data-action="send-packet-to-studio" data-packet-id="${escapeHtml(selectedPacket._id)}" style="width: 100%; justify-content: center; margin-top: 4px;">
              <span class="material-symbols-outlined" style="font-size: 18px; margin-right: 4px;">edit</span> Adjust in Mapping Studio
            </button>
          </div>
        </section>
      </aside>
    ` : `
      <aside class="review-drawer empty">
        <div class="empty-state actionable">
          <span class="material-symbols-outlined">fact_check</span>
          <h3>Select a review item</h3>
          <p class="muted">Choose an item to inspect context, validation checks, draft mapping, and reviewer actions.</p>
        </div>
      </aside>
    `;

    const decisionRows = recentDecisions.length ? recentDecisions.map(item => `
      <tr>
        <td><strong>${escapeHtml(item.fileName || "-")}</strong></td>
        <td>${badge(item.status || "-")}</td>
        <td>${escapeHtml(item.decisionMode || "-")}</td>
        <td>${escapeHtml(item.parseStrategy?.strategy || "-")}</td>
        <td>${escapeHtml(formatDisplayDateTime(item.reviewedAt || item.createdAt || "-"))}</td>
      </tr>
    `).join("") : `<tr><td colspan="5" style="text-align:center; padding: 24px 0;">No recent packet decisions for this partner.</td></tr>`;

    return `
      ${metrics(summary)}
      ${renderPageFilters({ showDate: false, showClear: false })}
      <section class="page-section">
        <div class="section-heading">
          <div>
            <p class="eyebrow">Review Actions</p>
            <h2 class="section-title">Approval desk with full context</h2>
          </div>
        </div>
        ${renderApprovalUploadEntry("Upload a new sample or incoming file. The system will analyze the format, generate a draft mapping, and open the approval drawer if review is required.")}
        <div class="approval-desk-layout">
          <div class="review-card-grid">
            ${needsReview}
          </div>
          ${drawer}
        </div>
      </section>
      <section class="panel">
        <div class="panel-header" style="margin-bottom: 16px;">
          <div>
            <h2 style="margin: 0;">Recent Decisions</h2>
            <p class="section-subtitle">Recent reviewer outcomes with decision mode and runtime context.</p>
          </div>
        </div>
        ${table(["File", "Decision", "Decision Mode", "Parse Strategy", "Reviewed At"], decisionRows)}
      </section>
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
        ["Priority Actions", formatNumber(anomalyCount), anomalyCount ? "Start with review queue and mismatches" : "No immediate blockers detected"],
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
            <p class="muted">Severity stays above metadata. Use this to decide whether the next stop is Review Queue, Data Intake, or Reconciliation.</p>
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
    const resolutionPlaybook = {
      "AMOUNT_MISMATCH": {
        title: "Inspect amount transformation",
        detail: "Compare partner amount, internal amount, and fee logic. If the mapping changed, create a new draft in Mapping Studio.",
        cta: "Open Mapping Studio",
        action: "go-mapping-studio"
      },
      "STATUS_MISMATCH": {
        title: "Check lifecycle mapping",
        detail: "Review terminal-state translation and approval rules. If the config is wrong, submit an updated draft mapping.",
        cta: "Open Mapping Studio",
        action: "go-mapping-studio"
      },
      "MISSING_INTERNAL": {
        title: "Retry intake path",
        detail: "Verify whether the file landed and whether ingestion was blocked. Continue in Data Intake to inspect partner arrival and runtime status.",
        cta: "Go To Data Intake",
        action: "go-data-intake"
      },
      "MISSING_PARTNER": {
        title: "Confirm partner delivery",
        detail: "Check whether the partner delivery is late or incomplete. Use Data Intake to confirm latest files before escalating externally.",
        cta: "Go To Data Intake",
        action: "go-data-intake"
      },
      "UNMAPPED_SKIPPED": {
        title: "Create reviewable draft",
        detail: "These rows were skipped because the format is not mapped yet. Build a draft mapping, validate it, then send it to Review Queue.",
        cta: "Open Mapping Studio",
        action: "go-mapping-studio"
      },
      "DEFAULT": {
        title: "Review mismatch then route work",
        detail: "Use the selected mismatch class to choose the correct next step: intake, review, or mapping update.",
        cta: "Open Review Queue",
        action: "go-review-queue"
      }
    };
    const statusTabs = [
      ["", "All"],
      ["MATCHED", "Matched"],
      ["AMOUNT_MISMATCH", "Amount Mismatch"],
      ["STATUS_MISMATCH", "Status Mismatch"],
      ["MISSING_INTERNAL", "Missing Internal"],
      ["MISSING_PARTNER", "Missing Partner"],
      ["UNMAPPED_SKIPPED", "Unmapped"]
    ].map(([value, label]) => `
      <button class="status-tab ${state.reconStatus === value ? "active" : ""}" data-action="set-recon-status" data-status="${escapeHtml(value)}">
        ${escapeHtml(label)}
      </button>
    `).join("");

    const totalAmountDiff = items.reduce((sum, item) => {
      const partnerAmount = Number(item.partnerAmount || 0);
      const internalAmount = Number(item.internalAmount || 0);
      return sum + Math.abs(partnerAmount - internalAmount);
    }, 0);
    const mismatchRows = items.filter(item => String(item.reconciliationStatus || "") !== "MATCHED").length;
    const missingRows = items.filter(item => /MISSING_/.test(String(item.reconciliationStatus || ""))).length;

    const summaryCards = metrics([
      ["Visible Rows", formatNumber(data.total || items.length), state.reconStatus ? `Filtered by ${state.reconStatus}` : "Current result set"],
      ["Matched", formatNumber(items.filter(item => item.reconciliationStatus === "MATCHED").length), `${formatNumber(mismatchRows)} mismatches visible`],
      ["Missing Records", formatNumber(missingRows), "Internal or partner side is absent"],
      ["Amount Delta", formatAmount(totalAmountDiff), "Absolute difference across visible rows"]
    ]);
    const selectedGuide = resolutionPlaybook[state.reconStatus || ""] || resolutionPlaybook.DEFAULT;

    if (!items.length) {
      return `
        ${renderPageFilters({ showDate: true, showClear: false })}
        <section class="panel">
          <div class="panel-header with-icon">
            <div>
              <h2 class="section-title">Mismatch Status Tabs</h2>
              <p class="section-subtitle">Switch between matched and mismatch categories.</p>
            </div>
            <span class="material-symbols-outlined panel-header-icon">filter_alt</span>
          </div>
          <div class="status-tabs">${statusTabs}</div>
        </section>
        <section class="panel">
          <div class="empty-state actionable">
            <span class="material-symbols-outlined">info</span>
            <h3>No Reconciliation Results</h3>
            <p class="muted">No records matched the filter status for ${state.partner} / ${formatDisplayDate(state.date)}.</p>
            <button class="button" data-action="reset-recon-status">Show all statuses</button>
          </div>
        </section>
      `;
    }
    const headers = ["Partner TXN ID", "Internal TXN ID", "Partner Amount", "Internal Amount", "Partner Status", "Internal Status", "Reconciliation Status"];
    const rows = items.map(item => `
      <tr class="${reconciliationRowClass(item.reconciliationStatus)}">
        <td><code>${escapeHtml(item.partnerTxnId || "-")}</code></td>
        <td><code>${escapeHtml(item.internalTxnId || "-")}</code></td>
        <td style="font-variant-numeric: tabular-nums;">${formatAmount(item.partnerAmount)}</td>
        <td style="font-variant-numeric: tabular-nums;">${formatAmount(item.internalAmount)}</td>
        <td>${escapeHtml(item.partnerStatus || "-")}</td>
        <td>${escapeHtml(item.internalStatus || "-")}</td>
        <td>${badge(item.reconciliationStatus)}</td>
      </tr>
    `).join("");
    return `
        ${renderPageFilters({ showDate: true, showClear: false })}
      ${summaryCards}
      <section class="panel">
        <div class="panel-header with-icon">
          <div>
            <h2 class="section-title">Mismatch Status Tabs</h2>
            <p class="section-subtitle">Use tabs to isolate the mismatch category you want to resolve.</p>
          </div>
          <span class="material-symbols-outlined panel-header-icon">tune</span>
        </div>
        <div class="status-tabs">${statusTabs}</div>
      </section>
      <section class="panel">
        <div class="panel-header with-icon">
          <div>
            <h2 class="section-title">Ledger Detail Table</h2>
            <p class="section-subtitle">${formatNumber(data.total || items.length)} transactions in the current result set.</p>
          </div>
          <span class="material-symbols-outlined panel-header-icon">receipt_long</span>
        </div>
        ${table(headers, rows)}
      </section>
    `;
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
        <section class="panel review-queue-panel">
          <div class="review-queue-header">
            <div>
              <div class="review-queue-title-row">
                <h3>Review Item: ${escapeHtml(statusLabel(action.type || "UNKNOWN"))}</h3>
                ${badge(action.status || "PENDING_APPROVAL")}
              </div>
              <p class="muted review-queue-reason">${escapeHtml(action.reason || "Awaiting operator review.")}</p>
            </div>
            <div class="review-queue-actions">
              ${draftMappingId ? `<button class="button" data-action="approve-config" data-config-id="${escapeHtml(draftMappingId)}">Approve Draft</button>` : ""}
              ${draftMappingId ? `<button class="button secondary-action" data-action="reject-config" data-config-id="${escapeHtml(draftMappingId)}">Reject Draft</button>` : ""}
            </div>
          </div>
          <div class="review-queue-meta">
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
            <h2 style="margin: 0;">Review Queue</h2>
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
          <h2 style="margin: 0;">Review Queue</h2>
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
          <p class="muted" style="margin-bottom: 24px;">Upload a partner sample, review the draft mapping, then send it to the review queue.</p>`}
          
          ${stepsHeader}

          <div class="grid cols-3 studio-validation-grid">
            <!-- Option A: Upload Spreadsheet -->
            <div class="option-card" style="border: 1px dashed var(--border); border-radius: 8px; padding: 24px; text-align: center; background: rgba(240, 185, 11, 0.02); display: flex; flex-direction: column; justify-content: space-between; transition: var(--transition-smooth);">
              <div>
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
              </div>
              <div>
                <input type="file" id="studio-excel-upload" accept=".xlsx,.xls,.csv" style="display: none;">
                <button class="button primary" style="width: 100%;" onclick="document.getElementById('studio-excel-upload').click()">
                  <span class="material-symbols-outlined" style="font-size:18px;">upload</span> Generate Draft
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
      const fieldMappings = s.config?.fieldMappings || [];
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
          <p class="muted" style="margin-bottom: 20px;">Inspect the detected file structure and adjust the draft before it moves through the review queue.</p>
          
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
              <button class="button button-ghost" id="studio-add-field-btn">+ Add Mapping Row</button>
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
          <p class="muted" style="margin-bottom: 20px;">Resolve blocking issues, inspect warnings, test the transformed output, and then hand the draft to the review queue.</p>
          ${s.draftMappingId ? `
            <div class="panel" style="margin-bottom: 20px; padding: 12px 16px; display: flex; align-items: center; gap: 16px; background: rgba(59, 130, 246, 0.05); border: 1px solid rgba(59, 130, 246, 0.18); border-radius: 6px; flex-wrap: wrap;">
              <span class="material-symbols-outlined" style="color: var(--brand-accent-blue);">fact_check</span>
              <div style="font-size: 13px; color: var(--text-primary); flex-grow: 1;">
                This draft requires review queue action before activation.
              </div>
              <div style="display: flex; gap: 8px; align-items: center; margin-left: auto;">
                ${badge(s.configStatus || "PENDING_APPROVAL")}
                <button class="button ${s.handoffConfirmed ? "secondary-action" : "primary"}" id="studio-confirm-handoff-btn" style="height: 32px; padding: 0 12px; font-size: 12px;">
                  ${s.handoffConfirmed ? "Handoff Confirmed" : "Confirm Ready"}
                </button>
                <button class="button" id="studio-open-review-queue-btn" style="height: 32px; padding: 0 12px; font-size: 12px;">
                  Open Review Queue
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
                location.hash = "review-queue";
                return;
              }
              if (target.type === "review_queue") {
                showToast("Opening Review Queue.");
                location.hash = "review-queue";
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
          render();
          return;
        }
        if (action === "go-approvals" || action === "go-review-queue") {
          const partner = el.dataset.partner;
          if (partner) state.partner = partner;
          location.hash = "review-queue";
          return;
        }
        if (action === "go-review-packet") {
          const packetId = el.dataset.packetId;
          const partner = el.dataset.partner;
          if (partner) state.partner = partner;
          if (packetId) state.selectedReviewPacketId = packetId;
          location.hash = "review-queue";
          return;
        }
        if (action === "open-review-upload") {
          const uploadInput = el.parentElement?.querySelector(".review-upload-input")
            || el.closest(".panel")?.querySelector(".review-upload-input")
            || document.querySelector(".review-upload-input");
          uploadInput?.click();
          return;
        }
        if (action === "go-submit-sample" || action === "go-mapping-studio") {
          const partner = el.dataset.partner;
          if (partner) state.partner = partner;
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
        if (action === "go-data-intake") {
          const partner = el.dataset.partner;
          if (partner) state.partner = partner;
          location.hash = "data-intake";
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
          el.disabled = true;
          el.style.opacity = "0.65";
          el.innerHTML = `<span class="spinner small"></span> Validating...`;
          fetch(`/api/v1/review-packets/${encodeURIComponent(packetId)}/validate-runtime`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
          })
            .then(r => r.json().then(body => ({ ok: r.ok, body })))
            .then(({ ok, body }) => {
              el.disabled = false;
              el.style.opacity = "";
              el.innerHTML = "Validate";
              if (!ok) throw new Error(body.detail || "Runtime validation failed");
              updateReviewPacketLocally(packetId, packet => {
                const gates = Array.isArray(packet.validationGates) ? packet.validationGates.filter(gate => gate.gateKey !== body.gate.gateKey) : [];
                gates.push(body.gate);
                packet.validationGates = gates;
              });
              showToast(body.gate?.reason || "Runtime validation completed.");
              renderPreserveScroll();
            })
            .catch(err => {
              el.disabled = false;
              el.style.opacity = "";
              el.innerHTML = "Validate";
              showToast(err.message || "Runtime validation failed");
            });
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
            showToast("Review item created. Opening Review Queue.");
            location.hash = "review-queue";
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
        const formData = new FormData();
        formData.append("file", file);
        
        fetch(`/api/v1/mapping/ai-generate?partner=${encodeURIComponent(partner)}`, {
          method: "POST",
          body: formData
        })
          .then(r => r.json().then(body => ({ ok: r.ok, body })))
          .then(({ ok, body }) => {
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
              showToast("Draft created. Opening Review Queue with the review drawer.");
              location.hash = "review-queue";
              return;
            }

            showToast("Draft created. Review now continues in the Review Queue.");
            render();
          })
          .catch(err => showToast("AI Gen failed: " + err.message));
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

        showToast("Running validation rules engine...");
        
        fetch("/api/v1/mapping/validate", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(state.studio.config)
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

    const openReviewQueueBtn = document.getElementById("studio-open-review-queue-btn");
    if (openReviewQueueBtn) {
      openReviewQueueBtn.addEventListener("click", () => {
        if (state.studio.reviewItemId) {
          state.selectedReviewPacketId = state.studio.reviewItemId;
        }
        location.hash = "review-queue";
      });
    }

    const confirmHandoffBtn = document.getElementById("studio-confirm-handoff-btn");
    if (confirmHandoffBtn) {
      confirmHandoffBtn.addEventListener("click", () => {
        state.studio.handoffConfirmed = !state.studio.handoffConfirmed;
        showToast(state.studio.handoffConfirmed
          ? "Draft marked ready for reviewer handoff."
          : "Reviewer handoff mark removed.");
        render();
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
    const { showDate = true, showClear = true } = options;
    return `
      <div class="page-filters">
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
            <div class="date-picker-trigger" aria-label="Open date picker">
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

  function showToast(message) {
    toast.textContent = message;
    toast.classList.add("show");
    clearTimeout(showToast.timer);
    showToast.timer = setTimeout(() => toast.classList.remove("show"), 2400);
  }

  function updateReviewPacketLocally(packetId, updater) {
    state.reviewPackets = (state.reviewPackets || []).map(packet => {
      if (String(packet._id) !== String(packetId)) return packet;
      const nextPacket = { ...packet };
      updater(nextPacket);
      return nextPacket;
    });
  }

  function renderPreserveScroll() {
    const viewport = document.scrollingElement || document.documentElement;
    state.preservedScrollTop = viewport ? viewport.scrollTop : 0;
    render();
  }

  init();
})();
