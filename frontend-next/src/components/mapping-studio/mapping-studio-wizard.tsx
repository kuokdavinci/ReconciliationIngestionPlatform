/* eslint-disable @typescript-eslint/no-explicit-any */
"use client";

import { useState, useCallback, useRef } from "react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { useToast } from "@/components/ui/toast";
import type { StudioWizardState, DraftMappingConfig, FieldMapping } from "@/types/mapping";
import * as api from "@/lib/api/mapping-studio";
import styles from "./mapping-studio.module.css";

interface Props {
  initialPartner?: string;
  onNavigateReview?: (reviewItemId: string) => void;
}

const INITIAL_STATE: StudioWizardState = {
  step: 1,
  loading: false,
  partner: "MOMO",
  fileName: undefined,
  headers: [],
  sampleRows: [],
  config: null,
  draftMappingId: null,
  reviewItemId: null,
  configStatus: null,
  isRuntimeEligible: false,
  validation: null,
  testOutput: null,
  versions: [],
  handoffConfirmed: false,
};

const DEFAULT_TEMPLATE: DraftMappingConfig = {
  partner: "MOMO",
  workflowType: "UPC",
  fileType: "SETTLEMENT",
  sheetName: "Sheet1",
  startRow: 2,
  configVersion: "v_manual",
  fieldMappings: [
    { path: "id", column: 1, type: "STRING", required: true },
    { path: "amount", column: 2, type: "DECIMAL", required: true },
    { path: "transDate", column: 3, type: "DATE", required: true },
  ],
};

export function MappingStudioWizard({ initialPartner = "MOMO", onNavigateReview }: Props) {
  const [wizard, setWizard] = useState<StudioWizardState>({ ...INITIAL_STATE, partner: initialPartner });
  const [studioTab, setStudioTab] = useState<"visual" | "json">("visual");
  const { showToast } = useToast();

  const excelInputRef = useRef<HTMLInputElement>(null);
  const jsonInputRef = useRef<HTMLInputElement>(null);

  const updateWizard = useCallback((partial: Partial<StudioWizardState>) => {
    setWizard(prev => ({ ...prev, ...partial }));
  }, []);

  // ---- Step Indicator ----

  const renderStepRail = () => {
    const steps = [
      { num: 1 as const, label: "Select Sample" },
      { num: 2 as const, label: "Review Draft" },
      { num: 3 as const, label: "Validate Output" },
    ];
    return (
      <div className={styles.studioSteps}>
        {steps.map(s => (
          <div
            key={s.num}
            className={`${styles.studioStepItem} ${wizard.step === s.num ? styles.active : ""} ${wizard.step >= s.num ? styles.enabled : ""}`}
          >
            <span className={styles.studioStepIndex}>{s.num}</span>
            {s.label}
          </div>
        ))}
      </div>
    );
  };

  // ---- Step 1: Upload Sample ----

  const handleExcelUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    updateWizard({ loading: true });
    showToast("Uploading sample and generating a draft mapping...");
    try {
      const result = await api.aiGenerateMapping(wizard.partner, file);
      updateWizard({
        loading: false,
        fileName: file.name,
        headers: result.headers || [],
        sampleRows: result.sampleRows || [],
        config: result.config,
        draftMappingId: result.draftMappingId || null,
        reviewItemId: result.reviewItemId || null,
        configStatus: result.configStatus || null,
        isRuntimeEligible: result.isRuntimeEligible || false,
        handoffConfirmed: false,
      });
      if (result.reviewItemId) {
        showToast("Draft created. Opening Review Center with the review drawer.");
        onNavigateReview?.(result.reviewItemId);
      } else {
        setWizard(prev => ({ ...prev, step: 2, loading: false }));
        showToast("Draft created. Review now continues in the Review Center.", "success");
      }
    } catch (err: any) {
      updateWizard({ loading: false });
      showToast(err.message || "AI Gen failed", "error");
    }
    if (e.target) e.target.value = "";
  };

  const handleJsonUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (event) => {
      try {
        const json = JSON.parse(event.target?.result as string) as DraftMappingConfig;
        const headers = (json.fieldMappings || []).map(fm => fm.path);
        setWizard(prev => ({
          ...prev,
          config: json,
          fileName: file.name,
          step: 2,
          handoffConfirmed: false,
          headers,
          sampleRows: [],
        }));
        showToast("Existing mapping JSON schema loaded.", "success");
      } catch {
        showToast("Invalid JSON file schema structure.", "error");
      }
    };
    reader.readAsText(file);
    if (e.target) e.target.value = "";
  };

  const handleManualSetup = () => {
    const config = JSON.parse(JSON.stringify(DEFAULT_TEMPLATE));
    const headers = (config.fieldMappings || []).map((fm: FieldMapping) => fm.path);
    setWizard(prev => ({
      ...prev,
      config,
      step: 2,
      handoffConfirmed: false,
      headers,
      sampleRows: [],
    }));
    showToast("Starting manual setup with default template.", "info");
  };

  const renderStep1 = () => (
    <div>
      {renderStepRail()}
      <div className={styles.uploadGrid}>
        {/* Card 1: Upload Partner Sample */}
        <div className={`${styles.optionCard} ${styles.optionCardPrimary}`}>
          {wizard.loading ? (
            <div className={styles.centerSpinner}>
              <div className="spinner" style={{ marginBottom: 16 }} />
              <p style={{ fontSize: 13, fontWeight: 600, color: "var(--brand-primary)", margin: 0 }}>
                AI is analyzing your file...
              </p>
              <p style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 4 }}>
                Mapping structure extraction in progress
              </p>
            </div>
          ) : (
            <div>
              <div style={{ fontSize: 48, color: "var(--brand-primary)", marginBottom: 12 }}>🧠</div>
              <h3 style={{ margin: "0 0 8px 0", color: "#fff" }}>Upload Partner Sample</h3>
              <p style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 16 }}>
                Upload a spreadsheet (.xlsx, .xls, .csv) to generate a draft mapping.
              </p>
              <div style={{ marginBottom: 16, display: "flex", gap: 8, alignItems: "center", justifyContent: "center" }}>
                <span style={{ fontSize: 11, fontWeight: 700, color: "var(--text-muted)" }}>PARTNER:</span>
                <select
                  value={wizard.partner}
                  onChange={e => updateWizard({ partner: e.target.value })}
                  className={styles.studioSelect}
                >
                  <option value="VNPAY">VNPAY</option>
                  <option value="MOMO">MOMO</option>
                  <option value="ZALOPAY">ZALOPAY</option>
                  <option value="ACMEPAY">ACMEPAY</option>
                </select>
              </div>
            </div>
          )}
          <div>
            <input
              ref={excelInputRef}
              type="file"
              accept=".xlsx,.xls,.csv"
              style={{ display: "none" }}
              onChange={handleExcelUpload}
            />
            <Button
              variant="primary"
              style={{ width: "100%" }}
              disabled={wizard.loading}
              onClick={() => excelInputRef.current?.click()}
            >
              {wizard.loading ? "Processing..." : "Generate Draft"}
            </Button>
          </div>
        </div>

        {/* Card 2: Upload Existing Schema */}
        <div className={styles.optionCard}>
          <div>
            <div style={{ fontSize: 48, color: "var(--text-muted)", marginBottom: 12 }}>📄</div>
              <h3 style={{ margin: "0 0 8px 0", color: "#fff" }}>Upload Existing Schema</h3>
            <p style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 24 }}>
              Start from an existing JSON schema and send a revised version for review.
            </p>
          </div>
          <div>
            <input
              ref={jsonInputRef}
              type="file"
              accept=".json"
              style={{ display: "none" }}
              onChange={handleJsonUpload}
            />
            <Button
              variant="default"
              style={{ width: "100%" }}
              onClick={() => jsonInputRef.current?.click()}
            >
              Browse JSON File
            </Button>
          </div>
        </div>

        {/* Card 3: Manual Setup */}
        <div className={styles.optionCard}>
          <div>
            <div style={{ fontSize: 48, color: "var(--text-muted)", marginBottom: 12 }}>✏️</div>
            <h3 style={{ margin: "0 0 8px 0", color: "#fff" }}>Manual Setup</h3>
            <p style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 24 }}>
              Start configuration manually by pasting JSON mapping template.
            </p>
          </div>
          <div>
            <Button
              variant="default"
              style={{ width: "100%" }}
              onClick={handleManualSetup}
            >
              Paste Schema JSON
            </Button>
          </div>
        </div>
      </div>
    </div>
  );

  // ---- Step 2: Review Draft ----

  const getConfidenceBadge = (confidencePct: number) => {
    if (confidencePct >= 90) return { severity: "low" as const, label: "High" };
    if (confidencePct >= 80) return { severity: "neutral" as const, label: "Medium" };
    return { severity: "critical" as const, label: "Needs Review" };
  };

  const updateFieldMapping = (idx: number, updates: Partial<FieldMapping>) => {
    if (!wizard.config) return;
    const fms = [...(wizard.config.fieldMappings || [])];
    fms[idx] = { ...fms[idx], ...updates };
    setWizard(prev => ({ ...prev, config: { ...prev.config!, fieldMappings: fms } }));
  };

  const handleColumnChange = (idx: number, value: string) => {
    const col = value ? parseInt(value, 10) : null;
    if (col !== null) {
      updateFieldMapping(idx, { column: col, constant: undefined });
    } else {
      updateFieldMapping(idx, { column: null });
    }
  };

  const handleConstantChange = (idx: number, value: string) => {
    if (value !== "") {
      updateFieldMapping(idx, { constant: value, column: undefined });
    } else {
      updateFieldMapping(idx, { constant: null });
    }
  };

  const handleTypeChange = (idx: number, value: string) => {
    updateFieldMapping(idx, { type: value as FieldMapping["type"] });
  };

  const handleAddMappingRow = () => {
    if (!wizard.config) return;
    const count = wizard.config.fieldMappings?.length || 0;
    const newFm: FieldMapping = {
      path: `custom_field_${count + 1}`,
      column: null,
      type: "STRING",
      required: false,
    };
    setWizard(prev => ({
      ...prev,
      config: { ...prev.config!, fieldMappings: [...(prev.config!.fieldMappings || []), newFm] },
    }));
  };

  const handleCopyJson = () => {
    if (!wizard.config) return;
    void navigator.clipboard.writeText(JSON.stringify(wizard.config, null, 2));
    showToast("Schema JSON copied to clipboard.", "info");
  };

  const handleValidateAndProceed = async () => {
    if (!wizard.config) return;
    // If JSON tab was active, parse textarea value
    if (studioTab === "json") {
      // We'll handle this during the actual validate call
    }
    // Deep clone config and inject currency field
    const configCopy = JSON.parse(JSON.stringify(wizard.config));
    if (configCopy.fieldMappings && !configCopy.fieldMappings.some((fm: FieldMapping) => fm.path === "currency")) {
      configCopy.fieldMappings.push({
        path: "currency",
        type: "CONSTANT",
        constant: "VND",
        required: true,
      });
    }
    showToast("Running validation rules engine...");
    try {
      const data = await api.validateMapping(configCopy);
      const versions = await api.getMappingVersions(configCopy.partner || wizard.partner);
      setWizard(prev => ({
        ...prev,
        config: configCopy,
        validation: data,
        step: 3,
        handoffConfirmed: false,
        versions: versions.versions || [],
      }));
    } catch (err: any) {
      showToast("Validation fetch error: " + (err.message || "Unknown error"), "error");
    }
  };

  const renderFilePreview = () => {
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
              {wizard.sampleRows.slice(0, 10).map((row, rIdx) => (
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
  };

  const renderMappingTable = () => {
    const fieldMappings = (wizard.config?.fieldMappings || []);
    if (!fieldMappings.length) {
      return (
        <div className={styles.emptyBlock}>
          No field mappings defined.
        </div>
      );
    }
    const confidenceVal = wizard.config?.configHealth?.confidence || 0.85;
    const confidencePct = Math.round(confidenceVal * (confidenceVal > 1 ? 1 : 1)); // It's a decimal 0-1
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
                      onChange={e => handleColumnChange(idx, e.target.value)}
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
                      onChange={e => handleConstantChange(idx, e.target.value)}
                      placeholder="Constant..."
                    />
                  </td>
                  <td style={{ padding: "12px 16px", borderTop: "1px solid var(--border)" }}>
                    <select
                      className={styles.studioSelect}
                      value={fm.type}
                      onChange={e => handleTypeChange(idx, e.target.value)}
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
  };

  const renderStep2 = () => {
    const configJsonStr = wizard.config ? JSON.stringify(wizard.config, null, 2) : "";
    return (
      <div>
        <h2 style={{ color: "#fff" }}>Review Draft Mapping</h2>
        <p style={{ fontSize: 13, color: "var(--text-muted)", marginBottom: 20 }}>
          Inspect the detected file structure and adjust the draft before it moves through Review Center.
        </p>

        {renderStepRail()}

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

        {renderFilePreview()}

        <div className={styles.studioToolbar}>
          <div className={styles.studioToolbarTabs}>
            <Button
              variant={studioTab === "visual" ? "primary" : "default"}
              onClick={() => setStudioTab("visual")}
            >
              Visual Mapping
            </Button>
            <Button
              variant={studioTab === "json" ? "primary" : "default"}
              onClick={() => setStudioTab("json")}
            >
              Schema JSON
            </Button>
          </div>
          <div>
            <Button
              variant="default"
              onClick={handleAddMappingRow}
            >
              + Add Mapping Row
            </Button>
          </div>
        </div>

        {studioTab === "visual" && renderMappingTable()}

        {studioTab === "json" && (
          <div style={{ marginBottom: 24, display: "flex", flexDirection: "column", gap: 10 }}>
            <textarea
              className={styles.jsonTextarea}
              value={configJsonStr}
              onChange={e => {
                try {
                  const parsed = JSON.parse(e.target.value) as DraftMappingConfig;
                  setWizard(prev => ({ ...prev, config: parsed }));
                } catch {
                  // Allow editing even with invalid JSON - store raw
                }
              }}
              placeholder="Schema JSON..."
            />
            <div style={{ textAlign: "right" }}>
              <Button variant="default" onClick={handleCopyJson} style={{ height: 32, padding: "0 16px", fontSize: 12 }}>
                Copy JSON Schema
              </Button>
            </div>
          </div>
        )}

        <div style={{ display: "flex", gap: 12 }}>
          <Button variant="default" onClick={() => setWizard(prev => ({ ...prev, step: 1, handoffConfirmed: false }))}>
            Back to Step 1
          </Button>
          <Button variant="primary" onClick={handleValidateAndProceed}>
            Validate & Test Mapping Schema
          </Button>
        </div>
      </div>
    );
  };

  // ---- Step 3: Validate Output ----

  const handleRunTest = async () => {
    if (!wizard.config) return;
    const row = wizard.sampleRows[0] || ["TXN001", "150000", "SUCCESS"];
    showToast("Testing layout transformation output...");
    try {
      const data = await api.testMapping(wizard.config, row as unknown[]);
      setWizard(prev => ({ ...prev, testOutput: data.output || null }));
      showToast("Transformation test completed.", "success");
    } catch (err: any) {
      showToast("Transformation test failed: " + (err.message || "Unknown error"), "error");
    }
  };

  const handleRestoreVersion = async (versionId: string) => {
    showToast("Restoring schema version...");
    try {
      const data = await api.getVersion(versionId);
      const headers = (data as any).fieldMappings?.map((fm: FieldMapping) => fm.path) || [];
      setWizard(prev => ({
        ...prev,
        config: data as DraftMappingConfig,
        step: 2,
        headers,
      }));
      showToast(`Restored schema version: ${(data as any).configVersion || "unknown"}`, "success");
    } catch (err: any) {
      showToast("Restore failed: " + (err.message || "Unknown error"), "error");
    }
  };

  const handleHandoff = async () => {
    if (!wizard.draftMappingId) {
      showToast("No draft mapping to hand off. Save the draft mapping first.", "error");
      return;
    }
    try {
      await api.handoffReview(wizard.draftMappingId);
      showToast("Mapping submitted for review.", "success");
      setWizard(prev => ({ ...prev, handoffConfirmed: false }));
      onNavigateReview?.(wizard.draftMappingId!);
    } catch (err: any) {
      showToast(err.message || "Handoff failed", "error");
    }
  };

  const openReviewCenter = () => {
    if (wizard.reviewItemId) {
      onNavigateReview?.(wizard.reviewItemId);
    }
  };

  const renderStep3 = () => {
    const score = wizard.validation?.score ?? 100;
    const scoreClass = score >= 90 ? "matched" : score >= 75 ? "warning" : "critical";
    const scoreLabel = score >= 90 ? "Excellent" : score >= 75 ? "Good" : "Review Needed";

    const errors = wizard.validation?.errors || [];
    const warnings = wizard.validation?.warnings || [];
    const passedChecks = [
      errors.some(e => e.includes("required")) ? null : "Required fields are mapped for the canonical output.",
      warnings.some(w => w.includes("multiple")) ? null : "Duplicate mapping check passed.",
      warnings.some(w => w.includes("neither")) ? null : "Each field has either a source column or a constant.",
    ].filter(Boolean);

    const testOutputHtml = wizard.testOutput
      ? (
        <textarea
          readOnly
          className={styles.outputTextarea}
          value={JSON.stringify(wizard.testOutput, null, 2)}
        />
      )
      : (
        <div style={{ padding: 24, textAlign: "center", color: "var(--text-muted)" }}>
          Click &quot;Run Transformation Test&quot; to verify output layout.
        </div>
      );

    return (
      <div>
        <h2 style={{ color: "#fff" }}>Validate & Prepare Review Handoff</h2>
        <p style={{ fontSize: 13, color: "var(--text-muted)", marginBottom: 20 }}>
          Resolve blocking issues, inspect warnings, test the transformed output, and then hand the draft to Review Center.
        </p>

        {wizard.draftMappingId && (
          <div className={styles.infoBanner}>
            <span style={{ color: "var(--brand-accent-blue)" }}>✅</span>
            <div style={{ fontSize: 13, color: "var(--text-primary)", flexGrow: 1 }}>
              This draft requires Review Center action before activation.
            </div>
            <div style={{ display: "flex", gap: 8, alignItems: "center", marginLeft: "auto" }}>
              <Badge severity="neutral">{wizard.configStatus || "PENDING_APPROVAL"}</Badge>
              <Button
                variant={wizard.handoffConfirmed ? "secondary" : "primary"}
                onClick={handleHandoff}
                style={{ height: 32, padding: "0 12px", fontSize: 12 }}
              >
                {wizard.handoffConfirmed ? "Handoff Confirmed" : "Confirm Ready"}
              </Button>
              <Button
                variant="default"
                onClick={openReviewCenter}
                style={{ height: 32, padding: "0 12px", fontSize: 12 }}
              >
                Open Review Center
              </Button>
            </div>
          </div>
        )}

        {renderStepRail()}

        <div className={styles.validationGrid}>
          {/* Card 1: Mapping Quality Score */}
          <div className={styles.validationCard}>
            <h3 style={{ margin: "0 0 16px 0", fontSize: 14, textTransform: "uppercase", letterSpacing: "0.05em", color: "var(--text-muted)" }}>
              Mapping Quality Score
            </h3>
            <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: 8 }}>
              <strong className={`${styles.scoreNumber} ${score < 75 ? styles.scoreLow : styles.scoreHigh}`}>
                {score}
              </strong>
              <span style={{ fontSize: 14, color: "var(--text-muted)" }}>/ 100</span>
            </div>
            <Badge severity={scoreClass === "critical" ? "critical" : scoreClass === "warning" ? "medium" : "low"}>{scoreLabel}</Badge>
            <div className={styles.validationGroup}>
              <div className={styles.validationGroupTitle}>Passed Checks</div>
              {passedChecks.length > 0
                ? passedChecks.map((check, i) => (
                  <div key={i} className={`${styles.validationItem} ${styles.matched}`}>
                    <span>✓</span>
                    <span>{check}</span>
                  </div>
                ))
                : <div style={{ color: "var(--text-muted)" }}>None</div>
              }
            </div>
          </div>

          {/* Card 2: Validation Results */}
          <div className={styles.validationCard}>
            <h3 style={{ margin: "0 0 16px 0", fontSize: 14, textTransform: "uppercase", letterSpacing: "0.05em", color: "var(--text-muted)" }}>
              Validation Results
            </h3>
            <div className={styles.validationGroup}>
              <div className={`${styles.validationGroupTitle} ${styles.critical}`}>Blocking Errors</div>
              {errors.length > 0
                ? errors.map((err, i) => (
                  <div key={i} className={`${styles.validationItem} ${styles.critical}`}>
                    <span>✕</span>
                    <span>{err}</span>
                  </div>
                ))
                : <div style={{ color: "var(--text-muted)" }}>None</div>
              }
            </div>
            <div className={styles.validationGroup}>
              <div className={`${styles.validationGroupTitle} ${styles.warning}`}>Warnings</div>
              {warnings.length > 0
                ? warnings.map((warn, i) => (
                  <div key={i} className={`${styles.validationItem} ${styles.warning}`}>
                    <span>⚠</span>
                    <span>{warn}</span>
                  </div>
                ))
                : <div style={{ color: "var(--text-muted)" }}>None</div>
              }
            </div>
          </div>

          {/* Card 3: Schema Versions */}
          <div className={styles.validationCard}>
            <h3 style={{ margin: "0 0 12px 0", fontSize: 14, textTransform: "uppercase", letterSpacing: "0.05em", color: "var(--text-muted)" }}>
              Schema Versions
            </h3>
            <div style={{ maxHeight: 160, overflowY: "auto", border: "1px solid var(--border)", borderRadius: 4 }}>
              {wizard.versions.length > 0 ? (
                <table className={styles.versionTable}>
                  <thead>
                    <tr>
                      <th>Version</th>
                      <th>Published Date</th>
                      <th style={{ textAlign: "right" }}>Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {wizard.versions.map((v: Record<string, unknown>, i: number) => (
                      <tr key={i}>
                        <td style={{ fontWeight: 700 }}>{(v.configVersion as string) || "latest"}</td>
                        <td style={{ color: "var(--text-muted)" }}>{v.publishedAt ? new Date(v.publishedAt as string).toLocaleString() : "N/A"}</td>
                        <td style={{ textAlign: "right" }}>
                          <Button
                            variant="default"
                            onClick={() => handleRestoreVersion(v._id as string)}
                            style={{ height: 26, padding: "0 10px", fontSize: 11 }}
                          >
                            Restore
                          </Button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <div style={{ padding: 10, textAlign: "center", color: "var(--text-muted)", fontSize: 12 }}>
                  No previous versions.
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Test Mapping Transformation Result */}
        <div style={{ padding: 20, background: "var(--bg-surface)", border: "1px solid var(--border)", borderRadius: 8, marginBottom: 24 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
            <h3 style={{ margin: 0, fontSize: 15, fontWeight: 700, color: "#fff" }}>Test Mapping Transformation Result</h3>
            <Button variant="primary" onClick={handleRunTest}>
              Run Transformation Test
            </Button>
          </div>
          {testOutputHtml}
        </div>

        {/* Bottom actions */}
        <div style={{ display: "flex", gap: 12 }}>
          <Button variant="default" onClick={() => setWizard(prev => ({ ...prev, step: 2 }))}>
            Back to Step 2
          </Button>
          {!wizard.draftMappingId && (
            <Button variant="primary">
              Mark Ready for Review
            </Button>
          )}
        </div>
      </div>
    );
  };

  // ---- Main render ----

  return (
    <section className={styles.studioShell}>
      {wizard.step === 1 && renderStep1()}
      {wizard.step === 2 && renderStep2()}
      {wizard.step === 3 && renderStep3()}
    </section>
  );
}
