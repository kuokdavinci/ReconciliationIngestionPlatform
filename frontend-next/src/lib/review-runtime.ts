import type { ReviewPacket, ValidationGate } from "@/types/review-center";

export interface RuntimeValidationState {
  runtimeGate: ValidationGate | null;
  currentVersion: string | null;
  validatedVersion: string | null;
  validatedAt: string | null;
  hasValidation: boolean;
  isStale: boolean;
  failedRows: number;
  canProceed: boolean;
  summaryLabel: string;
}

export function getDraftMappingVersion(packet: ReviewPacket): string | null {
  return (packet?.draftMappingId) || null;
}

export function getRuntimeValidationState(packet: ReviewPacket): RuntimeValidationState {
  const runtimeGate = (packet?.validationGates || []).find(gate => gate.gateKey === "runtime_validation") || null;
  const details = (runtimeGate?.details || {}) as Record<string, unknown>;
  const currentVersion = getDraftMappingVersion(packet);
  const validatedVersion = (details.validatedMappingVersion as string) || null;
  const hasValidation = !!runtimeGate;
  const isStale = !!(hasValidation && currentVersion && validatedVersion && currentVersion !== validatedVersion);
  const failedRows = Number(details.failedRows || 0);
  const status = String(runtimeGate?.status || "").toLowerCase();
  const summaryLabel = !hasValidation
    ? "Not run"
    : isStale
      ? "Stale"
      : status !== "pass"
        ? "Failed"
        : failedRows > 0
          ? "Passed with warnings"
          : "Passed";

  return {
    runtimeGate,
    currentVersion,
    validatedVersion,
    validatedAt: (details.validatedAt as string) || null,
    hasValidation,
    isStale,
    failedRows,
    canProceed: !!(runtimeGate && !isStale && status === "pass"),
    summaryLabel,
  };
}
