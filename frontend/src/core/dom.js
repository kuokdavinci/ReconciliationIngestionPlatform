import { escapeHtml } from "./format.js";

export function loadingPanel(message) {
  return `
    <section class="panel" style="margin-bottom: 20px;">
      <div style="margin-bottom: 16px;">
        <div class="skeleton-text long shimmer"></div>
        <div class="skeleton-text medium shimmer"></div>
      </div>
      <div style="display: flex; flex-direction: column; gap: 8px;">
        ${Array.from({ length: 5 }).map(() => `
          <div class="skeleton-row">
            <div class="skeleton-text short shimmer" style="width: 20px; height: 20px; border-radius: 4px;"></div>
            <div class="skeleton-text short shimmer" style="width: 80px;"></div>
            <div class="skeleton-text medium shimmer" style="flex: 1;"></div>
            <div class="skeleton-text short shimmer" style="width: 60px;"></div>
          </div>
        `).join("")}
      </div>
    </section>
  `;
}

export function renderSkeletonMetrics(count = 4) {
  return `
    <div class="grid cols-${count}" style="margin-bottom: 20px;">
      ${Array.from({ length: count }).map(() => `
        <div class="skeleton-card">
          <div class="skeleton-text short shimmer"></div>
          <div class="skeleton-text long shimmer" style="height: 24px; margin-top: 8px;"></div>
        </div>
      `).join("")}
    </div>
  `;
}


export function renderError(err) {
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

export function metrics(items) {
  return `<div class="grid cols-4">${items.map(([label, value, hint]) => `
    <div class="metric compact">
      <span>${label}</span>
      <strong>${value}</strong>
      <small>${hint}</small>
    </div>
  `).join("")}</div>`;
}

export function table(headers, rows) {
  return `
    <div class="table-wrap">
      <table>
        <thead><tr>${headers.map(h => `<th>${h}</th>`).join("")}</tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
  `;
}

export function bars(items) {
  return `<div class="bars">${items.map(([label, value, tone]) => `
    <div class="bar-row">
      <strong>${label}</strong>
      <div class="bar-track"><div class="bar-fill ${tone || ""}" style="width:${Math.min(100, Number(value) || 0)}%"></div></div>
      <span style="font-weight: 600; text-align: right; display: block;">${Math.round(Number(value) || 0)}%</span>
    </div>
  `).join("")}</div>`;
}

export function donut(value, label) {
  return `
    <div class="donut" style="--value:${Math.round(value)}">
      <div class="donut-inner">${Math.round(value)}%</div>
    </div>
    <p style="text-align:center; margin-top:14px; font-weight: 600; color: var(--green-primary); letter-spacing: 0.02em;">${label}</p>
  `;
}

export function showToast(message) {
  const toastEl = document.getElementById("toast");
  if (!toastEl) return;
  toastEl.textContent = message;
  toastEl.classList.add("show");
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => toastEl.classList.remove("show"), 2400);
}

export function renderEmptyState(title, description, icon = "info") {
  return `
    <div class="empty-state-panel" style="text-align: center; padding: 48px 24px; border: 1px dashed var(--border); border-radius: 12px; background: rgba(255, 255, 255, 0.01); display: flex; flex-direction: column; align-items: center; justify-content: center; min-height: 220px; margin: 16px 0;">
      <span class="material-symbols-outlined" style="font-size: 48px; color: var(--text-muted); margin-bottom: 16px;">${icon}</span>
      <h3 style="margin: 0 0 8px 0; font-size: 16px; font-weight: 700; color: #fff;">${escapeHtml(title)}</h3>
      <p class="muted" style="margin: 0; max-width: 320px; font-size: 13px; line-height: 1.5;">${escapeHtml(description)}</p>
    </div>
  `;
}

