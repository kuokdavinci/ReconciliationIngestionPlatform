/* eslint-disable @typescript-eslint/no-explicit-any */
import { get, post } from "./client";
import type {
  MappingConstraint,
  ReviewPacket,
  ReviewScopeRecommendation,
  RuntimeFieldTrace,
  RuntimeTraceSample,
  RuntimeValidationFieldResult,
  RuntimeValidationPreviewRow,
  RuntimeValidationResult,
  RuntimeValidationTopIssue,
} from "@/types/review-center";

export interface ReviewPacketsResponse {
  packets: ReviewPacket[];
}

export interface ReviewPacketDetailResponse {
  packet: ReviewPacket;
}

export interface ApiOkResponse {
  ok: boolean;
  [key: string]: unknown;
}

function toTitleCase(value: string) {
  return value
    .replace(/_/g, " ")
    .toLowerCase()
    .replace(/\b\w/g, (char) => char.toUpperCase());
}



function pickSeverity(status: string): RuntimeValidationFieldResult["status"] {
  const normalized = String(status || "").toLowerCase();
  if (normalized === "fail" || normalized === "failed") return "INVALID";
  if (normalized === "warn" || normalized === "warning") return "WARNING";
  if (normalized === "missing") return "MISSING";
  return "OK";
}

function inferFieldStatus(errorCode?: string | null, errorMessage?: string | null): RuntimeValidationFieldResult["status"] {
  const code = String(errorCode || "").toLowerCase();
  const message = String(errorMessage || "").toLowerCase();
  if (code.includes("missing") || message.includes("missing")) return "MISSING";
  if (code.includes("invalid") || message.includes("invalid")) return "INVALID";
  return "WARNING";
}

function normalizePreviewRows(samplePreview: unknown[], validationTraceRows: unknown[]): RuntimeValidationPreviewRow[] {
  if (Array.isArray(validationTraceRows) && validationTraceRows.length > 0) {
    return validationTraceRows.slice(0, 5).map((sample, index) => {
      const row = sample as Record<string, unknown>;
      const normalizedData = (row.normalizedData as Record<string, unknown>) || {};
      const fieldTraces = Array.isArray(row.fieldTraces) ? row.fieldTraces as Array<Record<string, unknown>> : [];
      return {
        id: String(row.row ?? row.rowIndex ?? `sample_${index + 1}`),
        values: Object.fromEntries(
          Object.entries(normalizedData).map(([key, value]) => [key, value == null ? null : String(value)])
        ),
        invalidFields: fieldTraces
          .filter((trace) => String(trace.status || "").toLowerCase() !== "ok")
          .map((trace) => String(trace.path || "")),
      };
    });
  }

  return Array.isArray(samplePreview)
    ? samplePreview.slice(0, 5).map((sample, index) => {
        const row = sample as Record<string, unknown>;
        const values = Array.isArray(row.values) ? row.values : [];
        return {
          id: String(row.rowIndex ?? index + 1),
          values: Object.fromEntries(values.slice(0, 5).map((value, valueIndex) => [`Column ${valueIndex + 1}`, value == null ? null : String(value)])),
        };
      })
    : [];
}

function normalizeRuntimeValidation(packet: Record<string, unknown>): RuntimeValidationResult | null {
  const runtimeGate = Array.isArray(packet.validationGates)
    ? (packet.validationGates as Array<Record<string, unknown>>).find((gate) => gate.gateKey === "runtime_validation")
    : null;
  const details = (runtimeGate?.details as Record<string, unknown>) || {};
  const traceSamples = Array.isArray(details.traceSamples) ? details.traceSamples as Array<Record<string, unknown>> : [];
  const failedExamples = Array.isArray(details.failedExamples) ? details.failedExamples as Array<Record<string, unknown>> : [];
  const sampleRows = Number(details.sampledRows ?? traceSamples.length ?? 0);
  const successRows = Number(details.successRows ?? Math.max(sampleRows - failedExamples.length, 0));
  const failedRows = Number(details.failedRows ?? failedExamples.length);

  const fieldResultsMap = new Map<string, RuntimeValidationFieldResult>();
  for (const sample of traceSamples) {
    const fieldTraces = Array.isArray(sample.fieldTraces) ? sample.fieldTraces as Array<Record<string, unknown>> : [];
    for (const trace of fieldTraces) {
      const canonicalField = String(trace.path || "unknown");
      if (!fieldResultsMap.has(canonicalField)) {
        const sourceColumn = trace.sourceField ? String(trace.sourceField) : null;
        const traceStatus = String(trace.status || "").toLowerCase();
        fieldResultsMap.set(canonicalField, {
          canonicalField,
          sourceColumn,
          status: traceStatus === "ok" ? "OK" : inferFieldStatus(String(trace.errorCode || ""), String(trace.errorMessage || "")),
          issue: traceStatus === "ok" ? null : String(trace.errorMessage || trace.errorCode || "Requires review"),
        });
      }
    }
  }

  const gateRows = Array.isArray(packet.validationGates) ? packet.validationGates as Array<Record<string, unknown>> : [];
  for (const gate of gateRows) {
    if (gate.gateKey === "runtime_validation" || gate.gateKey === "proposal_generated") continue;
    const canonicalField = toTitleCase(String(gate.gateKey || "Validation"));
    if (!fieldResultsMap.has(canonicalField)) {
      fieldResultsMap.set(canonicalField, {
        canonicalField,
        sourceColumn: null,
        status: pickSeverity(String(gate.status || "")),
        issue: gate.reason ? String(gate.reason) : String(gate.label || "Review required"),
      });
    }
  }

  const fieldResults = Array.from(fieldResultsMap.values());
  const errorRows = failedRows;
  const validRows = Math.max(successRows, 0);
  const totalFields = Math.max(fieldResults.length, Number(packet.parseStrategy && (packet.parseStrategy as Record<string, unknown>).fieldMappingCount) || fieldResults.length || 1);
  const requiredFieldStatuses = fieldResults.filter((item) => item.status !== "WARNING");
  const requiredFieldsPassed = requiredFieldStatuses.filter((item) => item.status === "OK").length;
  const topIssues: RuntimeValidationTopIssue[] = [];

  if (Array.isArray(failedExamples) && failedExamples.length > 0) {
    topIssues.push({
      type: "FAILED_SAMPLE_ROWS",
      message: "Some sampled rows failed runtime parsing.",
      affectedRows: failedExamples.length,
      severity: "ERROR",
    });
  }

  for (const result of fieldResults) {
    if (result.status === "OK") continue;
    topIssues.push({
      type: `${result.status}_${result.canonicalField}`.toUpperCase().replace(/\s+/g, "_"),
      message: result.issue ? `${result.canonicalField}: ${result.issue}` : `${result.canonicalField} requires review`,
      affectedRows: result.status === "WARNING" ? failedRows || null : null,
      severity: result.status === "WARNING" ? "WARNING" : "ERROR",
    });
  }

  const status = errorRows > 0
    ? (fieldResults.some((item) => item.status === "MISSING" || item.status === "INVALID") ? "FAILED" : "WARNING")
    : "PASSED";

  return {
    validationStatus: status,
    canSave: status !== "FAILED",
    summary: {
      rowsChecked: sampleRows,
      mappedFields: fieldResults.filter((item) => item.sourceColumn || item.status === "OK").length,
      totalFields,
      requiredFieldsPassed,
      requiredFieldsTotal: requiredFieldStatuses.length || totalFields,
      validRows,
      errorRows,
      validRowsPercent: sampleRows > 0 ? Math.round((validRows / sampleRows) * 1000) / 10 : 0,
    },
    fieldResults,
    previewRows: normalizePreviewRows(Array.isArray(packet.samplePreview) ? packet.samplePreview : [], traceSamples),
    traceSamples: traceSamples.map((sample: Record<string, unknown>) => ({
      row: Number(sample.row ?? 0),
      normalizedData: (sample.normalizedData as Record<string, string | number | null>) || {},
      fieldTraces: (Array.isArray(sample.fieldTraces) ? sample.fieldTraces : []).map((trace: Record<string, unknown>) => ({
        path: String(trace.path ?? ""),
        sourceField: trace.sourceField != null ? String(trace.sourceField) : null,
        sourceValue: trace.sourceValue ?? null,
        outputValue: trace.outputValue ?? null,
        status: (String(trace.status ?? "ok") as "ok" | "warning" | "error"),
        type: trace.type != null ? String(trace.type) : undefined,
        column: trace.column != null ? Number(trace.column) : undefined,
        errorCode: trace.errorCode != null ? String(trace.errorCode) : undefined,
        errorMessage: trace.errorMessage != null ? String(trace.errorMessage) : undefined,
      })),
      buildErrors: Array.isArray(sample.buildErrors) ? sample.buildErrors.map((err: Record<string, unknown>) => ({
        field: String(err.field ?? ""),
        errorCode: String(err.errorCode ?? "CANONICAL_BUILD_FAILED"),
        reason: String(err.reason ?? ""),
      })) : undefined,
    })) as RuntimeTraceSample[],
    topIssues: topIssues.slice(0, 3),
    likelyCause: topIssues.length > 0 ? "Runtime validation found rows or fields that still need operator review." : undefined,
  };
}

function normalizeScopeRecommendation(packet: Record<string, unknown>): ReviewScopeRecommendation {
  const recommendation = packet.scopeRecommendation as Record<string, unknown> | undefined;
  return {
    scopeType: String(recommendation?.scopeType || packet.scopeType || "FULL_SNAPSHOT"),
    confidence: Number(recommendation?.confidence ?? packet.scopeConfidence ?? 0.7),
    reason: Array.isArray(recommendation?.reason)
      ? recommendation.reason.map((item) => String(item))
      : Array.isArray(packet.scopeReason)
        ? packet.scopeReason.map((item) => String(item))
        : [],
  };
}

function normalizeMappingConstraints(packet: Record<string, unknown>): MappingConstraint[] {
  const parseStrategy = (packet.parseStrategy as Record<string, unknown>) || {};
  const sheetName = parseStrategy.sheetName ? String(parseStrategy.sheetName) : "";
  const constraints = [
    { label: "Partner", value: String(packet.partner || "-") },
    { label: "Currency", value: "VND" },
    { label: "Method", value: String(packet.sourceType || "Scheduler") },
  ];
  if (sheetName) {
    constraints.push({ label: "Sheet", value: sheetName });
  } else {
    constraints.push({ label: "Format", value: String(packet.fileTypeDetected || "-").toUpperCase() });
  }
  constraints.push({ label: "Start row", value: String(parseStrategy.startRow || "-") });
  return constraints;
}

function normalizePacket(packet: Record<string, unknown>): ReviewPacket {
  const validationGates = Array.isArray(packet.validationGates)
    ? packet.validationGates.map((gate) => {
        const data = gate as Record<string, unknown>;
        return {
          gateKey: String(data.gateKey || "unknown"),
          status: String(data.status || "pending"),
          label: String(data.label || data.gateKey || "Validation"),
          message: data.reason ? String(data.reason) : undefined,
          details: data.details as Record<string, unknown> | undefined,
        };
      })
    : [];

  const normalizedPacket: ReviewPacket = {
    _id: String(packet._id || packet.id || ""),
    partner: String(packet.partner || ""),
    fileName: String(packet.fileName || "Unknown file"),
    fileTypeDetected: String(packet.fileTypeDetected || "SETTLEMENT"),
    status: String(packet.status || "PENDING"),
    draftMappingId: packet.draftMappingId ? String(packet.draftMappingId) : undefined,
    recommendedAction: packet.recommendedAction
      ? {
          actionType: String((packet.recommendedAction as Record<string, unknown>).actionType || "APPROVE_REQUIRED_BEFORE_RUNTIME"),
          reason: String((packet.recommendedAction as Record<string, unknown>).reason || "Awaiting reviewer decision."),
        }
      : undefined,
    parseStrategy: packet.parseStrategy
      ? {
          sheetName: (packet.parseStrategy as Record<string, unknown>).sheetName
            ? String((packet.parseStrategy as Record<string, unknown>).sheetName)
            : "",
          startRow: Number((packet.parseStrategy as Record<string, unknown>).startRow || 1),
          fieldMappingCount: Number((packet.parseStrategy as Record<string, unknown>).fieldMappingCount || 0) || undefined,
        }
      : undefined,
    validationGates,
    structureSignature: packet.structureSignature as any,
    riskSummary: packet.riskSummary
      ? {
          severity: String((packet.riskSummary as Record<string, unknown>).severity || "medium"),
          summary: String((packet.riskSummary as Record<string, unknown>).summary || ""),
        }
      : undefined,
    createdAt: String(packet.createdAt || new Date().toISOString()),
    reviewedAt: packet.reviewedAt ? String(packet.reviewedAt) : undefined,
    reviewedBy: packet.reviewedBy ? String(packet.reviewedBy) : undefined,
    sourceType: packet.sourceType ? String(packet.sourceType) : undefined,
    activeRuntimeConfigId: packet.activeRuntimeConfigId ? String(packet.activeRuntimeConfigId) : null,
    reconciliationDate: packet.reconciliationDate ? String(packet.reconciliationDate) : undefined,
    scopeType: packet.scopeType ? String(packet.scopeType) : undefined,
    scopeConfidence: packet.scopeConfidence ? Number(packet.scopeConfidence) : undefined,
    scopeReason: Array.isArray(packet.scopeReason) ? packet.scopeReason.map((item) => String(item)) : undefined,
    runtimeDecisionHint: packet.runtimeDecisionHint ? String(packet.runtimeDecisionHint) : undefined,
    samplePreview: normalizePreviewRows(Array.isArray(packet.samplePreview) ? packet.samplePreview : [], []),
    mappingConstraints: normalizeMappingConstraints(packet),
    scopeRecommendation: normalizeScopeRecommendation(packet),
    runtimeValidation: normalizeRuntimeValidation(packet),
  };

  return normalizedPacket;
}

export async function listReviewPackets(partner?: string, status?: string) {
  const response = await get<{ packets: Record<string, unknown>[] }>("/review-packets", { partner, status });
  return {
    packets: Array.isArray(response.packets) ? response.packets.map(normalizePacket) : [],
  };
}

export async function getReviewPacket(packetId: string) {
  const response = await get<{ packet: Record<string, unknown> }>(`/review-packets/${packetId}`);
  return {
    packet: normalizePacket(response.packet ?? {}),
  };
}

export async function approveActivate(packetId: string, reviewedBy: string, scopeType?: string) {
  return post<ApiOkResponse>(`/review-packets/${packetId}/approve-activate`, { reviewedBy, scopeType });
}

export async function approveKeepCurrent(packetId: string, reviewedBy: string, scopeType?: string) {
  return post<ApiOkResponse>(`/review-packets/${packetId}/approve-keep-current`, { reviewedBy, scopeType });
}

export async function rejectPacket(packetId: string, reviewedBy: string) {
  return post<ApiOkResponse>(`/review-packets/${packetId}/reject`, { reviewedBy });
}

export async function sendToStudio(packetId: string, reviewedBy: string) {
  return post<ApiOkResponse>(`/review-packets/${packetId}/send-to-studio`, { reviewedBy });
}

export async function classifyScope(packetId: string) {
  return post<Record<string, unknown>>(`/review-packets/${packetId}/classify-scope-llm`);
}

export async function setScope(packetId: string, scopeType: string) {
  return post<ApiOkResponse>(`/review-packets/${packetId}/scope`, { scopeType });
}

export async function validateRuntime(packetId: string) {
  return post<ApiOkResponse>(`/review-packets/${packetId}/validate-runtime`);
}

export async function generateAiMapping(packetId: string) {
  return post<Record<string, unknown>>(`/review-packets/${packetId}/generate-ai-mapping`);
}

export async function getPostApproveRun(packetId: string) {
  return get<{ run: Record<string, unknown> | null }>(`/review-packets/${packetId}/post-approve-run`);
}

export async function saveDraftMapping(
  packetId: string,
  payload: {
    sheetName: string;
    startRow: number;
    fieldMappings: Array<{
      path: string;
      column: number | null;
      type: string;
      required: boolean;
      constant?: string | null;
      sourceField?: string;
      mapping?: Record<string, string> | null;
    }>;
  }
) {
  return post<ApiOkResponse>(`/review-packets/${packetId}/save-draft-mapping`, payload);
}

