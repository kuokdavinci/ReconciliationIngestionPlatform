/* eslint-disable @typescript-eslint/no-explicit-any */
"use client";

import { useMemo, useState, useEffect, useRef, useCallback } from "react";
import { Dialog } from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";
import * as api from "@/lib/api/review-center";
import {
  getRuntimeValidationState,
  getValidationSuggestion,
} from "@/lib/review-runtime";
import type { ReviewPacket, PostApprovalRun } from "@/types/review-center";
import dialogStyles from "@/components/ui/dialog.module.css";
import styles from "./review-center.module.css";

const steps = ["Scope", "Mapping", "Validation", "Decision"];

interface Props {
  packet: ReviewPacket | null;
  open: boolean;
  onClose: () => void;
  onRefresh: () => void;
}

export function GuidedReviewModal({ packet, open, onClose, onRefresh }: Props) {
  const { showToast } = useToast();
  
  // Modal step state
  const [step, setStep] = useState(packet && String(packet.status).toUpperCase() === "APPROVED" ? 4 : 1);
  const [isSubmitting, setIsSubmitting] = useState(false);
  
  // Local synchronized copy of the packet
  const [localPacket, setLocalPacket] = useState<ReviewPacket | null>(packet);

  // Step 1: Scope States
  const [selectedScope, setSelectedScope] = useState(packet?.scopeRecommendation?.scopeType ?? packet?.scopeType ?? "FULL_SNAPSHOT");
  const [isSavingScope, setIsSavingScope] = useState(false);
  const [scopeClassification, setScopeClassification] = useState<any>(null);
  const [scopeLoading, setScopeLoading] = useState(false);
  const [scopeError, setScopeError] = useState("");

  // Step 2: Mapping States
  const [aiMapping, setAiMapping] = useState<any>(null);
  const [aiMappingLoading, setAiMappingLoading] = useState(false);
  const [aiMappingError, setAiMappingError] = useState("");
  const [fieldMappings, setFieldMappings] = useState<any[]>([]);
  const [isSavingMapping, setIsSavingMapping] = useState(false);

  // Step 3: Validation States
  const [isValidatingRuntime, setIsValidatingRuntime] = useState(false);
  const [traceDetailSampleIndex, setTraceDetailSampleIndex] = useState<number | null>(null);

  // Step 4: Decision & Polling States
  const [postApprovalRun, setPostApprovalRun] = useState<PostApprovalRun | null>(null);
  const pollingIntervalRef = useRef<NodeJS.Timeout | null>(null);

  // Poll post-approve-run status
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
        // Run may not be created yet, ignore error and let it retry
      }
    };
    void tick();
    pollingIntervalRef.current = setInterval(() => { void tick(); }, 1500);
  }, [onRefresh, onClose, showToast]);

  // Fetch initial run state for already-approved packets (no polling, no toast)
  useEffect(() => {
    if (localPacket && String(localPacket.status).toUpperCase() === "APPROVED") {
      void api.getPostApproveRun(localPacket._id).then(res => {
        if (res.run) setPostApprovalRun(res.run as any);
      });
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

  // Fetch scope classification in Step 1
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

  // Fetch AI suggestion in Step 2 (or Step 3 if not yet loaded)
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

  // Step 1: Save scope
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

  // Step 2: Handle inline select mapping changes
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

  // Step 2: Save inline draft mapping
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

  // Step 3: Run runtime validation
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

  // Step 4: Approve & Activate
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
    } catch (err: any) {
      showToast(err.message || "Failed to approve review packet.", "error");
    } finally {
      setIsSubmitting(false);
    }
  };

  // Step 4: Reject packet
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

  // Derived variables for validations
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

  const scopeConfidence = Math.round((scopeClassification?.probabilities?.[selectedScope] ?? 0) * 100);
  const scopeBorderColor = scopeConfidence >= 85 ? "#10b981" : scopeConfidence >= 60 ? "#f59e0b" : "#ef4444";
  const scopeBgColor = scopeConfidence >= 85 ? "rgba(16, 185, 129, 0.1)" : scopeConfidence >= 60 ? "rgba(245, 158, 11, 0.1)" : "rgba(239, 68, 68, 0.1)";
  const scopeLabelColor = scopeConfidence >= 85 ? "#10b981" : scopeConfidence >= 60 ? "#f59e0b" : "#ef4444";

  const sigHeaders = localPacket?.structureSignature?.headers || [];
  const previewRows = localPacket?.runtimeValidation?.previewRows ?? [];
  const fieldResults = localPacket?.runtimeValidation?.fieldResults ?? [];
  const topIssues = localPacket?.runtimeValidation?.topIssues ?? [];

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
  const summary = localPacket?.runtimeValidation?.summary;

  const isApproved = localPacket ? String(localPacket.status).toUpperCase() === "APPROVED" : false;

  if (!localPacket) return null;

  return (
    <Dialog open={open} onClose={handleClose} title={`Guided Review — ${localPacket.fileName}`} panelClassName={dialogStyles.wide}>
      {/* Step Indicator rail */}
      <div className={styles.stepRail}>
        {steps.map((label, index) => {
          const current = index + 1;
          const isActive = current === step;
          const isDone = current < step;
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

      {/* Step 1: Scope Selection */}
      {step === 1 && (
        <div className={styles.modalSection}>
          <h4 className={styles.modalTitle}>Confirm file scope</h4>
          
          {scopeLoading && (
            <div className={styles.loadingBlock}>
              <div className={styles.loadingSpinner} />
              <div className={styles.loadingText}>
                <h3>Running LLM Scope Analysis</h3>
                <p className={styles.introText}>Analyzing file name hints, received record counts, and database status...</p>
              </div>
            </div>
          )}

          {scopeError && (
            <div className={styles.emptyBlock}>
              <h3 style={{ color: "var(--status-failed)" }}>LLM Scope Analysis Failed</h3>
              <p className={styles.introText}>{scopeError}</p>
              <Button style={{ marginTop: 16 }} onClick={() => void api.classifyScope(localPacket._id).then(setScopeClassification)}>Retry</Button>
            </div>
          )}

          {!scopeLoading && !scopeError && scopeClassification && (
            <>
              <div className={styles.metricGrid}>
                <div className={styles.metricCard}>
                  <div className={styles.metricLabel}>Internal DB Records</div>
                  <div className={styles.metricValue}>{scopeClassification.internalDbRecordCount}</div>
                  <p className={styles.introText} style={{ marginTop: 4 }}>Transactions stored in system for same day</p>
                </div>
                <div className={styles.metricCard}>
                  <div className={styles.metricLabel}>Received Records</div>
                  <div className={styles.metricValue}>{scopeClassification.receivedRecordCount}</div>
                  <p className={styles.introText} style={{ marginTop: 4 }}>Records read from the uploaded file</p>
                </div>
              </div>

              <div className={styles.scopeCard} style={{ borderColor: scopeBorderColor, backgroundColor: scopeBgColor }}>
                <div className={styles.scopeHeader}>
                  <div>
                    <div className={styles.scopeLabel} style={{ color: scopeLabelColor }}>
                      {selectedScope === scopeClassification?.suggestedScope ? "Recommended file scope" : "Selected file scope"}
                    </div>
                    <strong className={styles.scopeValue}>{selectedScope.replace(/_/g, " ")}</strong>
                  </div>
                  <Badge severity={scopeConfidence >= 85 ? "low" : scopeConfidence >= 60 ? "medium" : "critical"}>
                    {scopeConfidence}% confidence
                  </Badge>
                </div>
                <p className={styles.scopeReason} style={{ fontWeight: 600, color: "#fff", marginBottom: 12 }}>
                  {selectedScope === "FULL_SNAPSHOT" && "File covers the full day, so the safest action is to replace the existing day snapshot with the uploaded partner file."}
                  {selectedScope === "INCREMENTAL_APPEND" && "File looks like a delta feed, so new rows should be appended without wiping previously ingested data."}
                  {selectedScope === "REPLACEMENT" && "File appears to contain correction/update rows, so matching records should be updated instead of appended."}
                </p>
                <div className={styles.scopeReasonBlock}>
                  <strong className={styles.scopeReasonTitle}>Why this option was selected</strong>
                  <div className={styles.reasonItem}>{scopeClassification.reasoning}</div>
                </div>
              </div>

              <div className={styles.scopeOptionGrid}>
                {[
                  { value: "FULL_SNAPSHOT", label: "Full Snapshot", desc: "Overwrite the day snapshot with the uploaded file." },
                  { value: "INCREMENTAL_APPEND", label: "Incremental Append", desc: "Append new partner rows without wiping prior data." },
                  { value: "REPLACEMENT", label: "Replacement", desc: "Update matching rows when this file is a correction batch." }
                ].map((opt) => (
                  <button
                    key={opt.value}
                    type="button"
                    onClick={() => setSelectedScope(opt.value)}
                    className={`${styles.scopeOptionCard} ${selectedScope === opt.value ? styles.scopeOptionSelected : ""}`}
                  >
                    <strong className={styles.scopeOptionTitle}>{opt.label}</strong>
                    <span className={styles.scopeOptionText}>{opt.desc}</span>
                  </button>
                ))}
              </div>

              <div className={styles.actionRow} style={{ marginTop: 16 }}>
                <Button variant="secondary" onClick={handleClose}>Cancel</Button>
                <Button variant="primary" disabled={isSavingScope} onClick={() => { void handleContinueFromScope(); }}>
                  {isSavingScope ? "Saving..." : "Continue"}
                </Button>
              </div>
            </>
          )}
        </div>
      )}

      {/* Step 2: Editable Mapping Form */}
      {step === 2 && (
        <div className={styles.modalSection}>
          <div>
            <h4 className={styles.modalTitle}>Draft Mapping Review</h4>
            <p className={styles.introText}>Review the AI proposal and adjust the partner field mapping before runtime validation.</p>
          </div>

          {aiMappingLoading && (
            <div className={styles.loadingBlock}>
              <div className={styles.loadingSpinner} />
              <div className={styles.loadingText}>
                <h3>Generating Draft Mapping</h3>
                <p className={styles.introText}>Building partner-to-canonical field suggestions from the current sample rows...</p>
              </div>
            </div>
          )}

          {aiMappingError && (
            <div className={styles.emptyBlock}>
              <h3 style={{ color: "var(--status-failed)" }}>Draft Mapping Generation Failed</h3>
              <p className={styles.introText}>{aiMappingError}</p>
            </div>
          )}

          {!aiMappingLoading && !aiMappingError && aiMapping && (
            <>
              <div className={styles.metricGrid}>
                <div className={styles.metricCard}>
                  <div className={styles.metricLabel}>Partner Columns Available</div>
                  <div className={styles.metricValue}>{sigHeaders.length}</div>
                  <p className={styles.introText} style={{ marginTop: 4 }}>Columns detected in the incoming partner file</p>
                </div>
                <div className={styles.metricCard}>
                  <div className={styles.metricLabel}>Candidate Columns For Reconciliation</div>
                  <div className={styles.metricValue}>{sourceBackedMappings.length}</div>
                  <p className={styles.introText} style={{ marginTop: 4 }}>Columns currently selected from the partner file</p>
                </div>
              </div>

              <div className={styles.scopeCard} style={{ borderColor: "#10b981" }}>
                <div className={styles.scopeHeader}>
                  <div>
                    <div className={styles.scopeLabel} style={{ color: "#10b981" }}>Recommended mapping setup</div>
                    <strong className={styles.scopeValue}>{fieldMappings.filter(m => m.path).length} canonical fields mapped</strong>
                  </div>
                  <Badge severity="low">Ready to review</Badge>
                </div>
                <p className={styles.scopeReason} style={{ color: "#fff", marginBottom: 12 }}>
                  The current draft covers fields required for runtime processing. You can adjust the mappings below if needed.
                </p>
                {aiMapping.configHealth?.reasoning && (
                  <div className={styles.scopeReasonBlock}>
                    <strong className={styles.scopeReasonTitle}>Why this mapping is recommended</strong>
                    <div className={styles.reasonItem}>{aiMapping.configHealth.reasoning}</div>
                  </div>
                )}
              </div>

              {constantMappings.length > 0 && (
                <div className={styles.sectionCard}>
                  <h5 className={styles.sectionCardTitle}>Runtime constants and rule-based values</h5>
                  <div className={styles.constraintGrid}>
                    {constantMappings.map((m, idx) => (
                      <div key={idx} className={styles.constraintCard}>
                        <div className={styles.constraintLabel}>{m.path}</div>
                        <div className={styles.constraintValue}>{m.constant || "Rule mapping"}</div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              <div className={styles.sectionCard}>
                <h5 className={styles.sectionCardTitle}>AI Suggestion / Draft Mapping</h5>
                <table className={styles.fieldTable}>
                  <thead>
                    <tr>
                      <th>Partner Column</th>
                      <th>Populate Via</th>
                      <th>Canonical Field</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sourceBackedMappings.map((m, idx) => {
                      const sourceCol = Number(m.column);
                      const headerLabel = sourceCol > 0 && sigHeaders[sourceCol - 1] ? sigHeaders[sourceCol - 1] : (m.sourceField || `Column ${sourceCol}`);
                      const populateVia = m.type === "CONSTANT" ? "Constant" : sourceCol > 0 ? `Source column ${sourceCol}` : "Source column";
                      
                      return (
                        <tr key={idx}>
                          <td><code>{headerLabel}</code></td>
                          <td style={{ color: "var(--text-muted)" }}>{populateVia}</td>
                          <td>
                            <select
                              aria-label="Canonical field mapping"
                              value={m.path || ""}
                              onChange={(e) => handleMappingChange(sourceCol, e.target.value)}
                              style={{
                                width: "100%",
                                background: "rgba(0,0,0,0.3)",
                                border: "1px solid #444",
                                color: "#fff",
                                borderRadius: "4px",
                                padding: "4px",
                                fontSize: "12px"
                              }}
                            >
                              <option value="">unmapped</option>
                              <option value="id">partner_txn_id</option>
                              <option value="amount">amount</option>
                              <option value="currency">currency</option>
                              <option value="status">status</option>
                              <option value="transDate">transaction_time</option>
                            </select>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              <div className={styles.actionRow} style={{ marginTop: 16 }}>
                <Button variant="secondary" onClick={() => setStep(1)}>Back</Button>
                <div className={styles.actionGroup}>
                  <Button variant="secondary" onClick={() => { window.open("/mapping-studio", "_blank"); }}>
                    Open full Mapping Studio
                  </Button>
                  <Button variant="primary" disabled={isSavingMapping} onClick={() => { void handleSaveMapping(); }}>
                    {isSavingMapping ? "Saving..." : "Save draft mapping"}
                  </Button>
                </div>
              </div>
            </>
          )}
        </div>
      )}

      {/* Step 3: Runtime Validation Result */}
      {step === 3 && (
        <div className={styles.modalSection}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12, flexWrap: "wrap" }}>
            <div>
              <h4 className={styles.modalTitle}>Runtime Validation</h4>
              <p className={styles.introText}>Inspect the latest validation gate outcome before making a decision.</p>
            </div>
            <Button variant="primary" disabled={isValidatingRuntime} onClick={() => { void handleValidateRuntime(); }}>
              {isValidatingRuntime ? "Validating..." : validationState.hasValidation ? "Re-run runtime validation" : "Run runtime validation"}
            </Button>
          </div>

          <div className={`${styles.validationBanner} ${validationState.tone}`}>
            <div>
              <h3 className={styles.bannerTitle}>{validationState.title}</h3>
              <p className={styles.bannerText}>{validationState.text}</p>
            </div>
            <Badge severity={validationState.status === "PASSED" || validationState.status === "PASS" ? "low" : validationState.status === "FAILED" || validationState.status === "FAIL" ? "critical" : "medium"}>
              {validationState.status}
            </Badge>
          </div>

          {summary && (
            <div className={styles.metricPills}>
              <span className={styles.metricPill}>{summary.rowsChecked} rows checked</span>
              <span className={styles.metricPill}>{summary.mappedFields}/{summary.totalFields} fields mapped</span>
              <span className={styles.metricPill}>{summary.requiredFieldsPassed}/{summary.requiredFieldsTotal} required fields</span>
              <span className={styles.metricPill}>{summary.validRowsPercent}% valid</span>
              <span className={styles.metricPill}>{summary.errorRows} errors</span>
            </div>
          )}

          {/* Progress bar + freshness */}
          {runtimeValidationState?.runtimeGate && (
            <div className={styles.progressBarWrap}>
              <div className={styles.freshnessGrid}>
                <div>
                  <div className={styles.progressLabel}>
                    <span className={styles.progressTitle}>Runtime Coverage</span>
                    <span className={styles.progressRate} style={{ color: summary ? (summary.validRowsPercent >= 80 ? "#10B981" : summary.validRowsPercent >= 50 ? "#F59E0B" : "#EF4444") : undefined }}>
                      {summary ? `${Math.round(summary.validRowsPercent)}% pass rate` : ""}
                    </span>
                  </div>
                  {summary && (
                    <>
                      <div className={styles.progressBar}>
                        <div className={styles.progressSegmentGreen} style={{ width: `${Math.max(summary.validRowsPercent, 0)}%` }} />
                        {summary.errorRows > 0 && summary.validRowsPercent < 100 && (
                          <div className={styles.progressSegmentRed} style={{ width: `${Math.max(100 - summary.validRowsPercent, 0)}%` }} />
                        )}
                      </div>
                      <div className={styles.progressLegend}>
                        <span className={styles.progressLegendItem}>
                          <span className={styles.progressDot} style={{ background: "#10B981" }} />
                          <span><strong className={styles.progressLegendCount}>{summary.rowsChecked - summary.errorRows}</strong> success</span>
                        </span>
                        {summary.errorRows > 0 && (
                          <span className={styles.progressLegendItem}>
                            <span className={styles.progressDot} style={{ background: "#EF4444" }} />
                            <span><strong className={styles.progressLegendCount}>{summary.errorRows}</strong> failed</span>
                          </span>
                        )}
                        <span style={{ color: "var(--text-muted)" }}>
                          <strong className={styles.progressLegendCount}>{summary.rowsChecked}</strong> sampled
                        </span>
                      </div>
                    </>
                  )}
                </div>
                <div className={styles.progressFreshness}>
                  <div className={styles.progressTitle} style={{ marginBottom: 8 }}>Validation Freshness</div>
                  <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 10 }}>
                    <span className={`${styles.freshnessBadge} ${
                      runtimeValidationState.isStale ? styles.freshnessWarning
                      : runtimeValidationState.hasValidation ? styles.freshnessMatched
                      : styles.freshnessNeutral
                    }`}>
                      {runtimeValidationState.summaryLabel}
                    </span>
                    <span className={`${styles.freshnessBadge} ${styles.freshnessNeutral}`}>
                      Draft {runtimeValidationState.currentVersion || "-"}
                    </span>
                  </div>
                  <div className={styles.freshnessVersion}>
                    Validated on <code className={styles.freshnessVersionCode}>v{runtimeValidationState.validatedVersion || "-"}</code>
                  </div>
                </div>
              </div>
            </div>
          )}

          <section className={styles.sectionCard}>
            <h5 className={styles.sectionCardTitle}>Field mapping result</h5>
            <table className={styles.fieldTable}>
              <thead>
                <tr>
                  <th>Canonical field</th>
                  <th>Mapped from</th>
                  <th>Status</th>
                  <th>Issue</th>
                </tr>
              </thead>
              <tbody>
                {displayFieldResults.map((field) => {
                  const isConstant = constantMappings.some(m => m.path === field.canonicalField);
                  const colIdx = Number(field.sourceColumn);
                  const sourceLabel = isConstant
                    ? `Constant: ${field.sourceColumn}`
                    : (!isNaN(colIdx) && colIdx > 0 && sigHeaders[colIdx - 1])
                      ? sigHeaders[colIdx - 1]
                      : field.sourceColumn ?? "-";
                  return (
                    <tr key={field.canonicalField}>
                      <td>{field.canonicalField}</td>
                      <td>{sourceLabel}</td>
                      <td>
                        <Badge severity={field.status === "OK" ? "low" : field.status === "WARNING" ? "medium" : "critical"}>
                          {field.status}
                        </Badge>
                      </td>
                      <td>{field.issue ?? "-"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </section>

          {/* Trace gallery: before/after source → normalized */}
          {localPacket.runtimeValidation?.traceSamples && localPacket.runtimeValidation.traceSamples.length > 0 && (
            <section className={styles.sectionCard}>
              <h5 className={styles.sectionCardTitle}>Runtime Trace Review</h5>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center", marginBottom: 10 }}>
                <span style={{ fontSize: 12, fontWeight: 700, textTransform: "uppercase", color: "var(--text-muted)" }}>Sample Trace Gallery</span>
                <span className={`${styles.freshnessBadge} ${styles.freshnessNeutral}`}>
                  {localPacket.runtimeValidation.traceSamples.length} rows
                </span>
              </div>
              <div className={styles.traceGallery}>
                {localPacket.runtimeValidation.traceSamples.slice(0, 5).map((sample, idx) => {
                  const hasError = sample.fieldTraces.some(t => t.status === "error");
                  const hasWarning = sample.fieldTraces.some(t => t.status === "warning");
                  const tone = hasError ? "critical" : hasWarning ? "medium" : "low";
                  const label = hasError ? "Failed" : hasWarning ? "Warning" : "Passed";
                  const sourceFields = sample.fieldTraces.filter(t => t.sourceField || t.sourceValue != null);
                  const normalizedEntries = Object.entries(sample.normalizedData).filter(([, v]) => v != null && v !== "");

                  return (
                    <div key={sample.row} className={styles.traceCard}>
                      <div className={styles.traceCardHeader}>
                        <div className={styles.traceCardTitle}>
                          <strong className={styles.traceCardSampleName}>Sample Row {sample.row}</strong>
                          <Badge severity={tone as any}>{label}</Badge>
                        </div>
                        <button
                          className={styles.traceDetailButton}
                          onClick={() => setTraceDetailSampleIndex(idx)}
                          title="View field-level detail"
                          type="button"
                        >
                          🔍
                        </button>
                      </div>
                      <div className={styles.traceColumns}>
                        <div className={styles.traceColumn}>
                          <div className={styles.traceColumnTitle}>Before / Raw Source</div>
                          {sourceFields.length > 0 ? sourceFields.map((trace, ti) => (
                            <div key={ti} className={styles.traceRow}>
                              <span className={styles.traceRowKey}>{trace.sourceField || trace.path || "-"}</span>
                              <span className={styles.traceRowValue}>{trace.sourceValue ?? "-"}</span>
                            </div>
                          )) : <span style={{ color: "var(--text-muted)", fontSize: 11.5 }}>No source values</span>}
                        </div>
                        <div className={styles.traceColumn}>
                          <div className={styles.traceColumnTitle}>After / Normalized Output</div>
                          {normalizedEntries.length > 0 ? normalizedEntries.map(([key, value]) => (
                            <div key={key} className={styles.traceRow}>
                              <span className={styles.traceRowKey}>{key}</span>
                              <span className={styles.traceRowValue}>{value ?? "-"}</span>
                            </div>
                          )) : <span style={{ color: "var(--text-muted)", fontSize: 11.5 }}>No normalized output</span>}
                        </div>
                      </div>
                      {sample.buildErrors && sample.buildErrors.length > 0 && (
                        <div className={styles.traceBuildError}>
                          {sample.buildErrors.length} canonical build error{sample.buildErrors.length !== 1 ? "s" : ""}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </section>
          )}

          <section className={styles.sectionCard}>
            <h5 className={styles.sectionCardTitle}>Validation Issues</h5>
            <div className={styles.issuesList}>
              {topIssues.length > 0 ? (
                topIssues.map((issue) => (
                  <div key={`${issue.type}-${issue.message}`} className={styles.issueRow}>
                    <div>
                      <span className={styles.issueText}>{issue.message}</span>
                      <div style={{ fontSize: 10.5, color: "var(--text-muted)", marginTop: 4 }}>
                        {getValidationSuggestion(issue.type.split("_")[0], issue.message.split(":")[0])}
                      </div>
                    </div>
                    <span className={styles.issueCount}>{issue.affectedRows != null ? `${issue.affectedRows} rows` : issue.severity}</span>
                  </div>
                ))
              ) : (
                <div className={styles.footerNote}>No validation issues found in sampled rows.</div>
              )}
            </div>
          </section>

          {/* Trace Detail Modal Overlay */}
          {traceDetailSampleIndex !== null && localPacket.runtimeValidation?.traceSamples && (
            <div className={styles.traceDetailOverlay}>
              <div className={styles.traceDetailPanel} onClick={e => e.stopPropagation()}>
                {(() => {
                  const sample = localPacket.runtimeValidation!.traceSamples![traceDetailSampleIndex];
                  if (!sample) return null;
                  const sourceFields = sample.fieldTraces.filter(t => t.sourceField || t.sourceValue != null || t.path);
                  const normalizedEntries = Object.entries(sample.normalizedData).filter(([, v]) => v != null && v !== "");
                  return (
                    <>
                      <div className={styles.traceDetailHeader}>
                        <div>
                          <h3 className={styles.traceDetailTitle}>Runtime Trace Detail</h3>
                          <p className={styles.traceDetailSubtitle}>Sample {sample.row}</p>
                        </div>
                        <button className={styles.traceDetailClose} onClick={() => setTraceDetailSampleIndex(null)}>✕</button>
                      </div>
                      <div className={styles.traceDetailColumns}>
                        <div className={styles.traceDetailSection}>
                          <div className={styles.traceDetailSectionTitle}>Raw Source Snapshot</div>
                          {sourceFields.length > 0 ? sourceFields.map((trace, ti) => (
                            <div key={ti} className={styles.traceRow}>
                              <span className={styles.traceRowKey}>{trace.sourceField || trace.path || "-"}</span>
                              <span className={styles.traceRowValue}>{trace.sourceValue ?? "-"}</span>
                            </div>
                          )) : <span style={{ color: "var(--text-muted)", fontSize: 11.5 }}>No source values</span>}
                        </div>
                        <div className={styles.traceDetailSection}>
                          <div className={styles.traceDetailSectionTitle}>Normalized Output</div>
                          {normalizedEntries.length > 0 ? normalizedEntries.map(([key, value]) => (
                            <div key={key} className={styles.traceRow}>
                              <span className={styles.traceRowKey}>{key}</span>
                              <span className={styles.traceRowValue}>{value ?? "-"}</span>
                            </div>
                          )) : <span style={{ color: "var(--text-muted)", fontSize: 11.5 }}>No normalized output</span>}
                        </div>
                      </div>
                      <div style={{ marginTop: 12 }}>
                        <div className={styles.traceDetailSectionTitle}>Field-Level Trace</div>
                        <div style={{ overflowX: "auto" }}>
                          <table className={styles.traceTable}>
                            <thead>
                              <tr>
                                <th>Raw Partner Field</th>
                                <th>Raw Partner Value</th>
                                <th>Target Internal Field</th>
                                <th>Transform</th>
                                <th>Final Normalized Value</th>
                                <th>Validation Status</th>
                                <th>Failure Reason</th>
                              </tr>
                            </thead>
                            <tbody>
                              {sample.fieldTraces.map((trace, ti) => (
                                <tr key={ti}>
                                  <td style={{ fontFamily: "var(--font-mono)" }}>{trace.sourceField || (trace.column != null ? `Column ${trace.column}` : trace.type === "CONSTANT" ? "Constant" : "-")}</td>
                                  <td style={{ fontFamily: "var(--font-mono)" }}>{trace.sourceValue ?? "-"}</td>
                                  <td style={{ fontFamily: "var(--font-mono)" }}>{trace.path || "-"}</td>
                                  <td>{trace.type || "-"}</td>
                                  <td style={{ fontFamily: "var(--font-mono)" }}>{trace.outputValue ?? "-"}</td>
                                  <td style={{ color: trace.status === "error" ? "#ef4444" : trace.status === "warning" ? "#f59e0b" : "#10B981", textTransform: "capitalize" }}>{trace.status}</td>
                                  <td style={{ color: "var(--text-muted)" }}>{trace.errorMessage || trace.errorCode || "-"}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </div>
                      {sample.buildErrors && sample.buildErrors.length > 0 && (
                        <div className={styles.traceBuildErrorBlock}>
                          <div style={{ fontSize: 11, fontWeight: 700, textTransform: "uppercase", color: "#fca5a5", marginBottom: 6 }}>Canonical Build Errors</div>
                          {sample.buildErrors.map((err, ei) => (
                            <div key={ei} style={{ fontSize: 12, marginTop: 4 }}>
                              <strong>{err.field || "-"}</strong> · {err.errorCode} · {err.reason}
                            </div>
                          ))}
                        </div>
                      )}
                    </>
                  );
                })()}
              </div>
            </div>
          )}

          <div className={styles.actionRow} style={{ marginTop: 16 }}>
            <Button variant="secondary" onClick={() => setStep(2)}>Back</Button>
            <Button variant="primary" disabled={!validationState.canProceed} onClick={() => setStep(4)}>
              Continue
            </Button>
          </div>
        </div>
      )}

      {/* Step 4: Decision & Polling */}
      {step === 4 && (
        <div className={styles.modalSection}>
          <h4 className={styles.modalTitle}>Decision</h4>

          {/* If the background job hasn't started yet */}
          {!postApprovalRun && !isApproved && (
            <>
              <div className={styles.recommendPanel}>
                <strong className={styles.recommendLabel}>Decision summary</strong>
                <p className={styles.recommendText}>
                  {validationState.canProceed
                    ? "The latest draft mapping configuration is ready for approval. Approving will activate it, ingest the uploaded partner file, and run reconciliation."
                    : "This packet still has validation issues. Please return to validation and ensure runtime mapping passes before approving."}
                </p>
              </div>

              <div className={styles.actionRow} style={{ marginTop: 16 }}>
                <Button variant="secondary" onClick={() => setStep(3)}>Back</Button>
                <div className={styles.actionGroup}>
                  <Button variant="secondary" disabled={isSubmitting} onClick={() => { void handleReject(); }}>
                    Reject change
                  </Button>
                  <Button variant="primary" disabled={!validationState.canProceed || isSubmitting} onClick={() => { void handleApproveActivate(); }}>
                    {isSubmitting ? "Processing..." : "Approve & Activate"}
                  </Button>
                </div>
              </div>
            </>
          )}

          {/* Active / Completed Pipeline tracking */}
          {(postApprovalRun || isApproved) && (
            <div className={styles.approveProgress}>
              <div className={styles.recommendPanel} style={{ background: "rgba(255, 255, 255, 0.02)", borderColor: "rgba(255, 255, 255, 0.08)" }}>
                <div style={{ display: "flex", justifyContent: "space-between", flexWrap: "wrap", gap: 12 }}>
                  <div>
                    <strong className={styles.recommendLabel} style={{ color: "var(--text-muted)", textTransform: "uppercase" }}>
                      Pipeline Status
                    </strong>
                    <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 4 }}>
                      <Badge severity={postApprovalRun?.status === "COMPLETED" ? "low" : postApprovalRun?.status === "FAILED" ? "critical" : "medium"}>
                        {postApprovalRun?.status || "QUEUED"}
                      </Badge>
                      {postApprovalRun?.stage && (
                        <Badge severity="neutral">
                          {postApprovalRun.stage.replace(/_/g, " ").toUpperCase()}
                        </Badge>
                      )}
                    </div>
                  </div>
                  {postApprovalRun?.updatedAt && (
                    <span className={styles.footerNote} style={{ fontSize: "11px" }}>
                      Updated: {new Date(postApprovalRun.updatedAt).toLocaleTimeString()}
                    </span>
                  )}
                </div>
                <div style={{ marginTop: 12, fontSize: "13px", color: "#fff" }}>
                  {postApprovalRun?.message || "Post-approval background task has started."}
                </div>
              </div>

              <div className={styles.progressCard}>
                <div className={styles.progressHeader}>
                  <div>
                    <h5 className={styles.progressTitle}>Ingest Partner File</h5>
                    <p className={styles.progressCopy}>Importing partner transactions into database.</p>
                  </div>
                  {postApprovalRun?.stage === "approval" ? (
                    <Badge severity="neutral">Queued</Badge>
                  ) : postApprovalRun?.stage === "ingestion" && postApprovalRun?.status !== "COMPLETED" && postApprovalRun?.status !== "FAILED" ? (
                    <div className={styles.spinner} />
                  ) : postApprovalRun?.status === "FAILED" && postApprovalRun?.stage === "ingestion" ? (
                    <Badge severity="critical">Failed</Badge>
                  ) : (
                    <Badge severity="low">Done</Badge>
                  )}
                </div>
              </div>

              <div className={styles.progressCard}>
                <div className={styles.progressHeader}>
                  <div>
                    <h5 className={styles.progressTitle}>Run Reconciliation</h5>
                    <p className={styles.progressCopy}>Computing discrepancies and matching transactions.</p>
                  </div>
                  {postApprovalRun?.status === "COMPLETED" ? (
                    <Badge severity="low">Done</Badge>
                  ) : postApprovalRun?.status === "FAILED" && postApprovalRun?.stage === "reconciliation" ? (
                    <Badge severity="critical">Failed</Badge>
                  ) : postApprovalRun?.stage === "reconciliation" ? (
                    <div className={styles.spinner} />
                  ) : (
                    <Badge severity="neutral">Queued</Badge>
                  )}
                </div>
              </div>

              {postApprovalRun?.stats && Object.keys(postApprovalRun.stats).length > 0 && (
                <div className={styles.sectionCard}>
                  <h5 className={styles.sectionCardTitle}>Processed Row Counts</h5>
                  <div className={styles.metricGrid} style={{ gridTemplateColumns: "repeat(3, 1fr)" }}>
                    <div className={styles.metricCard}>
                      <div className={styles.metricLabel} style={{ fontSize: "10px" }}>Total Rows</div>
                      <div className={styles.metricValue} style={{ fontSize: "20px" }}>{postApprovalRun.stats.totalRows ?? 0}</div>
                    </div>
                    <div className={styles.metricCard}>
                      <div className={styles.metricLabel} style={{ fontSize: "10px" }}>Success Rows</div>
                      <div className={styles.metricValue} style={{ fontSize: "20px", color: "#10b981" }}>{postApprovalRun.stats.successRows ?? 0}</div>
                    </div>
                    <div className={styles.metricCard}>
                      <div className={styles.metricLabel} style={{ fontSize: "10px" }}>Failed Rows</div>
                      <div className={styles.metricValue} style={{ fontSize: "20px", color: "#ef4444" }}>{postApprovalRun.stats.failedRows ?? 0}</div>
                    </div>
                  </div>
                </div>
              )}

              {postApprovalRun?.reconciliationCount !== undefined && postApprovalRun?.reconciliationCount !== null && (
                <div className={styles.footerNote} style={{ fontWeight: 600, textAlign: "center", color: "#fff" }}>
                  Reconciliation output: {postApprovalRun.reconciliationCount} results written.
                </div>
              )}

              <div className={styles.actionRow} style={{ justifyContent: "center", marginTop: 12 }}>
                {postApprovalRun?.status === "FAILED" ? (
                  <Button variant="secondary" onClick={() => setStep(3)}>Return to Step 3</Button>
                ) : (
                  <Button variant="secondary" onClick={handleClose}>
                    {postApprovalRun?.status === "COMPLETED" ? "Close" : "Close and Keep Processing in Background"}
                  </Button>
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </Dialog>
  );
}
