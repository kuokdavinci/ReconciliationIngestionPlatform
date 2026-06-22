export function getReviewCenterPendingItems(state, data) {
  const packets = (data.packets || []).filter(packet => !state.partner || packet.partner === state.partner);
  const mappings = (data.mappings || []).filter(item => item.partner === state.partner);
  const pendingPackets = packets.filter(item => String(item.status || "").toUpperCase() === "PENDING");
  const pendingMappings = mappings.filter(item => item.status === "PENDING_APPROVAL" && !pendingPackets.some(p => p.draftMappingId === item._id));
  const virtualPackets = pendingMappings.map(mapping => ({
    _id: mapping._id,
    partner: mapping.partner,
    fileName: mapping.sheetName || "Manual Configuration",
    fileTypeDetected: mapping.fileType || "SETTLEMENT",
    status: "PENDING",
    draftMappingId: mapping._id,
    recommendedAction: { actionType: "APPROVE_REQUIRED_BEFORE_RUNTIME", reason: mapping.configHealth?.reasoning || "Pending mapping review." },
    parseStrategy: { sheetName: mapping.sheetName, startRow: mapping.startRow, fieldMappingCount: (mapping.fieldMappings || []).length },
    validationGates: mapping.validationGates || [],
    samplePreview: [],
    riskSummary: { severity: "medium" },
    createdAt: mapping.createdAt,
    isVirtual: true
  }));

  return [...pendingPackets, ...virtualPackets].map(packet => {
    const localDraftMappingId = state.localDraftMappingIds ? state.localDraftMappingIds[packet._id] : null;
    if (state.localValidationGates && state.localValidationGates[packet._id]) {
      return {
        ...packet,
        validationGates: state.localValidationGates[packet._id],
        draftMappingId: localDraftMappingId || packet.draftMappingId || null
      };
    }
    if (localDraftMappingId) {
      return {
        ...packet,
        draftMappingId: localDraftMappingId
      };
    }
    return packet;
  });
}

export function getSelectedReviewPacket(state, items) {
  return items.find(packet => packet._id === state.selectedReviewPacketId) || items[0] || null;
}

export function getTrackedReviewPacket(state, data) {
  const packetId = state.selectedReviewPacketId;
  if (!packetId) return null;
  const packets = data?.packets || state.reviewPackets || [];
  return packets.find(packet => String(packet._id) === String(packetId)) || null;
}

export function getReviewPacketById(state, packetId) {
  return ([...(state.reviewCenterCache?.data?.packets || []), ...(state.reviewPackets || [])]
    .find(item => String(item._id) === String(packetId)) || null);
}

export function summarizeReviewPacket(packet) {
  const gateSummary = (packet.validationGates || []).reduce((acc, gate) => {
    const status = String(gate.status || "").toLowerCase();
    acc[status] = (acc[status] || 0) + 1;
    return acc;
  }, {});
  const hasFailedGates = !!((gateSummary.fail || 0) + (gateSummary.failed || 0));
  const runtimeGate = (packet.validationGates || []).find(gate => gate.gateKey === "runtime_validation");
  const runtimeValidated = String(runtimeGate?.status || "").toLowerCase() === "pass";
  const mappingReady = !!packet.draftMappingId;
  return {
    gateSummary,
    hasFailedGates,
    runtimeGate,
    runtimeValidated,
    mappingReady,
    readyToActivate: mappingReady && runtimeValidated && !hasFailedGates
  };
}
