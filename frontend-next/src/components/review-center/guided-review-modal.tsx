/* eslint-disable @typescript-eslint/no-explicit-any */
"use client";

import { useMemo, useState, useEffect, useRef, useCallback } from "react";
import { Dialog } from "@/components/ui/dialog";
import { useToast } from "@/components/ui/toast";
import * as api from "@/lib/api/review-center";
import { getRuntimeValidationState } from "@/lib/review-runtime";
import type { ReviewPacket, PostApprovalRun } from "@/types/review-center";
import dialogStyles from "@/components/ui/dialog.module.css";
import styles from "./review-center.module.css";
import { GuidedReviewScopeStep } from "./guided-review-scope-step";
import { GuidedReviewMappingStep } from "./guided-review-mapping-step";
import { GuidedReviewValidationStep } from "./guided-review-validation-step";
import { GuidedReviewDecisionStep } from "./guided-review-decision-step";

const steps = ["Scope", "Mapping", "Validation", "Decision"];

interface Props {
  packet: ReviewPacket | null;
  open: boolean;
  onClose: () => void;
  onRefresh: () => void;
}

export function GuidedReviewModal({ packet, open, onClose, onRefresh }: Props) {
  const { showToast } = useToast();
  
  const [step, setStep] = useState(packet && String(packet.status).toUpperCase() === "APPROVED" ? 4 : 1);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [localPacket, setLocalPacket] = useState<ReviewPacket | null>(packet);

  const [selectedScope, setSelectedScope] = useState(packet?.scopeRecommendation?.scopeType ?? packet?.scopeType ?? "FULL_SNAPSHOT");
  const [isSavingScope, setIsSavingScope] = useState(false);
  const [scopeClassification, setScopeClassification] = useState<any>(null);
  const [scopeLoading, setScopeLoading] = useState(false);
  const [scopeError, setScopeError] = useState("");

  const [aiMapping, setAiMapping] = useState<any>(null);
  const [aiMappingLoading, setAiMappingLoading] = useState(false);
  const [aiMappingError, setAiMappingError] = useState("");
  const [fieldMappings, setFieldMappings] = useState<any[]>([]);
  const [isSavingMapping, setIsSavingMapping] = useState(false);

  const [isValidatingRuntime, setIsValidatingRuntime] = useState(false);
  const [traceDetailSampleIndex, setTraceDetailSampleIndex] = useState<number | null>(null);

  const [postApprovalRun, setPostApprovalRun] = useState<PostApprovalRun | null>(null);
  const pollingIntervalRef = useRef<NodeJS.Timeout | null>(null);

  const startPolling = useCallback((packetId: string) => {
    if (pollingIntervalRef.current) return;

    const tick = async () => {
      try {
        const response = await api.getPostApproveRun(packetId);
        if (response.run) {
          const run = response.run as any;
          setPostApprovalRun(run);
          if (run.status === "COMPLETED" || run.status === "FAILED") {
            if (pollingIntervalRef.current) {
              clearInterval(pollingIntervalRef.current);
              pollingIntervalRef.current = null;
            }
            if (run.status === "COMPLETED") {
              showToast("Ingestion and reconciliation completed!", "success");
              onRefresh();
            }
          }
        }
      } catch {
        // Run may not be created yet
      }
    };
    void tick();
    pollingIntervalRef.current = setInterval(() => { void tick(); }, 1500);
  }, [onRefresh, onClose, showToast]);

  useEffect(() => {
    if (localPacket && String(localPacket.status).toUpperCase() === "APPROVED") {
      void api.getPostApproveRun(localPacket._id).then(res => {
        if (res.run) setPostApprovalRun(res.run as any);
      }).catch(() => {});
    }
  }, [localPacket]);

  const handleClose = () => {
    if (pollingIntervalRef.current) {
      clearInterval(pollingIntervalRef.current);
      pollingIntervalRef.current = null;
    }
    setStep(1);
    setScopeClassification(null);
    setAiMapping(null);
    setFieldMappings([]);
    setPostApprovalRun(null);
    onClose();
  };

  useEffect(() => {
    if (open && localPacket?._id && step === 1 && !scopeClassification && !scopeLoading) {
      const loadScope = async () => {
        setScopeLoading(true);
        setScopeError("");
        try {
          const res = (await api.classifyScope(localPacket._id)) as any;
          setScopeClassification(res);
          if (res.suggestedScope) {
            setSelectedScope(res.suggestedScope);
          }
        } catch (err: any) {
          setScopeError(err.message || "Failed to load scope classification.");
        } finally {
          setScopeLoading(false);
        }
      };
      void loadScope();
    }
  }, [open, localPacket?._id, step, scopeClassification, scopeLoading]);

  useEffect(() => {
    const shouldLoad = open && localPacket?._id && !aiMapping && !aiMappingLoading &&
      (step === 2 || (step === 3 && fieldMappings.length === 0));
    if (shouldLoad) {
      const loadMapping = async () => {
        setAiMappingLoading(true);
        setAiMappingError("");
        try {
          const res = (await api.generateAiMapping(localPacket._id)) as any;
          setAiMapping(res.mapping || null);
          
          const rawDraftFieldMappings = res.mapping?.fieldMappings || [];
          const idMapping = rawDraftFieldMappings.find((m: any) => m.path === "id");
          const draftFieldMappings = rawDraftFieldMappings.filter((m: any) => {
            if (m.path !== "trace") return true;
            if (!idMapping) return true;
            return Number(m.column || 0) !== Number(idMapping.column || 0);
          });
          setFieldMappings(draftFieldMappings);
        } catch (err: any) {
          setAiMappingError(err.message || "Failed to load AI mapping proposal.");
        } finally {
          setAiMappingLoading(false);
        }
      };
      void loadMapping();
    }
  }, [open, localPacket?._id, step, aiMapping, aiMappingLoading, fieldMappings.length]);

  const handleContinueFromScope = async () => {
    if (!localPacket) return;
    setIsSavingScope(true);
    try {
      await api.setScope(localPacket._id, selectedScope);
      const refreshed = await api.getReviewPacket(localPacket._id);
      setLocalPacket(refreshed.packet);
      
      const pkt = refreshed.packet;
      if (String(pkt.status).toUpperCase() === "APPROVED") {
        setStep(4);
      } else {
        const runtimeGate = (pkt.validationGates || []).find(g => g.gateKey === "runtime_validation");
        const alreadyValidated = runtimeGate && ["PASS", "PASSED", "FAIL", "FAILED"].includes(String(runtimeGate.status).toUpperCase());
        setStep(alreadyValidated ? 3 : 2);
      }
    } catch (err: any) {
      showToast(err.message || "Failed to save file scope.", "error");
    } finally {
      setIsSavingScope(false);
    }
  };

  const handleMappingChange = (sourceColumn: number, newPath: string) => {
    setFieldMappings((prev) =>
      prev.map((mapping) => {
        if (Number(mapping.column) === sourceColumn) {
          return {
            ...mapping,
            path: newPath,
            required: ["id", "amount", "transDate"].includes(newPath),
            type: newPath ? "STRING" : mapping.type || "STRING",
          };
        }
        return mapping;
      })
    );
  };

  const handleSaveMapping = async () => {
    if (!localPacket) return;
    setIsSavingMapping(true);
    try {
      const sheetName = localPacket.parseStrategy?.sheetName || "Sheet1";
      const startRow = localPacket.parseStrategy?.startRow || 2;
      const payloadMappings = fieldMappings.map((m, index) => ({
        path: m.path,
        column: m.column !== null && m.column !== undefined && m.column !== "" ? Number(m.column) : null,
        type: m.type || "STRING",
        required: m.required ?? false,
        constant: m.constant || null,
        sourceField: m.sourceField || `Column ${index + 1}`,
        mapping: m.mapping || null,
      }));

      await api.saveDraftMapping(localPacket._id, {
        sheetName,
        startRow,
        fieldMappings: payloadMappings,
      });

      const refreshed = await api.getReviewPacket(localPacket._id);
      setLocalPacket(refreshed.packet);
      showToast("Draft mapping saved successfully.", "success");
      setStep(3);
    } catch (err: any) {
      showToast(err.message || "Failed to save draft mapping.", "error");
    } finally {
      setIsSavingMapping(false);
    }
  };

  const handleValidateRuntime = async () => {
    if (!localPacket) return;
    setIsValidatingRuntime(true);
    try {
      const response = (await api.validateRuntime(localPacket._id)) as any;
      showToast(response.gate?.message || "Runtime validation completed.", "success");
      const refreshed = await api.getReviewPacket(localPacket._id);
      setLocalPacket(refreshed.packet);
    } catch (err: any) {
      showToast(err.message || "Runtime validation failed.", "error");
    } finally {
      setIsValidatingRuntime(false);
    }
  };

  const handleApproveActivate = async () => {
    if (!localPacket) return;
    setIsSubmitting(true);
    try {
      const response = (await api.approveActivate(localPacket._id, "Administrator", selectedScope)) as any;
      showToast("Approved and activated. Reprocessing has started.", "success");
      if (response.postApproveRun) {
        setPostApprovalRun(response.postApproveRun as any);
      }
      startPolling(localPacket._id);
      onRefresh();
    } catch (err: any) {
      showToast(err.message || "Failed to approve review packet.", "error");
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleReject = async () => {
    if (!localPacket) return;
    setIsSubmitting(true);
    try {
      await api.rejectPacket(localPacket._id, "Administrator");
      showToast("Review packet rejected.", "success");
      onRefresh();
      handleClose();
    } catch (err: any) {
      showToast(err.message || "Failed to reject review packet.", "error");
    } finally {
      setIsSubmitting(false);
    }
  };

  const validationState = useMemo(() => {
    if (!localPacket) return { hasValidation: false, canProceed: false, tone: styles.validationWarning, title: "Pending", text: "Load packet to proceed.", status: "PENDING" };
    const runtimeGate = localPacket.validationGates?.find((g) => g.gateKey === "runtime_validation");
    const status = runtimeGate?.status ? String(runtimeGate.status).toUpperCase() : "PENDING";
    const hasValidation = !!runtimeGate;
    const canProceed = status === "PASS" || status === "PASSED" || status === "WARNING" || status === "WARN";
    
    let tone = styles.validationWarning;
    let title = "Runtime validation is pending.";
    let text = "Run runtime validation before approving.";
    
    if (status === "PASS" || status === "PASSED") {
      tone = styles.validationPassed;
      title = "Runtime Validation Passed";
      text = runtimeGate?.message || "All sampled rows validated successfully.";
    } else if (status === "FAIL" || status === "FAILED") {
      tone = styles.validationFailed;
      title = "Runtime Validation Failed";
      text = runtimeGate?.message || "The current mapping did not validate successfully.";
    } else if (status === "WARN" || status === "WARNING") {
      tone = styles.validationWarning;
      title = "Runtime Validation Passed with Warnings";
      text = runtimeGate?.message || "Some sampled rows still failed validation.";
    }

    return { hasValidation, canProceed, tone, title, text, status };
  }, [localPacket?.validationGates]);

  const runtimeValidationState = useMemo(() => {
    if (!localPacket) return null;
    return getRuntimeValidationState(localPacket);
  }, [localPacket]);

  const sourceBackedMappings = useMemo(() => {
    return fieldMappings.filter(
      (m) => m.type !== "CONSTANT" && !(m.mapping && (m.column === null || m.column === undefined || m.column === ""))
    );
  }, [fieldMappings]);

  const constantMappings = useMemo(() => {
    return fieldMappings.filter(
      (m) => m.type === "CONSTANT" || (m.mapping && (m.column === null || m.column === undefined || m.column === ""))
    );
  }, [fieldMappings]);

  const constantFieldEntries = useMemo(() => {
    return constantMappings.map(m => ({
      canonicalField: m.path,
      sourceColumn: m.constant ?? "-",
      status: "OK" as const,
      issue: null,
    }));
  }, [constantMappings]);

  const sigHeaders = localPacket?.structureSignature?.headers || [];
  const summary = localPacket?.runtimeValidation?.summary;
  const topIssues = localPacket?.runtimeValidation?.topIssues ?? [];

  const fieldResults = localPacket?.runtimeValidation?.fieldResults ?? [];

  const displayFieldResults = useMemo(() => {
    const existingPaths = new Set(fieldResults.map(f => f.canonicalField));
    const merged = [...fieldResults];
    for (const ce of constantFieldEntries) {
      if (!existingPaths.has(ce.canonicalField)) {
        merged.push(ce);
      }
    }
    return merged;
  }, [fieldResults, constantFieldEntries]);

  const isApproved = localPacket ? String(localPacket.status).toUpperCase() === "APPROVED" : false;

  if (!localPacket) return null;

  return (
    <Dialog open={open} onClose={handleClose} title={`Guided Review — ${localPacket.fileName}`} panelClassName={dialogStyles.wide}>
      <div className={styles.stepRail}>
        {steps.map((label, index) => {
          const current = index + 1;
          const isActive = current === step && !isApproved;
          const isDone = current < step || (current === step && isApproved);
          return (
            <div key={label} className={styles.stepCell}>
              <div className={`${styles.stepDot} ${isDone ? styles.stepDone : ""} ${isActive ? styles.stepActive : ""}`}>
                {isDone ? "✓" : current}
              </div>
              <span className={`${styles.stepName} ${isActive ? styles.stepNameActive : ""}`}>{label}</span>
            </div>
          );
        })}
      </div>

      {step === 1 && (
        <GuidedReviewScopeStep
          localPacket={localPacket}
          scopeClassification={scopeClassification}
          scopeLoading={scopeLoading}
          scopeError={scopeError}
          selectedScope={selectedScope}
          isSavingScope={isSavingScope}
          onScopeChange={setSelectedScope}
          onContinue={handleContinueFromScope}
          onCancel={handleClose}
          onRetry={() => {
            if (localPacket) {
              void api.classifyScope(localPacket._id).then(res => {
                setScopeClassification(res);
              });
            }
          }}
        />
      )}

      {step === 2 && (
        <GuidedReviewMappingStep
          aiMapping={aiMapping}
          aiMappingLoading={aiMappingLoading}
          aiMappingError={aiMappingError}
          sigHeaders={sigHeaders}
          sourceBackedMappings={sourceBackedMappings}
          constantMappings={constantMappings}
          fieldMappings={fieldMappings}
          isSavingMapping={isSavingMapping}
          onMappingChange={handleMappingChange}
          onSaveMapping={handleSaveMapping}
          onBack={() => setStep(1)}
        />
      )}

      {step === 3 && (
        <GuidedReviewValidationStep
          localPacket={localPacket}
          validationState={validationState}
          runtimeValidationState={runtimeValidationState}
          displayFieldResults={displayFieldResults}
          constantMappings={constantMappings}
          sigHeaders={sigHeaders}
          summary={summary}
          topIssues={topIssues}
          traceDetailSampleIndex={traceDetailSampleIndex}
          isValidatingRuntime={isValidatingRuntime}
          onValidateRuntime={handleValidateRuntime}
          onBack={() => setStep(2)}
          onContinue={() => setStep(4)}
          onSetTraceDetailSampleIndex={setTraceDetailSampleIndex}
        />
      )}

      {step === 4 && (
        <GuidedReviewDecisionStep
          postApprovalRun={postApprovalRun}
          isApproved={isApproved}
          validationState={validationState}
          isSubmitting={isSubmitting}
          onApproveActivate={handleApproveActivate}
          onReject={handleReject}
          onBack={() => setStep(3)}
          onClose={handleClose}
        />
      )}
    </Dialog>
  );
}

