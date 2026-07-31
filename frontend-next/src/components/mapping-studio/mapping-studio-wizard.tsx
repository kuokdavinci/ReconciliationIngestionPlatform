/* eslint-disable @typescript-eslint/no-explicit-any */
"use client";

import { useState, useCallback } from "react";
import { useToast } from "@/components/ui/toast";
import type { StudioWizardState, DraftMappingConfig, FieldMapping } from "@/types/mapping";
import * as api from "@/lib/api/mapping-studio";
import styles from "./mapping-studio.module.css";
import { MappingStudioUploadStep } from "./mapping-studio-upload-step";
import { MappingStudioFieldMappingStep } from "./mapping-studio-field-mapping-step";
import { MappingStudioValidateStep } from "./mapping-studio-validate-step";
import { MappingStudioExecuteStep } from "./mapping-studio-execute-step";

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

  const updateWizard = useCallback((partial: Partial<StudioWizardState>) => {
    setWizard(prev => ({ ...prev, ...partial }));
  }, []);

  const renderStepRail = () => {
    const steps = [
      { num: 1 as const, label: "1. Evaluate File" },
      { num: 2 as const, label: "2. Mapping Config" },
      { num: 3 as const, label: "3. Validate" },
      { num: 4 as const, label: "4. Approve & Run" },
    ];
    return (
      <div className={styles.studioSteps}>
        {steps.map(s => (
          <div key={s.num} className={`${styles.studioStepItem} ${wizard.step === s.num ? styles.active : ""} ${wizard.step >= s.num ? styles.enabled : ""}`}>
            <span className={styles.studioStepIndex}>{s.num}</span>
            {s.label}
          </div>
        ))}
      </div>
    );
  };

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

  const updateFieldMapping = (idx: number, updates: Partial<FieldMapping>) => {
    if (!wizard.config) return;
    const fms = [...(wizard.config.fieldMappings || [])];
    fms[idx] = { ...fms[idx], ...updates };
    setWizard(prev => ({ ...prev, config: { ...prev.config!, fieldMappings: fms } }));
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

  const handleConfigJsonChange = (value: string) => {
    try {
      const parsed = JSON.parse(value) as DraftMappingConfig;
      setWizard(prev => ({ ...prev, config: parsed }));
    } catch {
      // Allow editing even with invalid JSON
    }
  };

  const handleValidateAndProceed = async () => {
    if (!wizard.config) return;
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
      showToast("Moving to Step 4: Approve & Run...", "info");
      setWizard(prev => ({ ...prev, step: 4 }));
      return;
    }
    try {
      await api.handoffReview(wizard.draftMappingId);
      showToast("Mapping submitted for review. Moving to Step 4...", "success");
      setWizard(prev => ({ ...prev, step: 4, handoffConfirmed: true }));
    } catch (err: any) {
      showToast(err.message || "Handoff failed", "error");
    }
  };

  const openReviewCenter = () => {
    if (wizard.reviewItemId) {
      onNavigateReview?.(wizard.reviewItemId);
    }
  };

  return (
    <section className={styles.studioShell}>
      {renderStepRail()}

      {wizard.step === 1 && (
        <MappingStudioUploadStep
          wizard={wizard}
          onExcelUpload={handleExcelUpload}
          onJsonUpload={handleJsonUpload}
          onManualSetup={handleManualSetup}
        />
      )}

      {wizard.step === 2 && (
        <MappingStudioFieldMappingStep
          wizard={wizard}
          studioTab={studioTab}
          onTabChange={setStudioTab}
          onColumnChange={handleColumnChange}
          onConstantChange={handleConstantChange}
          onTypeChange={handleTypeChange}
          onAddMappingRow={handleAddMappingRow}
          onCopyJson={handleCopyJson}
          onValidateAndProceed={handleValidateAndProceed}
          onBack={() => setWizard(prev => ({ ...prev, step: 1, handoffConfirmed: false }))}
          onConfigJsonChange={handleConfigJsonChange}
        />
      )}

      {wizard.step === 3 && (
        <MappingStudioValidateStep
          wizard={wizard}
          onRunTest={handleRunTest}
          onRestoreVersion={handleRestoreVersion}
          onHandoff={handleHandoff}
          onOpenReviewCenter={openReviewCenter}
          onBack={() => setWizard(prev => ({ ...prev, step: 2 }))}
        />
      )}

      {wizard.step === 4 && (
        <MappingStudioExecuteStep
          wizard={wizard}
          onBack={() => setWizard(prev => ({ ...prev, step: 3 }))}
          onOpenReconciliation={() => {
            window.location.href = "/reconciliation";
          }}
        />
      )}
    </section>
  );
}
