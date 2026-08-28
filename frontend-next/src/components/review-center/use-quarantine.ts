import { useCallback, useEffect, useMemo, useState } from "react";
import * as api from "@/lib/api/quarantine";
import type { QuarantineFilters, QuarantineListResponse, QuarantineRecord } from "@/types/quarantine";

export function useQuarantine(filters: QuarantineFilters) {
  const [response, setResponse] = useState<QuarantineListResponse | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedDetail, setSelectedDetail] = useState<QuarantineRecord | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const filterKey = useMemo(() => JSON.stringify(filters), [filters]);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const next = await api.listQuarantine(filters);
      setResponse(next);
      const refreshedSelectedId = selectedId && next.items.some((item) => item._id === selectedId)
        ? selectedId
        : null;
      setSelectedId(refreshedSelectedId);
      if (refreshedSelectedId) {
        try {
          setSelectedDetail(await api.getQuarantineRecord(refreshedSelectedId));
        } catch {
          // Keep the list response usable if the detail refresh races a terminal transition.
        }
      } else {
        setSelectedDetail(null);
      }
      setError(null);
      return next;
    } catch (caught) {
      const nextError = caught instanceof Error ? caught : new Error("Unable to load quarantine queue.");
      setError(nextError);
      setResponse(null);
      setSelectedId(null);
      throw nextError;
    } finally {
      setLoading(false);
    }
  }, [filters, selectedId]);

  useEffect(() => {
    let cancelled = false;
    api.listQuarantine(filters)
      .then((next) => {
        if (cancelled) return;
        setResponse(next);
        setSelectedId((current) => current && next.items.some((item) => item._id === current) ? current : null);
        setError(null);
      })
      .catch((caught) => {
        if (cancelled) return;
        setError(caught instanceof Error ? caught : new Error("Unable to load quarantine queue."));
        setResponse(null);
        setSelectedId(null);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [filterKey, filters]);

  useEffect(() => {
    if (!selectedId) return;
    api.getQuarantineRecord(selectedId)
      .then((next) => setSelectedDetail(next))
      .catch(() => undefined);
  }, [selectedId]);

  const selectedRecord = selectedId && selectedDetail?._id === selectedId
    ? selectedDetail
    : response?.items.find((item) => item._id === selectedId) ?? null;

  return {
    items: response?.items ?? [],
    nextCursor: response?.nextCursor ?? null,
    summary: response?.summary ?? null,
    groups: response?.groups ?? [],
    selectedId,
    selectedRecord,
    loading,
    error,
    setSelectedId,
    refresh,
  };
}
