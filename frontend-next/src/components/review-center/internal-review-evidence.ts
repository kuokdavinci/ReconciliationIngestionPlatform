import type { InternalReviewPreviewRow, ReviewPacket } from "@/types/review-center";

interface ScopeEvidenceResponse {
  internalDbRecordCount?: number;
  internalPreview?: InternalReviewPreviewRow[];
}

export function resolveInternalReviewEvidence(
  packet: ReviewPacket,
  scopeClassification: ScopeEvidenceResponse | null,
) {
  const packetCount = Number(packet.internalRecordCount ?? 0);
  const classifiedCount = Number(scopeClassification?.internalDbRecordCount ?? 0);
  const packetPreview = packet.internalPreview ?? [];
  const classifiedPreview = scopeClassification?.internalPreview ?? [];

  return {
    // A transient/stale scope response must not hide evidence already attached to the packet.
    recordCount: classifiedCount > 0 ? classifiedCount : packetCount,
    preview: classifiedPreview.length > 0 ? classifiedPreview : packetPreview,
  };
}
