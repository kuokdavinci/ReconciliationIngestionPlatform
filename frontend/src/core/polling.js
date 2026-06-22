export function pollAutomationOverview({
  state,
  view,
  fetchJson,
  renderAutomation,
  bindViewActions,
  isActiveRuntimeStatus,
  pollers,
  badge,
  escapeHtml,
  formatDisplayDateTime,
  formatNumber,
  metrics,
  severityBadge,
  table
}) {
  if (pollers.automation || state.route !== "automation") return;
  const tick = async () => {
    try {
      const data = await fetchJson(`/api/v1/automation/jobs`);
      if (state.route !== "automation") {
        clearInterval(pollers.automation);
        pollers.automation = null;
        return;
      }
      const recentPacketIds = (data.jobs || [])
        .flatMap(job => (job.recentPackets || []).map(packet => String(packet._id || "")))
        .filter(Boolean);
      const hadKnownPackets = Array.isArray(state.automationKnownPacketIds) && state.automationKnownPacketIds.length > 0;
      const knownPacketIds = new Set(state.automationKnownPacketIds || []);
      const nextNewPacketIds = hadKnownPackets
        ? recentPacketIds.filter(id => !knownPacketIds.has(id))
        : [];
      state.automationKnownPacketIds = recentPacketIds;
      if (nextNewPacketIds.length) {
        state.automationNewPacketIds = nextNewPacketIds;
        window.setTimeout(() => {
          state.automationNewPacketIds = (state.automationNewPacketIds || []).filter(id => !nextNewPacketIds.includes(id));
          if (state.route === "automation") {
            view.innerHTML = renderAutomation({
              state,
              data,
              badge,
              escapeHtml,
              formatDisplayDateTime,
              formatNumber,
              metrics,
              severityBadge,
              table,
            });
            bindViewActions();
          }
        }, 2200);
      }
      const activePartners = new Set(
        (data.jobs || [])
          .filter(job => isActiveRuntimeStatus(job.status))
          .map(job => String(job.partner || ""))
      );
      const nextRunningPartners = { ...(state.automationRunningPartners || {}) };
      (data.jobs || []).forEach(job => {
        const partner = String(job.partner || "");
        if (!partner) return;
        if (activePartners.has(partner)) {
          nextRunningPartners[partner] = true;
        }
        const hasNewPacketForPartner = (job.recentPackets || []).some(packet =>
          nextNewPacketIds.includes(String(packet._id || ""))
        );
        if (hasNewPacketForPartner) {
          nextRunningPartners[partner] = false;
        }
      });
      state.automationRunningPartners = nextRunningPartners;
      view.innerHTML = renderAutomation({
        state,
        data,
        badge,
        escapeHtml,
        formatDisplayDateTime,
        formatNumber,
        metrics,
        severityBadge,
        table,
      });
      bindViewActions();
      const hasActiveRuns = (data.jobs || []).some(job => isActiveRuntimeStatus(job.status))
        || Object.values(state.automationRunningPartners || {}).some(Boolean);
      if (!hasActiveRuns) {
        clearInterval(pollers.automation);
        pollers.automation = null;
      }
    } catch (_) {
      clearInterval(pollers.automation);
      pollers.automation = null;
    }
  };
  tick();
  pollers.automation = setInterval(tick, 5000);
}

export function pollReconciliationRun({
  state,
  render,
  hasMeaningfulRunChange,
  isLiveReconciliationRunStatus,
  isTerminalReconciliationRun,
  pollers
}) {
  if (pollers.reconciliation || !state.partner || !state.date) return;
  const tick = () => {
    fetch(`/api/v1/reconciliation/run-status?partner=${encodeURIComponent(state.partner)}&date=${encodeURIComponent(state.date)}`)
      .then(r => r.json().then(body => ({ ok: r.ok, body })))
      .then(async ({ ok, body }) => {
        if (!ok) throw new Error(body.detail || "Failed to load reconciliation run.");
        const run = body.run || null;
        if (!run) return;
        const previousRun = state.reconciliationRun;
        state.reconciliationRun = run;
        if (hasMeaningfulRunChange(previousRun, run)) {
          render();
        }
        if (!isLiveReconciliationRunStatus(run.status)) {
          clearInterval(pollers.reconciliation);
          pollers.reconciliation = null;
          return;
        }
        if (isTerminalReconciliationRun(run)) {
          clearInterval(pollers.reconciliation);
          pollers.reconciliation = null;
          if (String(run.status).toUpperCase() === "COMPLETED") {
            state.activeReconData = null;
            await render();
          }
        }
      })
      .catch(() => {
        clearInterval(pollers.reconciliation);
        pollers.reconciliation = null;
      });
  };
  tick();
  pollers.reconciliation = setInterval(tick, 3000);
}

export function pollPostApprovalRun({
  state,
  render,
  packetId,
  upsertPostApprovalRun,
  isTerminalPostApprovalRun,
  syncLocalReviewPacket,
  pollers
}) {
  if (!packetId || pollers.postApproval[packetId]) return;
  const tick = () => {
    fetch(`/api/v1/review-packets/${encodeURIComponent(packetId)}/post-approve-run`)
      .then(r => r.json().then(body => ({ ok: r.ok, body })))
      .then(({ ok, body }) => {
        if (!ok) throw new Error(body.detail || "Failed to load post-approval run.");
        const run = body.run || null;
        if (!run) return;
        upsertPostApprovalRun(run);
        render();
        if (isTerminalPostApprovalRun(run)) {
          clearInterval(pollers.postApproval[packetId]);
          delete pollers.postApproval[packetId];
          let shouldRender = true;
          state.reviewCenterCache = null;
          if (String(run.status || "").toUpperCase() === "COMPLETED") {
            syncLocalReviewPacket(packetId, {
              status: "APPROVED",
              reviewedAt: run.finishedAt || new Date().toISOString(),
            });
            if (state.selectedReviewPacketId === packetId) {
              state.selectedReviewPacketId = null;
            }
            state.guidedReviewOpen = false;
            state.guidedReviewTraceModal = { open: false, sampleIndex: null };
          }
          if (state.route === "reconciliation" && run.partner === state.partner && run.date === state.date) {
            state.activeReconData = null;
            state.reconciliationRun = null;
            shouldRender = true;
          }
          if (state.route === "review-center") {
            shouldRender = true;
          }
          if (shouldRender) render();
        }
      })
      .catch(() => {
        clearInterval(pollers.postApproval[packetId]);
        delete pollers.postApproval[packetId];
      });
  };
  tick();
  pollers.postApproval[packetId] = setInterval(tick, 4000);
}
