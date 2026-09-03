"use client";

import { useEffect, useMemo, useCallback, useState } from "react";
import { Topbar } from "@/components/layout/topbar";
import { PageSection } from "@/components/ui/page-section";
import { Panel } from "@/components/ui/panel";
import { SummaryStrip } from "@/components/reconciliation/summary-strip";
import { InsightGrid } from "@/components/reconciliation/insight-grid";
import { EvidenceTable } from "@/components/reconciliation/evidence-table";
import {
  SummaryStripSkeleton,
  InsightGridSkeleton,
  EvidenceTableSkeleton,
} from "@/components/reconciliation/reconciliation-skeleton";
import { BulkActionBar } from "@/components/reconciliation/bulk-action-bar";
import { EvidenceDetailDialog } from "@/components/reconciliation/evidence-detail-dialog";
import { InsightExplainDialog } from "@/components/reconciliation/insight-explain-dialog";
import { BatchReviewDialog } from "@/components/reconciliation/batch-review-dialog";
import { RunStatusPanel } from "@/components/reconciliation/run-status-panel";
import { useReconciliationStore } from "@/lib/state/reconciliation-store";
import { useToast } from "@/components/ui/toast";
import * as api from "@/lib/api/reconciliation";
import styles from "@/components/reconciliation/reconciliation.module.css";
import { ReviewRecord, ReconciliationRow } from "@/types/reconciliation";

const RECONCILIATION_PARTNERS = ["DEMO", "MOMO", "VNPAY", "ZALOPAY", "ACMEPAY", "VIETTELPAY"] as const;
const PARTNER = "DEMO";

function currentBusinessDate(): string {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Ho_Chi_Minh",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date());
  const values = Object.fromEntries(parts.map(({ type, value }) => [type, value]));
  return `${values.year}-${values.month}-${values.day}`;
}

const DATE = currentBusinessDate();

function reconciliationRowKey(row: ReconciliationRow): string {
  return row.partnerTxnId || row.internalTxnId || row.id;
}

function reviewableRowCount(rows: ReconciliationRow[]): number {
  return new Set(
      rows
      .filter((row) => !["MATCHED", "UNMAPPED_SKIPPED"].includes(row.reconciliationStatus))
      .map(reconciliationRowKey),
  ).size;
}

function reviewedRowCount(rows: ReconciliationRow[]): number {
  return new Set(
    rows
      .filter(
        (row) =>
          !["MATCHED", "UNMAPPED_SKIPPED"].includes(row.reconciliationStatus) &&
          (row.reviewState?.reviewed || row.reviewState?.resolvedStatus),
      )
      .map(reconciliationRowKey),
  ).size;
}

export default function ReconciliationPage() {
  const store = useReconciliationStore();
  const {
    partner,
    setPartner,
    date,
    setDate,
    reconStatus,
    setReconStatus,
    filters,
    updateFilters,
    pagination,
    setPagination,
    setRunStatus,
    setStats,
    results,
    setResults,
    insights,
    setInsights,
    selectedRows,
    selectedEvidenceRowId,
    setSelectedEvidenceRowId,
    explainItem,
    setExplainItem,
    clearSelection,
    setRowsSelection,
    toggleRow,
    setLoading,
  } = store;

  const { showToast } = useToast();

  const [tableType, setTableType] = useState("all");
  const [reviewFilter, setReviewFilter] = useState("all");
  const [batchOpen, setBatchOpen] = useState(false);
  const [batchType, setBatchType] = useState<"APPROVE" | "FLAG">("APPROVE");
  const [previewRows, setPreviewRows] = useState<ReconciliationRow[]>([]);

  const tableTypeOptions = [
    { value: "all", label: "All Records" },
    { value: "matched", label: "Matched" },
    { value: "unmatched", label: "Unmatched" },
    { value: "missing", label: "Missing Data" },
  ];

  const reviewFilterOptions = [
    { value: "all", label: "All Reviews" },
    { value: "pending", label: "Pending Review" },
    { value: "reviewed", label: "Reviewed" },
    { value: "resolved", label: "Resolved" },
  ];

  const statusOptions = ["", "MATCHED", "AMOUNT_MISMATCH", "MISSING_PARTNER", "MISSING_INTERNAL", "STATUS_MISMATCH", "MULTIPLE_MISMATCH", "AMBIGUOUS_KEY", "UNMAPPED_SKIPPED"];

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const handle404OrThrow = (defaultValue: any) => (err: any) => {
      const errMsg = String(err.message || "").toLowerCase();
      if (errMsg.includes("404") || errMsg.includes("not found")) {
        return defaultValue;
      } else {
        throw err;
      }
    };

  const handleSilentRefresh = useCallback(async () => {
    try {
      const [statsRes, resultsRes, reviewRecordsRes, previewResponses] = await Promise.all([
        api.getStats(partner, date).catch(handle404OrThrow(null)),
        api.getResults(partner, date, { limit: 100 }).catch(handle404OrThrow({ results: [] })),
        api.getReviewRecords(partner, date).catch(handle404OrThrow({ records: [] })),
        Promise.all([
          api.getResults(partner, date, { status: "AMOUNT_MISMATCH", limit: 25 }).catch(handle404OrThrow({ results: [] })),
          api.getResults(partner, date, { status: "STATUS_MISMATCH", limit: 25 }).catch(handle404OrThrow({ results: [] })),
          api.getResults(partner, date, { status: "MULTIPLE_MISMATCH", limit: 25 }).catch(handle404OrThrow({ results: [] })),
          api.getResults(partner, date, { status: "MISSING_PARTNER", limit: 25 }).catch(handle404OrThrow({ results: [] })),
          api.getResults(partner, date, { status: "MISSING_INTERNAL", limit: 25 }).catch(handle404OrThrow({ results: [] })),
        ]),
      ]);

      const rawResults = resultsRes.results ?? [];
      const reviewRecords = (reviewRecordsRes.records ?? []) as ReviewRecord[];
      const reviewMap = new Map(reviewRecords.map((r: ReviewRecord) => [r.recordKey, r]));
      
      const mappedResults = rawResults.map((r: ReconciliationRow) => {
        const id = r.partnerTxnId || r.internalTxnId || r.id;
        return {
          ...r,
          reviewState: reviewMap.get(id) || null,
        };
      });

      if (statsRes) {
        const totalReviewable =
          (statsRes.byStatus["AMOUNT_MISMATCH"] ?? 0) +
          (statsRes.byStatus["STATUS_MISMATCH"] ?? 0) +
          (statsRes.byStatus["MULTIPLE_MISMATCH"] ?? 0) +
          (statsRes.byStatus["AMBIGUOUS_KEY"] ?? 0) +
          (statsRes.byStatus["MISSING_PARTNER"] ?? 0) +
          (statsRes.byStatus["MISSING_INTERNAL"] ?? 0);
        const reviewedCount = reviewedRowCount(mappedResults);

        setStats({
          total: statsRes.total,
          matched: statsRes.byStatus["MATCHED"] ?? 0,
          unmatched: (statsRes.byStatus["AMOUNT_MISMATCH"] ?? 0) + (statsRes.byStatus["STATUS_MISMATCH"] ?? 0),
          missingPartner: statsRes.byStatus["MISSING_PARTNER"] ?? 0,
          missingInternal: statsRes.byStatus["MISSING_INTERNAL"] ?? 0,
          matchRate: statsRes.total > 0 ? Math.round((statsRes.byStatus["MATCHED"] ?? 0) / statsRes.total * 10000) / 100 : 0,
          totalReviewable,
          reviewedCount,
          timestampEvidence: statsRes.timestampEvidence,
        });
      } else {
        setStats(null);
      }

      setResults(mappedResults);

      const previewRaw = previewResponses.flatMap((res) => res.results ?? []);
      const previewUnique = Array.from(
        new Map(
          previewRaw.map((r: ReconciliationRow) => {
            const id = r.partnerTxnId || r.internalTxnId || r.id;
            return [id, { ...r, reviewState: reviewMap.get(id) || null }];
          })
        ).values()
      ).slice(0, 25) as ReconciliationRow[];
      setPreviewRows(previewUnique);
    } catch {
      showToast("Failed to refresh reconciliation data silently", "error");
    }
  }, [partner, date, setResults, setStats, showToast]);

  const handleLocalRowUpdate = useCallback((recordKey: string, updatedRecord: ReviewRecord) => {
    setResults((prevResults) => {
      const nextResults = prevResults.map((row: ReconciliationRow) => {
        const id = row.partnerTxnId || row.internalTxnId || row.id;
        if (id === recordKey) {
          return {
            ...row,
            reviewState: updatedRecord,
          };
        }
        return row;
      });

      // Recalculate stats locally
      setStats((prevStats) => {
        if (!prevStats) return null;
        const totalReviewable = reviewableRowCount(nextResults);
        const reviewedCount = reviewedRowCount(nextResults);
        return {
          ...prevStats,
          totalReviewable,
          reviewedCount,
        };
      });

      return nextResults;
    });
  }, [setResults, setStats]);

  const handleLocalRowBatchUpdate = useCallback((recordKeys: string[], updatedRecords: Record<string, ReviewRecord>) => {
    setResults((prevResults) => {
      const nextResults = prevResults.map((row: ReconciliationRow) => {
        const id = row.partnerTxnId || row.internalTxnId || row.id;
        if (recordKeys.includes(id) && updatedRecords[id]) {
          return {
            ...row,
            reviewState: updatedRecords[id],
          };
        }
        return row;
      });

      // Recalculate stats locally
      setStats((prevStats) => {
        if (!prevStats) return null;
        const totalReviewable = reviewableRowCount(nextResults);
        const reviewedCount = reviewedRowCount(nextResults);
        return {
          ...prevStats,
          totalReviewable,
          reviewedCount,
        };
      });

      return nextResults;
    });
  }, [setResults, setStats]);

  const loadInsights = useCallback(async (partner: string, date: string) => {
    try {
      const [anomalies, patterns, recommendations] = await Promise.all([
        api.getInsights(partner, date, "anomalies").catch((err) => {
          const errMsg = String(err.message || "").toLowerCase();
          if (errMsg.includes("404") || errMsg.includes("not found")) return [];
          throw err;
        }),
        api.getInsights(partner, date, "patterns").catch((err) => {
          const errMsg = String(err.message || "").toLowerCase();
          if (errMsg.includes("404") || errMsg.includes("not found")) return [];
          throw err;
        }),
        api.getInsights(partner, date, "recommendations").catch((err) => {
          const errMsg = String(err.message || "").toLowerCase();
          if (errMsg.includes("404") || errMsg.includes("not found")) return [];
          throw err;
        }),
      ]);
      setInsights({ anomalies, patterns, recommendations });
    } catch (err) {
      console.error("Failed to load insights:", err);
      setInsights({ anomalies: [], patterns: [], recommendations: [] });
    }
  }, [setInsights]);

  const loadPage = useCallback(async (partner: string, date: string) => {
    setLoading(true);
    setInsights({ anomalies: null, patterns: null, recommendations: null });
    void loadInsights(partner, date);

    try {
      const [runStatusRes, statsRes, resultsRes, reviewRecordsRes, previewResponses] = await Promise.all([
        api.getRunStatus(partner, date).catch(handle404OrThrow(null)),
        api.getStats(partner, date).catch(handle404OrThrow(null)),
        api.getResults(partner, date, { limit: 100 }).catch(handle404OrThrow({ results: [] })),
        api.getReviewRecords(partner, date).catch(handle404OrThrow({ records: [] })),
        Promise.all([
          api.getResults(partner, date, { status: "AMOUNT_MISMATCH", limit: 25 }).catch(handle404OrThrow({ results: [] })),
          api.getResults(partner, date, { status: "STATUS_MISMATCH", limit: 25 }).catch(handle404OrThrow({ results: [] })),
          api.getResults(partner, date, { status: "MULTIPLE_MISMATCH", limit: 25 }).catch(handle404OrThrow({ results: [] })),
          api.getResults(partner, date, { status: "MISSING_PARTNER", limit: 25 }).catch(handle404OrThrow({ results: [] })),
          api.getResults(partner, date, { status: "MISSING_INTERNAL", limit: 25 }).catch(handle404OrThrow({ results: [] })),
        ]),
      ]);

      if (runStatusRes && runStatusRes.run) {
        const statsObj = statsRes?.byStatus || {};
        setRunStatus({
          status: runStatusRes.run.status,
          startedAt: runStatusRes.run.startedAt as string ?? "",
          completedAt: runStatusRes.run.completedAt as string,
          totalRows: statsRes?.total ?? (runStatusRes.run.stats as Record<string, number>)?.["resultCount"] ?? 0,
          matchedRows: (statsObj["MATCHED"] ?? 0) + (statsObj["MATCHED_FAILED"] ?? 0) + (statsObj["MATCHED_REVERSED"] ?? 0),
          unmatchedRows: (statsObj["AMOUNT_MISMATCH"] ?? 0) + (statsObj["STATUS_MISMATCH"] ?? 0) + (statsObj["MULTIPLE_MISMATCH"] ?? 0),
          missingPartnerRows: statsObj["MISSING_PARTNER"] ?? 0,
          missingInternalRows: statsObj["MISSING_INTERNAL"] ?? 0,
        });
      } else {
        setRunStatus(null);
      }

      const rawResults = resultsRes.results ?? [];
      const reviewRecords = (reviewRecordsRes.records ?? []) as ReviewRecord[];
      const reviewMap = new Map(reviewRecords.map((r: ReviewRecord) => [r.recordKey, r]));
      
      const mappedResults = rawResults.map((r: ReconciliationRow) => {
        const id = r.partnerTxnId || r.internalTxnId || r.id;
        return {
          ...r,
          reviewState: reviewMap.get(id) || null,
        };
      });

      if (statsRes) {
        const totalReviewable =
          (statsRes.byStatus["AMOUNT_MISMATCH"] ?? 0) +
          (statsRes.byStatus["STATUS_MISMATCH"] ?? 0) +
          (statsRes.byStatus["MULTIPLE_MISMATCH"] ?? 0) +
          (statsRes.byStatus["AMBIGUOUS_KEY"] ?? 0) +
          (statsRes.byStatus["MISSING_PARTNER"] ?? 0) +
          (statsRes.byStatus["MISSING_INTERNAL"] ?? 0);
        const reviewedCount = reviewedRowCount(mappedResults);

        setStats({
          total: statsRes.total,
          matched: statsRes.byStatus["MATCHED"] ?? 0,
          unmatched: (statsRes.byStatus["AMOUNT_MISMATCH"] ?? 0) + (statsRes.byStatus["STATUS_MISMATCH"] ?? 0),
          missingPartner: statsRes.byStatus["MISSING_PARTNER"] ?? 0,
          missingInternal: statsRes.byStatus["MISSING_INTERNAL"] ?? 0,
          matchRate: statsRes.total > 0 ? Math.round((statsRes.byStatus["MATCHED"] ?? 0) / statsRes.total * 10000) / 100 : 0,
          totalReviewable,
          reviewedCount,
          timestampEvidence: statsRes.timestampEvidence,
        });
      } else {
        setStats(null);
      }

      setResults(mappedResults);
      const previewRaw = previewResponses.flatMap((res) => res.results ?? []);
      const previewUnique = Array.from(
        new Map(
          previewRaw.map((r: ReconciliationRow) => {
            const id = r.partnerTxnId || r.internalTxnId || r.id;
            return [id, { ...r, reviewState: reviewMap.get(id) || null }];
          })
        ).values()
      ).slice(0, 25) as ReconciliationRow[];
      setPreviewRows(previewUnique);
      setPagination({ limit: 25, offset: 0 });
    } catch {
      showToast("Failed to load reconciliation data from backend", "error");
      setRunStatus(null);
      setStats(null);
      setResults([]);
      setPreviewRows([]);
      setInsights({ anomalies: null, patterns: null, recommendations: null });
    } finally {
      setLoading(false);
    }
  }, [loadInsights, setInsights, setLoading, setPagination, setResults, setRunStatus, setStats, showToast]);

  const handleTriggerRun = useCallback(async () => {
    try {
      await api.runReconciliation({ partner, date });
      showToast(`Manual reconciliation queued for ${partner} on ${date}.`, "success");
      await loadPage(partner, date);
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Failed to start reconciliation.", "error");
    }
  }, [date, loadPage, partner, showToast]);

  useEffect(() => {
    let isSubscribed = true;
    if (!partner || !date) {
      setPartner(PARTNER);
      setDate(DATE);
      return;
    }
    const timer = setTimeout(() => {
      if (isSubscribed) {
        void loadPage(partner, date);
      }
    }, 0);
    return () => {
      isSubscribed = false;
      clearTimeout(timer);
    };
  }, [date, loadPage, partner, setDate, setPartner]);

  // Load results dynamically when filters change
  useEffect(() => {
    if (!partner || !date) return;

    const fetchResults = async () => {
      try {
        let statusesToFetch: string[] = [];
        if (reconStatus) {
          statusesToFetch = [reconStatus];
        } else if (tableType === "matched") {
          statusesToFetch = ["MATCHED", "MATCHED_FAILED", "MATCHED_REVERSED"];
        } else if (tableType === "unmatched") {
          statusesToFetch = ["AMOUNT_MISMATCH", "STATUS_MISMATCH", "MULTIPLE_MISMATCH"];
        } else if (tableType === "missing") {
          statusesToFetch = ["MISSING_PARTNER", "MISSING_INTERNAL"];
        }

        let rawResults: ReconciliationRow[] = [];

        if (statusesToFetch.length > 0) {
          const fetchPromises = statusesToFetch.map(status => 
            api.getResults(partner, date, { status, limit: 250 }).catch(() => ({ results: [] }))
          );
          const resultsResponses = await Promise.all(fetchPromises);
          rawResults = resultsResponses.flatMap(res => (res.results as ReconciliationRow[]) ?? []);
        } else {
          // Default / "All" tab: Load errors first, then matched records
          const [amtMismatchRes, statusMismatchRes, missingPartnerRes, missingInternalRes, matchedRes] = await Promise.all([
            api.getResults(partner, date, { status: "AMOUNT_MISMATCH", limit: 100 }).catch(() => ({ results: [] })),
            api.getResults(partner, date, { status: "STATUS_MISMATCH", limit: 100 }).catch(() => ({ results: [] })),
            api.getResults(partner, date, { status: "MISSING_PARTNER", limit: 100 }).catch(() => ({ results: [] })),
            api.getResults(partner, date, { status: "MISSING_INTERNAL", limit: 100 }).catch(() => ({ results: [] })),
            api.getResults(partner, date, { status: "MATCHED", limit: 250 }).catch(() => ({ results: [] })),
          ]);
          rawResults = [
            ...((amtMismatchRes.results as ReconciliationRow[]) ?? []),
            ...((statusMismatchRes.results as ReconciliationRow[]) ?? []),
            ...((missingPartnerRes.results as ReconciliationRow[]) ?? []),
            ...((missingInternalRes.results as ReconciliationRow[]) ?? []),
            ...((matchedRes.results as ReconciliationRow[]) ?? [])
          ];
        }
        
        const reviewRecordsRes = await api.getReviewRecords(partner, date).catch(() => ({ records: [] }));
        const reviewMap = new Map(((reviewRecordsRes.records as ReviewRecord[]) ?? []).map((r) => [r.recordKey, r]));
        
        const mappedResults = rawResults.map((r: ReconciliationRow) => {
          const id = r.partnerTxnId || r.internalTxnId || r.id;
          return {
            ...r,
            reviewState: reviewMap.get(id) || null,
          };
        });
        
        setResults(mappedResults);
      } catch (err) {
        console.error("Failed to load results dynamically:", err);
      }
    };

    void fetchResults();
  }, [partner, date, reconStatus, tableType, setResults]);

  // Polling for run status if processing
  useEffect(() => {
    if (!partner || !date || !store.runStatus) return;
    const activeStatuses = ["PROCESSING", "INGESTING", "RECONCILING", "RUNNING", "QUEUED"];
    if (!activeStatuses.includes(store.runStatus.status)) return;

    let intervalId: NodeJS.Timeout | null = null;

    const checkStatus = async () => {
      try {
        const runStatusRes = await api.getRunStatus(partner, date);
        if (runStatusRes && runStatusRes.run) {
          const currentStatus = runStatusRes.run.status;
          
          setRunStatus({
            status: currentStatus,
            startedAt: runStatusRes.run.startedAt as string ?? "",
            completedAt: runStatusRes.run.completedAt as string,
            totalRows: (runStatusRes.run.stats as Record<string, number>)?.["resultCount"] ?? 0,
            matchedRows: 0,
            unmatchedRows: 0,
            missingPartnerRows: 0,
            missingInternalRows: 0,
          });

          if (!activeStatuses.includes(currentStatus)) {
            if (intervalId) clearInterval(intervalId);
            void loadPage(partner, date);
          }
        }
      } catch (err) {
        console.error("Polling run status failed:", err);
      }
    };

    intervalId = setInterval(checkStatus, 3000);
    return () => {
      if (intervalId) clearInterval(intervalId);
    };
  }, [partner, date, store.runStatus, setRunStatus, loadPage]);

  const filteredRows = useMemo(() => {
    let items = results;
    if (tableType === "matched") {
      items = items.filter((r) => r.reconciliationStatus === "MATCHED");
    } else if (tableType === "unmatched") {
      items = items.filter((r) => ["AMOUNT_MISMATCH", "STATUS_MISMATCH", "MULTIPLE_MISMATCH", "AMBIGUOUS_KEY"].includes(r.reconciliationStatus));
    } else if (tableType === "missing") {
      items = items.filter((r) => r.reconciliationStatus === "MISSING_PARTNER" || r.reconciliationStatus === "MISSING_INTERNAL");
    }
    
    if (reviewFilter === "pending") {
      items = items.filter((r) => !["MATCHED", "UNMAPPED_SKIPPED"].includes(r.reconciliationStatus) && !r.reviewState?.resolvedStatus && !r.reviewState?.reviewed);
    } else if (reviewFilter === "reviewed") {
      items = items.filter((r) => !["MATCHED", "UNMAPPED_SKIPPED"].includes(r.reconciliationStatus) && r.reviewState?.reviewed && !r.reviewState?.resolvedStatus);
    } else if (reviewFilter === "resolved") {
      items = items.filter((r) => !["MATCHED", "UNMAPPED_SKIPPED"].includes(r.reconciliationStatus) && r.reviewState?.resolvedStatus);
    }

    if (reconStatus) {
      items = items.filter((r) => r.reconciliationStatus === reconStatus);
    }
    const f = filters;
    if (f.amountMin) {
      items = items.filter((r) => {
        const delta = r.delta ?? Math.abs(Number(r.internalAmount ?? 0) - Number(r.partnerAmount ?? 0));
        return delta >= Number(f.amountMin);
      });
    }
    if (f.amountMax) {
      items = items.filter((r) => {
        const delta = r.delta ?? Math.abs(Number(r.internalAmount ?? 0) - Number(r.partnerAmount ?? 0));
        return delta <= Number(f.amountMax);
      });
    }
    return items;
  }, [results, reconStatus, filters, tableType, reviewFilter]);

  const paginatedRows = useMemo(() => {
    const start = pagination.offset;
    return filteredRows.slice(start, start + pagination.limit);
  }, [filteredRows, pagination]);

  const handlePageChange = useCallback((offset: number) => {
    setPagination((prev: { limit: number; offset: number }) => ({ ...prev, offset }));
    clearSelection();
  }, [clearSelection, setPagination]);

  const handleLimitChange = useCallback((limit: number) => {
    setPagination({ limit, offset: 0 });
    clearSelection();
  }, [clearSelection, setPagination]);

  const selectedEvidenceRow = useMemo(() => {
    if (!selectedEvidenceRowId) return null;
    return results.find((r) => (r.partnerTxnId || r.internalTxnId || r.id) === selectedEvidenceRowId) ?? null;
  }, [selectedEvidenceRowId, results]);

  const selectedCount = Object.keys(selectedRows).length;


  return (
    <div>
      <Topbar
        title="Reconciliation"
        subtitle="Run status, risk signals, and evidence ledger for the selected settlement batch."
        actions={
          <div className={styles.toolbar}>
            <div className={styles.toolbarField}>
              <span className={styles.toolbarLabel}>Partner</span>
              <select
                value={partner}
                onChange={(e) => setPartner(e.target.value)}
                className={styles.toolbarControl}
              >
                {RECONCILIATION_PARTNERS.map((partner) => (
                  <option key={partner} value={partner}>{partner}</option>
                ))}
              </select>
            </div>
            <div className={styles.toolbarField}>
              <span className={styles.toolbarLabel}>Date</span>
              <input
                type="date"
                value={date}
                onChange={(e) => setDate(e.target.value)}
                className={styles.toolbarControl}
              />
            </div>
          </div>
        }
      />

      <PageSection>
        {store.loading ? (
          <>
            <SummaryStripSkeleton />
            <Panel
              header={
                <div style={{ width: "100%" }}>
                  <strong className={styles.panelTitle} style={{ marginBottom: 4 }}>Risk Signals</strong>
                  <p className={styles.panelDescription}>
                    Compact AI findings grouped into operational signals, trends, and next actions.
                  </p>
                </div>
              }
            >
              <InsightGridSkeleton />
            </Panel>
            <Panel
              header={
                <div style={{ width: "100%" }}>
                  <strong className={styles.panelTitle} style={{ marginBottom: 4 }}>Evidence Ledger</strong>
                  <p className={styles.panelDescription}>
                    Filter, paginate, and review large reconciliation result sets without changing the underlying bulk workflow.
                  </p>
                </div>
              }
            >
              <EvidenceTableSkeleton />
            </Panel>
          </>
        ) : (
          <>
            <SummaryStrip stats={store.stats} />
            <RunStatusPanel runStatus={store.runStatus} onTriggerRun={handleTriggerRun} />
            {previewRows.length > 0 && (
              <Panel
                header={
                  <div style={{ width: "100%" }}>
                    <strong className={styles.panelTitle} style={{ marginBottom: 4 }}>Discrepancy Preview</strong>
                    <p className={styles.panelDescription}>
                      First 25 mismatched or missing records, surfaced before the main ledger.
                    </p>
                  </div>
                }
              >
                <EvidenceTable
                  rows={previewRows}
                  total={previewRows.length}
                  limit={25}
                  offset={0}
                  hidePagination
                  selectedRowId={selectedEvidenceRowId}
                  selectedRows={selectedRows}
                  onPageChange={() => {}}
                  onLimitChange={() => {}}
                  onSelectRow={setSelectedEvidenceRowId}
                  onToggleCheck={toggleRow}
                  onSetVisibleSelection={setRowsSelection}
                  onSelectEvidence={setSelectedEvidenceRowId}
                />
              </Panel>
            )}
            <Panel
              header={
                <div style={{ width: "100%" }}>
                  <strong className={styles.panelTitle} style={{ marginBottom: 4 }}>Risk Signals</strong>
                  <p className={styles.panelDescription}>
                    Compact AI findings grouped into operational signals, trends, and next actions.
                  </p>
                </div>
              }
            >
              <div className={styles.insightColumns}>
                <InsightGrid title="Risk Signals" items={insights.anomalies} onExplain={setExplainItem} />
                <InsightGrid title="Trend Signals" items={insights.patterns} onExplain={setExplainItem} />
                <InsightGrid title="Operator Actions" items={insights.recommendations} onExplain={setExplainItem} />
              </div>
            </Panel>
            <Panel
              header={
                <div style={{ width: "100%" }}>
                  <strong className={styles.panelTitle} style={{ marginBottom: 4 }}>Evidence Ledger</strong>
                  <p className={styles.panelDescription}>
                    Filter, paginate, and review large reconciliation result sets without changing the underlying bulk workflow.
                  </p>
                </div>
              }
            >
              <div className={styles.ledgerFilters}>
                <div className={styles.toolbarField}>
                  <label className={styles.toolbarLabel}>Table</label>
                  <select
                    value={tableType}
                    onChange={(e) => { setTableType(e.target.value); setPagination((prev: { limit: number; offset: number }) => ({ ...prev, offset: 0 })); }}
                    className={styles.toolbarControl}
                  >
                    {tableTypeOptions.map((t) => (
                      <option key={t.value} value={t.value}>{t.label}</option>
                    ))}
                  </select>
                </div>
                <div className={styles.toolbarField}>
                  <label className={styles.toolbarLabel}>Status</label>
                  <select
                    value={reconStatus}
                    onChange={(e) => { setReconStatus(e.target.value); setPagination((prev: { limit: number; offset: number }) => ({ ...prev, offset: 0 })); }}
                    className={styles.toolbarControl}
                  >
                    {statusOptions.map((s) => (
                      <option key={s} value={s}>{s || "All Statuses"}</option>
                    ))}
                  </select>
                </div>
                <div className={styles.toolbarField}>
                  <label className={styles.toolbarLabel}>Review</label>
                  <select
                    value={reviewFilter}
                    onChange={(e) => { setReviewFilter(e.target.value); setPagination((prev: { limit: number; offset: number }) => ({ ...prev, offset: 0 })); }}
                    className={styles.toolbarControl}
                  >
                    {reviewFilterOptions.map((r) => (
                      <option key={r.value} value={r.value}>{r.label}</option>
                    ))}
                  </select>
                </div>
                <div className={styles.toolbarField}>
                  <label className={styles.toolbarLabel}>Delta Min</label>
                  <input
                    type="number"
                    placeholder="Min amount"
                    value={filters.amountMin}
                    onChange={(e) => updateFilters({ amountMin: e.target.value })}
                    className={styles.toolbarControl}
                  />
                </div>
                <div className={styles.toolbarField}>
                  <label className={styles.toolbarLabel}>Delta Max</label>
                  <input
                    type="number"
                    placeholder="Max amount"
                    value={filters.amountMax}
                    onChange={(e) => updateFilters({ amountMax: e.target.value })}
                    className={styles.toolbarControl}
                  />
                </div>
              </div>

              <EvidenceTable
                rows={paginatedRows}
                total={filteredRows.length}
                limit={pagination.limit}
                offset={pagination.offset}
                selectedRowId={selectedEvidenceRowId}
                selectedRows={selectedRows}
                onPageChange={handlePageChange}
                onLimitChange={handleLimitChange}
                onSelectRow={setSelectedEvidenceRowId}
                onToggleCheck={toggleRow}
                onSetVisibleSelection={(rows, selected) => setRowsSelection(rows, selected)}
                onSelectEvidence={setSelectedEvidenceRowId}
              />
            </Panel>
          </>
        )}
      </PageSection>

      <BulkActionBar
        selectedCount={selectedCount}
        onApprove={() => { setBatchType("APPROVE"); setBatchOpen(true); }}
        onFlag={() => { setBatchType("FLAG"); setBatchOpen(true); }}
        onClear={clearSelection}
      />

      <EvidenceDetailDialog
        row={selectedEvidenceRow}
        partner={partner}
        date={date}
        open={!!selectedEvidenceRowId}
        onClose={() => setSelectedEvidenceRowId(null)}
        onRefresh={handleSilentRefresh}
        onLocalUpdate={handleLocalRowUpdate}
      />

      <InsightExplainDialog
        item={explainItem}
        open={!!explainItem}
        onClose={() => setExplainItem(null)}
      />

      <BatchReviewDialog
        selectedIds={Object.keys(selectedRows)}
        partner={partner}
        date={date}
        open={batchOpen}
        onClose={() => setBatchOpen(false)}
        onRefresh={() => {
          clearSelection();
          void handleSilentRefresh();
        }}
        onLocalBatchUpdate={handleLocalRowBatchUpdate}
        actionType={batchType}
      />
    </div>
  );
}
