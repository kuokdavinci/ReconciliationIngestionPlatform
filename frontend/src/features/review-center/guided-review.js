const INLINE_FIELD_TYPES = {
  id: "STRING",
  amount: "DECIMAL",
  transDate: "DATE",
  status: "STRING",
  trace: "STRING",
  extra_data: "STRING",
  currency: "STRING",
  description: "STRING"
};

// Shared helper to save draft mapping
async function saveDraftMapping({
  el,
  packetId,
  state,
  render,
  showToast,
  withActorHeaders,
  syncLocalReviewPacket,
  originalText
}) {
  const currentPacket = [
    ...(state.reviewPackets || []),
    ...((state.reviewCenterCache && state.reviewCenterCache.data && state.reviewCenterCache.data.packets) || [])
  ].find(packet => String(packet._id) === String(packetId)) || null;

  const rows = Array.from(document.querySelectorAll(".inline-field-select"));
  const fieldMappings = rows.map((select, index) => {
    const path = select.value;
    if (!path) return null;
    const sourceHeader = select.dataset.sourceHeader || `Column ${index + 1}`;
    const rawSourceColumn = select.dataset.sourceColumn;
    const sourceColumn = rawSourceColumn ? Number(rawSourceColumn) : null;
    const originalPath = select.dataset.originalPath || "";
    const originalType = select.dataset.originalType || "";
    const originalRequired = select.dataset.originalRequired === "true";
    const originalConstant = select.dataset.originalConstant || null;
    let originalMapping = null;
    if (select.dataset.originalMapping) {
      try {
        originalMapping = JSON.parse(select.dataset.originalMapping);
      } catch (err) {
        originalMapping = null;
      }
    }

    if (path === originalPath) {
      return {
        path,
        column: sourceColumn,
        sourceField: sourceHeader,
        type: originalType || INLINE_FIELD_TYPES[path] || "STRING",
        required: originalRequired,
        constant: originalConstant,
        mapping: originalMapping
      };
    }

    return {
      path,
      column: sourceColumn,
      sourceField: sourceHeader,
      type: INLINE_FIELD_TYPES[path] || "STRING",
      required: ["id", "amount", "transDate"].includes(path)
    };
  }).filter(Boolean);

  el.disabled = true;
  el.style.opacity = "0.65";
  el.innerHTML = `<span class="spinner-mini" style="display:inline-block; width:12px; height:12px; border:2px solid #fff; border-top:2px solid transparent; border-radius:50%; animation:spin 1s linear infinite; margin-right:6px; vertical-align:middle;"></span>Saving...`;

  try {
    const response = await fetch(`/api/v1/review-packets/${encodeURIComponent(packetId)}/save-draft-mapping`, {
      method: "POST",
      headers: withActorHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({
        sheetName: currentPacket?.parseStrategy?.sheetName || "Sheet1",
        startRow: currentPacket?.parseStrategy?.startRow || 2,
        fieldMappings
      }),
    });
    
    const body = await response.json();
    el.disabled = false;
    el.style.opacity = "";
    el.innerHTML = originalText;

    if (!response.ok) {
      const detail = body.detail;
      if (detail && typeof detail === "object") {
        const msg = [detail.message, ...(detail.errors || []), ...(detail.warnings || [])]
          .filter(Boolean)
          .join(" ");
        throw new Error(msg || "Save mapping failed");
      }
      throw new Error(detail || "Save mapping failed");
    }

    state.guidedReviewAI = {
      loading: false,
      error: "",
      mapping: {
        ...(state.guidedReviewAI.mapping || {}),
        _id: body.draftMappingId,
        configVersion: body.draftMappingVersion || state.guidedReviewAI.mapping?.configVersion || body.draftMappingId,
        draftMappingVersion: body.draftMappingVersion || body.draftMappingId,
        fieldMappings,
        sheetName: body.sheetName,
        startRow: body.startRow,
      },
      packetId
    };

    syncLocalReviewPacket(packetId, {
      draftMappingId: body.draftMappingId,
      draftMappingVersion: body.draftMappingVersion || body.draftMappingId,
      validationGates: Array.isArray(body.validationGates) ? body.validationGates : [],
      parseStrategy: {
        ...(currentPacket?.parseStrategy || {}),
        sheetName: body.sheetName,
        startRow: body.startRow,
        fieldMappingCount: body.fieldMappingCount
      }
    });

    state.reviewCenterCache = null;
    showToast("Draft mapping saved.");
    state.guidedReviewStep = 3;
    render();
  } catch (err) {
    el.disabled = false;
    el.style.opacity = "";
    el.innerHTML = originalText;
    showToast(err.message || "Save mapping failed");
  }
}

export function handleGuidedReviewAction({
  action,
  el,
  state,
  render,
  renderPreserveScroll,
  showToast,
  withActorHeaders,
  getReviewPacketById,
  syncLocalReviewPacket,
  updateReviewPacketLocally,
  getReviewCenterPendingItems,
  getSelectedReviewPacket,
  getTrackedReviewPacket,
  getRuntimeValidationState,
  pollPostApprovalRun,
  loadGuidedReviewScopeLLM,
  loadGuidedReviewAIMapping
}) {
  if (action === "open-guided-review") {
    state.guidedReviewOpen = true;
    state.guidedReviewScope = { loading: false, error: "", data: null, packetId: null };
    state.guidedReviewAI = { loading: false, error: "", mapping: null, packetId: null };
    state.guidedReviewTraceModal = { open: false, sampleIndex: null };
    state.guidedReviewScopeChoice = "";
    
    let packet = getTrackedReviewPacket(state.reviewCenterCache?.data);
    if (!packet) {
      packet = getSelectedReviewPacket(getReviewCenterPendingItems(state.reviewCenterCache?.data || { packets: state.reviewPackets, mappings: [], intake: {} }));
    }
    if (packet && String(packet.status).toUpperCase() === "APPROVED") {
      state.guidedReviewStep = 4;
      render();
      pollPostApprovalRun(packet._id);
    } else {
      state.guidedReviewStep = 1;
      render();
      if (packet) {
        loadGuidedReviewScopeLLM(packet);
      }
    }
    return true;
  }

  if (action === "open-guided-runtime-detail") {
    const sampleIndex = Number(el.dataset.sampleIndex);
    if (!Number.isInteger(sampleIndex)) return true;
    state.guidedReviewTraceModal = { open: true, sampleIndex };
    renderPreserveScroll();
    return true;
  }

  if (action === "close-guided-runtime-detail") {
    state.guidedReviewTraceModal = { open: false, sampleIndex: null };
    renderPreserveScroll();
    return true;
  }

  if (action === "guided-next") {
    const packetId = el.dataset.packetId;
    if (!packetId) return true;

    const step = state.guidedReviewStep || 1;
    if (step === 1) {
      const choice = document.querySelector('input[name="guided-scope-choice"]:checked');
      const scopeType = state.guidedReviewScopeChoice || choice?.value || "";
      if (!scopeType) {
        showToast("Please select a file scope.");
        return true;
      }
      const originalText = el.innerHTML;
      el.disabled = true;
      el.style.opacity = "0.6";
      el.innerHTML = "Saving...";
      
      fetch(`/api/v1/review-packets/${encodeURIComponent(packetId)}/scope`, {
        method: "POST",
        headers: withActorHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({ scopeType }),
      })
        .then(r => r.json().then(body => ({ ok: r.ok, body })))
        .then(({ ok, body }) => {
          el.disabled = false;
          el.style.opacity = "";
          el.innerHTML = originalText;
          if (!ok) throw new Error(body.detail || "Failed to update scope.");
          
          updateReviewPacketLocally(packetId, currentPacket => {
            currentPacket.scopeType = scopeType;
          });
          
          const currentPacket = [
            ...(state.reviewPackets || []),
            ...((state.reviewCenterCache && state.reviewCenterCache.data && state.reviewCenterCache.data.packets) || [])
          ].find(packet => String(packet._id) === String(packetId)) || null;
          
          if (currentPacket && getRuntimeValidationState(currentPacket).hasValidation) {
            state.guidedReviewStep = 3;
          } else {
            state.guidedReviewStep = 2;
            if (currentPacket) {
              loadGuidedReviewAIMapping(currentPacket);
            }
          }
          render();
        })
        .catch(err => {
          el.disabled = false;
          el.style.opacity = "";
          el.innerHTML = originalText;
          showToast(err.message || "Failed to save scope.");
        });
      return true;
    } else if (step === 2) {
      saveDraftMapping({
        el,
        packetId,
        state,
        render,
        showToast,
        withActorHeaders,
        syncLocalReviewPacket,
        originalText: el.innerHTML
      });
      return true;
    } else if (step === 3) {
      const currentPacket = getReviewPacketById(packetId);
      if (!getRuntimeValidationState(currentPacket || {}).canProceed) {
        showToast("Run current runtime validation before moving to the decision step.");
        return true;
      }
      state.guidedReviewStep = 4;
      render();
      return true;
    }
    return true;
  }

  if (action === "guided-prev") {
    if (state.guidedReviewStep && state.guidedReviewStep > 1) {
      state.guidedReviewStep -= 1;
      state.guidedReviewTraceModal = { open: false, sampleIndex: null };
      render();
    }
    return true;
  }

  if (action === "back-to-guided-step-1") {
    state.guidedReviewStep = 1;
    render();
    return true;
  }

  if (action === "back-to-guided-step-3") {
    state.guidedReviewStep = 3;
    state.guidedReviewTraceModal = { open: false, sampleIndex: null };
    render();
    return true;
  }

  if (action === "close-guided-review") {
    state.guidedReviewOpen = false;
    state.guidedReviewAI = { loading: false, error: "", mapping: null, packetId: null };
    state.guidedReviewTraceModal = { open: false, sampleIndex: null };
    render();
    return true;
  }

  if (action === "save-inline-mapping") {
    const packetId = el.dataset.packetId;
    if (!packetId) return true;
    saveDraftMapping({
      el,
      packetId,
      state,
      render,
      showToast,
      withActorHeaders,
      syncLocalReviewPacket,
      originalText: el.innerHTML
    });
    return true;
  }

  return false;
}

export function loadGuidedReviewAIMapping(state, packet, fetchJson, withActorHeaders, syncLocalReviewPacket, render) {
  if (!packet || !packet.partner) {
    state.guidedReviewAI = {
      loading: false,
      error: "No review item is available for AI mapping.",
      mapping: null,
      packetId: packet?._id || null
    };
    render();
    return;
  }
  if (
    state.guidedReviewAI &&
    state.guidedReviewAI.packetId === packet._id &&
    (state.guidedReviewAI.loading || state.guidedReviewAI.mapping || state.guidedReviewAI.error)
  ) {
    return;
  }
  state.guidedReviewAI = {
    loading: true,
    error: "",
    mapping: null,
    packetId: packet._id
  };
  render();
  fetch(`/api/v1/review-packets/${encodeURIComponent(packet._id)}/generate-ai-mapping`, {
    method: "POST",
    headers: withActorHeaders({ "Content-Type": "application/json" }),
  })
    .then(r => r.json().then(body => ({ ok: r.ok, body })))
    .then(({ ok, body }) => {
      if (!ok) {
        throw new Error(body.detail || "Failed to generate AI mapping proposal.");
      }
      const mapping = body.mapping || null;
      if (body.draftMappingId) {
        syncLocalReviewPacket(packet._id, {
          draftMappingId: body.draftMappingId,
          draftMappingVersion: body.draftMappingVersion || mapping?.draftMappingVersion || mapping?.configVersion || body.draftMappingId,
          validationGates: Array.isArray(body.validationGates) ? body.validationGates : [],
          parseStrategy: {
            ...(packet.parseStrategy || {}),
            sheetName: mapping?.sheetName || packet?.parseStrategy?.sheetName || "Sheet1",
            startRow: mapping?.startRow || packet?.parseStrategy?.startRow || 2,
            fieldMappingCount: (mapping?.fieldMappings || []).length,
          }
        });
      }
      state.guidedReviewAI = {
        loading: false,
        error: mapping ? "" : "AI draft mapping was not found for this review item.",
        mapping,
        packetId: packet._id
      };
      render();
    })
    .catch(err => {
      state.guidedReviewAI = {
        loading: false,
        error: err.message || "Failed to load AI mapping proposal.",
        mapping: null,
        packetId: packet._id
      };
      render();
    });
}

export function loadGuidedReviewScopeLLM(state, packet, withActorHeaders, renderPreserveScroll) {
  if (!packet || !packet._id) return;
  if (state.guidedReviewScope && state.guidedReviewScope.packetId === packet._id && (state.guidedReviewScope.loading || state.guidedReviewScope.data)) {
    return;
  }
  state.guidedReviewScope = {
    loading: true,
    error: "",
    data: null,
    packetId: packet._id
  };
  renderPreserveScroll();
  fetch(`/api/v1/review-packets/${encodeURIComponent(packet._id)}/classify-scope-llm`, {
    method: "POST",
    headers: withActorHeaders({ "Content-Type": "application/json" }),
  })
    .then(r => r.json().then(body => ({ ok: r.ok, body })))
    .then(({ ok, body }) => {
      if (!ok) {
        throw new Error(body.detail || "Failed to classify scope.");
      }
      state.guidedReviewScope.loading = false;
      state.guidedReviewScope.data = body;
      renderPreserveScroll();
    })
    .catch(err => {
      state.guidedReviewScope.loading = false;
      state.guidedReviewScope.error = err.message || "Failed to load scope classification.";
      renderPreserveScroll();
    });
}
