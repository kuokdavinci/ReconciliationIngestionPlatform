export interface MappingConfig {
  _id: string;
  partner: string;
  sheetName: string;
  startRow: number;
  fieldMappingCount: number;
  status: string;
  version: string;
  createdAt: string;
  approvedAt?: string;
  configHealth?: { confidence?: number; reasoning?: string };
}

export interface PendingAction {
  _id: string;
  title: string;
  reason: string;
  status: string;
  draftMappingId?: string;
  partner: string;
  workflowType?: string;
  fileType?: string;
  confidence?: number;
  mappingCount?: number;
}

// A single field mapping entry in a draft config
export interface FieldMapping {
  path: string;
  column?: number | null;
  constant?: string | null;
  type: "STRING" | "DECIMAL" | "DATE" | "CONSTANT";
  required?: boolean;
  mapping?: Record<string, unknown> | null;
}

// A full draft mapping config returned by ai-generate or version restore
export interface DraftMappingConfig {
  partner?: string;
  workflowType?: string;
  fileType?: string;
  sheetName?: string;
  startRow?: number;
  configVersion?: string;
  fieldMappings?: FieldMapping[];
  configHealth?: { confidence?: number; reasoning?: string; stale?: boolean; status?: string };
  _id?: string;
  approvedAt?: string;
  supersededByConfigId?: string;
}

// Response from aiGenerateMapping
export interface AiGenerateResponse {
  headers?: string[];
  sampleRows?: unknown[][];
  config?: DraftMappingConfig;
  draftMappingId?: string | null;
  reviewItemId?: string | null;
  configStatus?: string | null;
  isRuntimeEligible?: boolean;
}

// Response from validateMapping
export interface ValidationResult {
  score?: number;
  errors?: string[];
  warnings?: string[];
}

// Response from testMapping
export interface TestMappingResponse {
  output?: Record<string, unknown>;
}

// Response from handoffReview
export interface HandoffResponse {
  success?: boolean;
  reviewPacketId?: string;
}

// Full wizard state (used internally by the wizard component)
export interface StudioWizardState {
  step: 1 | 2 | 3;
  loading: boolean;
  partner: string;
  fileName?: string;
  headers: string[];
  sampleRows: unknown[][];
  config: DraftMappingConfig | null;
  draftMappingId: string | null;
  reviewItemId: string | null;
  configStatus: string | null;
  isRuntimeEligible: boolean;
  validation: ValidationResult | null;
  testOutput: Record<string, unknown> | null;
  versions: Record<string, unknown>[];
  handoffConfirmed: boolean;
}
