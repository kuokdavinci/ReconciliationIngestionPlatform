import type { MappingConfig, PendingAction } from "@/types/mapping";

export const mockMappingConfigs: MappingConfig[] = [
  { _id: "cfg_1", partner: "MOMO", sheetName: "Sheet1", startRow: 2, fieldMappingCount: 8, status: "APPROVED", version: "1.2", createdAt: "2026-06-01T00:00:00Z", approvedAt: "2026-06-10T14:30:00Z" },
  { _id: "cfg_2", partner: "MOMO", sheetName: "Transactions", startRow: 1, fieldMappingCount: 10, status: "APPROVED", version: "1.1", createdAt: "2026-05-15T00:00:00Z", approvedAt: "2026-05-20T00:00:00Z" },
  { _id: "cfg_3", partner: "ZALOPAY", sheetName: "Sheet1", startRow: 3, fieldMappingCount: 6, status: "PENDING_APPROVAL", version: "1.0", createdAt: "2026-06-08T00:00:00Z" },
];

export const mockPendingActions: PendingAction[] = [
  { _id: "action_1", title: "Approve MOMO Config v1.2", reason: "Draft mapping validated against 12,450 sample rows. All fields mapped.", status: "PENDING_APPROVAL", draftMappingId: "dm_1", partner: "MOMO", workflowType: "SETTLEMENT", fileType: "XLSX", confidence: 94, mappingCount: 8 },
];
