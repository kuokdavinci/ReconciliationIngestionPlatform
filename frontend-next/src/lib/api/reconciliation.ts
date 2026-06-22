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
  params: { status?: string; limit?: number; offset?: number } = {}
) {
  return get<ReconciliationResultsResponse>("/reconciliation/results", {
    partner,
    date,
    status: params.status,
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

function normalizeInsight(item: Record<string, unknown>): InsightItem {
  const recommendation = (item.recommendation as Record<string, unknown>) || {};
  return {
    id: String(item.id || item._id || crypto.randomUUID()),
    category: String(item.category || "ANOMALY"),
    severity: String(item.severity || "MEDIUM").toUpperCase(),
    title: String(item.title || "Insight"),
    shortSummary: String(item.shortSummary || item.summary || "Review the selected evidence for details."),
    affectedCount: Number(item.affectedCount ?? item.affected_records ?? 0),
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
    likelyCause: item.likelyCause ? String(item.likelyCause) : undefined,
    recommendation: Object.keys(recommendation).length > 0
      ? {
          action: String(recommendation.action || "Review the affected evidence."),
          why: recommendation.why ? String(recommendation.why) : undefined,
          owner: recommendation.owner ? String(recommendation.owner) : undefined,
          priority: recommendation.priority ? String(recommendation.priority) : undefined,
          expectedOutcome: recommendation.expectedOutcome ? String(recommendation.expectedOutcome) : undefined,
        }
      : undefined,
    impact: item.impact ? (item.impact as Record<string, unknown>) as InsightItem["impact"] : undefined,
    samples: Array.isArray(item.samples) ? item.samples.map((sample) => sample as Record<string, unknown>) : [],
  };
}

export async function getInsights(partner: string, date: string, type: string) {
  const response = await get<Record<string, unknown>[]>("/reconciliation/insights", { partner, date, type });
  return Array.isArray(response) ? response.map(normalizeInsight) : [];
}
