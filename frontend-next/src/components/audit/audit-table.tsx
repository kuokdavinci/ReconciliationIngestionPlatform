"use client";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { AuditEvent } from "@/types/audit";

interface Props {
  events: AuditEvent[];
  onSelect: (id: string) => void;
}

const entityColors: Record<string, "low" | "medium" | "high" | "critical"> = {
  REVIEW_PACKET: "medium",
  DISCREPANCY_REVIEW: "medium",
  MAPPING_CONFIG: "high",
  RECONCILIATION_RUN: "low",
  INGESTION_QUARANTINE: "high",
  INGESTION_QUARANTINE_SOURCE_UNIT: "high",
};

const actionColors: Record<string, "low" | "medium" | "high" | "critical"> = {
  APPROVED: "low",
  COMMENTED: "low",
  RESOLVED: "low",
  APPROVE_ACTIVATE_NEXT_RUNTIME: "low",
  REJECTED: "high",
  REJECT: "high",
  COMPLETED: "low",
  FAILED: "critical",
  QUARANTINE_CLAIMED: "medium",
  QUARANTINE_REPROCESSED: "low",
  QUARANTINE_ACCEPTED_EXISTING: "low",
  QUARANTINE_REJECTED: "critical",
  QUARANTINE_RETRY_SCHEDULED: "medium",
  QUARANTINE_ESCALATED: "medium",
  QUARANTINE_SOURCE_UNIT_RESUMED: "low",
};

export function AuditTable({ events, onSelect }: Props) {
  if (events.length === 0) {
    return (
      <div style={{ padding: 32, textAlign: "center", color: "var(--text-muted)" }}>
        <h3 style={{ margin: "0 0 8px" }}>No audit events</h3>
        <p style={{ margin: 0, fontSize: 13 }}>
          No audit entries match the current partner/date/filter combination.
        </p>
      </div>
    );
  }

  return (
    <table style={{ width: "100%", borderCollapse: "collapse" }}>
      <thead>
        <tr style={{ borderBottom: "1px solid var(--border)" }}>
          {["Timestamp", "Entity", "Action", "Reference", "Detail"].map((h) => (
            <th key={h} style={{ padding: "10px 12px", fontSize: 12, fontWeight: 700, color: "var(--text-muted)", textAlign: "left" }}>{h}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {events.map((event) => (
          <tr key={event._id} style={{ borderBottom: "1px solid rgba(255,255,255,0.04)" }}>
            <td style={{ padding: "10px 12px" }}>
              <code style={{ fontFamily: "var(--font-mono)", fontSize: 11 }}>{new Date(event.createdAt).toLocaleString()}</code>
            </td>
            <td style={{ padding: "10px 12px" }}>
              <Badge severity={entityColors[event.entityType] ?? "neutral"}>{event.entityType}</Badge>
            </td>
            <td style={{ padding: "10px 12px" }}>
              <Badge severity={actionColors[event.action] ?? "neutral"}>{event.action}</Badge>
            </td>
            <td style={{ padding: "10px 12px" }}>
              <code style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--text-muted)" }}>
                {String(event.metadata?.reference ?? event.metadata?.recordKey ?? event.entityId ?? "-")}
              </code>
            </td>
            <td style={{ padding: "10px 12px" }}>
              <Button variant="secondary" onClick={() => onSelect(event._id)}>
                Open detail
              </Button>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
