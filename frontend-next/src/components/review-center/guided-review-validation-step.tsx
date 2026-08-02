"use client";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { getValidationSuggestion } from "@/lib/review-runtime-validation";
import type {
  ReviewPacket,
  RuntimeValidationFieldResult,
  RuntimeValidationTopIssue,
  RuntimeTraceSample,
  RuntimeFieldTrace,
} from "@/types/review-center";
import { RuntimeValidationState } from "@/lib/review-runtime";
import type { FieldMappingItem } from "./guided-review-mapping-step";
import styles from "./review-center.module.css";

import { ValidationStateSummary } from "./guided-review-decision-step";

interface ValidationSummaryStats {
  validRowsPercent?: number;
  validRows?: number;
  rowsChecked?: number;
  mappedFields?: number;
  totalFields?: number;
  requiredFieldsPassed?: number;
  requiredFieldsTotal?: number;
  errorRows?: number;
}

interface Props {
  localPacket: ReviewPacket | null;
  validationState: ValidationStateSummary;
  runtimeValidationState: RuntimeValidationState | null | undefined;
  displayFieldResults: RuntimeValidationFieldResult[];
  constantMappings: FieldMappingItem[];
  sigHeaders: string[];
  summary?: ValidationSummaryStats;
  topIssues: RuntimeValidationTopIssue[];
  traceDetailSampleIndex: number | null;
  isValidatingRuntime: boolean;
  onValidateRuntime: () => void;
  onBack: () => void;
  onContinue: () => void;
  onSetTraceDetailSampleIndex: (index: number | null) => void;
}

export function GuidedReviewValidationStep({
  localPacket,
  validationState,
  runtimeValidationState,
  displayFieldResults,
  constantMappings,
  sigHeaders,
  summary,
  topIssues,
  traceDetailSampleIndex,
  isValidatingRuntime,
  onValidateRuntime,
  onBack,
  onContinue,
  onSetTraceDetailSampleIndex,
}: Props) {
  if (!localPacket) return null;

  return (
    <div className={styles.modalSection}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12, flexWrap: "wrap" }}>
        <div>
          <h4 className={styles.modalTitle}>Runtime Validation</h4>
          <p className={styles.introText}>Inspect the latest validation gate outcome before making a decision.</p>
        </div>
        <Button variant="primary" disabled={isValidatingRuntime} onClick={onValidateRuntime}>
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
          <span className={styles.metricPill}>{summary.rowsChecked ?? 0} rows checked</span>
          <span className={styles.metricPill}>{summary.mappedFields ?? 0}/{summary.totalFields ?? 0} fields mapped</span>
          <span className={styles.metricPill}>{summary.requiredFieldsPassed ?? 0}/{summary.requiredFieldsTotal ?? 0} required fields</span>
          <span className={styles.metricPill}>{summary.validRowsPercent ?? 0}% valid</span>
          <span className={styles.metricPill}>{summary.errorRows ?? 0} errors</span>
        </div>
      )}

      {runtimeValidationState?.runtimeGate && (
        <div className={styles.progressBarWrap}>
          <div className={styles.freshnessGrid}>
            <div>
              <div className={styles.progressLabel}>
                <span className={styles.progressTitle}>Runtime Coverage</span>
                <span className={styles.progressRate} style={{ color: summary ? ((summary.validRowsPercent ?? 0) >= 80 ? "#10B981" : (summary.validRowsPercent ?? 0) >= 50 ? "#F59E0B" : "#EF4444") : undefined }}>
                  {summary ? `${Math.round(summary.validRowsPercent ?? 0)}% pass rate` : ""}
                </span>
              </div>
              {summary && (
                <>
                  <div className={styles.progressBar}>
                    <div className={styles.progressSegmentGreen} style={{ width: `${Math.max(summary.validRowsPercent ?? 0, 0)}%` }} />
                    {(summary.errorRows ?? 0) > 0 && (summary.validRowsPercent ?? 0) < 100 && (
                      <div className={styles.progressSegmentRed} style={{ width: `${Math.max(100 - (summary.validRowsPercent ?? 0), 0)}%` }} />
                    )}
                  </div>
                  <div className={styles.progressLegend}>
                    <span className={styles.progressLegendItem}>
                      <span className={styles.progressDot} style={{ background: "#10B981" }} />
                      <span><strong className={styles.progressLegendCount}>{(summary.rowsChecked ?? 0) - (summary.errorRows ?? 0)}</strong> success</span>
                    </span>
                    {(summary.errorRows ?? 0) > 0 && (
                      <span className={styles.progressLegendItem}>
                        <span className={styles.progressDot} style={{ background: "#EF4444" }} />
                        <span><strong className={styles.progressLegendCount}>{summary.errorRows ?? 0}</strong> failed</span>
                      </span>
                    )}
                    <span style={{ color: "var(--text-muted)" }}>
                      <strong className={styles.progressLegendCount}>{summary.rowsChecked ?? 0}</strong> sampled
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
            {displayFieldResults.map((field: RuntimeValidationFieldResult) => {
              const isConstant = constantMappings.some((m: FieldMappingItem) => m.path === field.canonicalField);
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
            {localPacket.runtimeValidation.traceSamples.slice(0, 5).map((sample: RuntimeTraceSample, idx: number) => {
              const hasError = sample.fieldTraces.some((t: RuntimeFieldTrace) => t.status === "error");
              const hasWarning = sample.fieldTraces.some((t: RuntimeFieldTrace) => t.status === "warning");
              const tone = hasError ? "critical" : hasWarning ? "medium" : "low";
              const label = hasError ? "Failed" : hasWarning ? "Warning" : "Passed";
              const sourceFields = sample.fieldTraces.filter((t: RuntimeFieldTrace) => t.sourceField || t.sourceValue != null);
              const normalizedEntries = Object.entries(sample.normalizedData).filter(([, v]) => v != null && v !== "");

              return (
                <div key={sample.row} className={styles.traceCard}>
                  <div className={styles.traceCardHeader}>
                    <div className={styles.traceCardTitle}>
                      <strong className={styles.traceCardSampleName}>Sample Row {sample.row}</strong>
                      <Badge severity={tone as "critical" | "medium" | "low"}>{label}</Badge>
                    </div>
                    <button
                      className={styles.traceDetailButton}
                      onClick={() => onSetTraceDetailSampleIndex(idx)}
                      title="View field-level detail"
                      type="button"
                    >
                      🔍
                    </button>
                  </div>
                  <div className={styles.traceColumns}>
                    <div className={styles.traceColumn}>
                      <div className={styles.traceColumnTitle}>Before / Raw Source</div>
                      {sourceFields.length > 0 ? sourceFields.map((trace: RuntimeFieldTrace, ti: number) => (
                        <div key={ti} className={styles.traceRow}>
                          <span className={styles.traceRowKey}>{trace.sourceField || trace.path || "-"}</span>
                          <span className={styles.traceRowValue}>{trace.sourceValue ?? "-"}</span>
                        </div>
                      )) : <span className={styles.traceEmpty}>No source values</span>}
                    </div>
                    <div className={styles.traceColumn}>
                      <div className={styles.traceColumnTitle}>After / Normalized Output</div>
                      {normalizedEntries.length > 0 ? normalizedEntries.map(([key, value]) => (
                        <div key={key} className={styles.traceRow}>
                          <span className={styles.traceRowKey}>{key}</span>
                          <span className={styles.traceRowValue}>{value != null ? String(value) : "-"}</span>
                        </div>
                      )) : <span className={styles.traceEmpty}>No normalized output</span>}
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
            topIssues.map((issue: RuntimeValidationTopIssue) => (
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

      {traceDetailSampleIndex !== null && localPacket.runtimeValidation?.traceSamples && (
        <div className={styles.traceDetailOverlay}>
          <div className={styles.traceDetailPanel} onClick={e => e.stopPropagation()}>
            {(() => {
              const sample = localPacket.runtimeValidation!.traceSamples![traceDetailSampleIndex];
              if (!sample) return null;
              const sourceFields = sample.fieldTraces.filter((t: RuntimeFieldTrace) => t.sourceField || t.sourceValue != null || t.path);
              const normalizedEntries = Object.entries(sample.normalizedData).filter(([, v]) => v != null && v !== "");
              return (
                <>
                  <div className={styles.traceDetailHeader}>
                    <div>
                      <h3 className={styles.traceDetailTitle}>Runtime Trace Detail</h3>
                      <p className={styles.traceDetailSubtitle}>Sample {sample.row}</p>
                    </div>
                    <button className={styles.traceDetailClose} onClick={() => onSetTraceDetailSampleIndex(null)}>✕</button>
                  </div>
                  <div className={styles.traceDetailColumns}>
                    <div className={styles.traceDetailSection}>
                      <div className={styles.traceDetailSectionTitle}>Raw Source Snapshot</div>
                      {sourceFields.length > 0 ? sourceFields.map((trace: RuntimeFieldTrace, ti: number) => (
                        <div key={ti} className={styles.traceRow}>
                          <span className={styles.traceRowKey}>{trace.sourceField || trace.path || "-"}</span>
                          <span className={styles.traceRowValue}>{trace.sourceValue ?? "-"}</span>
                        </div>
                      )) : <span className={styles.traceEmpty}>No source values</span>}
                    </div>
                    <div className={styles.traceDetailSection}>
                      <div className={styles.traceDetailSectionTitle}>Normalized Output</div>
                      {normalizedEntries.length > 0 ? normalizedEntries.map(([key, value]) => (
                        <div key={key} className={styles.traceRow}>
                          <span className={styles.traceRowKey}>{key}</span>
                          <span className={styles.traceRowValue}>{value != null ? String(value) : "-"}</span>
                        </div>
                      )) : <span className={styles.traceEmpty}>No normalized output</span>}
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
                          {sample.fieldTraces.map((trace: RuntimeFieldTrace, ti: number) => (
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
                      {sample.buildErrors.map((err: { field?: string; errorCode: string; reason: string }, ei: number) => (
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
        <Button variant="secondary" onClick={onBack}>Back</Button>
        <Button variant="primary" disabled={!validationState.canProceed} onClick={onContinue}>
          Continue
        </Button>
      </div>
    </div>
  );
}
