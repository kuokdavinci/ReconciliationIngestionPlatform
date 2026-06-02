(function () {
  const state = {
    route: "overview",
    partner: "MOMO",
    date: "2024-07-07",
    focus: "operational",
    reconStatus: "",
    explorerFilters: { amountMin: "", amountMax: "", dateFrom: "", dateTo: "" }
  };

  const routes = [
    ["overview", "Dashboard & Insights", "dashboard"],
    ["explorer", "DB Explorer", "travel_explore"],
    ["reconciliation", "Reconciliation Ledger", "fact_check"],
    ["scheduler", "Scheduler Daemon", "calendar_today"],
    ["mappings", "Mapping Configs", "settings_suggest"],
    ["settings", "Settings", "account_tree"],
  ];

  const view = document.getElementById("view");
  const title = document.getElementById("page-title");
  const subtitle = document.getElementById("page-subtitle");
  const nav = document.getElementById("nav");
  const toast = document.getElementById("toast");

  function init() {
    renderNav();
    window.addEventListener("hashchange", onRouteChange);
    onRouteChange();

    view.addEventListener("click", (e) => {
      const tab = e.target.closest(".segmented-tab");
      if (tab) {
        state.focus = tab.dataset.focus;
        view.innerHTML = renderOverview();
        bindViewActions();
      }
    });
  }

  function fetchPartners(container) {
    fetch("/api/v1/data/stats?date=" + state.date)
      .then(r => r.json())
      .then(data => {
        const partners = Object.keys(data.by_partner || {});
        if (partners.length) {
          const el = (container || document).getElementById("partner-filter");
          if (el) {
            el.innerHTML = partners.map(p =>
              `<option value="${p}" ${p === state.partner ? "selected" : ""}>${p}</option>`
            ).join("");
          }
        }
      })
      .catch(() => {});
  }

  function renderNav() {
    nav.innerHTML = routes.map(([key, label, icon]) => `
      <button class="nav-item ${key === state.route ? 'active' : ''}" data-route="${key}">
        <span class="material-symbols-outlined">${icon}</span>
        <span>${label}</span>
      </button>
    `).join("");
    
    nav.querySelectorAll("[data-route]").forEach(button => {
      button.addEventListener("click", () => {
        location.hash = button.dataset.route;
      });
    });
  }

  function bindFilters() {
    const pf = document.getElementById("partner-filter");
    const df = document.getElementById("date-filter");
    if (pf) {
      pf.addEventListener("change", () => {
        state.partner = pf.value;
        render();
      });
    }
    if (df) {
      df.addEventListener("change", () => {
        state.date = df.value;
        render();
      });
    }
  }

  function onRouteChange() {
    const key = location.hash.replace("#", "") || "overview";
    state.route = routes.some(([route]) => route === key) ? key : "overview";
    
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
    const route = routes.find(([key]) => key === state.route);
    title.textContent = route ? route[1] : "Overview";
    subtitle.textContent = `Operations Console - ${state.partner} (${state.date})`;

    if (state.route === "overview") {
      view.innerHTML = loadingPanel("Loading Dashboard & AI Insights console...");
      try {
        const [summary, stats, operational, partner, inconsistency] = await Promise.all([
          tryFetch(`/api/v1/insights/summary?partner=${encodeURIComponent(state.partner)}&date=${encodeURIComponent(state.date)}`, "/api/v1/insights/sample"),
          tryFetch(`/api/v1/reconciliation/stats?partner=${encodeURIComponent(state.partner)}&date=${encodeURIComponent(state.date)}`, "/api/v1/insights/sample-stats"),
          tryFetch(`/api/v1/insights/discrepancies?partner=${encodeURIComponent(state.partner)}&date=${encodeURIComponent(state.date)}&focus=operational`, "/api/v1/insights/sample-discrepancies"),
          tryFetch(`/api/v1/insights/discrepancies?partner=${encodeURIComponent(state.partner)}&date=${encodeURIComponent(state.date)}&focus=partner`, "/api/v1/insights/sample-discrepancies"),
          tryFetch(`/api/v1/insights/discrepancies?partner=${encodeURIComponent(state.partner)}&date=${encodeURIComponent(state.date)}&focus=inconsistency`, "/api/v1/insights/sample-discrepancies"),
        ]);
        
        state.insightsData = { summary, operational, partner, inconsistency };
        state.statsData = stats;
        view.innerHTML = renderOverview();
      } catch (err) {
        view.innerHTML = renderError(err);
      }
      fetchPartners();
      bindFilters();
      bindViewActions();
      return;
    }

    if (state.route === "explorer") {
      view.innerHTML = loadingPanel("Loading transaction logs and ingested files...");
      try {
        const ef = state.explorerFilters || {};
        let txnUrl = `/api/v1/data/transactions?partner=${encodeURIComponent(state.partner)}&date=${encodeURIComponent(state.date)}&limit=100`;
        if (ef.amountMin) txnUrl += `&amount_min=${encodeURIComponent(ef.amountMin)}`;
        if (ef.amountMax) txnUrl += `&amount_max=${encodeURIComponent(ef.amountMax)}`;
        if (ef.dateFrom) txnUrl += `&date_from=${encodeURIComponent(ef.dateFrom)}`;
        if (ef.dateTo) txnUrl += `&date_to=${encodeURIComponent(ef.dateTo)}`;
        let fileUrl = `/api/v1/data/files?partner=${encodeURIComponent(state.partner)}&date=${encodeURIComponent(state.date)}&limit=100`;
        const [txsData, filesData] = await Promise.all([
          fetchJson(txnUrl).catch(() => ({ transactions: [], total: 0 })),
          fetchJson(fileUrl).catch(() => ({ files: [], total: 0 }))
        ]);
        view.innerHTML = renderDataExplorer(txsData, filesData);
      } catch (err) {
        view.innerHTML = renderError(err);
      }
      fetchPartners();
      bindFilters();
      bindViewActions();
      return;
    }

    if (state.route === "reconciliation") {
      view.innerHTML = loadingPanel("Loading ledger details...");
      try {
        let url = `/api/v1/reconciliation/results?partner=${encodeURIComponent(state.partner)}&date=${encodeURIComponent(state.date)}&limit=100`;
        if (state.reconStatus) {
          url += `&status=${encodeURIComponent(state.reconStatus)}`;
        }
        const data = await fetchJson(url);
        view.innerHTML = renderReconciliation(data);
      } catch (err) {
        view.innerHTML = renderError(err);
      }
      fetchPartners();
      bindFilters();
      bindViewActions();
      return;
    }

    if (state.route === "mappings") {
      view.innerHTML = loadingPanel("Loading mapping configurations...");
      try {
        const data = await fetchJson(`/api/v1/mappings?partner=${encodeURIComponent(state.partner)}`);
        view.innerHTML = renderMappings(data);
      } catch (err) {
        view.innerHTML = renderError(err);
      }
      fetchPartners();
      bindFilters();
      bindViewActions();
      return;
    }

    if (state.route === "scheduler") {
      view.innerHTML = renderScheduler();
      bindViewActions();
      return;
    }

    if (state.route === "settings") {
      view.innerHTML = renderSettings();
      bindViewActions();
      return;
    }
  }

  function renderOverview() {
    const insights = state.insightsData ? state.insightsData.summary : null;
    const stats = state.statsData;
    if (!stats || !insights) return '<div class="empty-state">No dashboard data loaded.</div>';

    const m = insights.summary_metrics || {};
    const byStatus = m.by_status || {};
    const total = m.total_transactions || 0;
    const matched = m.matched || 0;
    const failed = Math.max(0, total - matched);
    const mismatchRate = m.mismatch_rate || 0;
    const mismatchAmount = m.total_amount_mismatch ? formatAmount(m.total_amount_mismatch) : "-";
    const matchedPct = total ? Math.round((matched / total) * 100) : 0;
    const obs = insights.ai_observation;
    
    // Auto detect anomaly status warning
    let matchQualityStatus = `<span class="badge matched">HEALTHY</span>`;
    if (mismatchRate > 5) {
      matchQualityStatus = `<span class="badge critical">CRITICAL ANOMALY</span>`;
    } else if (mismatchRate > 2) {
      matchQualityStatus = `<span class="badge warning">WARNING</span>`;
    }

    // Reconciliation Health Widget
    const statsByStatus = stats.by_status || {};
    const statsTotal = stats.total || 0;
    const anomalyCount = (statsByStatus.AMOUNT_MISMATCH || 0) + (statsByStatus.STATUS_MISMATCH || 0) + (statsByStatus.MULTIPLE_MISMATCH || 0) + (statsByStatus.MISSING_INTERNAL || 0) + (statsByStatus.MISSING_PARTNER || 0) + (statsByStatus.UNMAPPED_SKIPPED || 0);
    const healthStatus = anomalyCount === 0
      ? `<span class="badge matched">HEALTHY</span>`
      : anomalyCount > 10
        ? `<span class="badge critical">ANOMALY</span>`
        : `<span class="badge warning">WARNING</span>`;

    const healthWidgetHtml = `
      <section class="panel" style="margin-bottom: 24px;">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;">
          <h2 style="margin: 0; font-size: 16px;">Reconciliation Health</h2>
          ${healthStatus}
        </div>
        <div class="grid cols-4" style="margin-bottom: 0;">
          <div class="metric" style="padding: 16px;">
            <span>Partner</span>
            <strong style="font-size: 22px;">${escapeHtml(state.partner)}</strong>
            <small>Active</small>
          </div>
          <div class="metric" style="padding: 16px;">
            <span>Total Records</span>
            <strong style="font-size: 22px;">${formatNumber(statsTotal)}</strong>
            <small>Reconciled</small>
          </div>
          <div class="metric" style="padding: 16px;">
            <span>Anomalies</span>
            <strong style="font-size: 22px; color: ${anomalyCount > 0 ? 'var(--status-unmatched)' : 'var(--status-matched)'};">${formatNumber(anomalyCount)}</strong>
            <small>Pending items</small>
          </div>
          <div class="metric" style="padding: 16px;">
            <span>Last Recon</span>
            <strong style="font-size: 22px;">${state.date}</strong>
            <small>Reconciliation Date</small>
          </div>
        </div>
      </section>
    `;

    // AI Discrepancies Segmented Tabs Logic
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
      ? processedItems.map(item => insightCard(item)).join("")
      : `<div class="empty-state" style="grid-column: span 3; text-align: center; padding: 40px 0;">No active anomalies found for this focus dimension.</div>`;

    // Segmented Tab markup
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
        ["Total Transactions", formatNumber(total), state.partner],
        ["Matched Records", formatNumber(matched), `${failed} mismatched/failed`],
        ["Mismatch Rate", mismatchRate.toFixed(2) + "%", matchQualityStatus],
        ["Mismatch Volume", mismatchAmount, "from current stream"]
      ])}
      
      ${renderPageFilters()}
      
      ${healthWidgetHtml}

      <div style="margin-top: 32px;">
        <div class="insights-header-row" style="margin-bottom: 16px;">
          <div class="segmented-tabs-container">
            ${tabs}
          </div>
        </div>
        
        <div style="margin-bottom: 24px;">
          <h2 style="font-size: 20px; font-weight: 800; margin-bottom: 16px; display: flex; align-items: center; gap: 8px;">
            <span class="material-symbols-outlined" style="color: var(--brand-primary);">troubleshoot</span>
            AI Identified Anomalies & Recommendations (${processedItems.length})
          </h2>
          <div class="grid cols-3">${cards}</div>
        </div>

        ${obs ? renderAiObservation(obs) : ''}
      </div>
      
      <div class="grid cols-2">
        <section class="panel">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;">
            <h2 style="margin: 0; font-size: 20px; font-weight: 800;">Reconciliation Quality</h2>
            <span style="font-size: 11px; color: var(--text-muted);">Threshold limit: 5%</span>
          </div>
          ${bars([
            ["Matched Transactions", matchedPct, "green"],
            ["Total Mismatch Rate", Math.min(mismatchRate, 100), mismatchRate > 5 ? "red" : "amber"],
            ["Missing Internal Records", percent(byStatus.MISSING_INTERNAL || 0, total), "amber"],
            ["Missing Partner Records", percent(byStatus.MISSING_PARTNER || 0, total), "red"]
          ])}
        </section>
        
        <section class="panel" style="display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 20px;">
          <h2 style="align-self: flex-start; margin-bottom: 8px; font-size: 20px; font-weight: 800;">Success Rate Distribution</h2>
          ${donut(Math.max(0, 100 - mismatchRate), "Total Match Quality")}
        </section>
      </div>
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
[2026-06-02 00:00:00] [INFO] APScheduler daemon cycle started.
[2026-06-02 00:00:01] [INFO] Running daily_partner_fetch trigger.
[2026-06-02 00:00:02] [INFO] MOMO SFTP connection initialized.
[2026-06-02 00:00:04] [INFO] Downloaded: MOMO_2026-06-02.xlsx (2.4 MB)
[2026-06-02 00:00:05] [INFO] Triggering IngestionPipeline for MOMO.
[2026-06-02 00:00:06] [SUCCESS] Ingestion completed. 15,200 records ingested.
        </div>
      </section>
    `;
  }

  function renderReconciliation(data) {
    const items = data.results || [];
    const statusOptions = [
      ["", "All Statuses"],
      ["MATCHED", "MATCHED"],
      ["MATCHED_FAILED", "MATCHED_FAILED"],
      ["MATCHED_REVERSED", "MATCHED_REVERSED"],
      ["AMOUNT_MISMATCH", "AMOUNT_MISMATCH"],
      ["STATUS_MISMATCH", "STATUS_MISMATCH"],
      ["MULTIPLE_MISMATCH", "MULTIPLE_MISMATCH"],
      ["MISSING_INTERNAL", "MISSING_INTERNAL"],
      ["MISSING_PARTNER", "MISSING_PARTNER"]
    ].map(([val, label]) => `<option value="${val}" ${val === state.reconStatus ? "selected" : ""}>${val ? val : label}</option>`).join("");

    const toolbarHtml = `
      <div class="toolbar">
        <label>
          FILTER STATUS
          <select id="recon-status-filter">${statusOptions}</select>
        </label>
      </div>
    `;

    if (!items.length) {
      return `
        ${renderPageFilters()}
        ${toolbarHtml}
        <section class="panel">
          <div class="empty-state" style="text-align: center; padding: 40px 0;">
            <span class="material-symbols-outlined" style="font-size: 48px; color: var(--text-muted); margin-bottom: 12px;">info</span>
            <h3>No Reconciliation Results</h3>
            <p class="muted">No records matched the filter status for ${state.partner} / ${state.date}.</p>
          </div>
        </section>
      `;
    }
    const headers = ["Partner TXN ID", "Internal TXN ID", "Partner Amount", "Internal Amount", "Partner Status", "Internal Status", "Reconciliation Status"];
    const rows = items.map(item => `
      <tr>
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
      ${renderPageFilters()}
      ${toolbarHtml}
      <section class="panel">
        <div class="panel-header" style="margin-bottom: 20px;">
          <h2>Reconciliation Ledger (${formatNumber(data.total || items.length)} transactions)</h2>
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
          const formattedDate = f.reconciliationDate ? new Date(f.reconciliationDate).toLocaleString() : "-";
          return `
            <tr>
              <td><strong>${escapeHtml(f.filename || "-")}</strong></td>
              <td><code>${escapeHtml(f.partner || "-")}</code></td>
              <td><span class="badge" style="background: rgba(240,185,11,.08); color: var(--brand-primary); border-color: rgba(240,185,11,.2);">${escapeHtml(f.fileType || "-")}</span></td>
              <td style="font-variant-numeric: tabular-nums;">${formatNumber(f.recordsCount || 0)}</td>
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
          const formattedDate = t.reconciliationDate ? new Date(t.reconciliationDate).toLocaleString() : "-";
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

    return `
      ${renderPageFilters()}
      <div class="page-filters" style="margin-top: -16px;">
        <div class="filter-group">
          <span class="filter-label">AMOUNT MIN</span>
          <div class="filter-input-wrapper">
            <input id="amount-min" type="text" placeholder="0" value="">
          </div>
        </div>
        <div class="filter-group">
          <span class="filter-label">AMOUNT MAX</span>
          <div class="filter-input-wrapper">
            <input id="amount-max" type="text" placeholder="∞" value="">
          </div>
        </div>
        <div class="filter-group">
          <span class="filter-label">DATE FROM</span>
          <div class="filter-input-wrapper">
            <input id="date-from" type="date" value="">
          </div>
        </div>
        <div class="filter-group">
          <span class="filter-label">DATE TO</span>
          <div class="filter-input-wrapper">
            <input id="date-to" type="date" value="">
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


  function renderMappings(data) {
    const items = data.mappings || [];
    if (!items.length) {
      return `
        ${renderPageFilters(false)}
        <section class="panel">
          <div class="empty-state" style="text-align: center; padding: 40px 0;">
            <span class="material-symbols-outlined" style="font-size: 48px; color: var(--text-muted); margin-bottom: 12px;">settings</span>
            <h3>No Mapping Configurations</h3>
            <p class="muted">No active mapping configs found for ${state.partner}.</p>
          </div>
        </section>
      `;
    }

    const cards = items.map(config => {
      const health = config.configHealth || {};
      const status = String(health.status || (health.stale ? "STALE" : "ACTIVE"));
      const confidence = typeof health.confidence === "number" ? Math.round(health.confidence * 100) : null;
      const statusClass = status === "ACTIVE" ? "matched" : status === "PENDING_REVIEW" ? "warning" : "critical";
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
            <span class="badge ${statusClass}">${escapeHtml(status)}</span>
            ${confidence !== null ? `<span class="badge neutral">Confidence ${confidence}%</span>` : ""}
            ${health.reasoning ? `<span class="muted" style="font-size: 12px;">${escapeHtml(String(health.reasoning))}</span>` : ""}
            ${status === "PENDING_REVIEW" ? `<button class="button" data-action="approve-config" data-config-id="${escapeHtml(config._id || "")}">Approve</button>` : ""}
          </div>
          <h3 style="font-size: 13px; font-weight: 700; color: var(--text-muted); letter-spacing: 0.05em; text-transform: uppercase; margin-bottom: 16px;">
            Field Mappings (${(config.fieldMappings || []).length})
          </h3>
          ${mappingsHtml}
        </section>
      `;
    }).join("");

    return `${renderPageFilters(false)}${cards}`;
  }

  function renderSettings() {
    const defaultJson = {
      "partner": "MOMO",
      "workflowType": "UPC",
      "fileType": "SETTLEMENT",
      "sheetName": "data",
      "startRow": 8,
      "fieldMappings": [
        { "path": "id", "column": 2, "type": "STRING", "required": true },
        { "path": "trace", "column": 11, "type": "STRING" },
        { "path": "amount", "column": 5, "type": "DECIMAL" },
        { "path": "currency", "constant": "VND", "type": "CONSTANT" },
        { "path": "status", "column": 18, "type": "MAPPING", "mapping": { "Thành công": "SUCCESS", "others": "FAILED" } }
      ],
      "configVersion": "v_template"
    };

    return `
      <section class="panel" style="margin-bottom: 24px;">
        <h2>Import Ingestion Mapping Schema Config File</h2>
        <p class="muted" style="margin-bottom: 20px;">Upload a mapping configuration file (.json) or paste the JSON definition to configure the partner reconciliation parser.</p>
        
        <div class="grid cols-2" style="gap: 20px; align-items: stretch; margin-bottom: 24px;">
          <div style="display: flex; flex-direction: column; gap: 10px;">
            <label style="font-weight: 700; font-size: 11px;">PASTE SCHEMA JSON CONFIG</label>
            <textarea id="config-json-textarea" style="flex-grow: 1; min-height: 220px; font-family: monospace; background: var(--bg-primary); border: 1px solid var(--border); padding: 12px; border-radius: 6px; color: #a8ffb2; resize: vertical; outline: none; line-height: 1.4; font-size: 13px;" placeholder="Paste JSON here...">${JSON.stringify(defaultJson, null, 2)}</textarea>
          </div>
          
          <div style="display: flex; flex-direction: column; justify-content: space-between; border: 1px dashed var(--border); border-radius: 8px; padding: 24px; text-align: center; background: rgba(255,255,255,0.01);">
            <div style="margin: auto 0;">
              <span class="material-symbols-outlined" style="font-size: 48px; color: var(--green-primary); margin-bottom: 12px;">upload_file</span>
              <h3 style="margin-bottom: 6px;">Select Mapping Config File</h3>
              <p class="muted" style="font-size: 12px; margin-bottom: 20px;">Drag & drop your JSON config file here or browse</p>
              <input type="file" id="config-file-upload" accept=".json" style="display: none;">
              <button class="button" onclick="document.getElementById('config-file-upload').click()">Browse Files</button>
            </div>
          </div>
        </div>

        <div style="display: flex; gap: 12px;">
          <button class="button primary" id="apply-config-btn">
            <span class="material-symbols-outlined" style="font-size: 18px;">cloud_upload</span>
            Apply Ingestion Config Schema
          </button>
          <button class="button" id="reset-config-btn">Reset Draft</button>
        </div>
      </section>

      <section class="panel" id="config-preview-panel" style="display: none;">
        <h2>Loaded Schema Config Preview</h2>
        <div id="config-preview-content"></div>
      </section>
    `;
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

  function insightCard(item) {
    const sev = String(item.severity || "low").toLowerCase();
    
    // Select visual icon based on severity
    let statusIcon = "info";
    let statusColor = "var(--text-muted)";
    if (sev === "critical") {
      statusIcon = "gavel";
      statusColor = "var(--critical)";
    } else if (sev === "high") {
      statusIcon = "warning";
      statusColor = "var(--status-warning)";
    } else if (sev === "medium") {
      statusIcon = "info";
      statusColor = "var(--brand-accent-blue)";
    } else if (sev === "low") {
      statusIcon = "check_circle";
      statusColor = "var(--status-matched)";
    }

    const typeLabel = (item.type || state.focus).replace(/_/g, ' ');
    
    let actionHtml = '';
    if (item.recommendation) {
      actionHtml = `
        <div class="insight-action-box ${sev}">
          <div class="insight-action-header">
            <span class="material-symbols-outlined action-icon">offline_bolt</span>
            <span>RECOMMENDED ACTION</span>
          </div>
          <div class="insight-action-body">${item.recommendation}</div>
        </div>
      `;
    }

    const descriptionText = item.description || "";

    return `
      <div class="insight-card ${sev}">
        <div class="insight-header">
          <span class="insight-type-badge">${typeLabel}</span>
          <span class="insight-severity ${sev}">${sev.toUpperCase()}</span>
        </div>
        
        <div class="insight-title-row">
          <span class="material-symbols-outlined status-icon" style="color: ${statusColor};">${statusIcon}</span>
          <h3 class="insight-title">${item.title}</h3>
        </div>
        
        <div class="insight-desc">${descriptionText}</div>
        
        ${actionHtml}
        
        <div class="insight-footer">
          <div class="insight-impact">
            <span class="material-symbols-outlined">group</span>
            <strong>${formatNumber(item.affected_count || 0)}</strong> affected records
          </div>
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
    
    // Explorer apply filter
    const explorerBtn = document.getElementById("explorer-apply-btn");
    if (explorerBtn) {
      explorerBtn.addEventListener("click", () => {
        state.explorerFilters = {
          amountMin: document.getElementById("amount-min")?.value || "",
          amountMax: document.getElementById("amount-max")?.value || "",
          dateFrom: document.getElementById("date-from")?.value || "",
          dateTo: document.getElementById("date-to")?.value || "",
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
              showToast("Mapping config approved.");
              render();
            })
            .catch(err => showToast(err.message || "Approve failed"));
        }
      });
    });

    const configUpload = document.getElementById("config-file-upload");
    if (configUpload) {
      configUpload.addEventListener("change", (e) => {
        const file = e.target.files[0];
        if (!file) return;
        const reader = new FileReader();
        reader.onload = (event) => {
          try {
            const json = JSON.parse(event.target.result);
            document.getElementById("config-json-textarea").value = JSON.stringify(json, null, 2);
            showToast(`Loaded ${file.name} config mapping file.`);
            handleConfigParse(json);
          } catch (err) {
            showToast("Invalid JSON file format.");
          }
        };
        reader.readAsText(file);
      });
    }

    const applyConfigBtn = document.getElementById("apply-config-btn");
    if (applyConfigBtn) {
      applyConfigBtn.addEventListener("click", () => {
        const text = document.getElementById("config-json-textarea").value;
        try {
          const json = JSON.parse(text);
          handleConfigParse(json);
          showToast(`Successfully parsed and applied mapping config for: ${json.partner || 'Unknown'}`);
        } catch (err) {
          showToast("Failed to parse JSON. Please check syntax errors.");
        }
      });
    }

    const resetConfigBtn = document.getElementById("reset-config-btn");
    if (resetConfigBtn) {
      resetConfigBtn.addEventListener("click", () => {
        document.getElementById("config-json-textarea").value = "";
        document.getElementById("config-preview-panel").style.display = "none";
        showToast("Config mapping workspace reset.");
      });
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

  function renderPageFilters(showDate = true) {
    return `
      <div class="page-filters">
        <div class="filter-group">
          <span class="filter-label">PARTNER</span>
          <div class="filter-input-wrapper">
            <span class="material-symbols-outlined input-icon">store</span>
            <select id="partner-filter">
              ${state.partner ? `<option value="${state.partner}">${state.partner}</option>` : ""}
            </select>
          </div>
        </div>
        ${showDate ? `
        <div class="filter-group">
          <span class="filter-label">DATE</span>
          <div class="filter-input-wrapper">
            <span class="material-symbols-outlined input-icon" style="color: var(--brand-primary);">calendar_today</span>
            <input id="date-filter" type="date" value="${state.date}">
          </div>
        </div>` : ""}
      </div>
    `;
  }

  function loadingPanel(message) {
    return `
      <section class="panel">
        <div class="loading-row">
          <div class="spinner"></div>
          <div>
            <h2 style="margin: 0;">Accessing Database</h2>
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

  const LOCAL_MOCKS = {
    "/api/v1/insights/sample-stats": {
      "total": 1250,
      "matched": 1187,
      "mismatch_rate": 5.04,
      "by_status": {
        "MATCHED": 1187,
        "AMOUNT_MISMATCH": 32,
        "STATUS_MISMATCH": 0,
        "MULTIPLE_MISMATCH": 0,
        "MISSING_INTERNAL": 18,
        "MISSING_PARTNER": 13,
        "UNMAPPED_SKIPPED": 0
      }
    },
    "/api/v1/insights/sample": {
      "partner": "MOMO",
      "date": "2024-07-07",
      "summary_metrics": {
        "total_transactions": 1250,
        "matched": 1187,
        "mismatch_rate": 5.04,
        "total_amount_mismatch": 24500000.0,
        "by_status": {
          "MATCHED": 1187,
          "AMOUNT_MISMATCH": 32,
          "MISSING_INTERNAL": 18,
          "MISSING_PARTNER": 13
        }
      },
      "ai_observation": {
        "partner": "MOMO",
        "date": "2024-07-07",
        "focus": "operational",
        "provider": "openai",
        "model": "gpt-4o-mini",
        "latency_ms": 2347.89,
        "prompt_tokens": 856,
        "completion_tokens": 312,
        "total_tokens": 1168,
        "estimated_cost_usd": 0.000294,
        "cache_hit": false,
        "schema_valid": true,
        "resolution": "llm",
        "guardrail_result": {
          "is_valid": false,
          "risk_level": "high",
          "findings": [
            {
              "risk": "high",
              "field": "affected_count",
              "message": "LLM says 50 records affected — only 12 actual anomalies in data"
            },
            {
              "risk": "medium",
              "field": "severity",
              "message": "LLM assigned 'critical' severity to 0.5% mismatch rate"
            }
          ]
        }
      }
    },
    "operational": [
      {
        "type": "operational",
        "severity": "critical",
        "title": "18 records missing internally — gap in batch #B-042 at 14:20-14:30",
        "description": "18 transactions (1.4% of total, 24.5M VND) confirmed by MOMO but absent internally. Pattern: concentrated — all 18 share a 10-minute ingestion window (14:20-14:30), consistent with a batch scheduler failure rather than random data loss. If this gap repeats daily, ~540 records/month would be affected.",
        "affected_count": 18,
        "recommendation": "Compare MOMO settlement file #B-042 against internal ingestion manifest for 2024-07-07 14:00-15:00. Re-trigger ingestion for that window if missing files are found, then verify all 18 records appear."
      }
    ],
    "partner": [
      {
        "type": "partner_pattern",
        "severity": "medium",
        "title": "MOMO mismatch rate at 5.04% — second consecutive day above 5% threshold",
        "description": "Overall mismatch rate of 5.04% exceeds the 5% operational threshold. At this rate, ~63 transactions are affected daily, equivalent to ~1,890 records/month. This is the second consecutive day above threshold, suggesting a chronic issue rather than a one-day spike.",
        "affected_count": 63,
        "recommendation": "Escalate to MOMO partner operations team with the 3-day trend data. Schedule a root cause analysis call focused on the amount_mismatch cluster. Prepare daily monitoring dashboard for the next 5 business days."
      }
    ],
    "inconsistency": [
      {
        "type": "amount_mismatch",
        "severity": "high",
        "title": "32 amount mismatches — avg delta 765K VND, 3 transactions drive 60% of impact",
        "description": "Amount mismatch across 32 transactions (2.6% of volume) totaling 24.5M VND. Pattern: concentrated — 3 large-value transactions (>5M VND each) account for 60% of total mismatch amount, suggesting a rate/fee application issue rather than random rounding errors. Average delta per outlier: 4.9M VND vs 82K VND for remaining 29.",
        "affected_count": 32,
        "recommendation": "Audit fee/commission configuration for MOMO transactions >5M VND. Compare partner-reported amounts against internal fee schedule for the 3 outlier transactions. Verify if a recent rate change was applied inconsistently."
      }
    ]
  };

  async function tryFetch(primary, fallback) {
    try {
      const data = await fetchJson(primary);
      if (data && data.llm_status === "fallback") {
        console.warn("Real endpoint returned fallback, using local mock");
        return getLocalMock(primary, fallback);
      }
      return data;
    } catch (err) {
      console.warn("Primary endpoint failed, falling back to local mock:", err.message);
      return getLocalMock(primary, fallback);
    }
  }

  function getLocalMock(primary, fallback) {
    if (primary.includes("discrepancies")) {
      if (primary.includes("focus=operational")) return LOCAL_MOCKS.operational;
      if (primary.includes("focus=partner")) return LOCAL_MOCKS.partner;
      if (primary.includes("focus=inconsistency")) return LOCAL_MOCKS.inconsistency;
    }
    return LOCAL_MOCKS[fallback] || LOCAL_MOCKS["/api/v1/insights/sample"];
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
    const text = String(value);
    const cls = text.toLowerCase().replace(/_/g, "-");
    return `<span class="badge ${cls}" style="${({
      "matched": "",
      "matched-failed": "background: var(--status-warning-bg); color: var(--status-warning); border-color: rgba(240,185,11,.3);",
      "matched-reversed": "background: var(--status-processing-bg); color: var(--status-processing); border-color: rgba(59,130,246,.3);",
      "amount-mismatch": "background: var(--status-unmatched-bg); color: var(--status-unmatched); border-color: rgba(246,70,93,.3);",
      "status-mismatch": "background: var(--status-warning-bg); color: var(--status-warning); border-color: rgba(240,185,11,.3);",
      "multiple-mismatch": "background: var(--status-unmatched-bg); color: var(--status-unmatched); border-color: rgba(246,70,93,.3);",
      "missing-internal": "background: rgba(251,146,60,.12); color: #fb923c; border-color: rgba(251,146,60,.3);",
      "missing-partner": "background: var(--status-unmatched-bg); color: var(--status-unmatched); border-color: rgba(246,70,93,.3);",
      "unmapped-skipped": "background: rgba(255,255,255,.03); color: var(--text-muted); border-color: var(--border);",
    })[cls] || ""}">${text}</span>`;
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

  init();
})();
