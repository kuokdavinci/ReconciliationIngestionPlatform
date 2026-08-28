import { get, post } from "./client";
import type {
  QuarantineActionFields,
  QuarantineActionResponse,
  QuarantineContinuationResponse,
  QuarantineFilters,
  QuarantineListResponse,
  QuarantineReprocessMode,
} from "@/types/quarantine";

export function listQuarantine(filters: QuarantineFilters = {}) {
  return get<QuarantineListResponse>("/quarantine", {
    partner: filters.partner,
    status: filters.status,
    priority: filters.priority,
    issueType: filters.issueType,
    overdue: filters.overdue === undefined ? undefined : String(filters.overdue),
    claimedBy: filters.claimedBy,
    reviewPacketId: filters.reviewPacketId,
    postApprovalRunId: filters.postApprovalRunId,
    cursor: filters.cursor,
    limit: filters.limit ?? 100,
  });
}

export function getQuarantineRecord(recordId: string) {
  return get<import("@/types/quarantine").QuarantineRecord>(`/quarantine/${encodeURIComponent(recordId)}`);
}

export function claimQuarantine(recordId: string, fields: QuarantineActionFields) {
  return post<QuarantineActionResponse>(`/quarantine/${encodeURIComponent(recordId)}/claim`, fields);
}

export function reprocessQuarantine(
  recordId: string,
  fields: QuarantineActionFields & {
    mode: QuarantineReprocessMode;
    correctedRow?: unknown;
    mappingVersion?: string;
  },
) {
  return post<QuarantineActionResponse>(`/quarantine/${encodeURIComponent(recordId)}/reprocess`, fields);
}

export function acceptExistingQuarantine(recordId: string, fields: QuarantineActionFields) {
  return post<QuarantineActionResponse>(`/quarantine/${encodeURIComponent(recordId)}/accept-existing`, fields);
}

export function rejectQuarantine(recordId: string, fields: QuarantineActionFields & { reason: string }) {
  return post<QuarantineActionResponse>(`/quarantine/${encodeURIComponent(recordId)}/reject`, fields);
}

export function escalateQuarantine(recordId: string, fields: QuarantineActionFields & { reason: string }) {
  return post<QuarantineActionResponse>(`/quarantine/${encodeURIComponent(recordId)}/escalate`, fields);
}

export function resumeQuarantineSourceUnit(
  sourceUnitKey: string,
  fields: { operatorId?: string; actionId: string; reason: string },
) {
  return post<Record<string, unknown>>(
    `/quarantine/source-units/${encodeURIComponent(sourceUnitKey)}/resume`,
    fields,
  );
}

export function continuePostApprovalRun(packetId: string) {
  return post<QuarantineContinuationResponse>(
    `/review-packets/${encodeURIComponent(packetId)}/post-approve-run/continue`,
    {},
  );
}
