"use client";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { PendingAction } from "@/types/mapping";

interface Props {
  actions: PendingAction[];
  onApprove: (id: string) => void;
  onReject: (id: string) => void;
}

export function PendingActionsList({ actions, onApprove, onReject }: Props) {
  if (actions.length === 0) return null;

  return (
    <div style={{ display: "grid", gap: 16 }}>
      {actions.map((a) => (
        <div
          key={a._id}
          style={{
            padding: 24,
            borderRadius: 18,
            background: "var(--bg-surface)",
            border: "1px solid var(--border)",
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", gap: 16, alignItems: "flex-start", marginBottom: 12 }}>
            <div>
              <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", marginBottom: 4 }}>
                <strong>{a.title}</strong>
                <Badge severity="medium">PENDING_APPROVAL</Badge>
              </div>
              <p style={{ margin: 0, fontSize: 13, color: "var(--text-muted)" }}>{a.reason}</p>
            </div>
            <div style={{ display: "flex", gap: 8, flexShrink: 0 }}>
              {a.draftMappingId && (
                <>
                  <Button variant="primary" onClick={() => onApprove(a.draftMappingId!)}>Approve Draft</Button>
                  <Button variant="secondary" onClick={() => onReject(a.draftMappingId!)}>Reject Draft</Button>
                </>
              )}
            </div>
          </div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <Badge severity="neutral">{a.partner}</Badge>
            {a.workflowType && <Badge severity="neutral">{a.workflowType}</Badge>}
            {a.fileType && <Badge severity="neutral">{a.fileType}</Badge>}
            {a.confidence != null && <Badge severity="neutral">{a.confidence}% confidence</Badge>}
            {a.mappingCount != null && <Badge severity="neutral">{a.mappingCount} field mappings</Badge>}
          </div>
        </div>
      ))}
    </div>
  );
}
