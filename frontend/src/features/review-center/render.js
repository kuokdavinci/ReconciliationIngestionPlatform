export function createReviewCenterRenderer(deps) {
  const {
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
    renderPageFilters,
    statusLabel,
    summarizeReviewPacket,
    table,
  } = deps;

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
    const gates = Array.isArray(selectedPacket.validationGates) ? selectedPacket.validationGates : [];

    const gateRowsHtml = gates.length ? gates.map(gate => {
      const gStatus = String(gate.status || 'pending').toLowerCase();
      const gIcon = gStatus === 'pass' ? 'check_circle' : gStatus === 'fail' ? 'cancel' : 'hourglass_top';
      const gColor = gStatus === 'pass' ? '#10B981' : gStatus === 'fail' ? '#EF4444' : '#F59E0B';
      const gClass = gStatus === 'pass' ? '' : gStatus === 'fail' ? 'fail' : 'warn';
      return `
        <div class="gate-row ${gClass}">
          <div style="display:flex; gap:8px; align-items:center; min-width:0;">
            <span class="material-symbols-outlined" style="font-size:18px; color:${gColor};">${gIcon}</span>
            <div style="min-width:0;">
              <strong style="display:block; font-size:13px;">${escapeHtml(gate.gateKey?.replace(/_/g, ' ') || 'Gate')}</strong>
              <span class="muted" style="font-size:11px;">${escapeHtml(gate.message || gStatus)}</span>
            </div>
          </div>
          <span class="badge ${gStatus === 'pass' ? 'matched' : gStatus === 'fail' ? 'failed' : 'warning'}" style="font-size:10px; flex-shrink:0;">${gStatus.toUpperCase()}</span>
        </div>
      `;
    }).join('') : `<div class="muted" style="font-size:12px; padding:8px 0;">No validation gates recorded.</div>`;

    return `
      <aside class="review-drawer review-summary-drawer">
        <div class="review-drawer-header">
          <div>
            <h3 style="margin:0 0 6px 0; font-size:16px; font-weight:700;">${escapeHtml(shortTitle)}</h3>
            <p class="muted" style="margin:0; font-size:13px; line-height:1.5;">${escapeHtml(shortReason)}</p>
          </div>
          <div style="display:flex; gap:6px; flex-wrap:wrap; flex-shrink:0;">
            <span class="badge ${risk === 'critical' || risk === 'high' ? 'failed' : 'warning'}" style="font-size:10px;">${escapeHtml(risk.toUpperCase())} RISK</span>
            ${reviewSummary.runtimeValidated ? '<span class="badge matched" style="font-size:10px;">Validated</span>' : '<span class="badge warning" style="font-size:10px;">Pending</span>'}
          </div>
        </div>

        <div class="drawer-section">
          <h4>Overview</h4>
          <div class="drawer-meta-grid">
            <div><span class="muted" style="font-size:11px;">FILE</span><strong style="font-size:13px; word-break:break-all;">${escapeHtml(selectedPacket.fileName || '-')}</strong></div>
            <div><span class="muted" style="font-size:11px;">RISK LEVEL</span><strong style="font-size:13px;">${escapeHtml(risk.charAt(0).toUpperCase() + risk.slice(1))}</strong></div>
            <div><span class="muted" style="font-size:11px;">RUNTIME</span><strong style="font-size:13px;">${selectedPacket.activeRuntimeConfigId ? 'Active' : 'None'}</strong></div>
            <div><span class="muted" style="font-size:11px;">DRAFT MAPPING</span><strong style="font-size:13px;">${reviewSummary.mappingReady ? 'Ready' : 'Missing'}</strong></div>
          </div>
        </div>

        <div class="drawer-section">
          <h4>Validation gates</h4>
          <div class="gate-list">
            ${gateRowsHtml}
          </div>
        </div>

        <div style="margin-top:20px; display:flex; gap:10px; flex-direction:column;">
          <button class="button primary" data-action="open-guided-review" style="width:100%; justify-content:center;">
            <span class="material-symbols-outlined" style="font-size:18px; margin-right:4px;">quickreply</span> Open Review Panel
          </button>
          <button class="button secondary-action" data-action="go-mapping-studio" style="width:100%; justify-content:center;">
            <span class="material-symbols-outlined" style="font-size:18px; margin-right:4px;">schema</span> Open Mapping Studio
          </button>
        </div>
      </aside>
    `;
  }

  function renderReviewHistoryTab() {
    if (state.reviewHistoryLoading) {
      return loadingPanel("Loading decision history...");
    }
    const history = state.reviewHistoryCache || { decisions: [], reconNotes: [] };
    const postApprovalRuns = Object.values(state.postApprovalRuns || {}).sort((a, b) => {
      const left = new Date(b.updatedAt || b.createdAt || 0).getTime();
      const right = new Date(a.updatedAt || a.createdAt || 0).getTime();
      return left - right;
    });
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
    const postRunRows = postApprovalRuns.length ? postApprovalRuns.map(run => `
      <tr>
        <td><code>${escapeHtml(run.packetId || "-")}</code></td>
        <td>${badge(run.status || "-")}</td>
        <td>${escapeHtml(run.stage || "-")}</td>
        <td>${escapeHtml(run.message || "-")}</td>
        <td>${escapeHtml(formatDisplayDateTime(run.updatedAt || run.createdAt || "-"))}</td>
      </tr>
    `).join("") : `<tr><td colspan="5" style="text-align:center; padding: 24px 0; color: var(--text-muted);">No post-approval runs tracked in this session.</td></tr>`;

    return `
      <section class="panel">
        <div class="panel-header" style="margin-bottom: 16px;">
          <div>
            <h2 style="margin: 0; font-size: 18px;">Post-Approval Runs</h2>
            <p class="section-subtitle">Background execution status after approving a review packet.</p>
          </div>
        </div>
        ${table(["Packet", "Status", "Stage", "Message", "Updated At"], postRunRows)}
      </section>
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
    if (!state.guidedReviewOpen || !selectedPacket) return "";
    if (!state.guidedReviewStep) state.guidedReviewStep = 1;

    const step = state.guidedReviewStep;
    const stepsList = ["Scope", "Mapping", "Validation", "Decision"];
    const progressSteps = stepsList.map((s, i) => {
      const stepIdx = i + 1;
      const isActive = stepIdx === step;
      const isDone = stepIdx < step;
      return `
        <div class="brief-step ${isActive ? "active" : isDone ? "done" : ""}" style="flex: 1; text-align: center; padding: 10px;">
          <span class="brief-step-dot" style="display: block; margin: 0 auto 8px; width: 28px; height: 28px; line-height: 28px; border-radius: 50%; background: ${isDone ? "#10B981" : isActive ? "var(--brand-accent-blue)" : "rgba(255,255,255,0.1)"}; color: #000; font-weight: 700;">${isDone ? "✓" : stepIdx}</span>
          <span class="brief-step-name" style="font-size: 11px; display: block; color: ${isActive ? "#FFF" : "var(--text-muted)"};">${s}</span>
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
        const currentScope = state.guidedReviewScopeChoice || selectedPacket.scopeType || scopeData.suggestedScope || "FULL_SNAPSHOT";
        const selectedConfidence = Math.round((scopeData.probabilities?.[currentScope] || 0) * 100);
        const recommendationTone = selectedConfidence >= 85 ? {
          border: "#10B981",
          bg: "rgba(16,185,129,0.10)",
          badge: "matched",
          label: "High confidence"
        } : selectedConfidence >= 60 ? {
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
          <section
            class="panel"
            id="guided-scope-summary"
            data-probabilities='${escapeHtml(JSON.stringify(scopeData.probabilities || {}))}'
            data-reasoning="${escapeHtml(scopeData.reasoning || "")}"
            style="margin:0 0 16px 0; padding:22px; border-radius:12px; border:1px solid ${recommendationTone.border}; background:${recommendationTone.bg}; box-shadow: inset 0 0 0 1px rgba(255,255,255,0.03);"
          >
            <div style="display:flex; justify-content:space-between; gap:12px; align-items:flex-start; flex-wrap:wrap; margin-bottom:14px;">
              <div>
                <div id="guided-scope-summary-label" style="font-size:11px; text-transform:uppercase; letter-spacing:0.06em; color:${recommendationTone.border}; font-weight:800; margin-bottom:6px;">Recommended file scope</div>
                <h3 id="guided-scope-summary-title" style="margin:0; font-size:24px; line-height:1.2;">${escapeHtml(currentScope.replace(/_/g, " "))}</h3>
              </div>
              <div style="display:flex; flex-direction:column; gap:8px; align-items:flex-end;">
                <span id="guided-scope-summary-badge" class="badge ${recommendationTone.badge}">${recommendationTone.label}</span>
                <strong id="guided-scope-summary-confidence" style="font-size:22px; font-family:var(--font-mono); color:${recommendationTone.border};">${selectedConfidence}%</strong>
              </div>
            </div>
            <div id="guided-scope-summary-meta" style="font-size:15px; line-height:1.6; color:#F8FAFC; font-weight:600; margin-bottom:12px;">
              ${escapeHtml(scopeOptionMeta[currentScope] || "This is the suggested operating mode for the uploaded file based on record shape and count alignment.")}
            </div>
            <div style="display:grid; grid-template-columns:1fr; gap:10px;">
              <div style="padding:14px 16px; border-radius:10px; background:rgba(0,0,0,0.18); border:1px solid rgba(255,255,255,0.08);">
                <strong style="display:block; margin-bottom:6px; font-size:12px; color:#FFFFFF;">Why this option was selected</strong>
                <div id="guided-scope-summary-reasoning" style="font-size:13px; line-height:1.6; color:#E2E8F0;">${escapeHtml(scopeData.reasoning)}</div>
              </div>
            </div>
          </section>
          <section class="panel" style="margin:0; padding:20px; border-radius:10px;">
            <h4 style="margin:0 0 16px 0; font-size:14px;">Confirm your reconciliation file scope</h4>
            <div style="display:grid; grid-template-columns:1fr 1fr 1fr; gap:12px;">
              ${[
                ["FULL_SNAPSHOT", "Full Snapshot", "Overwrite the day snapshot with the uploaded file."],
                ["INCREMENTAL_APPEND", "Incremental Append", "Append new partner rows without wiping prior data."],
                ["REPLACEMENT", "Replacement", "Update matching rows when this file is a correction batch."],
              ].map(([value, label, desc]) => `
                <label class="scope-select-card ${currentScope === value ? "selected" : ""}" data-scope-value="${value}" style="display:flex; flex-direction:column; gap:8px; padding:16px; border-radius:10px; cursor:pointer; text-align:left;">
                  <input type="radio" name="guided-scope-choice" value="${value}" ${currentScope === value ? "checked" : ""} onchange="window.updateGuidedScopeChoice('${value}')" style="display:none;">
                  <strong style="font-size:13px;">${label}</strong>
                  <span class="muted" style="font-size:12px; line-height:1.5;">${desc}</span>
                </label>
              `).join("")}
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
      const sourceBackedMappings = draftFieldMappings.filter(mapping =>
        mapping.type !== "CONSTANT" && !(mapping.mapping && (mapping.column === null || mapping.column === undefined || mapping.column === ""))
      );
      const constantMappings = draftFieldMappings.filter(mapping =>
        mapping.type === "CONSTANT" || (mapping.mapping && (mapping.column === null || mapping.column === undefined || mapping.column === ""))
      );
      const editableMappingRows = !state.guidedReviewAI.loading && !state.guidedReviewAI.error && aiMapping ? sourceBackedMappings.map((mapping, index) => {
        const sourceColumn = Number(mapping.column || 0);
        const headerLabel = sourceColumn > 0 && sigHeaders[sourceColumn - 1] ? sigHeaders[sourceColumn - 1] : (mapping.sourceField || `Column ${sourceColumn || "?"}`);
        const currentMap = mapping.path || "";
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
          </tr>
        `;
      }).join("") : "";
      const constantMappingCards = !state.guidedReviewAI.loading && !state.guidedReviewAI.error && aiMapping ? constantMappings.map(mapping => {
        const keyLabel = mapping.path || "field";
        const valueLabel = mapping.type === "CONSTANT"
          ? (mapping.constant || "-")
          : mapping.mapping
            ? "Mapped by configured rule"
            : "-";
        const sourceLabel = mapping.type === "CONSTANT"
          ? "Constant value"
          : "Rule mapping";
        return `
          <div style="padding:14px 16px; border-radius:10px; background:rgba(255,255,255,0.02); border:1px solid rgba(255,255,255,0.08);">
            <div style="display:flex; justify-content:space-between; gap:12px; align-items:flex-start; margin-bottom:8px;">
              <strong style="font-size:13px; color:#FFFFFF;">${escapeHtml(keyLabel)}</strong>
              <span class="badge neutral">${escapeHtml(sourceLabel)}</span>
            </div>
            <div style="font-size:15px; font-weight:700; color:#E2E8F0;">${escapeHtml(String(valueLabel))}</div>
          </div>
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
      const requiredFromSourceCount = requiredCanonicalFields.filter(field => draftFieldMappings.some(mapping => mapping.path === field && mapping.column !== null && mapping.column !== undefined && mapping.column !== "")).length;
      const requiredFromConstantsCount = requiredCanonicalFields.filter(field => draftFieldMappings.some(mapping => mapping.path === field && (mapping.type === "CONSTANT" || (mapping.mapping && mapping.type === "MAPPING" && (mapping.column === null || mapping.column === undefined || mapping.column === ""))))).length;
      const requiredCoveredCount = requiredCanonicalFields.filter(field => draftFieldMappings.some(mapping => mapping.path === field)).length;
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
          <section class="panel" style="margin:0 0 16px 0; padding:22px; border-radius:12px; border:1px solid #10B981; background:rgba(16,185,129,0.10); box-shadow: inset 0 0 0 1px rgba(255,255,255,0.03);">
            <div style="display:flex; justify-content:space-between; gap:12px; align-items:flex-start; flex-wrap:wrap; margin-bottom:14px;">
              <div>
                <div style="font-size:11px; text-transform:uppercase; letter-spacing:0.06em; color:#10B981; font-weight:800; margin-bottom:6px;">Recommended mapping setup</div>
                <h3 style="margin:0; font-size:24px; line-height:1.2;">${escapeHtml(`${mappedFieldCount} canonical fields mapped`)}</h3>
              </div>
              <div style="display:flex; flex-direction:column; gap:8px; align-items:flex-end;">
                <span class="badge matched">Ready to review</span>
                ${confidencePct !== null ? `<strong style="font-size:22px; font-family:var(--font-mono); color:#10B981;">${escapeHtml(String(confidencePct))}%</strong>` : ""}
              </div>
            </div>
            <div style="font-size:15px; line-height:1.6; color:#F8FAFC; font-weight:600; margin-bottom:12px;">
              ${escapeHtml(`The current draft covers ${requiredCoveredCount}/${requiredCanonicalFields.length} required canonical fields and uses ${selectedSourceColumnCount} source columns that matter for runtime processing.`)}
            </div>
            <div style="display:grid; grid-template-columns:1fr; gap:10px;">
              <div style="padding:14px 16px; border-radius:10px; background:rgba(0,0,0,0.18); border:1px solid rgba(255,255,255,0.08);">
                <strong style="display:block; margin-bottom:6px; font-size:12px; color:#FFFFFF;">Why this mapping is recommended</strong>
                <div style="font-size:13px; line-height:1.6; color:#E2E8F0;">
                  ${escapeHtml(`${sigHeaders.length} partner columns were detected, but only ${selectedSourceColumnCount} candidate columns are currently selected to populate ${mappedFieldCount} canonical mapping fields. Runtime processing only depends on relevant source columns, constants, and rules.`)}
                  ${candidateColumnLabels.length ? `<div style="margin-top:8px; color:var(--text-muted);">Top candidate columns: ${escapeHtml(candidateColumnLabels.join(", "))}</div>` : ""}
                  ${confidencePct !== null ? `<div style="margin-top:8px; color:var(--text-muted);">Overall AI confidence: ${escapeHtml(String(confidencePct))}%</div>` : ""}
                </div>
              </div>
            </div>
          </section>
          <section class="panel" style="margin:0; padding:20px; border-radius:10px;">
            <h4 style="margin:0 0 16px 0; font-size:15px; border-bottom:1px solid rgba(255,255,255,0.06); padding-bottom:8px; color:var(--brand-accent-blue);">AI Suggestion / Draft Mapping</h4>
            <p class="muted" style="margin:0 0 12px 0;">Use the AI draft if it is good enough, or open Mapping Studio for a full edit.</p>
            ${constantMappings.length ? `
              <div style="margin:0 0 16px 0;">
                <div style="font-size:11px; text-transform:uppercase; letter-spacing:0.06em; color:var(--text-muted); font-weight:800; margin-bottom:10px;">Runtime constants and rule-based values</div>
                <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(180px, 1fr)); gap:12px;">
                  ${constantMappingCards}
                </div>
              </div>
            ` : ""}
            <div class="table-wrap"><table style="width:100%; border-collapse:collapse; font-size: 12px;">
              <thead><tr style="background:rgba(255,255,255,0.05)"><th>Partner Column</th><th>Populate Via</th><th>Canonical Field</th></tr></thead>
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
      const issues = collectValidationIssues(runtimeGate);
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
          ${renderGuidedSampleRuntimePanel(selectedPacket, runtimeGate)}
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
        </div>
      `;
    } else if (step === 4) {
      const validationState = getRuntimeValidationState(selectedPacket);
      const isMappingReady = !!selectedPacket.draftMappingId;
      const isReady = isMappingReady && validationState.canProceed;
      const packetApproved = String(selectedPacket.status || "").toUpperCase() === "APPROVED";
      const postApprovalRun = getPostApprovalRunForPacket(selectedPacket._id);
      const hasPostApprovalRun = !!postApprovalRun;
      const postApprovalStatus = String(postApprovalRun?.status || "").toUpperCase();
      const postApprovalActive = hasPostApprovalRun && !isTerminalPostApprovalRun(postApprovalRun);
      const postApprovalCompleted = postApprovalStatus === "COMPLETED";
      const postApprovalTone = postApprovalStatus === "COMPLETED" ? "matched" : postApprovalStatus === "FAILED" ? "failed" : "warning";
      const postApprovalStage = String(postApprovalRun?.stage || "").toUpperCase();
      const ingestActive = postApprovalActive && ["QUEUED", "FETCHING", "INGESTING", "WAITING_REVIEW"].includes(postApprovalStage || postApprovalStatus);
      const ingestDone = postApprovalCompleted || ["WAITING_RECONCILE", "RECONCILING", "COMPLETED"].includes(postApprovalStage || postApprovalStatus);
      const reconcileActive = postApprovalActive && ["WAITING_RECONCILE", "RECONCILING"].includes(postApprovalStage || postApprovalStatus);
      const reconcileDone = postApprovalCompleted;
      const recommendation = isReady
        ? "The latest draft mapping is ready for approval and activation."
        : validationState.isStale
          ? "Validation is stale. Return to Step 3 and re-run runtime validation on the current draft mapping."
          : validationState.summaryLabel === "Failed"
            ? "Validation failed. Return to Step 3 and resolve the runtime mapping issues before approval."
            : "A current runtime validation is required before approval.";
      const activationProgressHtml = hasPostApprovalRun ? `
        <section class="panel" style="margin:0; padding:16px; border-radius:10px; border:1px solid rgba(255,255,255,0.08); background: rgba(255,255,255,0.015);">
          <div style="font-size:12px; font-weight:700; text-transform:uppercase; color:var(--text-muted); margin-bottom:12px;">Background Pipeline</div>
          <div style="display:grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap:12px;">
            <div style="padding:14px; border-radius:10px; border:1px solid ${ingestActive ? "rgba(96, 165, 250, 0.45)" : "rgba(255,255,255,0.08)"}; background:${ingestDone ? "rgba(16,185,129,0.08)" : ingestActive ? "rgba(59,130,246,0.08)" : "rgba(255,255,255,0.02)"};">
              <div style="display:flex; align-items:center; justify-content:space-between; gap:10px; margin-bottom:8px;">
                <strong style="font-size:13px;">Ingest</strong>
                <span class="badge ${ingestDone ? "matched" : ingestActive ? "processing" : "neutral"}">${ingestDone ? "Done" : ingestActive ? "Running" : "Pending"}</span>
              </div>
              <div style="display:flex; align-items:center; gap:8px; min-height:22px;">
                ${ingestActive ? `<span class="spinner-mini" style="display:inline-block; width:14px; height:14px; border:2px solid rgba(255,255,255,0.15); border-top:2px solid var(--brand-accent-blue); border-radius:50%; animation:spin 1s linear infinite;"></span>` : `<span class="material-symbols-outlined" style="font-size:16px; color:${ingestDone ? "#10B981" : "var(--text-muted)"};">${ingestDone ? "check_circle" : "schedule"}</span>`}
                <span style="font-size:12px; color:var(--text-muted);">${ingestDone ? "Partner file ingestion completed." : ingestActive ? "Importing approved file into runtime data store." : "Waiting to start ingestion."}</span>
              </div>
            </div>
            <div style="padding:14px; border-radius:10px; border:1px solid ${reconcileActive ? "rgba(96, 165, 250, 0.45)" : "rgba(255,255,255,0.08)"}; background:${reconcileDone ? "rgba(16,185,129,0.08)" : reconcileActive ? "rgba(59,130,246,0.08)" : "rgba(255,255,255,0.02)"};">
              <div style="display:flex; align-items:center; justify-content:space-between; gap:10px; margin-bottom:8px;">
                <strong style="font-size:13px;">Reconciliation</strong>
                <span class="badge ${reconcileDone ? "matched" : reconcileActive ? "processing" : "neutral"}">${reconcileDone ? "Done" : reconcileActive ? "Running" : "Pending"}</span>
              </div>
              <div style="display:flex; align-items:center; gap:8px; min-height:22px;">
                ${reconcileActive ? `<span class="spinner-mini" style="display:inline-block; width:14px; height:14px; border:2px solid rgba(255,255,255,0.15); border-top:2px solid var(--brand-accent-blue); border-radius:50%; animation:spin 1s linear infinite;"></span>` : `<span class="material-symbols-outlined" style="font-size:16px; color:${reconcileDone ? "#10B981" : "var(--text-muted)"};">${reconcileDone ? "check_circle" : "schedule"}</span>`}
                <span style="font-size:12px; color:var(--text-muted);">${reconcileDone ? "Mismatch computation finished." : reconcileActive ? "Comparing ingested rows against internal ledger." : "Queued after ingestion."}</span>
              </div>
            </div>
          </div>
        </section>
      ` : "";
      const activationStatusHtml = hasPostApprovalRun ? `
        <section class="panel" style="margin:0; padding:16px; border-radius:10px; border:1px solid rgba(255,255,255,0.08);">
          <div style="display:flex; justify-content:space-between; gap:12px; align-items:flex-start; flex-wrap:wrap;">
            <div>
              <div style="font-size:12px; font-weight:700; text-transform:uppercase; color:var(--text-muted); margin-bottom:8px;">Activation Progress</div>
              <div style="display:flex; gap:8px; flex-wrap:wrap; align-items:center;">
                <span class="badge ${postApprovalTone}">${escapeHtml(statusLabel(postApprovalStatus || "QUEUED"))}</span>
                ${postApprovalRun.stage ? `<span class="badge neutral">${escapeHtml(String(postApprovalRun.stage).replace(/_/g, " "))}</span>` : ""}
                ${postApprovalRun.outputFileId ? `<span class="badge neutral">File ${escapeHtml(postApprovalRun.outputFileId)}</span>` : ""}
              </div>
            </div>
            ${postApprovalRun.updatedAt ? `<span class="muted" style="font-size:12px;">Updated ${escapeHtml(formatDisplayDateTime(postApprovalRun.updatedAt))}</span>` : ""}
          </div>
          <div style="margin-top:12px; font-size:13px;">${escapeHtml(postApprovalRun.message || "Post-approval processing has started.")}</div>
          ${(postApprovalRun.stats && Object.keys(postApprovalRun.stats).length) ? `
            <div style="display:grid; grid-template-columns:repeat(3, minmax(0, 1fr)); gap:12px; margin-top:12px;">
              <div><div style="font-size:11px; color:var(--text-muted); text-transform:uppercase; font-weight:700;">Total Rows</div><div style="font-size:18px; font-weight:800;">${escapeHtml(String(postApprovalRun.stats.totalRows || 0))}</div></div>
              <div><div style="font-size:11px; color:var(--text-muted); text-transform:uppercase; font-weight:700;">Success Rows</div><div style="font-size:18px; font-weight:800;">${escapeHtml(String(postApprovalRun.stats.successRows || 0))}</div></div>
              <div><div style="font-size:11px; color:var(--text-muted); text-transform:uppercase; font-weight:700;">Failed Rows</div><div style="font-size:18px; font-weight:800;">${escapeHtml(String(postApprovalRun.stats.failedRows || 0))}</div></div>
            </div>
          ` : ""}
          ${postApprovalRun.reconciliationCount !== null && postApprovalRun.reconciliationCount !== undefined ? `<div style="margin-top:12px; font-size:12px; color:var(--text-muted);">Reconciliation results written: ${escapeHtml(String(postApprovalRun.reconciliationCount))}</div>` : ""}
        </section>
      ` : "";
      const approvalFinished = packetApproved || postApprovalCompleted;
      stepBodyHtml = `
        <div class="guided-step-content" style="display:flex; flex-direction:column; gap:14px;">
          <h4 style="margin:0;">Decision</h4>
          <section class="panel" style="margin:0; padding:16px; border-radius:10px;">
            <div style="display:flex; gap:10px; flex-wrap:wrap;">
              <span class="badge ${isMappingReady ? "matched" : "warning"}">Mapping ${isMappingReady ? "ready" : "missing"}</span>
              ${approvalFinished ? `<span class="badge matched">Approval completed</span>` : ""}
            </div>
            <div style="margin-top:12px; font-size:13px;">${escapeHtml(approvalFinished ? "This review item has already been approved and activated." : recommendation)}</div>
          </section>
          ${activationProgressHtml}
          ${activationStatusHtml}
          ${(!validationState.canProceed || !isMappingReady) ? `<button class="button secondary-action" data-action="back-to-guided-step-3">Return to Step 3</button>` : ""}
          <div style="display:flex; flex-direction:column; gap:10px;">
            <button class="button primary ${isReady ? "success-cta" : ""}" data-action="approve-packet-activate" data-packet-id="${escapeHtml(selectedPacket._id)}" ${(isReady && !postApprovalActive && !approvalFinished) ? "" : "disabled"}>${approvalFinished ? "Already Approved" : postApprovalActive ? "Activation In Progress..." : "Approve & Activate"}</button>
            <button class="button secondary-action" data-action="reject-packet" data-packet-id="${escapeHtml(selectedPacket._id)}" ${(postApprovalActive || approvalFinished) ? "disabled" : ""}>Reject change</button>
          </div>
        </div>
      `;
    }

    const step3State = step === 3 ? getRuntimeValidationState(selectedPacket) : null;
    const disableNext = step === 3 && !step3State?.canProceed;
    const footerHtml = `
      <div class="guided-review-footer" style="display:flex; justify-content:space-between; margin-top:20px; border-top: 1px solid rgba(255,255,255,0.08); padding-top: 16px;">
        <button class="button" data-action="guided-prev" ${step === 1 ? "disabled" : ""}>Back</button>
        ${step < 4 ? `<button class="button primary" data-action="guided-next" data-packet-id="${escapeHtml(selectedPacket._id)}" ${disableNext ? "disabled" : ""}>Next</button>` : ""}
      </div>
    `;

    return `
      <div class="guided-review-backdrop" id="guided-review-backdrop" style="position: fixed; inset: 0; background: rgba(0,0,0,0.8); display: flex; align-items: center; justify-content: center; z-index: 1000; padding: 16px; gap: 20px;">
        <div class="guided-review-modal" style="width: 100%; max-width: 760px; background: #111; padding: 24px; border-radius: 12px; border: 1px solid var(--border); box-shadow: var(--shadow); display: flex; flex-direction: column; max-height: 90vh;">
          <div class="guided-review-header" style="display:flex; justify-content:space-between; margin-bottom:20px; align-items: center; border-bottom: 1px solid rgba(255,255,255,0.06); padding-bottom: 12px;">
            <div>
              <h3 style="margin:0; font-size: 16px; font-weight: 800; color: #fff;">AI Assisted Guided Review</h3>
            </div>
            <button class="button tertiary compact" data-action="close-guided-review" style="padding: 4px; min-width: unset; height: unset;">
              <span class="material-symbols-outlined" style="font-size: 20px;">close</span>
            </button>
          </div>
          <div style="display:flex; margin-bottom:20px;">${progressSteps}</div>
          
          <div class="guided-review-split-container" style="display: flex; flex-direction: column; overflow-y: auto; flex: 1; min-height: 0; padding-right: 4px;">
            <div class="guided-review-left-panel" style="display: flex; flex-direction: column; gap: 16px;">
              ${stepBodyHtml}
            </div>
          </div>
          
          ${step === 3 ? renderGuidedRuntimeDetailModal(getRuntimeValidationState(selectedPacket).runtimeGate) : ""}
          ${footerHtml}
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

    if (!state.reviewTab) state.reviewTab = "pending";

    const mappings = (data.mappings || []).filter(item => item.partner === state.partner);
    const allPending = getReviewCenterPendingItems(data);
    const selectedPacket = (state.guidedReviewOpen && state.selectedReviewPacketId)
      ? (getTrackedReviewPacket(data) || getSelectedReviewPacket(allPending))
      : getSelectedReviewPacket(allPending);

    const intake = data.intake || {};
    const partners = intake.partners || [];
    const activePartnerInfo = partners.find(p => p.partner === state.partner) || {};
    const pendingCount = allPending.length;
    const latestFile = activePartnerInfo.latestFileSummary?.fileName || activePartnerInfo.latestFileSummary?.file_name || "-";
    const highestRisk = selectedPacket ? (selectedPacket.riskSummary?.severity || "medium") : "none";
    const riskLabel = highestRisk === "none" ? "No risk" : `${highestRisk.charAt(0).toUpperCase() + highestRisk.slice(1)} risk`;

    const headerHtml = `
      <div class="compact-page-header">
        <div class="compact-header-info">
          <h2>Review Center</h2>
          <div class="compact-header-meta">
            <strong>${escapeHtml(state.partner)}</strong> ·
            <span>${pendingCount} pending review${pendingCount !== 1 ? "s" : ""}</span> ·
            <span class="badge ${highestRisk === "critical" || highestRisk === "high" ? "failed" : "warning"}" style="padding: 2px 6px; font-size: 11px;">${riskLabel.toUpperCase()}</span> ·
            <span>Latest file: <span title="${escapeHtml(latestFile)}">${escapeHtml(middleTruncate(latestFile, 30))}</span></span>
          </div>
        </div>
      </div>
    `;

    const tabsNavHtml = `
      <div class="insights-tabs" style="margin-bottom: 20px;">
        <button class="insight-tab ${state.reviewTab === "pending" ? "active" : ""}" data-action="set-review-tab" data-tab="pending">Pending Reviews</button>
        <button class="insight-tab ${state.reviewTab === "history" ? "active" : ""}" data-action="set-review-tab" data-tab="history">Decision History</button>
        <button class="insight-tab ${state.reviewTab === "configs" ? "active" : ""}" data-action="set-review-tab" data-tab="configs">Runtime Configs</button>
      </div>
    `;

    let tabContentHtml = "";
    if (state.reviewTab === "pending") {
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
              <span class="badge ${risk === "critical" || risk === "high" ? "failed" : "warning"}">${escapeHtml(risk.toUpperCase())} RISK</span>
            </div>
            <div class="review-card-meta">
              <strong>${escapeHtml(packet.partner)}</strong> · <span class="review-status-label">Pending</span> · <span class="review-time">${escapeHtml(dateStr)}</span>
            </div>
            <p class="review-card-reason">${escapeHtml(shortReason)}</p>
            <div style="font-size: 12px; color: var(--text-muted); margin-top: 8px; font-family: monospace;">
              File: ${escapeHtml(middleTruncate(packet.fileName || "-", 35))}
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
      ${renderPageFilters({ showDate: false, showClear: false })}
      ${headerHtml}
      ${tabsNavHtml}
      ${tabContentHtml}
      ${renderGuidedReviewModal(selectedPacket)}
    `;
  }

  return {
    renderApprovals,
  };
}
