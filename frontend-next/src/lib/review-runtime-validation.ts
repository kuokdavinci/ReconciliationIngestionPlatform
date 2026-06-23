import type { ValidationGate } from "@/types/review-center";

const VALIDATION_SUGGESTIONS: Record<string, string> = {
  SOURCE_FIELD_NOT_FOUND: "Source field does not exist in sample data. Re-map this target to an existing partner field.",
  MISSING_REQUIRED_FIELD: "Required field '{field}' is missing. Map a partner field to this canonical field.",
  INVALID_DECIMAL: "Map the partner numeric amount field to 'amount' and ensure the sample value is numeric.",
  INVALID_DATE: "Check the source date field and ensure it matches a supported runtime date format.",
  UNMAPPED_VALUE: "Add a mapping rule for this partner value or configure a fallback rule.",
  INVALID_CANONICAL_STATUS: "Map the partner status into one of SUCCESS, FAILED, PENDING, REVERSED.",
};

export function getValidationSuggestion(code: string, field?: string): string {
  const template = VALIDATION_SUGGESTIONS[code] || "Review this mapping rule and align the partner source field, transform, and canonical target before validating again.";
  return template.replace("{field}", field || "field");
}

export function collectValidationIssues(runtimeGate: ValidationGate): Array<{
  code: string;
  field: string;
  row: number;
  message: string;
  suggestion: string;
}> {
  const issues: Array<{ code: string; field: string; row: number; message: string; suggestion: string }> = [];
  const seen = new Set<string>();
  const details = (runtimeGate?.details || {}) as Record<string, unknown>;
  const traceSamples = Array.isArray(details.traceSamples) ? details.traceSamples as Array<Record<string, unknown>> : [];

  traceSamples.forEach(sample => {
    const fieldTraces = Array.isArray(sample.fieldTraces) ? sample.fieldTraces as Array<Record<string, unknown>> : [];
    fieldTraces.forEach(trace => {
      if (!trace.errorCode) return;
      const key = `${String(trace.errorCode)}:${String(trace.path || "")}:${String(trace.errorMessage || "")}`;
      if (seen.has(key)) return;
      seen.add(key);
      issues.push({
        code: String(trace.errorCode),
        field: String(trace.path || trace.sourceField || ""),
        row: Number(sample.row ?? 0),
        message: String(trace.errorMessage || trace.errorCode),
        suggestion: getValidationSuggestion(String(trace.errorCode), String(trace.path)),
      });
    });

    const buildErrors = Array.isArray(sample.buildErrors) ? sample.buildErrors as Array<Record<string, unknown>> : [];
    buildErrors.forEach(err => {
      const key = `${String(err.errorCode || "CANONICAL_BUILD_FAILED")}:${String(err.field || "")}:${String(err.reason || "")}`;
      if (seen.has(key)) return;
      seen.add(key);
      issues.push({
        code: String(err.errorCode || "CANONICAL_BUILD_FAILED"),
        field: String(err.field || ""),
        row: Number(err.row ?? sample.row ?? 0),
        message: String(err.reason || err.errorCode || "Build failed"),
        suggestion: getValidationSuggestion(String(err.errorCode || "CANONICAL_BUILD_FAILED"), String(err.field)),
      });
    });
  });

  return issues;
}

export function collectRuntimeFieldStats(runtimeGate: ValidationGate): Array<{
  field: string;
  ok: number;
  warning: number;
  error: number;
}> {
  const stats: Record<string, { field: string; ok: number; warning: number; error: number }> = {};
  const details = (runtimeGate?.details || {}) as Record<string, unknown>;
  const traceSamples = Array.isArray(details.traceSamples) ? details.traceSamples as Array<Record<string, unknown>> : [];

  traceSamples.forEach(sample => {
    const fieldTraces = Array.isArray(sample.fieldTraces) ? sample.fieldTraces as Array<Record<string, unknown>> : [];
    fieldTraces.forEach(trace => {
      const key = String(trace.path || trace.sourceField || "unknown");
      if (!stats[key]) {
        stats[key] = { field: key, ok: 0, warning: 0, error: 0 };
      }
      const status = String(trace.status || "ok");
      if (status === "warning") stats[key].warning += 1;
      else if (status === "error") stats[key].error += 1;
      else stats[key].ok += 1;
    });
  });

  return Object.values(stats).sort((a, b) => (b.error - a.error) || (b.warning - a.warning) || a.field.localeCompare(b.field));
}

export function collectCandidateColumns(
  headers: string[],
  sampleRows: Array<Array<string | number | null | undefined>>
): Array<{
  index: number;
  header: string;
  nonEmptyCount: number;
  sampleValues: Array<string | number | null | undefined>;
  priority: number;
}> {
  const maxCols = Math.max(headers.length, ...sampleRows.map(row => row.length), 0);
  const candidates: Array<{ index: number; header: string; nonEmptyCount: number; sampleValues: Array<string | number | null | undefined>; priority: number }> = [];

  for (let index = 0; index < maxCols; index += 1) {
    const header = headers[index];
    const headerText = header === null || header === undefined ? "" : String(header).trim();
    const values = sampleRows
      .map(row => row[index])
      .filter(value => value !== null && value !== undefined && String(value).trim() !== "");

    if (!headerText && values.length === 0) continue;
    const meaningfulHeader = /[A-Za-zÀ-ỹ0-9]/.test(headerText);
    candidates.push({
      index,
      header: headerText || `Column ${index + 1}`,
      nonEmptyCount: values.length,
      sampleValues: values.slice(0, 2),
      priority: (meaningfulHeader ? 2 : 0) + Math.min(values.length, 3),
    });
  }

  return candidates.sort((a, b) => (b.priority - a.priority) || (b.nonEmptyCount - a.nonEmptyCount) || (a.index - b.index));
}
