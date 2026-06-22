export function isTerminalPostApprovalRun(run) {
  const status = String(run?.status || "").toUpperCase();
  return status === "COMPLETED" || status === "FAILED";
}

export function isTerminalReconciliationRun(run) {
  const status = String(run?.status || "").toUpperCase();
  return status === "COMPLETED" || status === "FAILED";
}

export function isLiveReconciliationRunStatus(status) {
  return ["QUEUED", "FETCHING", "INGESTING", "RECONCILING", "RUNNING"].includes(String(status || "").toUpperCase());
}

export function isActiveRuntimeStatus(status) {
  return ["QUEUED", "FETCHING", "INGESTING", "WAITING_REVIEW", "WAITING_RECONCILE", "RECONCILING", "RUNNING"].includes(String(status || "").toUpperCase());
}

export function getActivePostApprovalRunForContext(state) {
  const runs = Object.values(state.postApprovalRuns || {});
  return runs.find(run =>
    run &&
    run.partner === state.partner &&
    run.date === state.date &&
    !isTerminalPostApprovalRun(run)
  ) || null;
}

export function getPostApprovalRunForPacket(state, packetId) {
  if (!packetId) return null;
  return (state.postApprovalRuns || {})[String(packetId)] || null;
}

export function hasMeaningfulRunChange(previousRun, nextRun) {
  if (!previousRun && !nextRun) return false;
  if (!previousRun || !nextRun) return true;
  return [
    "status",
    "message",
    "reconciliationCount",
    "sourceFileId",
    "mappingVersion",
    "startedAt",
    "finishedAt"
  ].some(key => String(previousRun[key] ?? "") !== String(nextRun[key] ?? ""));
}

export function updateReviewPacketLocally(state, packetId, updater) {
  state.reviewPackets = (state.reviewPackets || []).map(packet => {
    if (String(packet._id) !== String(packetId)) return packet;
    const nextPacket = { ...packet };
    updater(nextPacket);
    return nextPacket;
  });
  if (state.reviewCenterCache && state.reviewCenterCache.data && Array.isArray(state.reviewCenterCache.data.packets)) {
    state.reviewCenterCache.data.packets = state.reviewCenterCache.data.packets.map(packet => {
      if (String(packet._id) !== String(packetId)) return packet;
      const nextPacket = { ...packet };
      updater(nextPacket);
      return nextPacket;
    });
  }
}

export function syncLocalReviewPacket(state, packetId, updates = {}) {
  if (updates.draftMappingId) {
    state.localDraftMappingIds = state.localDraftMappingIds || {};
    state.localDraftMappingIds[packetId] = updates.draftMappingId;
  }
  updateReviewPacketLocally(state, packetId, currentPacket => {
    if (Object.prototype.hasOwnProperty.call(updates, "status")) {
      currentPacket.status = updates.status;
    }
    if (Object.prototype.hasOwnProperty.call(updates, "reviewedAt")) {
      currentPacket.reviewedAt = updates.reviewedAt;
    }
    if (Object.prototype.hasOwnProperty.call(updates, "draftMappingId")) {
      currentPacket.draftMappingId = updates.draftMappingId;
    }
    if (Object.prototype.hasOwnProperty.call(updates, "draftMappingVersion")) {
      currentPacket.draftMappingVersion = updates.draftMappingVersion;
    }
    if (Object.prototype.hasOwnProperty.call(updates, "validationGates")) {
      currentPacket.validationGates = updates.validationGates || [];
    }
    if (Object.prototype.hasOwnProperty.call(updates, "parseStrategy")) {
      currentPacket.parseStrategy = updates.parseStrategy;
    }
  });
}

export function upsertPostApprovalRun(state, run) {
  if (!run || !run.packetId) return;
  state.postApprovalRuns = state.postApprovalRuns || {};
  state.postApprovalRuns[String(run.packetId)] = {
    ...(state.postApprovalRuns[String(run.packetId)] || {}),
    ...run
  };
}
