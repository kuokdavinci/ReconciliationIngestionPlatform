(function () {
  const data = window.AdapterMockData;
  const state = {
    route: "overview",
    partner: "MOMO",
    date: "2024-07-07",
    env: "local",
    collection: "reconciliation_file",
    search: "",
    focus: "operational",
    source: localStorage.getItem("adapterDashboardSource") || "mock",
    apiBase: localStorage.getItem("adapterDashboardApiBase") || defaultApiBase(),
    apiError: "",
    live: {}
  };

  const routes = [
    ["overview", "Overview"],
    ["partners", "Partners & Fetch"],
    ["scheduler", "Scheduler"],
    ["mapping", "Mapping Configs"],
    ["ingestion", "Ingestion"],
    ["reconciliation", "Reconciliation"],
    ["insights", "AI Insights"],
    ["reports", "Reports"],
    ["explorer", "Data Explorer"],
    ["settings", "Settings"]
  ];

  const view = document.getElementById("view");
  const title = document.getElementById("page-title");
  const nav = document.getElementById("nav");
  const partnerFilter = document.getElementById("partner-filter");
  const dateFilter = document.getElementById("date-filter");
  const envFilter = document.getElementById("env-filter");
  const sourceFilter = document.getElementById("source-filter");
  const apiBaseInput = document.getElementById("api-base");
  const sourceStatus = document.getElementById("source-status");
  const toast = document.getElementById("toast");

  function defaultApiBase() {
    return window.location.protocol === "file:" ? "http://localhost:8000" : window.location.origin;
  }

  function init() {
    renderNav();
    renderPartnerOptions();
    bindFilters();
    window.addEventListener("hashchange", onRouteChange);
    onRouteChange();
  }

  function renderNav() {
    nav.innerHTML = routes.map(([key, label]) => `
      <button class="nav-item" data-route="${key}">
        <span>${label}</span>
        <span>${routeCount(key)}</span>
      </button>
    `).join("");
    nav.addEventListener("click", (event) => {
      const button = event.target.closest("[data-route]");
      if (!button) return;
      location.hash = button.dataset.route;
    });
  }

  function routeCount(key) {
    const map = {
      partners: data.fetchConfigs.length,
      scheduler: data.schedulerJobs.length,
      mapping: data.mappingConfigs.length,
      ingestion: data.ingestionFiles.length,
      reconciliation: data.reconciliation.length,
      insights: data.insights.length,
      reports: data.reports.length
    };
    return map[key] || "";
  }

  function renderPartnerOptions() {
    partnerFilter.innerHTML = data.partners.map((partner) => `
      <option value="${partner}">${partner}</option>
    `).join("");
    partnerFilter.value = state.partner;
  }

  function bindFilters() {
    sourceFilter.value = state.source;
    apiBaseInput.value = state.apiBase;

    sourceFilter.addEventListener("change", () => {
      state.source = sourceFilter.value;
      state.apiError = "";
      state.live = {};
      localStorage.setItem("adapterDashboardSource", state.source);
      render();
    });
    apiBaseInput.addEventListener("change", () => {
      state.apiBase = apiBaseInput.value.trim().replace(/\/$/, "") || "http://localhost:8000";
      apiBaseInput.value = state.apiBase;
      state.apiError = "";
      state.live = {};
      localStorage.setItem("adapterDashboardApiBase", state.apiBase);
      render();
    });
    partnerFilter.addEventListener("change", () => {
      state.partner = partnerFilter.value;
      state.live = {};
      render();
    });
    dateFilter.addEventListener("change", () => {
      state.date = dateFilter.value;
      state.live = {};
      render();
    });
    envFilter.addEventListener("change", () => {
      state.env = envFilter.value;
      render();
    });
  }

  function onRouteChange() {
    const key = location.hash.replace("#", "") || "overview";
    state.route = routes.some(([route]) => route === key) ? key : "overview";
    renderNavState();
    render();
  }

  function renderNavState() {
    document.querySelectorAll(".nav-item").forEach((item) => {
      item.classList.toggle("active", item.dataset.route === state.route);
    });
  }

  async function render() {
    const route = routes.find(([key]) => key === state.route);
    title.textContent = route ? route[1] : "Overview";
    renderSourceStatus();
    const renderer = {
      overview: renderOverview,
      partners: renderPartners,
      scheduler: renderScheduler,
      mapping: renderMapping,
      ingestion: renderIngestion,
      reconciliation: renderReconciliation,
      insights: renderInsights,
      reports: renderReports,
      explorer: renderExplorer,
      settings: renderSettings
    }[state.route];

    if (usesLiveApi(state.route) && state.source === "live") {
      view.innerHTML = loadingPanel(`Calling ${state.apiBase}/api/v1 for ${state.partner} / ${state.date}...`);
      try {
        await loadLiveData(state.route);
        state.apiError = "";
      } catch (error) {
        state.apiError = error.message || String(error);
        showToast("Live API failed. Rendering mock fallback.");
      }
      renderSourceStatus();
    }

    view.innerHTML = renderer();
    bindViewActions();
    view.focus({ preventScroll: true });
  }

  function renderSourceStatus() {
    if (state.source === "mock") {
      sourceStatus.textContent = "Mock First / Full Ops";
      sourceStatus.classList.remove("source-error", "source-live");
      return;
    }
    sourceStatus.textContent = state.apiError ? "Live API unavailable / mock fallback" : "Live API for insights";
    sourceStatus.classList.toggle("source-error", Boolean(state.apiError));
    sourceStatus.classList.toggle("source-live", !state.apiError);
  }

  function usesLiveApi(route) {
    return ["overview", "insights", "reports"].includes(route);
  }

  function currentOverview() {
    return data.overview[state.partner] || data.overview.MOMO;
  }

  async function loadLiveData(route) {
    if (route === "overview") {
      state.live.summary = await apiClient.summary(state.partner, state.date);
      return;
    }
    if (route === "insights") {
      const [summary, discrepancies] = await Promise.all([
        apiClient.summary(state.partner, state.date),
        apiClient.discrepancies(state.partner, state.date, state.focus)
      ]);
      state.live.summary = summary;
      state.live.discrepancies = discrepancies;
      return;
    }
    if (route === "reports") {
      state.live.report = await apiClient.dailyReport(state.date);
    }
  }

  const apiClient = {
    async summary(partner, date) {
      return fetchJson(`/api/v1/insights/summary?partner=${encodeURIComponent(partner)}&date=${encodeURIComponent(date)}`);
    },
    async discrepancies(partner, date, focus) {
      return fetchJson(`/api/v1/insights/discrepancies?partner=${encodeURIComponent(partner)}&date=${encodeURIComponent(date)}&focus=${encodeURIComponent(focus)}`);
    },
    async dailyReport(date) {
      return fetchJson(`/api/v1/reports/daily?date=${encodeURIComponent(date)}`);
    }
  };

  async function fetchJson(path) {
    const response = await fetch(state.apiBase + path, {
      headers: { Accept: "application/json" }
    });
    if (!response.ok) {
      const text = await response.text();
      throw new Error(`HTTP ${response.status}: ${text.slice(0, 180)}`);
    }
    return response.json();
  }

  function liveSummaryMetrics() {
    return state.source === "live" && !state.apiError && state.live.summary
      ? state.live.summary.summary_metrics
      : null;
  }

  function renderOverview() {
    const mockSummary = currentOverview();
    const liveMetrics = liveSummaryMetrics();
    const total = liveMetrics ? liveMetrics.total_transactions : mockSummary.rows;
    const matched = liveMetrics ? liveMetrics.matched : mockSummary.success;
    const failed = liveMetrics ? Math.max(0, total - matched) : mockSummary.failed;
    const mismatchRate = liveMetrics ? liveMetrics.mismatch_rate : mockSummary.mismatchRate;
    const mismatchAmount = liveMetrics ? formatAmount(liveMetrics.total_amount_mismatch) : mockSummary.volume;
    const healthRows = apiAwareServices().map((service) => `
      <tr>
        <td>${service.name}</td>
        <td>${badge(service.status)}</td>
        <td>${service.latency}</td>
        <td>${service.detail}</td>
      </tr>
    `).join("");
    return `
      ${apiBanner()}
      ${metrics([
        [liveMetrics ? "API transactions" : "Files processed", liveMetrics ? formatNumber(total) : mockSummary.files, "for " + state.partner],
        ["Matched / accepted", formatNumber(matched), failed + " mismatched or failed"],
        ["Mismatch rate", mismatchRate + "%", "threshold 5.0%"],
        [liveMetrics ? "Mismatch amount" : "Daily volume", mismatchAmount, liveMetrics ? "from summary endpoint" : mockSummary.alerts + " active alerts"]
      ])}
      <div class="grid cols-2">
        <section class="panel">
          <div class="section-row">
            <h2>System Health</h2>
            <button class="button" data-action="refresh-health">Refresh</button>
          </div>
          ${table(["Service", "Status", "Latency", "Detail"], healthRows)}
        </section>
        <section class="panel">
          <h2>Reconciliation Shape</h2>
          ${donut(Math.max(0, 100 - mismatchRate), "Match")}
          ${bars([
            [liveMetrics ? "Matched" : "Ingestion success", percent(matched, total), "green"],
            ["Mismatch rate", mismatchRate, mismatchRate > 5 ? "red" : "amber"],
            [liveMetrics ? "Unmatched" : "Alert pressure", liveMetrics ? percent(failed, total) : mockSummary.alerts * 18, failed > 20 ? "red" : "amber"]
          ])}
        </section>
      </div>
    `;
  }

  function renderPartners() {
    const rows = data.fetchConfigs.map((config) => `
      <tr>
        <td><strong>${config.partner}</strong></td>
        <td>${badge(config.method)}</td>
        <td>${badge(config.enabled ? "enabled" : "disabled")}</td>
        <td>${config.schedule}</td>
        <td>${config.source}</td>
        <td>${config.archive}</td>
        <td>${config.cleanup ? "Yes" : "No"}</td>
        <td>${config.lastFetch}</td>
      </tr>
    `).join("");
    return `
      <div class="section-row">
        <div>
          <h2>Partner Fetch Configuration</h2>
          <p class="muted">Mock records mirror fetch_config documents.</p>
        </div>
        <div class="actions">
          <button class="button primary" data-action="new-partner">New Partner</button>
          <button class="button" data-action="validate-fetch">Validate Sources</button>
        </div>
      </div>
      ${table(["Partner", "Method", "State", "Cron", "Source", "Archive", "Cleanup", "Last Fetch"], rows)}
    `;
  }

  function renderScheduler() {
    const jobs = data.schedulerJobs.map((job) => `
      <tr>
        <td><strong>${job.id}</strong></td>
        <td>${job.name}</td>
        <td>${job.nextRun}</td>
        <td>${job.trigger}</td>
        <td>${badge(job.status)}</td>
        <td><button class="button" data-action="run-job" data-id="${job.id}">Run now</button></td>
      </tr>
    `).join("");
    const timeline = data.runHistory.map((item) => `
      <div class="timeline-item">
        <div class="timeline-time">${item.time}</div>
        <div>
          <strong>${item.partner} / ${item.event}</strong>
          ${badge(item.status)}
          <p class="muted">${item.detail}</p>
        </div>
      </div>
    `).join("");
    return `
      <div class="grid cols-2">
        <section class="panel">
          <div class="section-row">
            <h2>Jobs</h2>
            <button class="button primary" data-action="run-daily">Trigger daily_partner_fetch</button>
          </div>
          ${table(["ID", "Name", "Next Run", "Trigger", "Status", "Action"], jobs)}
        </section>
        <section class="panel">
          <h2>Run Timeline</h2>
          <div class="timeline">${timeline}</div>
        </section>
      </div>
    `;
  }

  function renderMapping() {
    const configs = data.mappingConfigs.map((config) => `
      <div class="config-tile">
        <h3>${config.partner} / ${config.version}</h3>
        <p class="muted">${config.workflow} - ${config.fileType}</p>
        <p>Sheet <strong>${config.sheet}</strong>, start row <strong>${config.startRow}</strong></p>
        <p class="muted">Updated ${config.updated}</p>
      </div>
    `).join("");
    const mappings = data.fieldMappings.map((field) => `
      <tr>
        <td><strong>${field.path}</strong></td>
        <td>${field.column}</td>
        <td>${badge(field.type)}</td>
        <td>${field.required ? "Yes" : "No"}</td>
        <td>${field.sample}</td>
      </tr>
    `).join("");
    return `
      <section class="panel">
        <div class="section-row">
          <h2>Mapping Configs</h2>
          <button class="button primary" data-action="upload-template">Upload Template</button>
        </div>
        <div class="config-list">${configs}</div>
      </section>
      <section class="panel">
        <h2>${state.partner} Field Mappings</h2>
        ${table(["Path", "Column", "Type", "Required", "Sample"], mappings)}
      </section>
    `;
  }

  function renderIngestion() {
    const rows = data.ingestionFiles.map((file) => `
      <tr>
        <td><strong>${file.partner}</strong></td>
        <td>${file.file}</td>
        <td>${badge(file.status.toLowerCase())}</td>
        <td>${formatNumber(file.total)}</td>
        <td>${formatNumber(file.success)}</td>
        <td>${formatNumber(file.failed)}</td>
        <td>${file.duration}</td>
        <td>${file.hash}</td>
      </tr>
    `).join("");
    const errors = data.rowErrors.map((error) => `
      <tr>
        <td>${error.row}</td>
        <td>${error.field}</td>
        <td>${error.reason}</td>
        <td>${error.trace}</td>
      </tr>
    `).join("");
    return `
      <div class="section-row">
        <h2>Ingestion Pipeline</h2>
        <div class="actions">
          <button class="button primary" data-action="manual-ingest">Run Manual Ingest</button>
          <button class="button" data-action="clear-errors">Acknowledge Errors</button>
        </div>
      </div>
      ${table(["Partner", "File", "Status", "Total", "Success", "Failed", "Duration", "Hash"], rows)}
      <section class="panel">
        <h2>Recent Row Errors</h2>
        ${table(["Row", "Field", "Reason", "Trace"], errors)}
      </section>
    `;
  }

  function renderReconciliation() {
    const records = data.reconciliation.filter((item) => item.partner === state.partner);
    const counts = countBy(records, "status");
    const rows = records.map((item) => `
      <tr>
        <td>${item.key}</td>
        <td>${badge(item.status.toLowerCase())}</td>
        <td>${money(item.partnerAmount)}</td>
        <td>${money(item.internalAmount)}</td>
        <td>${item.partnerStatus}</td>
        <td>${item.internalStatus}</td>
      </tr>
    `).join("");
    return `
      <div class="grid cols-2">
        <section class="panel">
          <div class="section-row">
            <h2>Result Breakdown</h2>
            <button class="button primary" data-action="run-reconcile">Run Reconcile</button>
          </div>
          ${bars(Object.entries(counts).map(([key, value]) => [key, percent(value, records.length), key === "MATCHED" ? "green" : "amber"]))}
        </section>
        <section class="panel">
          <h2>Execution Context</h2>
          ${kvList([
            ["Partner", state.partner],
            ["Date", state.date],
            ["Mode", "Deterministic"],
            ["Records", records.length]
          ])}
        </section>
      </div>
      ${table(["Partner Txn ID", "Status", "Partner Amount", "Internal Amount", "Partner Status", "Internal Status"], rows)}
    `;
  }

  function renderInsights() {
    const options = ["operational", "partner", "inconsistency"].map((focus) => `
      <option value="${focus}" ${focus === state.focus ? "selected" : ""}>${focus}</option>
    `).join("");
    const liveItems = state.source === "live" && !state.apiError && Array.isArray(state.live.discrepancies)
      ? state.live.discrepancies
      : null;
    const mockItems = data.insights.filter((item) => item.partner === state.partner && item.focus === state.focus);
    const cards = (liveItems || mockItems).map((item) => insightCard(item, Boolean(liveItems))).join("")
      || `<div class="empty-state">No ${liveItems ? "API" : "mock"} insights for ${state.partner} / ${state.focus}.</div>`;
    const liveMetrics = liveSummaryMetrics();
    const statusCounts = liveMetrics ? liveMetrics.by_status || {} : null;
    return `
      ${apiBanner()}
      <div class="toolbar">
        <label>
          Focus
          <select id="focus-filter">${options}</select>
        </label>
        <button class="button primary" data-action="generate-insights">Generate Insights</button>
      </div>
      <div class="grid cols-3">${cards}</div>
      <section class="panel">
        <h2>${liveMetrics ? "Live Summary Metrics" : "Summary Endpoint Shape"}</h2>
        ${liveMetrics ? bars([
          ["matched", percent(liveMetrics.matched, liveMetrics.total_transactions), "green"],
          ["mismatch_rate", liveMetrics.mismatch_rate, liveMetrics.mismatch_rate > 5 ? "red" : "amber"],
          ["missing_internal", percent(statusCounts.MISSING_INTERNAL || 0, liveMetrics.total_transactions), "red"],
          ["missing_partner", percent(statusCounts.MISSING_PARTNER || 0, liveMetrics.total_transactions), "red"]
        ]) : bars([
          ["summary_metrics", 92, "green"],
          ["grouped_stats", 78, "teal"],
          ["key_findings", 64, "amber"],
          ["alerts", 36, "red"]
        ])}
      </section>
    `;
  }

  function renderReports() {
    const liveReport = state.source === "live" && !state.apiError ? state.live.report : null;
    const livePartners = liveReport && Array.isArray(liveReport.partners) ? liveReport.partners : null;
    const rows = (livePartners || data.reports).map((report) => {
      const metrics = report.summary_metrics || report;
      const total = metrics.total_transactions ?? report.total;
      const matched = metrics.matched ?? report.matched;
      const mismatchRate = metrics.mismatch_rate ?? report.mismatchRate;
      const mismatchAmount = metrics.total_amount_mismatch ?? report.totalMismatch;
      return `
      <tr>
        <td><strong>${report.partner}</strong></td>
        <td>${formatNumber(total || 0)}</td>
        <td>${formatNumber(matched || 0)}</td>
        <td>${mismatchRate || 0}%</td>
        <td>${formatAmount(mismatchAmount)}</td>
        <td>${report.alerts ?? (report.key_findings ? report.key_findings.length : 0)}</td>
      </tr>
    `;
    }).join("");
    const global = liveReport ? liveReport.global_stats || {} : null;
    const totalAlerts = liveReport && Array.isArray(liveReport.alerts)
      ? liveReport.alerts.length
      : data.reports.reduce((sum, item) => sum + item.alerts, 0);
    return `
      ${apiBanner()}
      ${metrics([
        ["Report date", liveReport ? liveReport.date || state.date : state.date, "daily batch"],
        ["Partners", livePartners ? livePartners.length : data.reports.length, livePartners ? "from API" : "active mock"],
        ["Global mismatch", global ? (global.total_mismatch_rate || 0) + "%" : "3.4%", livePartners ? "from daily report" : "weighted mock average"],
        ["Open alerts", totalAlerts, "threshold breaches"]
      ])}
      <div class="section-row">
        <h2>Daily Report</h2>
        <button class="button primary" data-action="export-report">Export JSON</button>
      </div>
      ${table(["Partner", "Total", "Matched", "Mismatch Rate", "Mismatch Amount", "Alerts"], rows)}
    `;
  }

  function renderExplorer() {
    const collectionOptions = Object.keys(data.collections).map((name) => `
      <option value="${name}" ${name === state.collection ? "selected" : ""}>${name}</option>
    `).join("");
    const source = data.collections[state.collection];
    const keys = Array.from(new Set(source.flatMap((record) => Object.keys(record))));
    return `
      <div class="toolbar">
        <label>
          Collection
          <select id="collection-filter">${collectionOptions}</select>
        </label>
        <label>
          Search
          <input id="collection-search" class="search" value="${escapeHtml(state.search)}" placeholder="trace, status, partner">
        </label>
      </div>
      <div class="table-wrap">
        <table>
          <thead><tr>${keys.map((header) => `<th>${header}</th>`).join("")}</tr></thead>
          <tbody id="explorer-body">${explorerRows(keys)}</tbody>
        </table>
      </div>
    `;
  }

  function renderSettings() {
    const groups = groupBy(data.settings, "group");
    const content = Object.entries(groups).map(([group, values]) => {
      const rows = values.map((item) => `
        <tr>
          <td><strong>${item.key}</strong></td>
          <td>${item.value}</td>
        </tr>
      `).join("");
      return `<section class="panel"><h2>${group}</h2>${table(["Key", "Value"], rows)}</section>`;
    }).join("");
    return `
      <div class="section-row">
        <h2>Runtime Settings</h2>
        <button class="button" data-action="check-indexes">Check Indexes</button>
      </div>
      <div class="grid cols-2">${content}</div>
    `;
  }

  function bindViewActions() {
    view.querySelectorAll("[data-action]").forEach((button) => {
      button.addEventListener("click", () => {
        if (state.source === "live" && ["refresh-health", "generate-insights", "export-report"].includes(button.dataset.action)) {
          state.live = {};
          state.apiError = "";
          showToast("Refreshing from Live API...");
          render();
          return;
        }
        showToast(mockMessage(button.dataset.action, button.dataset.id));
      });
    });
    const collectionFilter = document.getElementById("collection-filter");
    if (collectionFilter) {
      collectionFilter.addEventListener("change", () => {
        state.collection = collectionFilter.value;
        render();
      });
    }
    const search = document.getElementById("collection-search");
    if (search) {
      search.addEventListener("input", () => {
        state.search = search.value;
        const source = data.collections[state.collection];
        const keys = Array.from(new Set(source.flatMap((record) => Object.keys(record))));
        document.getElementById("explorer-body").innerHTML = explorerRows(keys);
      });
    }
    const focus = document.getElementById("focus-filter");
    if (focus) {
      focus.addEventListener("change", () => {
        state.focus = focus.value;
        delete state.live.discrepancies;
        render();
      });
    }
  }

  function mockMessage(action, id) {
    const messages = {
      "refresh-health": "Mock health refresh completed.",
      "new-partner": "Partner creation flow is ready for API integration.",
      "validate-fetch": "Fetch sources validated against mock config.",
      "run-job": `Mock trigger queued for ${id}.`,
      "run-daily": "Mock daily_partner_fetch trigger queued.",
      "upload-template": "Template upload flow is staged.",
      "manual-ingest": "Manual ingestion command staged.",
      "clear-errors": "Row errors acknowledged in mock state.",
      "run-reconcile": "Reconciliation run staged for " + state.partner + " / " + state.date + ".",
      "generate-insights": "AI insights generated from mock aggregates.",
      "export-report": "Daily report export staged.",
      "check-indexes": "All required mock indexes are present."
    };
    return messages[action] || "Action completed.";
  }

  function metrics(items) {
    return `<div class="grid cols-4">${items.map(([label, value, hint]) => `
      <div class="metric">
        <span>${label}</span>
        <strong>${value}</strong>
        <small>${hint}</small>
      </div>
    `).join("")}</div>`;
  }

  function loadingPanel(message) {
    return `
      <section class="panel">
        <div class="loading-row">
          <div class="spinner"></div>
          <div>
            <h2>Loading Live API</h2>
            <p class="muted">${message}</p>
          </div>
        </div>
      </section>
    `;
  }

  function apiBanner() {
    if (state.source !== "live") {
      return "";
    }
    if (state.apiError) {
      return `
        <section class="panel api-banner error">
          <strong>Live API unavailable. Showing mock fallback.</strong>
          <span>${escapeHtml(state.apiError)}</span>
        </section>
      `;
    }
    return `
      <section class="panel api-banner live">
        <strong>Live API connected.</strong>
        <span>${escapeHtml(state.apiBase)} / ${state.partner} / ${state.date}</span>
      </section>
    `;
  }

  function apiAwareServices() {
    if (state.source !== "live") return data.services;
    return data.services.map((service) => {
      if (service.name !== "FastAPI") return service;
      return {
        ...service,
        status: state.apiError ? "failed" : "healthy",
        detail: state.apiError ? "API call failed or CORS blocked" : "Live insights endpoints responding"
      };
    });
  }

  function insightCard(item, isLive) {
    const affected = isLive ? item.affected_count : item.affected;
    return `
      <div class="metric">
        <span>${isLive ? item.type || state.focus : item.focus}</span>
        <strong>${item.title}</strong>
        <small>${badge(item.severity || "low")} ${affected || 0} affected</small>
        <p class="muted">${item.recommendation || item.description || "No recommendation returned."}</p>
      </div>
    `;
  }

  function kvList(items) {
    return `<div class="kv-list">${items.map(([label, value]) => `
      <div class="kv-row">
        <span>${label}</span>
        <strong>${value}</strong>
      </div>
    `).join("")}</div>`;
  }

  function table(headers, rows) {
    return `
      <div class="table-wrap">
        <table>
          <thead><tr>${headers.map((header) => `<th>${header}</th>`).join("")}</tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    `;
  }

  function explorerRows(keys) {
    const records = data.collections[state.collection].filter((record) => {
      const haystack = JSON.stringify(record).toLowerCase();
      return haystack.includes(state.search.toLowerCase());
    });
    if (!records.length) {
      return `<tr><td colspan="${keys.length || 1}">No mock records found.</td></tr>`;
    }
    return records.map((record) => `
      <tr>${keys.map((key) => `<td>${record[key] ?? "-"}</td>`).join("")}</tr>
    `).join("");
  }

  function badge(value) {
    const text = String(value);
    return `<span class="badge ${text.toLowerCase().replace(/_/g, "-")}">${text}</span>`;
  }

  function bars(items) {
    return `<div class="bars">${items.map(([label, value, tone]) => `
      <div class="bar-row">
        <strong>${label}</strong>
        <div class="bar-track"><div class="bar-fill ${tone || ""}" style="width:${Math.min(100, Number(value) || 0)}%"></div></div>
        <span>${Math.round(Number(value) || 0)}%</span>
      </div>
    `).join("")}</div>`;
  }

  function donut(value, label) {
    return `
      <div class="donut" style="--value:${Math.round(value)}">
        <div class="donut-inner">${Math.round(value)}%</div>
      </div>
      <p class="muted" style="text-align:center;margin-top:10px">${label}</p>
    `;
  }

  function countBy(items, key) {
    return items.reduce((acc, item) => {
      acc[item[key]] = (acc[item[key]] || 0) + 1;
      return acc;
    }, {});
  }

  function groupBy(items, key) {
    return items.reduce((acc, item) => {
      const group = item[key];
      if (!acc[group]) acc[group] = [];
      acc[group].push(item);
      return acc;
    }, {});
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

  function money(value) {
    if (value === null || value === undefined) return "-";
    return formatNumber(value) + " VND";
  }

  function escapeHtml(value) {
    return String(value).replace(/[&<>"']/g, (char) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      "\"": "&quot;",
      "'": "&#039;"
    }[char]));
  }

  function showToast(message) {
    toast.textContent = message;
    toast.classList.add("show");
    window.clearTimeout(showToast.timer);
    showToast.timer = window.setTimeout(() => toast.classList.remove("show"), 2400);
  }

  init();
})();
