import { formatNumber, escapeHtml, boldNumbers } from "../../core/format.js";
import { severityBadge } from "../../core/status.js";

export function renderAiObservation(obs) {
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
    const hasCountHallucination = gr.findings.some(f => f.field === 'affected_count');
    const countCheck = {
      title: "Record Count Verification",
      status: hasCountHallucination ? "fail" : "pass",
      desc: hasCountHallucination 
        ? "Discrepancy detected: LLM affected counts deviate from actual database records."
        : "Verified. LLM anomaly counts match underlying database metrics."
    };

    const hasSeverityMismatch = gr.findings.some(f => f.field === 'severity');
    const severityCheck = {
      title: "Severity Level Calibration",
      status: hasSeverityMismatch ? "warn" : "pass",
      desc: hasSeverityMismatch
        ? "Deviation flagged: LLM severity level is slightly misaligned with threshold rules."
        : "Verified. Anomaly severity corresponds correctly to operational rules."
    };

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

export function insightCard(item, state) {
  const sev = String(item.severity || "low").toLowerCase();
  
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

export function renderInsightLoadingState(tabKey) {
  const labelMap = {
    anomalies: {
      title: "Analyzing anomaly clusters",
      detail: "AI is grouping the most important mismatch anomalies for this reconciliation window."
    },
    patterns: {
      title: "Detecting recurring patterns",
      detail: "AI is reading grouped error signals to identify repeatable operational or partner-side patterns."
    },
    recommendations: {
      title: "Drafting operator actions",
      detail: "AI is turning summary metrics and selected errors into concrete next steps for operators."
    }
  };
  const activeState = labelMap[tabKey] || {
    title: "Preparing insight",
    detail: "AI is processing selected reconciliation signals."
  };
  return `
    <div class="insight-content empty" style="padding: 12px 4px;">
      <div style="margin-bottom:14px;">
        <p class="muted" style="margin:0; color: var(--text-primary); font-weight:600;">${escapeHtml(activeState.title)}</p>
        <p class="muted" style="margin:4px 0 0 0; font-size:11px;">${escapeHtml(activeState.detail)}</p>
      </div>
      <div class="skeleton-card" style="padding:18px; gap:14px; background:linear-gradient(180deg, rgba(255,255,255,0.03), rgba(255,255,255,0.015)); border-color: rgba(255,255,255,0.07); box-shadow: var(--shadow);">
        <div style="display:flex; gap:16px; align-items:flex-start;">
          <div class="shimmer" style="width:68px; height:68px; border-radius:12px; flex-shrink:0;"></div>
          <div style="flex:1; min-width:0;">
            <div class="shimmer" style="width:90px; height:18px; border-radius:999px; margin-bottom:10px;"></div>
            <span class="skeleton-text shimmer long"></span>
            <span class="skeleton-text shimmer medium"></span>
            <span class="skeleton-text shimmer short"></span>
          </div>
        </div>
        <div style="padding:10px 12px; border-radius:8px; background:rgba(0,0,0,0.2); border-left:3px solid rgba(255,255,255,0.1);">
          <span class="skeleton-text shimmer short"></span>
          <span class="skeleton-text shimmer long"></span>
        </div>
      </div>
    </div>
  `;
}

export function highlightInsightText(text) {
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
