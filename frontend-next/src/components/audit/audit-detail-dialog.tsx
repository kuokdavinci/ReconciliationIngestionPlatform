"use client";

import { Dialog } from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import type { AuditEvent } from "@/types/audit";
import polish from "@/components/ui/dashboard-polish.module.css";

interface Props {
  event: AuditEvent | null;
  open: boolean;
  onClose: () => void;
}

export function AuditDetailDialog({ event, open, onClose }: Props) {
  if (!event) return null;
  const meta = event.metadata ?? {};

  const detailRows: [string, string][] = [
    ["Entity type", event.entityType],
    ["Entity ID", String(meta.entityId ?? "-")],
    ["Action", event.action],
    ["Actor", event.actor],
    ["Partner", String(meta.partner ?? "-")],
    ["Date", String(meta.date ?? "-")],
    ["Reference", String(meta.reference ?? "-")],
    ["Status", String(meta.status ?? "-")],
    ["Mapping version", String(meta.mappingVersion ?? "-")],
    ["Draft mapping version", String(meta.draftMappingVersion ?? "-")],
    ["Draft mapping", String(meta.draftMappingId ?? "-")],
    ["Source file", String(meta.sourceFileId ?? "-")],
    ["Created at", event.createdAt],
  ];

  return (
    <Dialog open={open} onClose={onClose} title="Audit Detail">
      <div className={polish.toolbar} style={{ marginBottom: 16 }}>
        <Badge severity="neutral">{event.entityType}</Badge>
        <Badge severity="neutral">{event.action}</Badge>
      </div>

      <div className={polish.detailGrid}>
        {detailRows.map(([label, value]) => (
          <div key={label} className={polish.detailRow}>
            <strong className={polish.detailLabel}>{label}</strong>
            <span className={polish.detailValue}>{value}</span>
          </div>
        ))}
      </div>

      <div className={polish.codeBlock}>
        <p className={polish.codeLabel}>Raw Metadata</p>
        <pre className={polish.codeText}>{JSON.stringify(meta, null, 2)}</pre>
      </div>
    </Dialog>
  );
}
