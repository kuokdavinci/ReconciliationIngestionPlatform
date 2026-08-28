export type QuarantineStatus = "PENDING" | "REPROCESSING" | "RESOLVED" | "REJECTED";
export type QuarantinePriority = "NORMAL" | "HIGH";
export type QuarantinePhase = "NORMALIZATION" | "VALIDATION" | "BATCH";
export type QuarantineReprocessMode = "REPLAY_SOURCE_ROW" | "CORRECTED_ROW";
export type QuarantineIssueType = "SCHEMA" | "REQUIRED_FIELD" | "FORMAT" | "DUPLICATE" | "RECOVERY" | "OTHER";

export interface QuarantineSampleField {
  sourceField: string;
  canonicalPath?: string | null;
  column?: number | string | null;
  value: unknown;
  state: "OK" | "MISSING" | "INVALID" | "UNKNOWN";
}

export interface QuarantineMappingEvidence {
  configVersion: string | null;
  requiredFields: Array<{
    canonicalPath: string;
    sourceField: string | null;
    column: number | string | null;
    type: string;
    state: "PRESENT" | "MISSING" | "UNKNOWN";
  }>;
  observedColumns: string[] | null;
}

export interface QuarantineDuplicateEvidence {
  status: "CONFLICT" | "EQUIVALENT" | "UNAVAILABLE";
  fields: Array<{
    name: "id" | "trace" | "amount" | "currency" | "status";
    incoming: unknown;
    existing: unknown;
    result: "MATCH" | "DIFF" | "UNAVAILABLE";
  }>;
}

export interface QuarantineEvidence {
  sampleFields?: QuarantineSampleField[];
  mapping?: QuarantineMappingEvidence;
  duplicate?: QuarantineDuplicateEvidence;
}

export interface QuarantineResolutionEvent {
  eventId: string;
  fromStatus: QuarantineStatus;
  toStatus: QuarantineStatus;
  action: string;
  actor: string;
  reason: string;
  attempt: number;
  actionId?: string | null;
  outcome?: string | null;
  timestamp: string;
  metadata: Record<string, unknown>;
}

export interface QuarantineRecord {
  _id: string;
  sourceFileId: string;
  sourceUnitKey?: string | null;
  reviewPacketId?: string | null;
  postApprovalRunId?: string | null;
  quarantineGroupKey?: string | null;
  partner: string;
  reconciliationDate: string;
  rowNumber?: number | null;
  phase: QuarantinePhase;
  severity: string;
  configVersion?: string | null;
  status: QuarantineStatus;
  attemptCount: number;
  claimedBy?: string | null;
  claimedAt?: string | null;
  claimExpiresAt?: string | null;
  lastActionActor?: string | null;
  lastActionAt?: string | null;
  priority: QuarantinePriority;
  reviewDueAt?: string | null;
  escalationLevel: number;
  escalatedAt?: string | null;
  escalatedBy?: string | null;
  lastActionId?: string | null;
  errorCodes: string[];
  issueType?: QuarantineIssueType;
  issueSummary?: string;
  resolutionMetadata: Record<string, unknown>;
  createdAt: string;
  updatedAt: string;
  retentionUntil?: string | null;
  rawRow?: unknown;
  errors?: Array<Record<string, unknown>>;
  evidence?: QuarantineEvidence;
  resolutionHistory?: QuarantineResolutionEvent[];
}

export interface QuarantineSummary {
  pending: number;
  reprocessing: number;
  resolved: number;
  rejected: number;
  overdue: number;
  highPriority: number;
}

export interface QuarantineListResponse {
  items: QuarantineRecord[];
  nextCursor: string | null;
  limit: number;
  summary: QuarantineSummary;
  groups?: QuarantineGroupSummary[];
}

export interface QuarantineGroupSummary {
  groupKey: string;
  reviewPacketId?: string | null;
  postApprovalRunId?: string | null;
  sourceFileId?: string | null;
  partner: string;
  total: number;
  pending: number;
  reprocessing: number;
  resolved: number;
  rejected: number;
  overdue: number;
  highPriority: number;
  issueTypes: string[];
}

export interface QuarantineActionResponse {
  recordId: string;
  actionId: string;
  outcome: string;
  previousStatus: QuarantineStatus | null;
  status: QuarantineStatus | null;
  attemptCount: number | null;
  claimedBy: string | null;
  priority: QuarantinePriority | null;
  reviewDueAt: string | null;
  escalationLevel: number | null;
  sourceEvidenceAvailable: boolean | null;
  qualityCounters: Record<string, number>;
  errorCodes: string[];
  continuation?: QuarantineContinuationResponse;
}

export interface QuarantineContinuationResponse {
  ok: boolean;
  outcome: string;
  reconciliationCount?: number | null;
  qualityGateStatus?: string | null;
  qualityGateSummary?: Record<string, number> | null;
}

export interface QuarantineFilters {
  partner?: string;
  status?: QuarantineStatus;
  priority?: QuarantinePriority;
  issueType?: QuarantineIssueType;
  overdue?: boolean;
  claimedBy?: string;
  reviewPacketId?: string;
  postApprovalRunId?: string;
  cursor?: string;
  limit?: number;
}

export interface QuarantineActionFields {
  operatorId?: string;
  actionId: string;
  expectedStatus: QuarantineStatus;
  reason?: string;
}
