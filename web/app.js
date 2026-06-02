(function () {
  const state = {
    route: "overview",
    partner: "MOMO",
    date: "2024-07-07",
    focus: "operational",
    reconStatus: ""
  };

  const routes = [
    ["overview", "Overview", "dashboard"],
    ["scheduler", "Scheduler", "calendar_today"],
    ["reconciliation", "Reconciliation", "fact_check"],
    ["insights", "AI Insights", "analytics"],
    ["settings", "Mapping & Settings", "account_tree"]
  ];

  const view = document.getElementById("view");
  const title = document.getElementById("page-title");
  const subtitle = document.getElementById("page-subtitle");
  const nav = document.getElementById("nav");
  const partnerFilter = document.getElementById("partner-filter");
  const dateFilter = document.getElementById("date-filter");
  const toast = document.getElementById("toast");

  function init() {
    renderNav();
    fetchPartners();
    bindFilters();
    window.addEventListener("hashchange", onRouteChange);
    onRouteChange();
  }

  function fetchPartners() {
    fetch("/api/v1/data/stats?date=" + state.date)
      .then(r => r.json())
      .then(data => {
        const partners = Object.keys(data.by_partner || {});
        if (partners.length) {
          partnerFilter.innerHTML = partners.map(p =>
            `<option value="${p}" ${p === state.partner ? "selected" : ""}>${p}</option>`
          ).join("");
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
    partnerFilter.addEventListener("change", () => {
      state.partner = partnerFilter.value;
      render();
    });
    dateFilter.addEventListener("change", () => {
      state.date = dateFilter.value;
      render();
    });
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
      view.innerHTML = loadingPanel("Loading overview dashboard...");
      try {
        const data = await fetchJson(`/api/v1/insights/summary?partner=${encodeURIComponent(state.partner)}&date=${encodeURIComponent(state.date)}`);
        view.innerHTML = renderOverview(data);
      } catch (err) {
        view.innerHTML = renderError(err);
      }
      bindViewActions();
      return;
    }

    if (state.route === "insights") {
      view.innerHTML = loadingPanel("Loading AI discrepancies & insights...");
      try {
        const [summary, discrepancies] = await Promise.all([
          fetchJson(`/api/v1/insights/summary?partner=${encodeURIComponent(state.partner)}&date=${encodeURIComponent(state.date)}`),
          fetchJson(`/api/v1/insights/discrepancies?partner=${encodeURIComponent(state.partner)}&date=${encodeURIComponent(state.date)}&focus=${encodeURIComponent(state.focus)}`)
        ]);
        view.innerHTML = renderInsights(summary, discrepancies);
      } catch (err) {
        view.innerHTML = renderError(err);
      }
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

  function renderOverview(data) {
    const m = data.summary_metrics || {};
    const byStatus = m.by_status || {};
    const total = m.total_transactions || 0;
    const matched = m.matched || 0;
    const failed = Math.max(0, total - matched);
    const mismatchRate = m.mismatch_rate || 0;
    const mismatchAmount = m.total_amount_mismatch ? formatAmount(m.total_amount_mismatch) : "-";
    const matchedPct = total ? Math.round((matched / total) * 100) : 0;
    
    // Auto detect anomaly status warning
    let matchQualityStatus = `<span class="badge matched">HEALTHY</span>`;
    if (mismatchRate > 5) {
      matchQualityStatus = `<span class="badge critical">CRITICAL ANOMALY</span>`;
    } else if (mismatchRate > 2) {
      matchQualityStatus = `<span class="badge missing-internal">WARNING</span>`;
    }

    return `
      ${metrics([
        ["Total Transactions", formatNumber(total), state.partner],
        ["Matched Records", formatNumber(matched), `${failed} mismatched/failed`],
        ["Mismatch Rate", mismatchRate + "%", matchQualityStatus],
        ["Mismatch Volume", mismatchAmount, "from current stream"]
      ])}
      
      <div class="grid cols-2">
        <section class="panel">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;">
            <h2 style="margin: 0;">Reconciliation Quality</h2>
            <span style="font-size: 11px; color: var(--text-muted);">Threshold limit: 5%</span>
          </div>
          ${bars([
            ["Matched Transactions", matchedPct, "green"],
            ["Total Mismatch Rate", Math.min(mismatchRate, 100), mismatchRate > 5 ? "red" : "amber"],
            ["Missing Internal Records", percent(byStatus.MISSING_INTERNAL || 0, total), "amber"],
            ["Missing Partner Records", percent(byStatus.MISSING_PARTNER || 0, total), "red"]
          ])}
        </section>
        
        <section class="panel" style="display: flex; flex-direction: column; align-items: center; justify-content: center;">
          <h2 style="align-self: flex-start; margin-bottom: 8px;">Success Rate Distribution</h2>
          ${donut(Math.max(0, 100 - mismatchRate), "Total Match Quality")}
        </section>
      </div>
    `;
  }

  function renderInsights(summary, discrepancies) {
    const options = ["operational", "partner", "inconsistency"].map(focus =>
      `<option value="${focus}" ${focus === state.focus ? "selected" : ""}>${focus}</option>`
    ).join("");
    const items = Array.isArray(discrepancies) ? discrepancies : [];
    
    // Render custom mapped severity logic
    const cards = items.length
      ? items.map(item => {
          // If severity is undefined, calculate it based on affected count
          if (!item.severity) {
            item.severity = (item.affected_count > 100) ? "critical" : (item.affected_count > 10) ? "medium" : "low";
          }
          return insightCard(item);
        }).join("")
      : `<div class="empty-state" style="grid-column: span 3; text-align: center; padding: 40px 0;">No active anomalies found for focus: ${state.focus}.</div>`;
    
    return `
      <div class="toolbar">
        <label>
          ANOMALY FILTER CATEGORY
          <select id="focus-filter">${options}</select>
        </label>
        <button class="button primary" data-action="generate-insights">
          <span class="material-symbols-outlined">auto_awesome</span>
          Generate AI Insights
        </button>
      </div>
      <div class="grid cols-3">${cards}</div>
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
      ${toolbarHtml}
      <section class="panel">
        <div class="panel-header" style="margin-bottom: 20px;">
          <h2>Reconciliation Ledger (${formatNumber(data.total || items.length)} transactions)</h2>
        </div>
        ${table(headers, rows)}
      </section>
    `;
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
    if (sev === "critical") statusIcon = "dangerous";
    else if (sev === "high") statusIcon = "warning";
    else if (sev === "medium") statusIcon = "report";
    
    return `
      <div class="insight-card" style="border-left-color: ${sev === 'critical' ? 'var(--critical)' : 'var(--green-primary)'};">
        <div class="insight-header">
          <span class="insight-type" style="color: ${sev === 'critical' ? 'var(--critical)' : 'var(--green-primary)'};">${item.type || state.focus}</span>
          <span class="insight-severity ${sev}">${sev.toUpperCase()}</span>
        </div>
        <div class="insight-title" style="display: flex; align-items: center; gap: 8px;">
          <span class="material-symbols-outlined" style="font-size: 18px; color: ${sev === 'critical' ? 'var(--critical)' : 'var(--green-primary)'};">${statusIcon}</span>
          ${item.title}
        </div>
        <div class="insight-desc">${item.recommendation || item.description || ""}</div>
        <small style="color: var(--text-muted); display: block; margin-top: 8px; border-top: 1px solid rgba(255,255,255,0.05); padding-top: 8px;">
          <span class="material-symbols-outlined" style="font-size: 14px; vertical-align: middle;">group</span>
          <strong>${item.affected_count || 0}</strong> records affected
        </small>
      </div>
    `;
  }

  function bindViewActions() {
    const focus = document.getElementById("focus-filter");
    if (focus) {
      focus.addEventListener("change", () => {
        state.focus = focus.value;
        render();
      });
    }
    const reconStatus = document.getElementById("recon-status-filter");
    if (reconStatus) {
      reconStatus.addEventListener("change", () => {
        state.reconStatus = reconStatus.value;
        render();
      });
    }
    
    // Actions triggers
    document.querySelectorAll("[data-action]").forEach(el => {
      el.addEventListener("click", (e) => {
        const action = el.dataset.action;
        if (action === "generate-insights") {
          showToast("AI Insights generation triggered...");
        } else if (action === "run-job") {
          showToast(`Manual triggers active for partner: ${el.dataset.partner}`);
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
    return `<span class="badge ${text.toLowerCase().replace(/_/g, "-")}">${text}</span>`;
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
