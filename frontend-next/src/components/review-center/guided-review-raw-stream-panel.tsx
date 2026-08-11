"use client";

import { useCallback, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { getReviewPacketRawRecords } from "@/lib/api/review-center";
import type { RawStreamPage, RawStreamRow, ReviewPacket } from "@/types/review-center";
import styles from "./review-center.module.css";

const SAMPLE_ROW_LIMIT = 5;

function rowValues(values: unknown): Record<string, unknown> {
  if (Array.isArray(values)) {
    return Object.fromEntries(values.map((value, index) => [`Column ${index + 1}`, value]));
  }
  if (values && typeof values === "object") {
    return values as Record<string, unknown>;
  }
  return { Value: values };
}

function displayValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function rowLabel(row: RawStreamRow): string {
  const streamIndex = row.streamRowIndex ?? row.rowIndex;
  return `#${streamIndex}${row.page == null ? "" : ` · page ${row.page}`}`;
}

interface Props {
  packet: ReviewPacket;
  packetId: string;
  highlightedColumns?: string[];
}

export function GuidedReviewRawStreamPanel({ packet, packetId, highlightedColumns = [] }: Props) {
  const [data, setData] = useState<RawStreamPage | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [expanded, setExpanded] = useState(false);

  const loadPage = useCallback(async (offset: number) => {
    setLoading(true);
    setError("");
    try {
      setData(await getReviewPacketRawRecords(packetId, offset, SAMPLE_ROW_LIMIT));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load the retained raw stream.");
    } finally {
      setLoading(false);
    }
  }, [packetId]);

  const columns = useMemo(() => {
    const names = new Set<string>();
    for (const row of data?.rows || []) {
      Object.keys(rowValues(row.values)).forEach((name) => names.add(name));
    }
    return Array.from(names);
  }, [data?.rows]);
  const fileScopedEvidence = Boolean(
    packet.sourceFilePath &&
    (!packet.rawStageKey || packet.rawStageKey.includes(":FILEDROP:") || packet.rawStageKey.includes(":SFTP:")),
  );
  const isHighlighted = (column: string) => highlightedColumns.includes(column);
  const toggleExpanded = () => {
    const nextExpanded = !expanded;
    setExpanded(nextExpanded);
    if (nextExpanded) void loadPage(0);
  };

  return (
    <section className={styles.rawStreamPanel} aria-label="Retained raw stream records">
      <div className={styles.sectionCardHeading}>
        <div>
          <h5 className={styles.sectionCardTitle}>Partner records for mapping</h5>
          <p className={styles.sectionCardCopy}>
            {!fileScopedEvidence
              ? "Records are read from the retained raw stream that approval will replay. The table is paginated so large streams stay outside the packet payload."
              : "Records are read from the source file attached to this file-level review packet. The table is paginated so large files stay outside the packet payload."}
          </p>
        </div>
        <button
          type="button"
          className={styles.iconButton}
          aria-label={expanded ? "Hide partner mapping evidence" : "Show partner mapping evidence"}
          aria-expanded={expanded}
          onClick={toggleExpanded}
        >
          <svg aria-hidden="true" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            {expanded ? (
              <>
                <path d="M2.5 12s3.5-6 9.5-6 9.5 6 9.5 6-3.5 6-9.5 6-9.5-6-9.5-6Z" />
                <circle cx="12" cy="12" r="2.5" />
              </>
            ) : (
              <>
                <path d="M3 3l18 18" />
                <path d="M10.6 5.2A10.4 10.4 0 0 1 12 5c6 0 9.5 7 9.5 7a17 17 0 0 1-3.1 3.8" />
                <path d="M6.2 6.3C3.9 8 2.5 12 2.5 12s3.5 7 9.5 7a9.8 9.8 0 0 0 3.4-.6" />
              </>
            )}
          </svg>
        </button>
        {data && expanded && (
          <div className={styles.rawStreamMeta}>
            <span>{data.totalRecords} records</span>
            <span>{Math.min(data.rows.length, SAMPLE_ROW_LIMIT)} sample rows</span>
          </div>
        )}
      </div>

      {expanded && loading && <div className={styles.loadingBlock}><div className={styles.loadingSpinner} /><div className={styles.loadingText}>Loading 5 partner sample rows…</div></div>}

      {expanded && !loading && error && (
        <div className={styles.emptyBlock}>
          <h3 style={{ color: "var(--status-failed)" }}>Raw stream unavailable</h3>
          <p className={styles.introText}>{error}</p>
          <Button variant="secondary" onClick={() => void loadPage(data?.offset || 0)}>Retry loading records</Button>
        </div>
      )}

      {expanded && !loading && !error && data && data.rows.length === 0 && (
        <div className={styles.emptyBlock}>No retained raw records are available for this stream.</div>
      )}

      {expanded && !loading && !error && data && data.rows.length > 0 && (
        <>
          <div className={styles.rawStreamTableWrap}>
            <table className={styles.rawStreamTable}>
              <thead>
                <tr>
                  <th>Stream row</th>
                  <th>Source unit</th>
                  {columns.map((column) => <th key={column} className={isHighlighted(column) ? styles.mappingColumnHighlight : ""}>{column}</th>)}
                </tr>
              </thead>
              <tbody>
                {data.rows.map((row) => {
                  const values = rowValues(row.values);
                  return (
                    <tr key={`${row.sourceUnitKey}-${row.rowIndex}`}>
                      <td className={styles.rawStreamCellMeta}>{rowLabel(row)}</td>
                      <td className={styles.rawStreamCellMeta}><code>{row.sourceUnitKey || "—"}</code></td>
                      {columns.map((column) => {
                        const rendered = displayValue(values[column]);
                        return <td key={column} className={`${styles.rawStreamCell} ${isHighlighted(column) ? styles.mappingColumnHighlight : ""}`} title={rendered}>{rendered}</td>;
                      })}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div className={styles.rawStreamPagination}>
            <span className={styles.introText}>
              Showing {Math.min(data.rows.length, SAMPLE_ROW_LIMIT)} sample rows of {data.totalRecords}
            </span>
          </div>
        </>
      )}
    </section>
  );
}
