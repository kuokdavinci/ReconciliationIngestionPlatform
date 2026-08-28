"use client";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type {
  QuarantineIssueType,
  QuarantineRecord,
  QuarantineReprocessMode,
  QuarantineSampleField,
} from "@/types/quarantine";
import {
  badgeSeverity,
  canResolve,
  displaySampleValue,
  duplicateStatusLabel,
  formatDate,
  humanizeFieldName,
  isOverdue,
  issueTypeFor,
  ISSUE_TYPE_LABELS,
  issueTypeSeverity,
  resolutionPrompt,
  reviewInstruction,
  sampleEntries,
  timestampEntry,
  outcomeLabel,
} from "./quarantine-presenters";
import styles from "./review-center.module.css";

export type ActionKind = "CLAIM" | "REPROCESS" | "ACCEPT_EXISTING" | "REJECT" | "ESCALATE" | "RESUME";

function actionTitle(kind: ActionKind): string {
  if (kind === "CLAIM") return "Claim";
  if (kind === "ACCEPT_EXISTING") return "Accept existing";
  if (kind === "REPROCESS") return "Reprocess";
  if (kind === "RESUME") return "Resume source unit";
  return kind.charAt(0) + kind.slice(1).toLowerCase();
}

export function QuarantineActionForm({
  actionKind,
  busy,
  actionError,
  reason,
  correctedRow,
  reprocessMode,
  onReasonChange,
  onCorrectedRowChange,
  onReprocessModeChange,
  onCancel,
  onSubmit,
}: {
  actionKind: ActionKind;
  busy: boolean;
  actionError: string | null;
  reason: string;
  correctedRow: string;
  reprocessMode: QuarantineReprocessMode;
  onReasonChange: (value: string) => void;
  onCorrectedRowChange: (value: string) => void;
  onReprocessModeChange: (value: QuarantineReprocessMode) => void;
  onCancel: () => void;
  onSubmit: () => void;
}) {
  const title = actionTitle(actionKind);
  return (
    <section className={`${styles.sectionCard} ${styles.quarantineActionForm}`} aria-labelledby="quarantine-action-details">
      <div className={styles.quarantineSectionHeading}>
        <div>
          <h3 id="quarantine-action-details" className={styles.quarantineSectionTitle}>{title}</h3>
          <p className={styles.quarantineSectionCopy}>Confirm this action using the current row state. The detail stays open after completion.</p>
        </div>
      </div>
      {actionKind === "REPROCESS" ? (
        <>
          <label>Replay mode<select value={reprocessMode} onChange={(event) => onReprocessModeChange(event.target.value as QuarantineReprocessMode)}>
            <option value="REPLAY_SOURCE_ROW">Replay authoritative source row</option>
            <option value="CORRECTED_ROW">Submit corrected row</option>
          </select></label>
          {reprocessMode === "CORRECTED_ROW" ? <label>Corrected row JSON<textarea value={correctedRow} onChange={(event) => onCorrectedRowChange(event.target.value)} placeholder='{"id":"...","amount":"..."}' rows={6} /></label> : null}
        </>
      ) : null}
      {actionKind === "ACCEPT_EXISTING" ? <p className={styles.quarantineHint}>The existing record is verified internally; internal identifiers are never displayed here.</p> : null}
      {["REJECT", "ESCALATE", "RESUME"].includes(actionKind) ? <label>Reason<textarea value={reason} onChange={(event) => onReasonChange(event.target.value)} maxLength={500} rows={4} placeholder="Add a bounded operator reason" /></label> : null}
      {actionError ? <p className={styles.quarantineFormError} role="alert">{actionError}</p> : null}
      <div className={styles.quarantineDialogActions}>
        <Button type="button" variant="tertiary" disabled={busy} onClick={onCancel}>Cancel</Button>
        <Button type="button" variant="primary" disabled={busy} onClick={onSubmit}>{busy ? "Working..." : `Confirm ${title.toLowerCase()}`}</Button>
      </div>
    </section>
  );
}

export function SampleFieldTable({ entries }: { entries: QuarantineSampleField[] }) {
  return entries.length > 0 ? (
    <div className={styles.quarantineSampleTableWrap}>
      <table className={styles.quarantineSampleTable} aria-label="Sanitized sample row">
        <thead><tr><th scope="col">Source field</th><th scope="col">Canonical</th><th scope="col">Value</th><th scope="col">Review</th></tr></thead>
        <tbody>
          {entries.map((entry, index) => {
            const flagged = entry.state === "MISSING" || entry.state === "INVALID";
            return (
              <tr key={`${entry.sourceField}-${index}`} className={flagged ? styles.quarantineSampleErrorRow : undefined}>
                <th scope="row" className={styles.quarantineSampleField}>{humanizeFieldName(entry.sourceField)}</th>
                <td className={styles.quarantineSampleCanonical}>{entry.canonicalPath ? humanizeFieldName(entry.canonicalPath) : "—"}</td>
                <td className={styles.quarantineSampleValue}>{displaySampleValue(entry.value)}</td>
                <td>{flagged ? <span className={styles.quarantineSampleFlag}>{entry.state === "MISSING" ? "Missing" : "Check"}</span> : <span className={styles.quarantineSampleOkay}>{entry.state === "UNKNOWN" ? "Unknown" : "OK"}</span>}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  ) : (
    <p className={styles.quarantineEmptySample}>No sanitized sample evidence is available for this row.</p>
  );
}

export function QuarantineEvidencePanel({
  record,
  type,
  entries,
}: {
  record: QuarantineRecord;
  type: QuarantineIssueType;
  entries: QuarantineSampleField[];
}) {
  const mapping = record.evidence?.mapping;
  const duplicate = record.evidence?.duplicate;
  const sourceTimestamp = timestampEntry(entries);
  const isDuplicate = type === "DUPLICATE";
  const evidenceTitle = isDuplicate ? "Compare records" : "Offending row";
  const evidenceCopy = isDuplicate
    ? "Safe comparison fields only; internal identifiers and metadata are hidden."
    : `Sanitized source evidence for row ${record.rowNumber ?? "—"}.`;

  return (
    <section className={`${styles.sectionCard} ${styles.quarantineSampleCard}`} aria-labelledby="quarantine-offending-row">
      <div className={styles.quarantineSectionHeading}>
        <div>
          <h3 id="quarantine-offending-row" className={styles.quarantineSectionTitle}>{evidenceTitle}</h3>
          <p className={styles.quarantineSectionCopy}>{evidenceCopy}</p>
        </div>
        <span className={styles.quarantineSampleCount}>{isDuplicate ? "Safe fields" : `${entries.length} fields`}</span>
      </div>

      {isDuplicate ? (
        duplicate ? (
          <>
            <div className={styles.quarantineCompareStatus}>
              <Badge severity={duplicate.status === "CONFLICT" ? "critical" : "medium"} shape="pill">{duplicateStatusLabel(duplicate.status)}</Badge>
              <span>{duplicate.status === "EQUIVALENT" ? "All available safe fields match." : duplicate.status === "CONFLICT" ? "Review the differing fields before resolving." : "The existing transaction is not available for comparison."}</span>
            </div>
            {duplicate.status === "EQUIVALENT" ? (
              <p className={styles.quarantineEmptySample}>No differing fields. The incoming row is an exact duplicate of the persisted transaction.</p>
            ) : (
              <div className={styles.quarantineSampleTableWrap}>
                <table className={styles.quarantineSampleTable} aria-label="Incoming and existing transaction comparison">
                  <thead><tr><th scope="col">Field</th><th scope="col">Incoming</th><th scope="col">Existing</th><th scope="col">Result</th></tr></thead>
                  <tbody>
                    {(sourceTimestamp ? [
                      ...duplicate.fields,
                      { name: "timestamp", incoming: sourceTimestamp.value, existing: "Not shown", result: "UNAVAILABLE" as const },
                    ] : duplicate.fields).map((field) => {
                      const isDiff = field.result === "DIFF";
                      return (
                        <tr key={field.name} className={isDiff ? styles.quarantineSampleErrorRow : undefined}>
                          <th scope="row" className={styles.quarantineSampleField}>{humanizeFieldName(field.name)}</th>
                          <td className={styles.quarantineSampleValue}>{displaySampleValue(field.incoming)}</td>
                          <td className={styles.quarantineSampleValue}>{displaySampleValue(field.existing)}</td>
                          <td>
                            <span className={isDiff ? styles.quarantineSampleFlag : styles.quarantineSampleOkay}>
                              {field.result === "DIFF" ? "Diff" : field.result === "MATCH" ? "Match" : "Unavailable"}
                            </span>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </>
        ) : (
          <p className={styles.quarantineEmptySample}>No safe existing transaction comparison is available.</p>
        )
      ) : (
        type === "SCHEMA" || type === "REQUIRED_FIELD" ? (
          mapping?.requiredFields?.length ? (
            <div className={styles.quarantineMappingEvidence}>
              <div className={styles.quarantineSubsectionHeading}>
                <div>
                  <h4>Required field evidence</h4>
                  <p>Expected mapping and observed sample value in one view.</p>
                </div>
                <span>{mapping.configVersion ?? record.configVersion ?? "Config unavailable"}</span>
              </div>
              <div className={styles.quarantineSampleTableWrap}>
                <table className={styles.quarantineSampleTable} aria-label="Required field evidence">
                  <thead><tr><th scope="col">Canonical field</th><th scope="col">Source field</th><th scope="col">Type</th><th scope="col">Value</th><th scope="col">Review</th></tr></thead>
                  <tbody>
                    {mapping.requiredFields.map((field) => {
                      const sample = entries.find((entry) => entry.canonicalPath === field.canonicalPath || entry.sourceField === field.sourceField);
                      const state = field.state === "MISSING" || sample?.state === "MISSING"
                        ? "MISSING"
                        : sample?.state === "INVALID"
                          ? "INVALID"
                          : field.state;
                      const flagged = state === "MISSING" || state === "INVALID";
                      return (
                        <tr key={field.canonicalPath} className={flagged ? styles.quarantineSampleErrorRow : undefined}>
                          <th scope="row" className={styles.quarantineSampleField}>{humanizeFieldName(field.canonicalPath)}</th>
                          <td>{field.sourceField || (field.column == null ? "—" : `Column ${field.column}`)}</td>
                          <td>{field.type}</td>
                          <td className={styles.quarantineSampleValue}>{displaySampleValue(sample?.value)}</td>
                          <td><span className={flagged ? styles.quarantineSampleFlag : styles.quarantineSampleOkay}>{state}</span></td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              {mapping.observedColumns?.length ? <p className={styles.quarantineObservedColumns}><strong>Observed columns:</strong> {mapping.observedColumns.join(", ")}</p> : null}
            </div>
          ) : (
            <SampleFieldTable entries={entries} />
          )
        ) : (
          <SampleFieldTable entries={entries} />
        )
      )}
    </section>
  );
}

export function QuarantineDetail({ record }: { record: QuarantineRecord }) {
  const entries = sampleEntries(record);
  const type = issueTypeFor(record);
  const primaryError = record.errors?.[0];
  const primaryErrorReason = primaryError && typeof primaryError.reason === "string" ? primaryError.reason : null;
  return (
    <div className={styles.quarantineDetail} data-testid="quarantine-detail-panel">
      <div className={styles.summaryBadges}>
        <Badge severity={issueTypeSeverity(type)} shape="pill">{ISSUE_TYPE_LABELS[type]}</Badge>
        <Badge severity={badgeSeverity(record.status)} shape="pill">{outcomeLabel(record.status)}</Badge>
        <Badge severity={record.priority === "HIGH" ? "high" : "medium"} shape="pill">{record.priority} priority</Badge>
        {isOverdue(record) ? <Badge severity="critical" shape="pill">Overdue</Badge> : null}
      </div>
      <section className={`${styles.sectionCard} ${styles.quarantineDecisionCard}`} aria-labelledby="quarantine-validation-issue">
        <div className={styles.quarantineSectionHeading}>
          <div>
            <h3 id="quarantine-validation-issue" className={styles.quarantineSectionTitle}>Validation issue</h3>
            <p className={styles.quarantineSectionCopy}>{record.errorCodes[0] ?? "Quarantined row"}</p>
          </div>
        </div>
        <p className={styles.quarantineInstruction}>{reviewInstruction(record)}</p>
        {primaryErrorReason ? <p className={styles.quarantineErrorReason}>{primaryErrorReason}</p> : null}
      </section>

      <QuarantineEvidencePanel record={record} type={type} entries={entries} />

      <section className={styles.sectionCard} aria-labelledby="quarantine-source-context">
        <div className={styles.quarantineSectionHeading}>
          <h3 id="quarantine-source-context" className={styles.quarantineSectionTitle}>Source context</h3>
          <span className={styles.quarantineSampleCount}>Origin</span>
        </div>
        <div className={styles.quarantineDetailGrid}>
          <span><strong>Partner</strong>{record.partner}</span>
          <span><strong>Source file</strong>{record.sourceFileId}</span>
          <span><strong>Source unit</strong>{record.sourceUnitKey ?? "—"}</span>
          <span><strong>Row</strong>{record.rowNumber ?? "—"}</span>
          <span><strong>Phase</strong>{record.phase}</span>
          <span><strong>Severity</strong>{record.severity}</span>
          <span><strong>Config</strong>{record.configVersion ?? "—"}</span>
        </div>
      </section>

      <section className={styles.sectionCard} aria-labelledby="quarantine-review-status">
        <div className={styles.quarantineSectionHeading}>
          <h3 id="quarantine-review-status" className={styles.quarantineSectionTitle}>Review status</h3>
          <span className={styles.quarantineSampleCount}>Lifecycle</span>
        </div>
        <div className={styles.quarantineDetailGrid}>
          <span><strong>{record.claimedBy ? "Owner" : record.status === "REJECTED" && record.lastActionActor ? "Rejected by" : record.status === "RESOLVED" && record.lastActionActor ? "Resolved by" : "Owner"}</strong>{record.claimedBy ?? record.lastActionActor ?? "Unclaimed"}</span>
          <span><strong>Due</strong>{formatDate(record.reviewDueAt)}</span>
          <span><strong>Attempts</strong>{record.attemptCount}</span>
          <span><strong>Escalation</strong>{record.escalationLevel}/3</span>
        </div>
      </section>

      <details className={styles.quarantineHistoryDetails}>
        <summary>Resolution history <span>{record.resolutionHistory?.length ?? 0} events</span></summary>
        {record.resolutionHistory?.length ? <div className={styles.quarantineHistory}>{record.resolutionHistory.slice(0, 50).map((event) => <div key={event.eventId}><strong>{event.outcome ?? event.action}</strong><span>{event.actor} · {formatDate(event.timestamp)}</span><small>{event.reason}</small></div>)}</div> : <p className={styles.sectionCardCopy}>No operator actions recorded for this row.</p>}
      </details>
    </div>
  );
}

export function QuarantineActionBar({
  record,
  actor,
  onAction,
  onClose,
}: {
  record: QuarantineRecord;
  actor: string;
  onAction: (kind: ActionKind) => void;
  onClose: () => void;
}) {
  const resolving = canResolve(record, actor);
  const pending = record.status === "PENDING";
  const active = pending || record.status === "REPROCESSING";
  const sourceUnitReady = Boolean(record.sourceUnitKey && record.errorCodes.includes("SOURCE_UNIT_RECOVERY_REQUIRED"));

  return (
    <section className={styles.sectionCard} aria-labelledby="quarantine-resolution">
      <div className={styles.quarantineSectionHeading}>
        <div>
          <h3 id="quarantine-resolution" className={styles.quarantineSectionTitle}>Recommended action</h3>
          <p className={styles.quarantineSectionCopy}>{resolutionPrompt(record, resolving)}</p>
        </div>
      </div>
      {record.status === "REPROCESSING" && !resolving ? <p className={styles.quarantineOwnerWarning}>This row is owned by {record.claimedBy ?? "another operator"}. Switch the actor to continue.</p> : null}
      <div className={styles.quarantineDialogActions}>
        {pending ? <Button type="button" variant="primary" onClick={() => onAction("CLAIM")}>Claim</Button> : null}
        {active && record.escalationLevel < 3 ? <Button type="button" variant="tertiary" onClick={() => onAction("ESCALATE")}>Escalate</Button> : null}
        {resolving ? <>
          <Button type="button" variant="primary" onClick={() => onAction("REPROCESS")}>Reprocess</Button>
          <Button type="button" variant="secondary" onClick={() => onAction("ACCEPT_EXISTING")}>Accept existing</Button>
          <Button type="button" variant="tertiary" className={styles.quarantineRejectButton} onClick={() => onAction("REJECT")}>Reject</Button>
        </> : null}
        {sourceUnitReady ? <Button type="button" variant="secondary" onClick={() => onAction("RESUME")}>Resume source unit</Button> : null}
        <Button type="button" variant="tertiary" onClick={onClose}>Close</Button>
      </div>
    </section>
  );
}
