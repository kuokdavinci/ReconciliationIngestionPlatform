import type { AuditEvent } from "@/types/audit";

export const mockAuditEvents: AuditEvent[] = [
  {
    _id: "audit_1",
    entityType: "REVIEW_PACKET",
    action: "APPROVED",
    actor: "Administrator",
    createdAt: "2026-06-10T14:30:00Z",
    metadata: { partner: "MOMO", date: "2026-06-10", reference: "packet_1", mappingVersion: "1.2" },
  },
  {
    _id: "audit_2",
    entityType: "MAPPING_CONFIG",
    action: "APPROVE_ACTIVATE_NEXT_RUNTIME",
    actor: "Administrator",
    createdAt: "2026-06-10T14:25:00Z",
    metadata: { partner: "MOMO", date: "2026-06-10", reference: "mapping_1", draftMappingVersion: "1.3", draftMappingId: "dm_1" },
  },
  {
    _id: "audit_3",
    entityType: "RECONCILIATION_RUN",
    action: "COMPLETED",
    actor: "system",
    createdAt: "2026-06-10T10:42:00Z",
    metadata: { partner: "MOMO", date: "2026-06-10", status: "COMPLETED", reference: "run_42" },
  },
  {
    _id: "audit_4",
    entityType: "REVIEW_PACKET",
    action: "REJECTED",
    actor: "Operator",
    createdAt: "2026-06-09T16:00:00Z",
    metadata: { partner: "ZALOPAY", date: "2026-06-09", reference: "packet_2" },
  },
  {
    _id: "audit_5",
    entityType: "MAPPING_CONFIG",
    action: "APPROVED",
    actor: "Administrator",
    createdAt: "2026-06-09T15:00:00Z",
    metadata: { partner: "MOMO", date: "2026-06-09", reference: "mapping_0", mappingVersion: "1.1", draftMappingVersion: "1.2" },
  },
  {
    _id: "audit_6",
    entityType: "RECONCILIATION_RUN",
    action: "FAILED",
    actor: "system",
    createdAt: "2026-06-09T09:00:00Z",
    metadata: { partner: "ZALOPAY", date: "2026-06-09", status: "FAILED", reference: "run_41" },
  },
];
