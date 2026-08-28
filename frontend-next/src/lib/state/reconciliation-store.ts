"use client";

import { useState, useCallback } from "react";
import type { ReconciliationPageState, ReconciliationRow } from "@/types/reconciliation";

const initialFilters = { amountMin: "", amountMax: "", dateFrom: "", dateTo: "" };
const initialPagination = { limit: 25, offset: 0 };

export function useReconciliationStore() {
  const [partner, setPartner] = useState("DEMO");
  const [date, setDate] = useState("");
  const [reconStatus, setReconStatus] = useState("");
  const [filters, setFilters] = useState(initialFilters);
  const [pagination, setPagination] = useState(initialPagination);
  const [runStatus, setRunStatus] = useState<ReconciliationPageState["runStatus"]>(null);
  const [stats, setStats] = useState<ReconciliationPageState["stats"]>(null);
  const [results, setResults] = useState<ReconciliationRow[]>([]);
  const [insights, setInsights] = useState<ReconciliationPageState["insights"]>({
    anomalies: null,
    patterns: null,
    recommendations: null,
  });
  const [selectedRows, setSelectedRows] = useState<Record<string, boolean>>({});
  const [selectedEvidenceRowId, setSelectedEvidenceRowId] = useState<string | null>(null);
  const [explainItem, setExplainItem] = useState<ReconciliationPageState["explainItem"]>(null);
  const [loading, setLoading] = useState(false);

  const resetSelection = useCallback(() => {
    setSelectedRows({});
    setSelectedEvidenceRowId(null);
  }, []);

  const toggleRow = useCallback((rowId: string) => {
    setSelectedRows((prev) => {
      const next = { ...prev };
      if (next[rowId]) delete next[rowId];
      else next[rowId] = true;
      return next;
    });
  }, []);

  const selectAll = useCallback((rows: ReconciliationRow[], onlyUnmatched = true) => {
    const selection: Record<string, boolean> = {};
    for (const row of rows) {
      if (onlyUnmatched && row.reconciliationStatus === "MATCHED") continue;
      const id = row.partnerTxnId || row.internalTxnId || row.id;
      selection[id] = true;
    }
    setSelectedRows(selection);
  }, []);

  const clearSelection = useCallback(() => {
    setSelectedRows({});
  }, []);

  const setRowsSelection = useCallback((rows: ReconciliationRow[], selected: boolean, onlyUnmatched = true) => {
    setSelectedRows((prev) => {
      const next = { ...prev };
      for (const row of rows) {
        if (onlyUnmatched && row.reconciliationStatus === "MATCHED") continue;
        const id = row.partnerTxnId || row.internalTxnId || row.id;
        if (selected) next[id] = true;
        else delete next[id];
      }
      return next;
    });
  }, []);

  const updatePagination = useCallback((updates: Partial<typeof initialPagination>) => {
    setPagination((prev) => ({ ...prev, ...updates }));
  }, []);

  const updateFilters = useCallback((updates: Partial<typeof initialFilters>) => {
    setFilters((prev) => ({ ...prev, ...updates }));
  }, []);

  return {
    partner, setPartner,
    date, setDate,
    reconStatus, setReconStatus,
    filters, updateFilters, setFilters,
    pagination, updatePagination, setPagination,
    runStatus, setRunStatus,
    stats, setStats,
    results, setResults,
    insights, setInsights,
    selectedRows, selectedEvidenceRowId,
    setSelectedEvidenceRowId,
    explainItem, setExplainItem,
    loading, setLoading,
    toggleRow, selectAll, clearSelection, resetSelection, setRowsSelection,
  };
}

export type ReconciliationStore = ReturnType<typeof useReconciliationStore>;
