function normalizeAuditValue(value) {
  if (value === null || value === undefined || value === "") return "-";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function getSelectedAuditEvent(state) {
  const events = Array.isArray(state.audit.events) ? state.audit.events : [];
  return events.find(event => event._id === state.audit.selectedEventId) || null;
}

function renderAuditDetailPopup(event, { badge, escapeHtml }) {
  if (!event) return "";
  const metadata = event.metadata || {};
  const detailRows = [
    ["Entity type", event.entityType || "-"],
    ["Entity ID", event.entityId || "-"],
    ["Action", event.action || "-"],
    ["Actor", event.actor || "system"],
    ["Partner", metadata.partner || "-"],
    ["Date", metadata.date || "-"],
    ["Reference", metadata.reference || "-"],
    ["Status", metadata.status || "-"],
    ["Mapping version", metadata.mappingVersion || "-"],
    ["Draft mapping version", metadata.draftMappingVersion || "-"],
    ["Draft mapping", metadata.draftMappingId || "-"],
    ["Source file", metadata.sourceFileId || "-"],
    ["Created at", event.createdAt || "-"],
  ];

  return `
    <div class="brief-overlay">
      <button class="brief-overlay-backdrop" data-action="close-audit-detail" aria-label="Close audit detail"></button>
      <div class="brief-modal" style="max-width: 720px;">
        <div class="brief-modal-header">
          <div>
            <span class="brief-eyebrow">AUDIT DETAIL</span>
            <div class="brief-header-badges">
              ${badge(event.entityType || "UNKNOWN")}
              ${badge(event.action || "-")}
            </div>
          </div>
          <button class="brief-close-btn" data-action="close-audit-detail">&times;</button>
        </div>
        <div class="brief-modal-content">
          <div class="brief-review-item" style="margin-bottom: 16px;">
            <div class="brief-review-header">
              <span class="brief-review-kind badge neutral">${escapeHtml(event.actor || "system")}</span>
              <span class="badge neutral">${escapeHtml(metadata.partner || "-")}</span>
            </div>
            <h3 class="brief-review-title">${escapeHtml(event.entityId || "-")}</h3>
            <p class="brief-review-reason">${escapeHtml(metadata.date || "-")}</p>
          </div>
          <div class="review-summary-list" style="display:grid; gap:10px; margin-bottom: 18px;">
            ${detailRows.map(([label, value]) => `
              <div style="display:grid; grid-template-columns: 140px minmax(0, 1fr); gap:12px;">
                <strong>${escapeHtml(label)}</strong>
                <span style="word-break: break-word;">${escapeHtml(normalizeAuditValue(value))}</span>
              </div>
            `).join("")}
          </div>
          <div class="panel" style="margin:0; padding:16px;">
            <p class="brief-eyebrow" style="margin:0 0 10px 0;">Raw Metadata</p>
            <pre style="margin:0; white-space:pre-wrap; word-break:break-word; font-family:var(--font-mono); font-size:12px; color:var(--text-primary);">${escapeHtml(JSON.stringify(metadata, null, 2))}</pre>
          </div>
        </div>
      </div>
    </div>
  `;
}

function getFilteredAuditEvents(state) {
  const events = Array.isArray(state.audit.events) ? state.audit.events : [];
  return events.filter(event => {
    const metadata = event.metadata || {};
    const matchesPartner = !state.partner || metadata.partner === state.partner;
    const matchesDate = !state.date || metadata.date === state.date;
    const matchesEntity = !state.audit.entityType || event.entityType === state.audit.entityType;
    const matchesAction = !state.audit.action || event.action === state.audit.action;
    return matchesPartner && matchesDate && matchesEntity && matchesAction;
  });
}

export function renderAuditLog({
  state,
  badge,
  escapeHtml,
  formatDisplayDateTime,
  formatNumber,
  renderPageFilters,
  table,
}) {
  const filtered = getFilteredAuditEvents(state);
  const entityOptions = ["", "REVIEW_PACKET", "MAPPING_CONFIG", "RECONCILIATION_RUN"];
  const actionOptions = ["", "APPROVED", "REJECTED", "APPROVE_ACTIVATE_NEXT_RUNTIME", "APPROVE_KEEP_CURRENT_FOR_FILE", "REJECT", "COMPLETED", "FAILED"];
  const rows = filtered.map(event => {
    const metadata = event.metadata || {};
    return `
      <tr>
        <td><code>${escapeHtml(event.createdAt || "-")}</code></td>
        <td>${badge(event.entityType || "UNKNOWN")}</td>
        <td>${badge(event.action || "-")}</td>
        <td><code>${escapeHtml(normalizeAuditValue(metadata.reference))}</code></td>
        <td>
          <button
            class="button secondary-action"
            data-action="open-audit-detail"
            data-event-id="${escapeHtml(event._id || "")}"
            aria-label="View audit detail"
            title="View audit detail"
            style="min-width: 40px; padding: 8px 10px; justify-content:center;"
          >
            <span class="material-symbols-outlined" style="font-size:18px;">visibility</span>
          </button>
        </td>
      </tr>
    `;
  }).join("");

  const selectedAuditEvent = getSelectedAuditEvent(state);
  setTimeout(() => {
    let modalContainer = document.getElementById("modal-root");
    if (!modalContainer) {
      modalContainer = document.createElement("div");
      modalContainer.id = "modal-root";
      document.body.appendChild(modalContainer);
    }
    modalContainer.innerHTML = selectedAuditEvent ? renderAuditDetailPopup(selectedAuditEvent, { badge, escapeHtml }) : "";
  }, 0);

  return `
    <div class="compact-page-header">
      <div class="compact-header-info">
        <h2>Audit Log</h2>
        <div class="compact-header-meta">
          <strong>${escapeHtml(state.partner || '-')}</strong> ·
          <span>${formatNumber(filtered.length)} matched event${filtered.length !== 1 ? 's' : ''}</span> ·
          <span>Loaded ${escapeHtml(state.audit.lastLoadedAt ? formatDisplayDateTime(state.audit.lastLoadedAt) : '-')}</span>
        </div>
      </div>
      <div class="compact-header-actions">
        <button class="button secondary-action" data-action="refresh-audit">Refresh</button>
      </div>
    </div>
    <section class="panel">
      ${renderPageFilters({ showDate: true, showClear: false })}
      <div class="page-filters" style="margin-bottom: 16px;">
        <div class="filter-group">
          <span class="filter-label">ENTITY</span>
          <div class="filter-input-wrapper">
            <select id="audit-entity-filter">
              ${entityOptions.map(value => `<option value="${value}" ${value === state.audit.entityType ? "selected" : ""}>${value || "All entities"}</option>`).join("")}
            </select>
          </div>
        </div>
        <div class="filter-group">
          <span class="filter-label">ACTION</span>
          <div class="filter-input-wrapper">
            <select id="audit-action-filter">
              ${actionOptions.map(value => `<option value="${value}" ${value === state.audit.action ? "selected" : ""}>${value || "All actions"}</option>`).join("")}
            </select>
          </div>
        </div>
        <div class="filter-group" style="margin-left:auto;">
          <span class="filter-label">MATCHED EVENTS</span>
          <div class="filter-input-wrapper"><strong>${formatNumber(filtered.length)}</strong></div>
        </div>
      </div>
      ${filtered.length ? table(
        ["Timestamp", "Entity", "Action", "Reference", "Detail"],
        rows
      ) : `
        <div class="empty-state" style="padding: 32px 16px;">
          <span class="material-symbols-outlined">history</span>
          <h3>No audit events</h3>
          <p class="muted">No audit entries match the current partner/date/filter combination.</p>
        </div>
      `}
    </section>
  `;
}
