export function createMappingStudioRenderer(deps) {
  const {
    state,
    badge,
    escapeHtml,
    formatDisplayDate,
    formatDisplayDateTime,
    renderPageFilters,
  } = deps;

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
      const mappingsHtml = (config.fieldMappings || []).map(fm => `
        <div class="mapping-grid" style="margin-bottom: 8px;">
          <div class="mapping-card" style="padding: 10px 16px;">
            <div><strong>${escapeHtml(fm.path)}</strong></div>
            <div style="font-size: 11px; color: var(--text-muted);">
              ${fm.column ? `Col: ${escapeHtml(fm.column)}` : fm.constant ? `Const: ${escapeHtml(fm.constant)}` : "-"}
            </div>
          </div>
          <div class="mapping-arrow"><span class="material-symbols-outlined" style="font-size: 18px;">arrow_forward</span></div>
          <div class="mapping-card" style="padding: 10px 16px;">
            <code style="font-size: 11px;">${escapeHtml(fm.type)}</code>
            <div style="font-size: 10px; color: var(--text-muted); margin-top: 2px;">
              ${fm.required ? '<span style="color: var(--status-unmatched);">Required</span>' : "Optional"}
              ${fm.mapping ? `<span style="color: var(--brand-accent-blue); margin-left: 4px;">• ${Object.keys(fm.mapping).length} rules</span>` : ""}
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
              <strong style="font-size: 20px;">${escapeHtml(config.configVersion || "latest")}</strong>
            </div>
            <div class="metric" style="padding: 16px;">
              <span>File Type</span>
              <strong style="font-size: 20px;">${escapeHtml(config.fileType || "SETTLEMENT")}</strong>
            </div>
            <div class="metric" style="padding: 16px;">
              <span>Sheet / Row</span>
              <strong style="font-size: 20px;">${escapeHtml(config.sheetName || "-")} / ${config.startRow || 2}</strong>
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
        <div class="studio-step-item ${s.step === 1 ? "active" : ""}">
          <span class="studio-step-index">1</span>
          Select Sample
        </div>
        <div class="studio-step-item ${s.step === 2 ? "active" : ""} ${s.step >= 2 ? "enabled" : ""}">
          <span class="studio-step-index">2</span>
          Review Draft
        </div>
        <div class="studio-step-item ${s.step === 3 ? "active" : ""} ${s.step >= 3 ? "enabled" : ""}">
          <span class="studio-step-index">3</span>
          Validate Output
        </div>
      </div>
    `;

    if (s.step === 1) {
      return `
        <section class="panel" style="margin-bottom: 24px;">
          ${embedded ? "" : `<h2>Create Draft Mapping</h2>
          <p class="muted" style="margin-bottom: 24px;">Upload a partner sample, review the draft mapping, then send it to Review Center.</p>`}

          ${stepsHeader}

          <div class="grid cols-3 studio-validation-grid">
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

    if (s.step === 2) {
      let previewHtml = "";
      if (s.headers && s.headers.length) {
        const previewHeaders = s.headers.map(h => `<th style="text-align: left; padding: 10px;">${escapeHtml(h)}</th>`).join("");
        const previewRows = s.sampleRows.slice(0, 10).map((row, rIdx) => {
          const cells = row.map(c => `<td style="padding: 10px; border-top: 1px solid var(--border); font-size:12px;">${escapeHtml(String(c || ""))}</td>`).join("");
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

      const configJsonStr = s.config ? JSON.stringify(s.config, null, 2) : "";
      const fieldMappings = (s.config?.fieldMappings || []).filter(fm => fm.path !== "currency");
      const mappingRows = fieldMappings.map((fm, idx) => {
        const path = fm.path || "";
        const col = fm.column !== undefined ? fm.column : "";
        const constVal = fm.constant !== undefined ? fm.constant : "";
        const type = fm.type || "STRING";
        const isRequired = fm.required ? "Yes" : "No";
        const confidenceVal = s.config?.configHealth?.confidence || 0.85;
        const confidencePct = Math.round(confidenceVal * 100);
        let badgeClass = "neutral";
        let label = "Medium";
        if (confidencePct >= 90) {
          badgeClass = "matched";
          label = "High";
        } else if (confidencePct < 80) {
          badgeClass = "critical";
          label = "Needs Review";
        }

        return `
          <tr>
            <td style="padding: 12px 16px; font-weight:600; color: var(--text-primary); border-top:1px solid var(--border);">${escapeHtml(path)}</td>
            <td style="padding: 12px 16px; border-top:1px solid var(--border);">
              <select class="studio-mapping-col-select" data-idx="${idx}" style="font-size:12px; padding: 4px 8px; background: var(--bg-primary); border: 1px solid var(--border); border-radius: 4px; outline:none; color:var(--text-primary);">
                <option value="">-- Constant Only --</option>
                ${s.headers.map((h, hIdx) => `<option value="${hIdx + 1}" ${col === (hIdx + 1) ? "selected" : ""}>Col ${hIdx + 1}: ${h}</option>`).join("")}
              </select>
            </td>
            <td style="padding: 12px 16px; border-top:1px solid var(--border);">
              <input type="text" class="studio-mapping-const-input" data-idx="${idx}" value="${escapeHtml(String(constVal))}" style="font-size:12px; padding: 4px 8px; background: var(--bg-primary); border: 1px solid var(--border); border-radius: 4px; outline:none; color:var(--text-primary); width:100px;" placeholder="Constant...">
            </td>
            <td style="padding: 12px 16px; border-top:1px solid var(--border);">
              <select class="studio-mapping-type-select" data-idx="${idx}" style="font-size:12px; padding: 4px 8px; background: var(--bg-primary); border: 1px solid var(--border); border-radius: 4px; outline:none; color:var(--text-primary);">
                <option value="STRING" ${type === "STRING" ? "selected" : ""}>STRING</option>
                <option value="DECIMAL" ${type === "DECIMAL" ? "selected" : ""}>DECIMAL</option>
                <option value="DATE" ${type === "DATE" ? "selected" : ""}>DATE</option>
                <option value="CONSTANT" ${type === "CONSTANT" ? "selected" : ""}>CONSTANT</option>
              </select>
            </td>
            <td style="padding: 12px 16px; border-top:1px solid var(--border);"><span class="badge ${isRequired === "Yes" ? "warning" : "neutral"}">${isRequired}</span></td>
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

          <div class="studio-toolbar">
            <div class="studio-toolbar-tabs">
              <button class="button active studio-tab-button" id="studio-tab-visual">Visual Mapping</button>
              <button class="button studio-tab-button" id="studio-tab-json">Schema JSON</button>
            </div>

            <div>
              <button class="button button-ghost" id="studio-add-field-btn" style="height:32px; padding:0 12px; font-size:12px;">+ Add Mapping Row</button>
            </div>
          </div>

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

    if (s.step === 3) {
      const score = s.validation?.score || 100;
      let scoreClass = "matched";
      let scoreLabel = "Excellent";
      if (score < 75) {
        scoreClass = "critical";
        scoreLabel = "Review Needed";
      } else if (score < 90) {
        scoreClass = "warning";
        scoreLabel = "Good";
      }

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

      let testOutputHtml = `<div class="empty-state" style="padding: 24px; text-align:center;">Click "Run Transformation Test" to verify output layout.</div>`;
      if (s.testOutput) {
        testOutputHtml = `
          <textarea readonly style="width:100%; min-height: 180px; font-family: monospace; background: var(--bg-primary); border: 1px solid var(--border); padding: 12px; border-radius: 6px; color: #5bc0be; outline: none; line-height: 1.4; font-size: 13px;">${JSON.stringify(s.testOutput, null, 2)}</textarea>
        `;
      }

      const versionRows = (s.versions || []).map(v => `
        <tr style="border-top:1px solid var(--border);">
          <td style="padding:10px 12px; font-weight:700;">${escapeHtml(v.configVersion || "latest")}</td>
          <td style="padding:10px 12px; color:var(--text-muted);">${escapeHtml(v.publishedAt ? formatDisplayDateTime(v.publishedAt) : "N/A")}</td>
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
            <div class="panel studio-validation-card">
              <div>
                <h3 style="margin: 0 0 16px 0; font-size:14px; text-transform:uppercase; letter-spacing:0.05em; color:var(--text-muted);">Mapping Quality Score</h3>
                <div style="display:flex; align-items:baseline; gap:8px; margin-bottom:8px;">
                  <strong style="font-size:36px; color:${score < 75 ? "var(--status-unmatched)" : "var(--brand-primary)"};">${score}</strong>
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

            <div class="panel studio-validation-card studio-version-card">
              <div>
                <h3 style="margin:0 0 12px 0; font-size:14px; text-transform:uppercase; letter-spacing:0.05em; color:var(--text-muted);">Schema Versions</h3>
                <div class="table-wrap" style="max-height:160px; overflow-y:auto; border:1px solid var(--border); border-radius:4px;">
                  ${versionsTable}
                </div>
              </div>
            </div>
          </div>

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

  return {
    renderApprovalUploadEntry,
    renderMappings,
    renderSettings,
    renderSubmitSamplePage,
  };
}
