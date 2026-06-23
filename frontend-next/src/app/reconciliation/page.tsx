"use client";

import { useEffect, useMemo, useCallback, useState } from "react";
import { Topbar } from "@/components/layout/topbar";
import { PageSection } from "@/components/ui/page-section";
import { Panel } from "@/components/ui/panel";
import { RunStatusPanel } from "@/components/reconciliation/run-status-panel";
import { SummaryStrip } from "@/components/reconciliation/summary-strip";
import { InsightGrid } from "@/components/reconciliation/insight-grid";
import { EvidenceTable } from "@/components/reconciliation/evidence-table";
import {
  RunStatusPanelSkeleton,
  SummaryStripSkeleton,
  InsightGridSkeleton,
  EvidenceTableSkeleton,
} from "@/components/reconciliation/reconciliation-skeleton";
import { BulkActionBar } from "@/components/reconciliation/bulk-action-bar";
import { EvidenceDetailDialog } from "@/components/reconciliation/evidence-detail-dialog";
import { InsightExplainDialog } from "@/components/reconciliation/insight-explain-dialog";
import { BatchReviewDialog } from "@/components/reconciliation/batch-review-dialog";
import { useReconciliationStore } from "@/lib/state/reconciliation-store";
import { useToast } from "@/components/ui/toast";
import * as api from "@/lib/api/reconciliation";
import styles from "@/components/reconciliation/reconciliation.module.css";

const PARTNER = "MOMO";
const DATE = new Date().toISOString().slice(0, 10);

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

  const statusOptions = ["", "MATCHED", "AMOUNT_MISMATCH", "MISSING_PARTNER", "MISSING_INTERNAL", "STATUS_MISMATCH"];

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
      const [statsRes, resultsRes, reviewRecordsRes] = await Promise.all([
        api.getStats(partner, date).catch(handle404OrThrow(null)),
        api.getResults(partner, date, { limit: 100 }).catch(handle404OrThrow({ results: [] })),
        api.getReviewRecords(partner, date).catch(handle404OrThrow({ records: [] })),
      ]);

      const rawResults = resultsRes.results ?? [];
      const reviewMap = new Map((reviewRecordsRes.records ?? []).map((r: any) => [r.recordKey, r]));
      
      const mappedResults = rawResults.map((r: any) => {
        const id = r.partnerTxnId || r.internalTxnId || r.id;
        return {
          ...r,
          reviewState: reviewMap.get(id) || null,
        };
      });

      if (statsRes) {
        const totalReviewable = mappedResults.filter((r: any) => r.reconciliationStatus !== "MATCHED").length;
        const reviewedCount = mappedResults.filter((r: any) => 
          r.reconciliationStatus !== "MATCHED" && (r.reviewState?.reviewed || r.reviewState?.resolvedStatus)
        ).length;

        setStats({
          total: statsRes.total,
          matched: statsRes.byStatus["MATCHED"] ?? 0,
          unmatched: (statsRes.byStatus["AMOUNT_MISMATCH"] ?? 0) + (statsRes.byStatus["STATUS_MISMATCH"] ?? 0),
          missingPartner: statsRes.byStatus["MISSING_PARTNER"] ?? 0,
          missingInternal: statsRes.byStatus["MISSING_INTERNAL"] ?? 0,
          matchRate: statsRes.total > 0 ? Math.round((statsRes.byStatus["MATCHED"] ?? 0) / statsRes.total * 10000) / 100 : 0,
          totalReviewable,
          reviewedCount,
        });
      } else {
        setStats(null);
      }

      setResults(mappedResults);
    } catch {
      showToast("Failed to refresh reconciliation data silently", "error");
    }
  }, [partner, date, setResults, setStats, showToast]);

  const handleLocalRowUpdate = useCallback((recordKey: string, updatedRecord: any) => {
    setResults((prevResults) => {
      const nextResults = prevResults.map((row) => {
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
        const totalReviewable = nextResults.filter((r: any) => r.reconciliationStatus !== "MATCHED").length;
        const reviewedCount = nextResults.filter((r: any) => 
          r.reconciliationStatus !== "MATCHED" && (r.reviewState?.reviewed || r.reviewState?.resolvedStatus)
        ).length;
        return {
          ...prevStats,
          totalReviewable,
          reviewedCount,
        };
      });

      return nextResults;
    });
  }, [setResults, setStats]);

  const handleLocalRowBatchUpdate = useCallback((recordKeys: string[], updatedRecords: Record<string, any>) => {
    setResults((prevResults) => {
      const nextResults = prevResults.map((row) => {
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
        const totalReviewable = nextResults.filter((r: any) => r.reconciliationStatus !== "MATCHED").length;
        const reviewedCount = nextResults.filter((r: any) => 
          r.reconciliationStatus !== "MATCHED" && (r.reviewState?.reviewed || r.reviewState?.resolvedStatus)
        ).length;
        return {
          ...prevStats,
          totalReviewable,
          reviewedCount,
        };
      });

      return nextResults;
    });
  }, [setResults, setStats]);

  const loadPage = useCallback(async (partner: string, date: string) => {
    setLoading(true);

    try {
      const [runStatusRes, statsRes, resultsRes, reviewRecordsRes] = await Promise.all([
        api.getRunStatus(partner, date).catch(handle404OrThrow(null)),
        api.getStats(partner, date).catch(handle404OrThrow(null)),
        api.getResults(partner, date, { limit: 100 }).catch(handle404OrThrow({ results: [] })),
        api.getReviewRecords(partner, date).catch(handle404OrThrow({ records: [] })),
        Promise.all([
          api.getInsights(partner, date, "anomalies").catch((err) => {
            const errMsg = String(err.message || "").toLowerCase();
            if (errMsg.includes("404") || errMsg.includes("not found")) return null;
            throw err;
          }),
          api.getInsights(partner, date, "patterns").catch((err) => {
            const errMsg = String(err.message || "").toLowerCase();
            if (errMsg.includes("404") || errMsg.includes("not found")) return null;
            throw err;
          }),
          api.getInsights(partner, date, "recommendations").catch((err) => {
            const errMsg = String(err.message || "").toLowerCase();
            if (errMsg.includes("404") || errMsg.includes("not found")) return null;
            throw err;
          }),
        ]).then(([anomalies, patterns, recommendations]) => {
          setInsights({ anomalies, patterns, recommendations });
        }),
      ]);

      if (runStatusRes && runStatusRes.run) {
        setRunStatus({
          status: runStatusRes.run.status,
          startedAt: runStatusRes.run.startedAt as string ?? "",
          completedAt: runStatusRes.run.completedAt as string,
          totalRows: (runStatusRes.run.stats as Record<string, number>)?.["resultCount"] ?? 0,
          matchedRows: 0,
          unmatchedRows: 0,
          missingPartnerRows: 0,
          missingInternalRows: 0,
        });
      } else {
        setRunStatus(null);
      }

      const rawResults = resultsRes.results ?? [];
      const reviewMap = new Map((reviewRecordsRes.records ?? []).map((r: any) => [r.recordKey, r]));
      
      const mappedResults = rawResults.map((r: any) => {
        const id = r.partnerTxnId || r.internalTxnId || r.id;
        return {
          ...r,
          reviewState: reviewMap.get(id) || null,
        };
      });

      if (statsRes) {
        const totalReviewable = mappedResults.filter((r: any) => r.reconciliationStatus !== "MATCHED").length;
        const reviewedCount = mappedResults.filter((r: any) => 
          r.reconciliationStatus !== "MATCHED" && (r.reviewState?.reviewed || r.reviewState?.resolvedStatus)
        ).length;

        setStats({
          total: statsRes.total,
          matched: statsRes.byStatus["MATCHED"] ?? 0,
          unmatched: (statsRes.byStatus["AMOUNT_MISMATCH"] ?? 0) + (statsRes.byStatus["STATUS_MISMATCH"] ?? 0),
          missingPartner: statsRes.byStatus["MISSING_PARTNER"] ?? 0,
          missingInternal: statsRes.byStatus["MISSING_INTERNAL"] ?? 0,
          matchRate: statsRes.total > 0 ? Math.round((statsRes.byStatus["MATCHED"] ?? 0) / statsRes.total * 10000) / 100 : 0,
          totalReviewable,
          reviewedCount,
        });
      } else {
        setStats(null);
      }

      setResults(mappedResults);
      setPagination({ limit: 25, offset: 0 });
    } catch {
      showToast("Failed to load reconciliation data from backend", "error");
      setRunStatus(null);
      setStats(null);
      setResults([]);
      setInsights({ anomalies: null, patterns: null, recommendations: null });
    } finally {
      setLoading(false);
    }
  }, [setInsights, setLoading, setPagination, setResults, setRunStatus, setStats, showToast]);

  useEffect(() => {
    setPartner(PARTNER);
    setDate(DATE);
    void loadPage(PARTNER, DATE);
  }, [loadPage, setDate, setPartner]);

  useEffect(() => {
    if (!partner || !date) return;
    if (partner === PARTNER && date === DATE) return;
    void loadPage(partner, date);
  }, [date, loadPage, partner]);

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
  }, [partner, date, store.runStatus?.status, setRunStatus, loadPage]);

  const filteredRows = useMemo(() => {
    let items = results;
    if (tableType === "matched") {
      items = items.filter((r) => r.reconciliationStatus === "MATCHED");
    } else if (tableType === "unmatched") {
      items = items.filter((r) => r.reconciliationStatus === "AMOUNT_MISMATCH" || r.reconciliationStatus === "STATUS_MISMATCH");
    } else if (tableType === "missing") {
      items = items.filter((r) => r.reconciliationStatus === "MISSING_PARTNER" || r.reconciliationStatus === "MISSING_INTERNAL");
    }
    
    if (reviewFilter === "pending") {
      items = items.filter((r) => r.reconciliationStatus !== "MATCHED" && !r.reviewState?.resolvedStatus && !r.reviewState?.reviewed);
    } else if (reviewFilter === "reviewed") {
      items = items.filter((r) => r.reconciliationStatus !== "MATCHED" && r.reviewState?.reviewed && !r.reviewState?.resolvedStatus);
    } else if (reviewFilter === "resolved") {
      items = items.filter((r) => r.reconciliationStatus !== "MATCHED" && r.reviewState?.resolvedStatus);
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

  const handleTriggerReconciliation = useCallback(async () => {
    try {
      await api.runReconciliation({ partner, date });
      showToast("Reconciliation run triggered successfully.", "success");
      // Short timeout to let ingestion register on backend before reload
      setTimeout(() => {
        void loadPage(partner, date);
      }, 1000);
    } catch {
      showToast("Failed to trigger reconciliation run.", "error");
    }
  }, [partner, date, loadPage, showToast]);

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
                {["MOMO", "VNPAY", "ZALOPAY", "ACMEPAY"].map((partner) => (
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
            <RunStatusPanelSkeleton />
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
            <RunStatusPanel runStatus={store.runStatus} onTriggerRun={handleTriggerReconciliation} />
            <SummaryStrip stats={store.stats} />
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
