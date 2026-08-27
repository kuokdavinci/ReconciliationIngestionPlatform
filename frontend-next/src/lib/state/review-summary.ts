import type { ReviewPacket } from "@/types/review-center";

export function summarizeReviewPacket(packet: ReviewPacket) {
  const gateSummary = (packet.validationGates || []).reduce<Record<string, number>>((acc, gate) => {
    const status = String(gate.status || "").toLowerCase();
    acc[status] = (acc[status] || 0) + 1;
    return acc;
  }, {});
  const hasFailedGates = !!((gateSummary.fail || 0) + (gateSummary.failed || 0));
  const runtimeGate = (packet.validationGates || []).find((gate) => gate.gateKey === "runtime_validation");
  const runtimeValidated = String(runtimeGate?.status || "").toLowerCase() === "pass";
  const mappingReady = !!packet.draftMappingId;
  return {
    gateSummary,
    hasFailedGates,
    runtimeGate,
    runtimeValidated,
    mappingReady,
    readyToActivate: mappingReady && runtimeValidated && !hasFailedGates,
  };
}
