export const RECOVERY_STATUSES = [
  "IDLE",
  "PENDING",
  "PROCESSING",
  "FAILED",
  "BLOCKED",
  "WAITING_REVIEW",
  "COMPLETED",
  "REPLAYED",
] as const;

export type RecoveryStatus = (typeof RECOVERY_STATUSES)[number];

export const RECOVERY_UNIT_STATUSES = [
  "PENDING",
  "PROCESSING",
  "COMPLETED",
  "FAILED",
  "BLOCKED",
  "WAITING_REVIEW",
  "REPLAYED",
  "SKIPPED",
] as const;

export type RecoveryUnitStatus = (typeof RECOVERY_UNIT_STATUSES)[number];

export interface RecoveryUnitSummary {
  unitKey: string;
  label?: string | null;
  page?: number | null;
  status: RecoveryUnitStatus;
  cursorBefore?: string | null;
  cursorAfter?: string | null;
  attemptCount: number;
  lastError?: string | null;
  errorCode?: string | null;
  retryable?: boolean | null;
  nextRetryAt?: string | null;
  startedAt?: string | null;
  completedAt?: string | null;
  updatedAt?: string | null;
}

export interface RecoveryEvent {
  eventId: string;
  unitKey?: string | null;
  status: string;
  action?: string | null;
  timestamp: string;
  actor?: string | null;
  reason?: string | null;
  errorCode?: string | null;
  message?: string | null;
  requestAttempt?: number;
}

export interface RecoverySummary {
  status: RecoveryStatus;
  streamKey?: string | null;
  mode?: string | null;
  lastCompletedUnitKey?: string | null;
  currentUnitKey?: string | null;
  currentPage?: number | null;
  cursorBefore?: string | null;
  attemptCount: number;
  maxAttempts: number;
  requestAttemptCount: number;
  retryable?: boolean | null;
  nextRetryAt?: string | null;
  errorCode?: string | null;
  lastError?: string | null;
  units: RecoveryUnitSummary[];
  fetchedUnitCount: number;
  completedUnitCount: number;
  totalUnitCount: number;
  duplicateCount: number;
  safeDuplicate?: boolean;
  duplicateSourceOutcome?: string | null;
  duplicateMessage?: string | null;
  events: RecoveryEvent[];
}

export interface ScheduleJob {
  partner: string;
  fetchMethod: string;
  schedule: string;
  destination: string;
  enabled: boolean;
  status: string;
  statusMessage?: string;
  duplicateOutcome?: "FILE_DUPLICATE" | "FETCH_UNIT_REPLAY" | "NO_NEW_FILE" | "SAFE_DUPLICATE";
  safeDuplicate?: boolean;
  duplicateSourceOutcome?: string | null;
  duplicateMessage?: string | null;
  hasPendingFile?: boolean;
  pendingReviewPackets?: number;
  latestRuntimeRun?: RuntimeRunSummary | null;
  recentRuntimeRuns?: RuntimeRunSummary[];
  activeRuntimeRun?: RuntimeRunSummary | null;
  recovery?: RecoverySummary | null;
  activeBackfill?: BackfillRun | null;
  recentPackets?: RecentPacket[];
}

export interface RuntimeRunSummary {
  _id?: string;
  id?: string;
  partner?: string;
  date?: string;
  status?: string;
  message?: string;
  stats?: Record<string, unknown>;
  reconciliationCount?: number | null;
  startedAt?: string | null;
  finishedAt?: string | null;
  attemptHistory?: Array<{
    eventId: string;
    status: string;
    timestamp: string;
    attempt?: number;
    actor?: string | null;
    errorCode?: string | null;
    message?: string | null;
  }>;
  orchestration?: {
    dagId?: string;
    dagRunId?: string;
    taskId?: string;
    taskState?: string | null;
    mapIndex?: number | null;
    tryNumber?: number;
    correlationId?: string | null;
  } | null;
}

export interface RecentPacket {
  _id: string;
  partner: string;
  fileName: string;
  fetchMethod: string;
  status: string;
  createdAt?: string;
  decisionMode?: string | null;
  sourceType?: string;
  riskSummary?: { severity: string };
  recommendedAction?: { reason: string };
  reviewedAt?: string;
  reviewedBy?: string;
}

export type BackfillRunStatus = "WAITING_CONFIG" | "QUEUED" | "RUNNING" | "COMPLETED" | "FAILED";
export type BackfillDayStatus = "PENDING" | "RUNNING" | "COMPLETED" | "FAILED" | "WAITING_CONFIG";

export interface BackfillDay {
  businessDate: string;
  status: BackfillDayStatus;
  runtimeRunId?: string | null;
  message?: string | null;
  updatedAt?: string;
}

export interface BackfillRun {
  _id: string;
  partner: string;
  fetchConfigId: string;
  mode: "BACKFILL";
  status: BackfillRunStatus;
  fromDate: string;
  toDate: string;
  currentDate?: string | null;
  completedDays: number;
  totalDays: number;
  configVersion?: string | null;
  mappingVersion?: string | null;
  approvalRequired: boolean;
  approvalContext?: {
    reviewPacketId?: string | null;
    reason?: string | null;
  } | null;
  orchestration?: RuntimeRunSummary["orchestration"];
  days: BackfillDay[];
}
