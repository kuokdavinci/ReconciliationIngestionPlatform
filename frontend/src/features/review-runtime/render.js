const VALIDATION_SUGGESTIONS = {
  SOURCE_FIELD_NOT_FOUND: "Source field does not exist in sample data. Re-map this target to an existing partner field.",
  MISSING_REQUIRED_FIELD: "Required field '<field>' is missing. Map a partner field to this canonical field.",
  INVALID_DECIMAL: "Map the partner numeric amount field to 'amount' and ensure the sample value is numeric.",
  INVALID_DATE: "Check the source date field and ensure it matches a supported runtime date format.",
  UNMAPPED_VALUE: "Add a mapping rule for this partner value or configure a fallback rule.",
  INVALID_CANONICAL_STATUS: "Map the partner status into one of SUCCESS, FAILED, PENDING, REVERSED.",
};

export function createReviewRuntimeHelpers({ state, escapeHtml }) {
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
    const freshnessTone = validationState?.isStale ? "warning" : validationState?.hasValidation ? "matched" : "neutral";
    const barTone = validationState?.summaryLabel === "Failed" ? "#EF4444" : validationState?.summaryLabel === "Passed with warnings" ? "#F59E0B" : "#10B981";

    return `
      <section class="panel" style="margin:0; padding:20px; border-radius:12px; background: rgba(255,255,255,0.01); border: 1px solid var(--border); box-shadow: var(--shadow);">
        <div style="display:grid; grid-template-columns: 1.2fr 1fr; gap:24px; align-items:center;">
          <div>
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
              <span style="font-size:11px; font-weight:800; color:var(--text-muted); text-transform:uppercase; letter-spacing:0.05em;">Runtime Coverage</span>
              <span style="font-size:12px; font-weight:700; color:${barTone};">${Math.round(okPercent)}% pass rate</span>
            </div>
            <div style="height:8px; border-radius:4px; overflow:hidden; background:rgba(255,255,255,0.06); display:flex; margin-bottom:12px;">
              <div style="width:${okPercent}%; background:#10B981; transition: width 0.3s ease;"></div>
              <div style="width:${warnPercent}%; background:#F59E0B; transition: width 0.3s ease;"></div>
              <div style="width:${failPercent}%; background:#EF4444; transition: width 0.3s ease;"></div>
            </div>
            <div style="display:flex; gap:16px; flex-wrap:wrap; font-size:11.5px;">
              <span style="color:var(--text-muted);"><strong>${escapeHtml(String(sampledRows))}</strong> sampled</span>
              <span style="color:#10B981; display:flex; align-items:center; gap:4px;"><span style="width:6px; height:6px; border-radius:50%; background:#10B981;"></span><strong>${escapeHtml(String(successRows))}</strong> success</span>
              <span style="color:#F59E0B; display:flex; align-items:center; gap:4px;"><span style="width:6px; height:6px; border-radius:50%; background:#F59E0B;"></span><strong>${escapeHtml(String(warningRows))}</strong> warnings</span>
              <span style="color:#EF4444; display:flex; align-items:center; gap:4px;"><span style="width:6px; height:6px; border-radius:50%; background:#EF4444;"></span><strong>${escapeHtml(String(hardFailedRows))}</strong> failed</span>
            </div>
          </div>
          
          <div style="border-left: 1px solid rgba(255,255,255,0.06); padding-left:24px;">
            <div style="font-size:11px; font-weight:800; color:var(--text-muted); text-transform:uppercase; letter-spacing:0.05em; margin-bottom:8px;">Validation Freshness</div>
            <div style="display:flex; gap:8px; flex-wrap:wrap; margin-bottom:10px;">
              <span class="badge ${freshnessTone}" style="padding:2px 8px; font-size:10px; border-radius:4px; font-weight:700;">${escapeHtml(validationState?.summaryLabel || "Not run")}</span>
              <span class="badge neutral" style="padding:2px 8px; font-size:10px; border-radius:4px; font-weight:700;">Draft ${escapeHtml(validationState?.currentVersion || "-")}</span>
            </div>
            <div style="font-size:11.5px; color:var(--text-muted);">Validated on <code style="background:rgba(0,0,0,0.2); padding:2px 6px; border-radius:4px;">v${escapeHtml(validationState?.validatedVersion || details.validatedMappingVersion || "-")}</code></div>
          </div>
        </div>
      </section>
    `;
  }

  function getGuidedRuntimeSamples(runtimeGate) {
    return Array.isArray(runtimeGate?.details?.traceSamples) ? runtimeGate.details.traceSamples : [];
  }

  function renderGuidedRuntimeTraceGallery(runtimeSamples) {
    const samples = Array.isArray(runtimeSamples) ? runtimeSamples.slice(0, 10) : [];
    if (!samples.length) {
      return `<div class="muted" style="font-size:12px;">No runtime trace previews are available yet.</div>`;
    }

    const hasDisplayValue = value => value !== null && value !== undefined && String(value).trim() !== "";

    const cards = samples.map((sample, index) => {
      const fieldTraces = Array.isArray(sample.fieldTraces)
        ? sample.fieldTraces.filter(trace =>
            hasDisplayValue(trace.sourceValue)
            || hasDisplayValue(trace.outputValue)
            || hasDisplayValue(trace.path)
            || hasDisplayValue(trace.errorMessage)
          )
        : [];
      const buildErrors = Array.isArray(sample.buildErrors) ? sample.buildErrors : [];
      const hasErrors = buildErrors.length > 0 || fieldTraces.some(trace => String(trace.status || "").toLowerCase() === "error");
      const hasWarnings = fieldTraces.some(trace => String(trace.status || "").toLowerCase() === "warning");
      const tone = hasErrors ? "failed" : hasWarnings ? "warning" : "matched";
      const label = hasErrors ? "Failed" : hasWarnings ? "Warning" : "Passed";
      const rawRows = fieldTraces.map(trace => {
        const sourceField = trace.sourceField || (trace.column ? `Column ${trace.column}` : trace.type === "CONSTANT" ? "Constant" : trace.path || "-");
        return `
          <div style="display:flex; justify-content:space-between; gap:12px; padding:6px 0; border-bottom:1px solid rgba(255,255,255,0.04);">
            <div style="font-family:var(--font-mono); color:var(--text-muted);">${escapeHtml(String(sourceField))}</div>
            <div style="font-family:var(--font-mono); text-align:right; word-break:break-word;">${escapeHtml(String(trace.sourceValue ?? "-"))}</div>
          </div>
        `;
      }).join("");
      const normalizedRows = Object.entries(sample.normalizedData || {})
        .filter(([, value]) => hasDisplayValue(value))
        .map(([key, value]) => `
          <div style="display:flex; justify-content:space-between; gap:12px; padding:6px 0; border-bottom:1px solid rgba(255,255,255,0.04);">
            <div style="font-family:var(--font-mono); color:var(--text-muted);">${escapeHtml(String(key))}</div>
            <div style="font-family:var(--font-mono); text-align:right; word-break:break-word;">${escapeHtml(String(value ?? "-"))}</div>
          </div>
        `).join("");
      const errorSummary = buildErrors.length
        ? `<div style="margin-top:10px; font-size:11px; color:#fca5a5;">${buildErrors.length} canonical build error${buildErrors.length !== 1 ? "s" : ""}</div>`
        : "";

      return `
        <article style="padding:14px 0; border-bottom:1px solid rgba(255,255,255,0.08);">
          <div style="display:flex; justify-content:space-between; gap:12px; align-items:center; margin-bottom:10px; flex-wrap:wrap; padding:0 2px;">
            <div style="display:flex; align-items:center; gap:8px; flex-wrap:wrap;">
              <strong>Sample ${escapeHtml(String(index + 1))}</strong>
              <span class="badge ${tone}">${label}</span>
            </div>
            <button class="button tertiary compact" data-action="open-guided-runtime-detail" data-sample-index="${escapeHtml(String(index))}" style="padding:2px; min-width:unset; height:unset; display:inline-flex; align-items:center; justify-content:center; cursor:pointer; color:var(--brand-primary); background:transparent; border:none;">
              <span class="material-symbols-outlined" style="font-size:18px;">visibility</span>
            </button>
          </div>
          <div style="display:grid; grid-template-columns:repeat(2, minmax(0, 1fr)); gap:12px;">
            <div style="padding:12px; border:1px solid rgba(255,255,255,0.05); border-radius:8px; background:rgba(255,255,255,0.015);">
              <div style="font-size:11px; font-weight:700; color:var(--text-muted); text-transform:uppercase; margin-bottom:8px;">Before / Raw Source</div>
              ${rawRows || `<span class="muted">No source values</span>`}
            </div>
            <div style="padding:12px; border:1px solid rgba(255,255,255,0.05); border-radius:8px; background:rgba(255,255,255,0.015);">
              <div style="font-size:11px; font-weight:700; color:var(--text-muted); text-transform:uppercase; margin-bottom:8px;">After / Normalized Output</div>
              ${normalizedRows || `<span class="muted">No normalized output</span>`}
            </div>
          </div>
          ${errorSummary}
        </article>
      `;
    }).join("");

    return `
      <div style="display:flex; justify-content:space-between; gap:12px; align-items:center; margin-bottom:10px; flex-wrap:wrap;">
        <div style="font-size:12px; font-weight:700; text-transform:uppercase; color:var(--text-muted);">Runtime Trace Review</div>
        <span class="badge neutral">${escapeHtml(String(samples.length))} preview rows</span>
      </div>
      <div style="display:flex; flex-direction:column; gap:10px;">
        ${cards}
      </div>
    `;
  }

  function renderGuidedSampleRuntimePanel(packet, runtimeGate) {
    const runtimeSamples = getGuidedRuntimeSamples(runtimeGate);
    if (!runtimeSamples.length) {
      return `
        <section class="panel" style="margin:0; padding:16px; border-radius:10px;">
          <div style="font-size:12px; font-weight:700; text-transform:uppercase; color:var(--text-muted); margin-bottom:8px;">Sample Rows & Runtime Preview</div>
          <div class="muted" style="font-size:12px;">No sample rows or runtime traces are available yet.</div>
        </section>
      `;
    }

    return `
      <section class="panel" style="margin:0; padding:16px; border-radius:10px;">
        <div style="font-size:12px; font-weight:700; text-transform:uppercase; color:var(--text-muted); margin-bottom:10px;">Sample Rows & Runtime Preview</div>
        ${renderGuidedRuntimeTraceGallery(runtimeSamples)}
      </section>
    `;
  }

  function renderGuidedRuntimeDetailModal(runtimeGate) {
    if (!state.guidedReviewTraceModal?.open) return "";
    const samples = getGuidedRuntimeSamples(runtimeGate);
    const index = Number(state.guidedReviewTraceModal.sampleIndex);
    const sample = Number.isInteger(index) ? samples[index] : null;
    if (!sample) return "";

    const hasDisplayValue = value => value !== null && value !== undefined && String(value).trim() !== "";
    const fieldTraces = Array.isArray(sample.fieldTraces)
      ? sample.fieldTraces.filter(trace =>
          hasDisplayValue(trace.sourceValue)
          || hasDisplayValue(trace.outputValue)
          || hasDisplayValue(trace.errorMessage)
          || hasDisplayValue(trace.path)
        )
      : [];
    const buildErrors = Array.isArray(sample.buildErrors) ? sample.buildErrors : [];
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
      <div class="guided-review-backdrop">
        <div class="guided-review-modal" style="max-width: 920px; width: 100%; background: #111; padding: 24px; border-radius: 12px;">
          <div class="guided-review-header" style="display:flex; justify-content:space-between; margin-bottom:20px;">
            <div>
              <h3 style="margin:0;">Runtime Trace Detail</h3>
              <p class="muted" style="margin:6px 0 0 0;">Sample ${escapeHtml(String(index + 1))}</p>
            </div>
            <button class="button-link" data-action="close-guided-runtime-detail"><span class="material-symbols-outlined">close</span></button>
          </div>
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
      </div>
    `;
  }

  return {
    collectCandidateColumns,
    collectRuntimeFieldStats,
    collectValidationIssues,
    getDraftMappingVersion,
    getRuntimeValidationState,
    renderGuidedRuntimeDetailModal,
    renderGuidedSampleRuntimePanel,
    renderGuidedRuntimeTraceGallery,
    renderRuntimeVisualSummary,
  };
}
