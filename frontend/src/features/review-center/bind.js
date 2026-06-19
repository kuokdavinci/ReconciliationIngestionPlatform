export function handleReviewCenterAction({
  action,
  el,
  state,
  render,
  renderPreserveScroll,
  showToast,
  getActorName,
  withActorHeaders,
  getReviewPacketById,
  openPacketInStudio,
  syncLocalReviewPacket,
  upsertPostApprovalRun,
  pollPostApprovalRun,
  loadReviewHistoryData,
  getReviewCenterPendingItems,
  getSelectedReviewPacket,
  getTrackedReviewPacket,
  getRuntimeValidationState,
  updateReviewPacketLocally,
  loadGuidedReviewScopeLLM
}) {
  if (action === "scope-override-select") {
    // This is a select change, handled separately or inline.
    return false;
  }

  if (action === "select-review-packet") {
    const packetId = el.dataset.packetId;
    if (packetId) {
      state.selectedReviewPacketId = packetId;
      state.guidedReviewOpen = false;
      render();
    }
    return true;
  }

  if (action === "go-review-center") {
    state.route = "review-center";
    render();
    return true;
  }

  if (action === "go-review-packet") {
    const packetId = el.dataset.packetId;
    if (packetId) {
      state.selectedReviewPacketId = packetId;
      state.route = "review-center";
      state.guidedReviewOpen = false;
      render();
    }
    return true;
  }

  if (action === "open-review-upload") {
    state.route = "mapping-studio";
    state.studio.step = 1;
    render();
    return true;
  }

  if (action === "approve-config") {
    const configId = el.dataset.configId;
    if (!configId) return true;
    fetch(`/api/v1/mappings/${encodeURIComponent(configId)}/approve`, {
      method: "POST",
      headers: withActorHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ reviewedBy: getActorName() }),
    })
      .then(r => r.json().then(body => ({ ok: r.ok, body })))
      .then(({ ok, body }) => {
        if (!ok) throw new Error(body.detail || "Approve failed");
        if (state.selectedReviewPacketId === configId) {
          state.selectedReviewPacketId = null;
        }
        showToast("Mapping config approved.");
        render();
      })
      .catch(err => showToast(err.message || "Approve failed"));
    return true;
  }

  if (action === "reject-config") {
    const configId = el.dataset.configId;
    if (!configId) return true;
    fetch(`/api/v1/mappings/${encodeURIComponent(configId)}/reject`, {
      method: "POST",
      headers: withActorHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ reviewedBy: getActorName() }),
    })
      .then(r => r.json().then(body => ({ ok: r.ok, body })))
      .then(({ ok, body }) => {
        if (!ok) throw new Error(body.detail || "Reject failed");
        if (state.selectedReviewPacketId === configId) {
          state.selectedReviewPacketId = null;
        }
        showToast("Draft mapping rejected.");
        render();
      })
      .catch(err => showToast(err.message || "Reject failed"));
    return true;
  }

  if (action === "refresh-config") {
    showToast("Re-run AI is triggered from the next fetch cycle.");
    return true;
  }

  if (
    action === "approve-packet-activate" ||
    action === "approve-packet-keep-current" ||
    action === "reject-packet" ||
    action === "send-packet-to-studio"
  ) {
    const packetId = el.dataset.packetId;
    if (!packetId) return true;

    let actionLabel = "";
    if (action === "approve-packet-activate") actionLabel = "approve and activate this configuration";
    if (action === "approve-packet-keep-current") actionLabel = "approve this file but keep the current runtime configuration";
    if (action === "reject-packet") actionLabel = "reject this proposed change";
    if (action === "send-packet-to-studio") actionLabel = "send this item to Mapping Studio for adjustments";

    const originalText = el.innerHTML;
    el.disabled = true;
    el.style.opacity = "0.6";
    el.style.cursor = "not-allowed";
    if (action === "approve-packet-activate") {
      el.innerHTML = `<span class="spinner-mini" style="display:inline-block; width:12px; height:12px; border:2px solid #000; border-top:2px solid transparent; border-radius:50%; animation:spin 1s linear infinite; margin-right:6px; vertical-align:middle;"></span>Reconciling...`;
    } else if (action === "approve-packet-keep-current") {
      el.innerHTML = `Approving...`;
    } else if (action === "reject-packet") {
      el.innerHTML = `Rejecting...`;
    } else {
      el.innerHTML = `Processing...`;
    }

    const isVirtual = !state.reviewPackets.some(p => p._id === packetId);
    if (isVirtual) {
      if (action === "send-packet-to-studio") {
        el.disabled = false;
        el.style.opacity = "";
        el.style.cursor = "";
        el.innerHTML = originalText;
        state.studio.reviewItemId = null;
        state.studio.draftMappingId = packetId;
        state.studio.step = 2;
        location.hash = "mapping-studio";
        return true;
      }
      const endpoint = action === "reject-packet" ? "reject" : "approve";
      fetch(`/api/v1/mappings/${encodeURIComponent(packetId)}/${endpoint}`, {
        method: "POST",
        headers: withActorHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({ reviewedBy: getActorName() }),
      })
        .then(r => r.json().then(body => ({ ok: r.ok, body })))
        .then(({ ok, body }) => {
          el.disabled = false;
          el.style.opacity = "";
          el.style.cursor = "";
          el.innerHTML = originalText;
          if (!ok) throw new Error(body.detail || "Action failed");
          if (state.selectedReviewPacketId === packetId) {
            state.selectedReviewPacketId = null;
          }
          showToast("Mapping config updated successfully.");
          render();
        })
        .catch(err => {
          el.disabled = false;
          el.style.opacity = "";
          el.style.cursor = "";
          el.innerHTML = originalText;
          showToast(err.message || "Action failed");
        });
      return true;
    }

    const endpointMap = {
      "approve-packet-activate": "approve-activate",
      "approve-packet-keep-current": "approve-keep-current",
      "reject-packet": "reject",
      "send-packet-to-studio": "send-to-studio",
    };
    const payload = {};
    if (action === "approve-packet-activate" || action === "approve-packet-keep-current") {
      const scopeSelectEl = document.getElementById("scope-override-select");
      if (scopeSelectEl) {
        payload.scopeType = scopeSelectEl.value;
      } else if (state.overrideScopes && state.overrideScopes[packetId]) {
        payload.scopeType = state.overrideScopes[packetId];
      }
    }
    payload.reviewedBy = getActorName();
    fetch(`/api/v1/review-packets/${encodeURIComponent(packetId)}/${endpointMap[action]}`, {
      method: "POST",
      headers: withActorHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify(payload),
    })
      .then(r => r.json().then(body => ({ ok: r.ok, body })))
      .then(async ({ ok, body }) => {
        el.disabled = false;
        el.style.opacity = "";
        el.style.cursor = "";
        el.innerHTML = originalText;
        if (!ok) throw new Error(body.detail || "Review packet action failed");
        if (action === "send-packet-to-studio") {
          showToast("Opening Mapping Studio with this review item.");
          await openPacketInStudio(packetId);
          return;
        }
        if (state.selectedReviewPacketId === packetId) {
          state.selectedReviewPacketId = null;
        }
        if (action === "approve-packet-activate") {
          const runInfo = body.postApproveRun ? {
            ...body.postApproveRun,
            packetId,
            partner: body.postApproveRun.partner || state.partner,
            date: body.postApproveRun.date || state.date,
            status: body.postApproveRun.status || "INGESTING",
            stage: body.postApproveRun.stage || "INGESTING",
            message: body.postApproveRun.message || "Approved. Ingesting partner file and preparing reconciliation.",
            updatedAt: body.postApproveRun.updatedAt || new Date().toISOString(),
          } : {
            packetId,
            partner: state.partner,
            date: state.date,
            status: "INGESTING",
            stage: "INGESTING",
            message: "Approved. Ingesting partner file and preparing reconciliation.",
            updatedAt: new Date().toISOString(),
          };
          if (runInfo?.partner) state.partner = runInfo.partner;
          if (runInfo?.date) state.date = runInfo.date;
          if (runInfo?.packetId) {
            syncLocalReviewPacket(packetId, {
              status: "APPROVED",
              reviewedAt: new Date().toISOString(),
            });
            state.selectedReviewPacketId = packetId;
            state.guidedReviewOpen = true;
            state.guidedReviewStep = 4;
            state.reviewCenterCache = null;
            upsertPostApprovalRun(runInfo);
            pollPostApprovalRun(runInfo.packetId);
            showToast("Approved. Ingestion and reconciliation have started.");
          } else {
            showToast("Review packet updated.");
            state.guidedReviewOpen = false;
          }
        } else {
          state.guidedReviewOpen = false;
          showToast("Review packet updated.");
        }
        render();
      })
      .catch(err => {
        el.disabled = false;
        el.style.opacity = "";
        el.style.cursor = "";
        el.innerHTML = originalText;
        showToast(err.message || "Review packet action failed");
      });
    return true;
  }

  if (action === "validate-runtime-packet") {
    const packetId = el.dataset.packetId;
    if (!packetId) {
      showToast("Missing review packet id for runtime validation.");
      return true;
    }
    const originalText = el.innerHTML;
    el.disabled = true;
    el.style.opacity = "0.65";
    el.innerHTML = `<span class="spinner-mini" style="display:inline-block; width:12px; height:12px; border:2px solid #fff; border-top:2px solid transparent; border-radius:50%; animation:spin 1s linear infinite; margin-right:6px; vertical-align:middle;"></span>Validating...`;
    fetch(`/api/v1/review-packets/${encodeURIComponent(packetId)}/validate-runtime`, {
      method: "POST",
      headers: withActorHeaders({ "Content-Type": "application/json" }),
    })
      .then(r => r.json().then(body => ({ ok: r.ok, body })))
      .then(({ ok, body }) => {
        el.disabled = false;
        el.style.opacity = "";
        el.innerHTML = originalText;
        if (!ok) throw new Error(body.detail || "Runtime validation failed");
        const currentPacket = ([...(state.reviewCenterCache?.data?.packets || []), ...(state.reviewPackets || [])].find(packet => String(packet._id) === String(packetId)) || {});
        const gates = Array.isArray(currentPacket.validationGates) ? currentPacket.validationGates.filter(gate => gate.gateKey !== body.gate.gateKey) : [];
        gates.push(body.gate);
        syncLocalReviewPacket(packetId, {
          draftMappingId: currentPacket.draftMappingId || null,
          draftMappingVersion: currentPacket.draftMappingVersion || body.gate?.details?.validatedMappingVersion || currentPacket.draftMappingId || null,
          validationGates: gates,
          parseStrategy: currentPacket.parseStrategy || {}
        });
        state.reviewCenterCache = null;
        showToast(body.gate?.reason || "Runtime validation completed.");
        renderPreserveScroll();
      })
      .catch(err => {
        el.disabled = false;
        el.style.opacity = "";
        el.innerHTML = originalText;
        showToast(err.message || "Runtime validation failed");
      });
    return true;
  }

  if (action === "set-review-tab") {
    const tab = el.dataset.tab;
    if (tab) {
      state.reviewTab = tab;
      render();
      if (tab === "history" && (!state.reviewHistoryCache || state.reviewHistoryCache.key !== `${state.partner}:${state.date}`)) {
        loadReviewHistoryData().catch(() => {
          showToast("Failed to load review history.");
        });
      }
    }
    return true;
  }

  if (action === "open-copilot-brief") {
    state.briefOpen = true;
    render();
    return true;
  }

  if (action === "close-brief") {
    state.briefOpen = false;
    state.briefStep = 0;
    render();
    return true;
  }

  if (action === "brief-next") {
    state.briefStep = Math.min(2, (state.briefStep || 0) + 1);
    render();
    return true;
  }

  if (action === "brief-prev") {
    state.briefStep = Math.max(0, (state.briefStep || 0) - 1);
    render();
    return true;
  }

  return false;
}
