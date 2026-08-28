import type {
  QuarantineDuplicateEvidence,
  QuarantineIssueType,
  QuarantineRecord,
  QuarantineSampleField,
  QuarantineStatus,
} from "@/types/quarantine";

export const ISSUE_TYPES: QuarantineIssueType[] = ["SCHEMA", "REQUIRED_FIELD", "FORMAT", "DUPLICATE", "RECOVERY", "OTHER"];

export const ISSUE_TYPE_LABELS: Record<QuarantineIssueType, string> = {
  SCHEMA: "Schema",
  REQUIRED_FIELD: "Required field",
  FORMAT: "Format",
  DUPLICATE: "Duplicate",
  RECOVERY: "Recovery",
  OTHER: "Other",
};

const ISSUE_TYPE_CODES: Record<QuarantineIssueType, string[]> = {
  SCHEMA: ["REQUIRED_SCHEMA_PATH", "MISSING_REQUIRED_SOURCE_COLUMN", "SCHEMA_CONFIG_DRIFT", "SOURCE_STRUCTURE_UNREADABLE", "CONFIG_VALIDATION"],
  REQUIRED_FIELD: ["MISSING_REQUIRED_FIELD"],
  FORMAT: ["MALFORMED_ROW", "INVALID_AMOUNT", "NEGATIVE_AMOUNT", "INVALID_TIMESTAMP", "INVALID_STATUS"],
  DUPLICATE: ["EQUIVALENT_DUPLICATE", "CONFLICTING_DUPLICATE"],
  RECOVERY: ["SOURCE_UNIT_RECOVERY_REQUIRED"],
  OTHER: [],
};

export function issueTypeFor(record: Pick<QuarantineRecord, "issueType" | "errorCodes">): QuarantineIssueType {
  if (record.issueType) return record.issueType;
  const code = record.errorCodes[0]?.toUpperCase();
  return ISSUE_TYPES.find((type) => ISSUE_TYPE_CODES[type].includes(code)) ?? "OTHER";
}

export function issueTypeSeverity(type: QuarantineIssueType): "critical" | "high" | "medium" {
  if (type === "DUPLICATE") return "critical";
  if (type === "FORMAT" || type === "RECOVERY") return "high";
  return "medium";
}

export function badgeSeverity(status: QuarantineStatus): "critical" | "high" | "medium" {
  if (status === "REJECTED") return "critical";
  if (status === "REPROCESSING") return "high";
  return "medium";
}

export function outcomeLabel(status: QuarantineStatus): string {
  if (status === "REPROCESSING") return "In review";
  if (status === "PENDING") return "Pending review";
  return status.charAt(0) + status.slice(1).toLowerCase();
}

export function duplicateStatusLabel(status: QuarantineDuplicateEvidence["status"]): string {
  if (status === "EQUIVALENT") return "Exact duplicate";
  if (status === "CONFLICT") return "Conflict";
  return "Unavailable";
}

export function timestampEntry(entries: QuarantineSampleField[]): QuarantineSampleField | undefined {
  return entries.find((entry) => /(transdate|timestamp|transactiontime)$/i.test(entry.canonicalPath ?? entry.sourceField));
}

export function formatDate(value?: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString();
}

export function isOverdue(record: QuarantineRecord): boolean {
  return (
    (record.status === "PENDING" || record.status === "REPROCESSING") &&
    Boolean(record.reviewDueAt) &&
    new Date(record.reviewDueAt ?? 0).getTime() <= Date.now()
  );
}

export function canResolve(record: QuarantineRecord, actor: string): boolean {
  return record.status === "REPROCESSING" && Boolean(actor.trim()) && record.claimedBy === actor.trim();
}

export function summaryValue(value: number | undefined): number {
  return typeof value === "number" ? value : 0;
}

export function humanizeFieldName(value: string): string {
  return value
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

export function displaySampleValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "object") {
    try {
      return JSON.stringify(value);
    } catch {
      return "[UNAVAILABLE]";
    }
  }
  return String(value);
}

export function sampleEntries(record: QuarantineRecord): QuarantineSampleField[] {
  return record.evidence?.sampleFields ?? [];
}

export function reviewInstruction(record: QuarantineRecord): string {
  const code = record.errorCodes[0];
  if (code === "CONFLICTING_DUPLICATE") {
    return "Compare this sample with the existing transaction before choosing a resolution.";
  }
  if (code === "EQUIVALENT_DUPLICATE") {
    return "Confirm the sample matches the persisted transaction, then accept the existing record.";
  }
  if (code === "SOURCE_UNIT_RECOVERY_REQUIRED") {
    return "Confirm the source unit is available and resume it from the durable checkpoint.";
  }
  if (code === "INVALID_TIMESTAMP") {
    return "Check the source date value and mapping before replaying this row.";
  }
  if (record.status === "PENDING") {
    return "Claim this row, inspect the sample, then choose the appropriate resolution.";
  }
  if (record.status === "REPROCESSING") {
    return "Verify the sample and choose source replay, accept existing, or reject.";
  }
  return "This row is terminal. Review the recorded outcome and bounded history.";
}

export function resolutionPrompt(record: QuarantineRecord, resolving: boolean): string {
  if (resolving) return "Choose the bounded resolution after reviewing the issue and source row.";
  if (record.status === "PENDING") return "Claim the row to make a resolution, or escalate it for another review.";
  if (record.status === "REPROCESSING") return `Owned by ${record.claimedBy ?? "another operator"}; switch actor to continue.`;
  return "No further resolution is available for this terminal row.";
}

export function actorMetaLabel(record: QuarantineRecord): string {
  if (record.claimedBy) return `Owner: ${record.claimedBy}`;
  if (record.lastActionActor) return `Action by: ${record.lastActionActor}`;
  return "Owner: Unclaimed";
}

export function actionTimestampLabel(record: QuarantineRecord): string {
  return `${record.lastActionActor ? "Action at" : "Updated at"}: ${formatDate(record.lastActionAt ?? record.updatedAt)}`;
}
