export interface AuditEvent {
  _id: string;
  entityType: string;
  action: string;
  actor: string;
  createdAt: string;
  metadata: Record<string, unknown>;
}

export interface AuditFilters {
  entityType: string;
  action: string;
}
