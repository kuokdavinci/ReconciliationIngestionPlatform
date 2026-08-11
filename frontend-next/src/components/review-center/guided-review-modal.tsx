/* eslint-disable @typescript-eslint/no-explicit-any */
"use client";

import { useState } from "react";
import { Dialog } from "@/components/ui/dialog";
import { useToast } from "@/components/ui/toast";
import type { ReviewPacket } from "@/types/review-center";
import dialogStyles from "@/components/ui/dialog.module.css";
import styles from "./review-center.module.css";
import { GuidedReviewScopeStep } from "./guided-review-scope-step";
import { GuidedReviewMappingStep } from "./guided-review-mapping-step";
import { GuidedReviewValidationStep } from "./guided-review-validation-step";
import { GuidedReviewDecisionStep } from "./guided-review-decision-step";
import { useGuidedReview } from "./use-guided-review";

const steps = ["Scope", "Mapping", "Validation", "Decision"];

interface Props {
  packet: ReviewPacket | null;
  open: boolean;
  onClose: () => void;
  onRefresh: () => void;
}

export function GuidedReviewModal({ packet, open, onClose, onRefresh }: Props) {
  const { showToast } = useToast();
  const [traceDetailSampleIndex, setTraceDetailSampleIndex] = useState<number | null>(null);

  const {
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

    handleClose,
    handleContinueFromScope,
    handleMappingChange,
    handleSaveMapping,
    handleValidateRuntime,
    handleApproveActivate,
    handleReject,
    retryScopeClassification,
  } = useGuidedReview({ packet, open, onRefresh, onClose });

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
          onContinue={async () => {
            try {
              await handleContinueFromScope();
            } catch (err: any) {
              showToast(err.message || "Failed to save file scope.", "error");
            }
          }}
          onCancel={handleClose}
          onRetry={retryScopeClassification}
        />
      )}

      {step === 2 && (
        <GuidedReviewMappingStep
          packet={localPacket}
          packetId={localPacket._id}
          aiMapping={aiMapping}
          aiMappingLoading={aiMappingLoading}
          aiMappingError={aiMappingError}
          sigHeaders={sigHeaders}
          sourceBackedMappings={sourceBackedMappings}
          constantMappings={constantMappings}
          fieldMappings={fieldMappings}
          isSavingMapping={isSavingMapping}
          onMappingChange={handleMappingChange}
          onSaveMapping={async () => {
            try {
              await handleSaveMapping();
              showToast("Draft mapping saved successfully.", "success");
            } catch (err: any) {
              showToast(err.message || "Failed to save draft mapping.", "error");
            }
          }}
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
          onValidateRuntime={async () => {
            try {
              const message = await handleValidateRuntime();
              showToast(message || "Runtime validation completed.", "success");
            } catch (err: any) {
              showToast(err.message || "Runtime validation failed.", "error");
            }
          }}
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
          onApproveActivate={async () => {
            try {
              await handleApproveActivate();
              showToast("Approved and activated. Reprocessing has started.", "success");
            } catch (err: any) {
              showToast(err.message || "Failed to approve review packet.", "error");
            }
          }}
          onReject={async () => {
            try {
              await handleReject();
              showToast("Review packet rejected.", "success");
            } catch (err: any) {
              showToast(err.message || "Failed to reject review packet.", "error");
            }
          }}
          onBack={() => setStep(3)}
          onClose={handleClose}
        />
      )}
    </Dialog>
  );
}
