import { get, post } from "./client";
import type { InsightItem } from "@/types/reconciliation";

export interface RunReconciliationPayload {
  partner: string;
  date: string;
  triggeredBy?: string;
}

export interface RunReconciliationResponse {
  ok: boolean;
  run: Record<string, unknown>;
}

export interface ReconciliationRunStatus {
  run: {
    status: string;
    message?: string;
    startedAt?: string;
    completedAt?: string;
    stats?: Record<string, unknown>;
    [key: string]: unknown;
  };
}

export interface ReconciliationStatsResponse {
  partner: string;
  date: string;
  total: number;
  byStatus: Record<string, number>;
  totalPartnerAmount: string | null;
  totalInternalAmount: string | null;
  timestampEvidence?: {
    byStatus: Record<string, number>;
    matched: number;
    mismatch: number;
    notAvailable: number;
    notEvaluated: number;
    mismatchRate: number;
  };
}

export interface ReconciliationResultsResponse {
  results: Record<string, unknown>[];
  total: number;
  limit: number;
  offset: number;
}

export interface ReviewRecordsResponse {
  records: Record<string, unknown>[];
}

export async function getRunStatus(partner: string, date: string) {
  return get<ReconciliationRunStatus>("/reconciliation/run-status", { partner, date });
}

export async function getStats(partner: string, date: string) {
  return get<ReconciliationStatsResponse>("/reconciliation/stats", { partner, date });
}

export async function getResults(
  partner: string,
  date: string,
  params: { status?: string; timestampStatus?: string; limit?: number; offset?: number } = {}
) {
  return get<ReconciliationResultsResponse>("/reconciliation/results", {
    partner,
    date,
    status: params.status,
    timestampStatus: params.timestampStatus,
    limit: params.limit ?? 25,
    offset: params.offset ?? 0,
  });
}

export async function runReconciliation(payload: RunReconciliationPayload) {
  return post<RunReconciliationResponse>("/reconciliation/run", payload);
}

export async function getReviewRecords(partner: string, date: string) {
  return get<ReviewRecordsResponse>("/reconciliation/review-records", { partner, date });
}

export async function addReviewNote(
  recordKey: string,
  payload: { partner: string; date: string; note: string; actor?: string }
) {
  return post<{ ok: boolean; record: Record<string, unknown> }>(
    `/reconciliation/review-records/${recordKey}/note`,
    payload
  );
}

export async function resolveReviewRecord(
  recordKey: string,
  payload: { partner: string; date: string; resolvedStatus: string; actor?: string; note?: string }
) {
  return post<{ ok: boolean; record: Record<string, unknown> }>(
    `/reconciliation/review-records/${recordKey}/resolve`,
    payload
  );
}

function normalizeInsight(item: Record<string, unknown>): InsightItem {
  const rawRec = item.recommendation;
  let parsedRec: InsightItem["recommendation"] = undefined;

  if (typeof rawRec === "string" && rawRec.trim()) {
    parsedRec = { action: rawRec };
  } else if (rawRec && typeof rawRec === "object") {
    const recObj = rawRec as Record<string, unknown>;
    parsedRec = {
      action: String(recObj.action || "Review the affected evidence."),
      why: recObj.why ? String(recObj.why) : undefined,
      owner: recObj.owner ? String(recObj.owner) : undefined,
      priority: recObj.priority ? String(recObj.priority) : undefined,
      expectedOutcome: recObj.expectedOutcome ? String(recObj.expectedOutcome) : undefined,
    };
  }

  return {
    id: String(item.id || item._id || crypto.randomUUID()),
    category: String(item.category || "ANOMALY"),
    severity: String(item.severity || "MEDIUM").toUpperCase(),
    title: String(item.title || "Insight"),
    shortSummary: String(item.shortSummary || item.summary || item.description || "Review the selected evidence for details."),
    affectedCount: Number(item.affectedCount ?? item.affected_count ?? (item.evidence as Record<string, unknown>)?.["affectedRecords"] ?? 0),
    partner: item.partner ? String(item.partner) : undefined,
    confidence: item.confidence != null ? Number(item.confidence) : undefined,
    metrics: Array.isArray(item.metrics)
      ? item.metrics
          .map((metric) => {
            const payload = metric as Record<string, unknown>;
            return {
              label: String(payload.label || ""),
              value: String(payload.value || ""),
            };
          })
          .filter((metric) => metric.value)
      : [],
    evidence: (item.evidence as Record<string, unknown>) || undefined,
    likelyCause: item.likelyCause ? String(item.likelyCause) : (item.likely_cause ? String(item.likely_cause) : undefined),
    recommendation: parsedRec,
    impact: item.impact ? (item.impact as Record<string, unknown>) as InsightItem["impact"] : undefined,
    samples: Array.isArray(item.samples) ? item.samples.map((sample) => sample as Record<string, unknown>) : [],
  };
}

export async function getInsights(partner: string, date: string, type: string) {
  const response = await get<Record<string, unknown>[]>("/reconciliation/insights", { partner, date, type });
  return Array.isArray(response) ? response.map(normalizeInsight) : [];
}
