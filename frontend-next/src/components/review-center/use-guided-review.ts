import { useCallback, useEffect, useMemo, useState } from "react";
import * as api from "@/lib/api/review-center";
import { getCurrentActor } from "@/lib/actor";
import { getRuntimeValidationState } from "@/lib/review-runtime";
import type { ReviewPacket, PostApprovalRun } from "@/types/review-center";
import styles from "./review-center.module.css";
import { usePostApprovalPolling } from "./use-post-approval-polling";
import type { FieldMappingItem, AiMappingData } from "./guided-review-mapping-step";
import type { ScopeClassificationInfo } from "./guided-review-scope-step";

function isGenericColumnLabel(value: unknown) {
  return /^column\s+\d+$/i.test(String(value || "").trim());
}

function resolveSourceFieldLabel(mapping: FieldMappingItem, sigHeaders: string[], fallbackIndex?: number) {
  const sourceColumn = Number(mapping?.column);
  const headerLabel = sourceColumn > 0 ? String(sigHeaders[sourceColumn - 1] || "").trim() : "";
  if (headerLabel) return headerLabel;

  const sourceField = String(mapping?.sourceField || "").trim();
  if (sourceField && !isGenericColumnLabel(sourceField)) return sourceField;

  if (sourceColumn > 0) return `Column ${sourceColumn}`;
  if (fallbackIndex != null) return `Column ${fallbackIndex + 1}`;
  return "Column";
}

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
  const [scopeClassification, setScopeClassification] = useState<ScopeClassificationInfo | null>(null);
  const [scopeLoading, setScopeLoading] = useState(false);
  const [scopeError, setScopeError] = useState("");

  const [aiMapping, setAiMapping] = useState<AiMappingData | null>(null);
  const [aiMappingLoading, setAiMappingLoading] = useState(false);
  const [aiMappingError, setAiMappingError] = useState("");
  const [fieldMappings, setFieldMappings] = useState<FieldMappingItem[]>([]);
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

  // Sync state when packet identity or status changes
  const packetId = packet?._id;
  const packetStatus = packet?.status;
  useEffect(() => {
    if (
      packet &&
      (packet._id !== localPacket?._id || packet.status !== localPacket?.status)
    ) {
      const timer = setTimeout(() => {
        setLocalPacket(packet);
        setStep(String(packet.status).toUpperCase() === "APPROVED" ? 4 : 1);
        setSelectedScope(packet.scopeRecommendation?.scopeType ?? packet.scopeType ?? "FULL_SNAPSHOT");
        setScopeClassification(null);
        setAiMapping(null);
        setFieldMappings([]);
        setPostApprovalRun(null);
      }, 0);
      return () => clearTimeout(timer);
    }
  }, [packet, localPacket?._id, localPacket?.status, packetId, packetStatus, setPostApprovalRun]);

  // Scope classification auto-load
  useEffect(() => {
    if (open && localPacket?._id && step === 1 && !scopeClassification && !scopeError) {
      let cancelled = false;
      const loadScope = async () => {
        setScopeLoading(true);
        setScopeError("");
        try {
          const res = (await api.classifyScope(localPacket._id)) as ScopeClassificationInfo & { suggestedScope?: string };
          if (cancelled) return;
          setScopeClassification(res);
          if (res.suggestedScope) {
            setSelectedScope(res.suggestedScope);
          }
        } catch (err: unknown) {
          if (cancelled) return;
          const message = err instanceof Error ? err.message : "Failed to load scope classification.";
          setScopeError(message);
        } finally {
          if (!cancelled) setScopeLoading(false);
        }
      };
      void loadScope();

      return () => {
        cancelled = true;
      };
    }
  }, [open, localPacket?._id, step, scopeClassification, scopeError]);

  // AI mapping auto-load
  useEffect(() => {
    const shouldLoad = open && localPacket?._id && !aiMapping && !aiMappingLoading &&
      (step === 2 || (step === 3 && fieldMappings.length === 0));
    if (shouldLoad) {
      const loadMapping = async () => {
        setAiMappingLoading(true);
        setAiMappingError("");
        try {
          const res = (await api.generateAiMapping(localPacket._id)) as { mapping?: { fieldMappings?: FieldMappingItem[] } & AiMappingData };
          setAiMapping(res.mapping || null);

          const rawDraftFieldMappings = res.mapping?.fieldMappings || [];
          const idMapping = rawDraftFieldMappings.find((m: FieldMappingItem) => m.path === "id");
          const draftFieldMappings = rawDraftFieldMappings.filter((m: FieldMappingItem) => {
            if (m.path !== "trace") return true;
            if (!idMapping) return true;
            return Number(m.column || 0) !== Number(idMapping.column || 0);
          }).map((m: FieldMappingItem, index: number) => ({
            ...m,
            sourceField: resolveSourceFieldLabel(m, localPacket?.structureSignature?.headers || [], index),
          }));
          setFieldMappings(draftFieldMappings);
        } catch (err: unknown) {
          const message = err instanceof Error ? err.message : "Failed to load AI mapping proposal.";
          setAiMappingError(message);
        } finally {
          setAiMappingLoading(false);
        }
      };
      void loadMapping();
    }
  }, [open, localPacket?._id, localPacket?.structureSignature?.headers, step, aiMapping, aiMappingLoading, fieldMappings.length]);

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
    } catch (err: unknown) {
      throw err;
    } finally {
      setIsSavingScope(false);
    }
  }, [localPacket, selectedScope]);

  const handleMappingChange = useCallback((sourceReference: number | string, newPath: string) => {
    setFieldMappings((prev) =>
      prev.map((mapping) => {
        const mappingReference = mapping.sourceField || mapping.column;
        if (String(mappingReference) === String(sourceReference)) {
          return {
            ...mapping,
            path: newPath,
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
        path: m.path || "",
        column: m.column !== null && m.column !== undefined && m.column !== "" ? Number(m.column) : null,
        type: m.type || "STRING",
        required: m.required ?? false,
        constant: m.constant || null,
        mapping: m.mapping || null,
        sourceField: resolveSourceFieldLabel(m, localPacket?.structureSignature?.headers || [], index),
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
    } catch (err: unknown) {
      throw err;
    } finally {
      setIsSavingMapping(false);
    }
  }, [localPacket, fieldMappings]);

  const handleValidateRuntime = useCallback(async () => {
    if (!localPacket) return;
    setIsValidatingRuntime(true);
    try {
      const response = (await api.validateRuntime(localPacket._id)) as { gate?: { message?: string } };
      const refreshed = await api.getReviewPacket(localPacket._id);
      setLocalPacket(refreshed.packet);
      return response.gate?.message || "Runtime validation completed.";
    } catch (err: unknown) {
      throw err;
    } finally {
      setIsValidatingRuntime(false);
    }
  }, [localPacket]);

  const handleApproveActivate = useCallback(async () => {
    if (!localPacket) return;
    setIsSubmitting(true);
    try {
      const optimisticRun: PostApprovalRun = {
        id: `optimistic-${localPacket._id}`,
        packetId: localPacket._id,
        partner: localPacket.partner,
        date: localPacket.reconciliationDate ?? "",
        status: "QUEUED",
        stage: "approval",
        message: "Approval accepted. Preparing post-approval processing...",
        sourceFileId: undefined,
        outputFileId: undefined,
        reconciliationCount: null,
        stats: {},
        errors: [],
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
      };
      setPostApprovalRun(optimisticRun);
      const response = (await api.approveActivate(localPacket._id, getCurrentActor(), selectedScope)) as { postApproveRun?: PostApprovalRun };
      if (response.postApproveRun) {
        setPostApprovalRun(response.postApproveRun);
      }
      startPolling(localPacket._id);
      onRefresh();
      return true;
    } catch (err: unknown) {
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
    } catch (err: unknown) {
      throw err;
    } finally {
      setIsSubmitting(false);
    }
  }, [localPacket, onRefresh, handleClose]);

  const retryScopeClassification = useCallback(() => {
    setScopeClassification(null);
    setScopeError("");
  }, []);

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
      (m) => {
        const hasSource = Boolean(m.sourceField) || (m.column !== null && m.column !== undefined && m.column !== "");
        return m.type !== "CONSTANT" && (!m.mapping || hasSource);
      }
    );
  }, [fieldMappings]);

  const constantMappings = useMemo(() => {
    return fieldMappings.filter(
      (m) => {
        const hasSource = Boolean(m.sourceField) || (m.column !== null && m.column !== undefined && m.column !== "");
        return m.type === "CONSTANT" || (Boolean(m.mapping) && !hasSource);
      }
    );
  }, [fieldMappings]);

  const constantFieldEntries = useMemo(() => {
    return constantMappings.map(m => ({
      canonicalField: m.path || "",
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
      if (ce.canonicalField && !existingPaths.has(ce.canonicalField)) {
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
