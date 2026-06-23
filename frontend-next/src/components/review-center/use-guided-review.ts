/* eslint-disable @typescript-eslint/no-explicit-any */
import { useCallback, useEffect, useMemo, useState } from "react";
import * as api from "@/lib/api/review-center";
import { getCurrentActor } from "@/lib/actor";
import { getRuntimeValidationState } from "@/lib/review-runtime";
import type { ReviewPacket } from "@/types/review-center";
import styles from "./review-center.module.css";
import { usePostApprovalPolling } from "./use-post-approval-polling";

export function useGuidedReview({
  packet,
  open,
  onRefresh,
  onClose,
}: {
  packet: ReviewPacket | null;
  open: boolean;
  onRefresh: () => void;
  onClose: () => void;
}) {
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

  const isApproved = localPacket ? String(localPacket.status).toUpperCase() === "APPROVED" : false;

  const {
    run: postApprovalRun,
    setRun: setPostApprovalRun,
    startPolling,
    stopPolling,
  } = usePostApprovalPolling({
    packetId: localPacket?._id,
    enabled: isApproved,
    onCompleted: onRefresh,
  });

  const handleClose = useCallback(() => {
    stopPolling();
    setStep(1);
    setScopeClassification(null);
    setAiMapping(null);
    setFieldMappings([]);
    setPostApprovalRun(null);
    onClose();
  }, [stopPolling, setPostApprovalRun, onClose]);

  // Sync state if packet prop changes, but ONLY if we are not actively in the decision step or running a post-approval process
  useEffect(() => {
    if (packet && packet._id !== localPacket?._id) {
      setLocalPacket(packet);
      setStep(String(packet.status).toUpperCase() === "APPROVED" ? 4 : 1);
      setSelectedScope(packet.scopeRecommendation?.scopeType ?? packet.scopeType ?? "FULL_SNAPSHOT");
      setScopeClassification(null);
      setAiMapping(null);
      setFieldMappings([]);
      setPostApprovalRun(null);
    }
  }, [packet, localPacket?._id, setPostApprovalRun]);

  // Scope classification auto-load
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

  // AI mapping auto-load
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

  const handleContinueFromScope = useCallback(async () => {
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
      throw err;
    } finally {
      setIsSavingScope(false);
    }
  }, [localPacket, selectedScope]);

  const handleMappingChange = useCallback((sourceColumn: number, newPath: string) => {
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
  }, []);

  const handleSaveMapping = useCallback(async () => {
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
      setStep(3);
      return true;
    } catch (err: any) {
      throw err;
    } finally {
      setIsSavingMapping(false);
    }
  }, [localPacket, fieldMappings]);

  const handleValidateRuntime = useCallback(async () => {
    if (!localPacket) return;
    setIsValidatingRuntime(true);
    try {
      const response = (await api.validateRuntime(localPacket._id)) as any;
      const refreshed = await api.getReviewPacket(localPacket._id);
      setLocalPacket(refreshed.packet);
      return response.gate?.message || "Runtime validation completed.";
    } catch (err: any) {
      throw err;
    } finally {
      setIsValidatingRuntime(false);
    }
  }, [localPacket]);

  const handleApproveActivate = useCallback(async () => {
    if (!localPacket) return;
    setIsSubmitting(true);
    try {
      const response = (await api.approveActivate(localPacket._id, getCurrentActor(), selectedScope)) as any;
      if (response.postApproveRun) {
        setPostApprovalRun(response.postApproveRun as any);
      }
      startPolling(localPacket._id);
      onRefresh();
      return true;
    } catch (err: any) {
      throw err;
    } finally {
      setIsSubmitting(false);
    }
  }, [localPacket, selectedScope, startPolling, onRefresh, setPostApprovalRun]);

  const handleReject = useCallback(async () => {
    if (!localPacket) return;
    setIsSubmitting(true);
    try {
      await api.rejectPacket(localPacket._id, getCurrentActor());
      onRefresh();
      handleClose();
      return true;
    } catch (err: any) {
      throw err;
    } finally {
      setIsSubmitting(false);
    }
  }, [localPacket, onRefresh, handleClose]);

  const retryScopeClassification = useCallback(() => {
    if (!localPacket) return;
    void api.classifyScope(localPacket._id).then(res => {
      setScopeClassification(res);
    });
  }, [localPacket]);

  // Derived state
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
  }, [localPacket]);

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

  const displayFieldResults = useMemo(() => {
    const fieldResults = localPacket?.runtimeValidation?.fieldResults ?? [];
    const existingPaths = new Set(fieldResults.map(f => f.canonicalField));
    const merged = [...fieldResults];
    for (const ce of constantFieldEntries) {
      if (!existingPaths.has(ce.canonicalField)) {
        merged.push(ce);
      }
    }
    return merged;
  }, [localPacket?.runtimeValidation?.fieldResults, constantFieldEntries]);

  return {
    localPacket,
    selectedScope,
    setSelectedScope,
    step,
    setStep,

    scopeClassification,
    scopeLoading,
    scopeError,
    isSavingScope,

    aiMapping,
    aiMappingLoading,
    aiMappingError,
    fieldMappings,
    sourceBackedMappings,
    constantMappings,
    isSavingMapping,

    validationState,
    runtimeValidationState,
    displayFieldResults,
    summary,
    topIssues,
    sigHeaders,
    isValidatingRuntime,

    isSubmitting,
    postApprovalRun,
    setPostApprovalRun,

    handleClose,
    handleContinueFromScope,
    handleMappingChange,
    handleSaveMapping,
    handleValidateRuntime,
    handleApproveActivate,
    handleReject,
    retryScopeClassification,
  };
}
