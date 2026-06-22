import { get } from "./client";

export interface AuditEventsResponse {
  events: Record<string, unknown>[];
  limit: number;
}

export async function listAuditEvents(params: {
  entityType?: string;
  entityId?: string;
  partner?: string;
  date?: string;
  action?: string;
  limit?: number;
} = {}) {
  return get<AuditEventsResponse>("/audit/events", params as Record<string, string | number | undefined>);
}
