"use client";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import type { StudioWizardState, FieldMapping } from "@/types/mapping";
import styles from "./mapping-studio.module.css";

interface Props {
  wizard: StudioWizardState;
  studioTab: "visual" | "json";
  onTabChange: (tab: "visual" | "json") => void;
  onColumnChange: (idx: number, value: string) => void;
  onConstantChange: (idx: number, value: string) => void;
  onTypeChange: (idx: number, value: string) => void;
  onAddMappingRow: () => void;
  onCopyJson: () => void;
  onValidateAndProceed: () => void;
  onBack: () => void;
  onConfigJsonChange: (json: string) => void;
}

function getConfidenceBadge(confidencePct: number) {
  if (confidencePct >= 90) return { severity: "low" as const, label: "High" };
  if (confidencePct >= 80) return { severity: "neutral" as const, label: "Medium" };
  return { severity: "critical" as const, label: "Needs Review" };
}

function renderFilePreview(wizard: StudioWizardState) {
  const displayHeaders = wizard.headers.length > 0
    ? wizard.headers
    : (wizard.config?.fieldMappings || []).filter(fm => fm.column != null).map(fm => `Col ${fm.column}: ${fm.path}`);
  if (!displayHeaders.length) return null;
  return (
    <div style={{ marginBottom: 24 }}>
      <h3 style={{ fontSize: 13, fontWeight: 700, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 12 }}>
        Detected File Structure Preview
      </h3>
      <div className={styles.filePreview}>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ background: "var(--bg-surface-hover)" }}>
              <th style={{ width: 40, padding: 10, textAlign: "left" }}>Row</th>
              {displayHeaders.map((h, i) => (
                <th key={i} style={{ textAlign: "left", padding: 10 }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {wizard.sampleRows.slice(0, 10).map((row: unknown[], rIdx: number) => (
              <tr key={rIdx}>
                <td style={{ padding: 10, borderTop: "1px solid var(--border)", fontWeight: 700, color: "var(--text-muted)", fontSize: 12 }}>{rIdx + 1}</td>
                {row.map((cell: unknown, cIdx: number) => (
                  <td key={cIdx} style={{ padding: 10, borderTop: "1px solid var(--border)", fontSize: 12 }}>
                    {String(cell ?? "")}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function renderMappingTable(
  wizard: StudioWizardState,
  onColumnChange: (idx: number, value: string) => void,
  onConstantChange: (idx: number, value: string) => void,
  onTypeChange: (idx: number, value: string) => void,
) {
  const fieldMappings = (wizard.config?.fieldMappings || []);
  if (!fieldMappings.length) {
    return <div className={styles.emptyBlock}>No field mappings defined.</div>;
  }
  const confidenceVal = wizard.config?.configHealth?.confidence || 0.85;
  const actualPct = confidenceVal > 1 ? confidenceVal : Math.round(confidenceVal * 100);

  return (
    <div style={{ marginBottom: 24, border: "1px solid var(--border)", borderRadius: 6, background: "var(--bg-surface)", overflow: "auto" }}>
      <table className={styles.mappingTable}>
        <thead>
          <tr style={{ background: "var(--bg-surface-hover)" }}>
            <th>Canonical Field</th>
            <th>Source Column</th>
            <th>Constant Value</th>
            <th>Data Type</th>
            <th>Required</th>
            <th>AI Confidence</th>
          </tr>
        </thead>
        <tbody>
          {fieldMappings.map((fm: FieldMapping, idx: number) => {
            const badgeInfo = getConfidenceBadge(actualPct);
            return (
              <tr key={idx}>
                <td style={{ padding: "12px 16px", fontWeight: 600, color: "var(--text-primary)", borderTop: "1px solid var(--border)" }}>
                  {fm.path}
                </td>
                <td style={{ padding: "12px 16px", borderTop: "1px solid var(--border)" }}>
                  <select
                    className={styles.studioSelect}
                    value={fm.column ?? ""}
                    onChange={e => onColumnChange(idx, e.target.value)}
                  >
                    <option value="">-- Constant Only --</option>
                    {wizard.headers.map((h, hIdx) => (
                      <option key={hIdx} value={hIdx + 1}>
                        Col {hIdx + 1}: {h}
                      </option>
                    ))}
                  </select>
                </td>
                <td style={{ padding: "12px 16px", borderTop: "1px solid var(--border)" }}>
                  <input
                    className={styles.studioInput}
                    type="text"
                    value={fm.constant ?? ""}
                    onChange={e => onConstantChange(idx, e.target.value)}
                    placeholder="Constant..."
                  />
                </td>
                <td style={{ padding: "12px 16px", borderTop: "1px solid var(--border)" }}>
                  <select
                    className={styles.studioSelect}
                    value={fm.type}
                    onChange={e => onTypeChange(idx, e.target.value)}
                  >
                    <option value="STRING">STRING</option>
                    <option value="DECIMAL">DECIMAL</option>
                    <option value="DATE">DATE</option>
                    <option value="CONSTANT">CONSTANT</option>
                  </select>
                </td>
                <td style={{ padding: "12px 16px", borderTop: "1px solid var(--border)" }}>
                  <Badge severity={fm.required ? "high" : "neutral"}>{fm.required ? "Yes" : "No"}</Badge>
                </td>
                <td style={{ padding: "12px 16px", borderTop: "1px solid var(--border)" }}>
                  <Badge severity={badgeInfo.severity}>{actualPct}% ({badgeInfo.label})</Badge>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function MappingStudioFieldMappingStep({
  wizard,
  studioTab,
  onTabChange,
  onColumnChange,
  onConstantChange,
  onTypeChange,
  onAddMappingRow,
  onCopyJson,
  onValidateAndProceed,
  onBack,
  onConfigJsonChange,
}: Props) {
  const configJsonStr = wizard.config ? JSON.stringify(wizard.config, null, 2) : "";

  return (
    <div>
      <h2 className={styles.studioTitle}>Review Draft Mapping</h2>
      <p className={styles.studioSubtitle}>
        Inspect the detected file structure and adjust the draft before it moves through Review Center.
      </p>

      {wizard.draftMappingId && (
        <div className={styles.infoBanner}>
          <span style={{ color: "var(--brand-accent-blue)" }}>ℹ️</span>
          <div style={{ fontSize: 13, color: "var(--text-primary)", flexGrow: 1 }}>
            This draft is currently pending review. Runtime eligibility: <strong>{wizard.isRuntimeEligible ? "Yes" : "No"}</strong>.
          </div>
          <div style={{ marginLeft: "auto" }}>
            <Badge severity="neutral">{wizard.configStatus || "PENDING_APPROVAL"}</Badge>
          </div>
        </div>
      )}

      {renderFilePreview(wizard)}

      <div className={styles.studioToolbar}>
        <div className={styles.studioToolbarTabs}>
          <Button variant={studioTab === "visual" ? "primary" : "default"} onClick={() => onTabChange("visual")}>
            Visual Mapping
          </Button>
          <Button variant={studioTab === "json" ? "primary" : "default"} onClick={() => onTabChange("json")}>
            Schema JSON
          </Button>
        </div>
        <div>
          <Button variant="default" onClick={onAddMappingRow}>+ Add Mapping Row</Button>
        </div>
      </div>

      {studioTab === "visual" && renderMappingTable(wizard, onColumnChange, onConstantChange, onTypeChange)}

      {studioTab === "json" && (
        <div style={{ marginBottom: 24, display: "flex", flexDirection: "column", gap: 10 }}>
          <textarea
            className={styles.jsonTextarea}
            value={configJsonStr}
            onChange={e => onConfigJsonChange(e.target.value)}
            placeholder="Schema JSON..."
          />
          <div style={{ textAlign: "right" }}>
            <Button variant="default" onClick={onCopyJson} style={{ height: 32, padding: "0 16px", fontSize: 12 }}>
              Copy JSON Schema
            </Button>
          </div>
        </div>
      )}

      <div style={{ display: "flex", gap: 12 }}>
        <Button variant="default" onClick={onBack}>Back to Step 1</Button>
        <Button variant="primary" onClick={onValidateAndProceed}>Validate & Test Mapping Schema</Button>
      </div>
    </div>
  );
}
