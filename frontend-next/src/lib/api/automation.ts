import { get, post } from "./client";
import {
  RECOVERY_STATUSES,
  RECOVERY_UNIT_STATUSES,
  type RecoveryStatus,
  type RecoveryEvent,
  type RecoveryUnitStatus,
  type RecoverySummary,
  type RecoveryUnitSummary,
  type RuntimeRunSummary,
  type ScheduleJob,
} from "@/types/schedules";

export interface AutomationJobsResponse {
  jobs: ScheduleJob[];
}

export interface RunJobResponse {
  ok: boolean;
  queued: boolean;
  actor: string;
  partner: string;
  message: string;
  runtimeRunId: string;
  run?: RuntimeRunSummary | null;
}

export interface RecoveryRetryResponse extends RunJobResponse {
  resumedFromUnitKey: string | null;
}

export interface RecoveryResolveResponse {
  ok: boolean;
  actor: string;
  partner: string;
  action: "RETRY" | "SKIP";
  unitKey: string;
  status: string;
  message: string;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function asString(value: unknown): string | null {
  return typeof value === "string" ? value : value == null ? null : String(value);
}

function asNumber(value: unknown, fallback = 0): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function asRecoveryStatus(value: unknown): RecoveryStatus {
  return typeof value === "string" && RECOVERY_STATUSES.includes(value as RecoveryStatus)
    ? (value as RecoveryStatus)
    : "IDLE";
}

function asRecoveryUnitStatus(value: unknown): RecoveryUnitStatus {
  return typeof value === "string" && RECOVERY_UNIT_STATUSES.includes(value as RecoveryUnitStatus)
    ? (value as RecoveryUnitStatus)
    : "PENDING";
}

function normalizeUnit(value: unknown): RecoveryUnitSummary | null {
  if (!isRecord(value)) return null;
  const unitKey = asString(value.unitKey);
  if (!unitKey) return null;
  return {
    unitKey,
    label: asString(value.label),
    page: typeof value.page === "number" ? value.page : null,
    status: asRecoveryUnitStatus(value.status),
    cursorBefore: asString(value.cursorBefore),
    cursorAfter: asString(value.cursorAfter),
    attemptCount: asNumber(value.attemptCount),
    lastError: asString(value.lastError),
    errorCode: asString(value.errorCode),
    retryable: typeof value.retryable === "boolean" ? value.retryable : null,
    nextRetryAt: asString(value.nextRetryAt),
    startedAt: asString(value.startedAt),
    completedAt: asString(value.completedAt),
    updatedAt: asString(value.updatedAt),
  };
}

function normalizeEvent(value: unknown): RecoveryEvent | null {
  if (!isRecord(value)) return null;
  const eventId = asString(value.eventId);
  const timestamp = asString(value.timestamp);
  const status = asString(value.status);
  if (!eventId || !timestamp || !status) return null;
  return {
    eventId,
    unitKey: asString(value.unitKey),
    status,
    action: asString(value.action),
    timestamp,
    actor: asString(value.actor),
    reason: asString(value.reason),
    errorCode: asString(value.errorCode),
    message: asString(value.message),
    requestAttempt: typeof value.requestAttempt === "number" ? value.requestAttempt : undefined,
  };
}

function normalizeRecovery(value: unknown): RecoverySummary | null {
  if (!isRecord(value)) return null;
  const units = Array.isArray(value.units)
    ? value.units.map(normalizeUnit).filter((unit): unit is RecoveryUnitSummary => unit !== null)
    : [];
  const events = Array.isArray(value.events)
    ? value.events.map(normalizeEvent).filter((event): event is RecoveryEvent => event !== null)
    : [];
  return {
    status: asRecoveryStatus(value.status),
    streamKey: asString(value.streamKey),
    mode: asString(value.mode),
    lastCompletedUnitKey: asString(value.lastCompletedUnitKey),
    currentUnitKey: asString(value.currentUnitKey),
    currentPage: typeof value.currentPage === "number" ? value.currentPage : null,
    cursorBefore: asString(value.cursorBefore),
    attemptCount: asNumber(value.attemptCount),
    maxAttempts: asNumber(value.maxAttempts),
    requestAttemptCount: asNumber(value.requestAttemptCount, asNumber(value.attemptCount)),
    retryable: typeof value.retryable === "boolean" ? value.retryable : null,
    nextRetryAt: asString(value.nextRetryAt),
    errorCode: asString(value.errorCode),
    lastError: asString(value.lastError),
    units,
    fetchedUnitCount: asNumber(value.fetchedUnitCount),
    completedUnitCount: asNumber(value.completedUnitCount),
    totalUnitCount: asNumber(value.totalUnitCount, units.length),
    duplicateCount: asNumber(value.duplicateCount),
    events,
  };
}

function normalizeJob(job: ScheduleJob): ScheduleJob {
  return { ...job, recovery: normalizeRecovery(job.recovery) };
}

export async function listJobs() {
  const response = await get<AutomationJobsResponse>("/automation/jobs");
  return { ...response, jobs: (response.jobs ?? []).map(normalizeJob) };
}

export async function getJob(partner: string) {
  const response = await listJobs();
  return response.jobs.find((job) => job.partner === partner) ?? null;
}

export async function runJob(partner: string) {
  return post<RunJobResponse>(`/automation/jobs/${partner}/run`);
}

export async function retryRecovery(partner: string) {
  return post<RecoveryRetryResponse>(`/automation/jobs/${partner}/recovery/retry`);
}

export async function resolveRecovery(
  partner: string,
  action: "RETRY" | "SKIP",
  reason: string,
) {
  return post<RecoveryResolveResponse>(`/automation/jobs/${partner}/recovery/resolve`, { action, reason });
}
