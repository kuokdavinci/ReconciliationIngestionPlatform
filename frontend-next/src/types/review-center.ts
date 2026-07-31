/* eslint-disable @typescript-eslint/no-explicit-any */
export interface ValidationGate {
  gateKey: string;
  status: string;
  label: string;
  message?: string;
  details?: Record<string, unknown>;
}

export interface ReviewScopeRecommendation {
  scopeType: string;
  confidence: number;
  reason: string[];
}

export interface MappingConstraint {
  label: string;
  value: string;
}

export interface RuntimeValidationFieldResult {
  canonicalField: string;
  sourceColumn: string | null;
  status: "OK" | "WARNING" | "MISSING" | "INVALID";
  issue: string | null;
}

export interface RuntimeValidationPreviewRow {
  id: string;
  values: Record<string, string | number | null>;
  invalidFields?: string[];
}

export interface RuntimeValidationTopIssue {
  type: string;
  message: string;
  affectedRows: number | null;
  severity: "ERROR" | "WARNING" | "INFO";
}

export interface RuntimeFieldTrace {
  path: string;
  sourceField: string | null;
  sourceValue?: string | number | null;
  outputValue?: string | number | null;
  status: "ok" | "warning" | "error";
  type?: string;
  column?: number;
  errorCode?: string;
  errorMessage?: string;
}

export interface RuntimeTraceSample {
  row: number;
  normalizedData: Record<string, string | number | null>;
  fieldTraces: RuntimeFieldTrace[];
  buildErrors?: Array<{ field: string; errorCode: string; reason: string }>;
}

export interface RuntimeValidationResult {
  validationStatus: "PASSED" | "WARNING" | "FAILED";
  canSave: boolean;
  summary: {
    rowsChecked: number;
    mappedFields: number;
    totalFields: number;
    requiredFieldsPassed: number;
    requiredFieldsTotal: number;
    validRows: number;
    errorRows: number;
    validRowsPercent: number;
  };
  fieldResults: RuntimeValidationFieldResult[];
  previewRows: RuntimeValidationPreviewRow[];
  topIssues: RuntimeValidationTopIssue[];
  traceSamples?: RuntimeTraceSample[];
  likelyCause?: string;
}

export interface ReviewPacket {
  _id: string;
  partner: string;
  fileName: string;
  fileTypeDetected: string;
  status: string;
  draftMappingId?: string;
  recommendedAction?: {
    actionType: string;
    reason: string;
  };
  parseStrategy?: {
    sheetName: string;
    startRow: number;
    fieldMappingCount?: number;
  };
  validationGates: ValidationGate[];
  structureSignature?: {
    headers: string[];
    headerRowIndex?: number;
    firstDataRowIndex?: number;
    columnCount?: number;
  };
  riskSummary?: {
    severity: string;
    summary?: string;
  };
  createdAt: string;
  reviewedAt?: string;
  reviewedBy?: string;
  isVirtual?: boolean;
  sourceType?: string;
  activeRuntimeConfigId?: string | null;
  reconciliationDate?: string;
  scopeType?: string;
  scopeConfidence?: number;
  scopeReason?: string[];
  runtimeDecisionHint?: string;
  mappingConstraints?: MappingConstraint[];
  scopeRecommendation?: ReviewScopeRecommendation;
  runtimeValidation?: RuntimeValidationResult | null;
  samplePreview?: RuntimeValidationPreviewRow[];
}

export interface PostApprovalRun {
  id: string;
  packetId: string;
  partner: string;
  date?: string;
  status: "QUEUED" | "INGESTING" | "RECONCILING" | "COMPLETED" | "FAILED";
  stage: "approval" | "ingestion" | "reconciliation" | "cache_invalidation";
  message?: string;
  sourceFileId?: string;
  outputFileId?: string;
  reconciliationCount?: number | null;
  stats: {
    totalRows?: number;
    successRows?: number;
    duplicateRows?: number;
    failedRows?: number;
    resultCount?: number;
    reconciliationCount?: number;
  };
  errors?: any[];
  startedAt?: string;
  finishedAt?: string;
  createdAt: string;
  updatedAt: string;
}

export interface ReviewSummary {
  gateSummary: Record<string, number>;
  hasFailedGates: boolean;
  runtimeValidated: boolean;
  mappingReady: boolean;
  readyToActivate: boolean;
}

export interface ReviewCenterState {
  packets: ReviewPacket[];
  selectedPacketId: string | null;
  guidedReviewOpen: boolean;
  guidedReviewStep: number;
  loading: boolean;
}
