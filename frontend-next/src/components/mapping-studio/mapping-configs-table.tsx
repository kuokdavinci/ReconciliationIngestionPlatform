"use client";

import { Badge } from "@/components/ui/badge";
import type { MappingConfig } from "@/types/mapping";

interface Props {
  configs: MappingConfig[];
}

export function MappingConfigsTable({ configs }: Props) {
  if (configs.length === 0) {
    return (
      <div style={{ padding: 24, textAlign: "center", color: "var(--text-muted)" }}>
        <p>No approved runtime configurations found for this partner.</p>
      </div>
    );
  }

  return (
    <table style={{ width: "100%", borderCollapse: "collapse" }}>
      <thead>
        <tr style={{ borderBottom: "1px solid var(--border)" }}>
          {["Version", "Sheet", "Start Row", "Mappings", "Status", "Approved At"].map((h) => (
            <th key={h} style={{ padding: "10px 12px", fontSize: 12, fontWeight: 700, color: "var(--text-muted)", textAlign: "left" }}>{h}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {configs.map((cfg) => (
          <tr key={cfg._id} style={{ borderBottom: "1px solid rgba(255,255,255,0.04)" }}>
            <td style={{ padding: "10px 12px" }}><strong>v{cfg.version}</strong></td>
            <td style={{ padding: "10px 12px" }}><code style={{ fontFamily: "var(--font-mono)", fontSize: 12 }}>{cfg.sheetName}</code></td>
            <td style={{ padding: "10px 12px" }}>Row {cfg.startRow}</td>
            <td style={{ padding: "10px 12px" }}>{cfg.fieldMappingCount} fields</td>
            <td style={{ padding: "10px 12px" }}>
              {cfg.status === "APPROVED" ? <Badge severity="low">Active</Badge> : <Badge severity="medium">{cfg.status}</Badge>}
            </td>
            <td style={{ padding: "10px 12px", fontSize: 12, color: "var(--text-muted)" }}>
              {cfg.approvedAt ? new Date(cfg.approvedAt).toLocaleString() : "-"}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
