import { useCallback, useEffect, useRef, useState } from "react";
import * as api from "@/lib/api/review-center";
import type { PostApprovalRun } from "@/types/review-center";

export function usePostApprovalPolling({
  packetId,
  enabled,
  onCompleted,
}: {
  packetId?: string | null;
  enabled: boolean;
  onCompleted?: () => void;
}) {
  const [run, setRun] = useState<PostApprovalRun | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const intervalRef = useRef<NodeJS.Timeout | null>(null);
  const inFlightRef = useRef(false);
  const eventSourceRef = useRef<EventSource | null>(null);

  const stopPolling = useCallback(() => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
  }, []);

  const startPolling = useCallback((id: string) => {
    if (intervalRef.current) return;
    setLoading(true);
    setError(null);

    const tick = async () => {
      if (inFlightRef.current) return;
      inFlightRef.current = true;
      try {
        const response = await api.getPostApproveRun(id);
        if (response.run) {
          const polledRun = response.run as unknown as PostApprovalRun;
          setRun(polledRun);
          if (polledRun.status === "COMPLETED" || polledRun.status === "FAILED") {
            stopPolling();
            setLoading(false);
            if (polledRun.status === "COMPLETED") {
              onCompleted?.();
            }
          }
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "Polling failed");
      } finally {
        inFlightRef.current = false;
      }
    };

    void tick();
    intervalRef.current = setInterval(() => { void tick(); }, 750);
  }, [stopPolling, onCompleted]);

  const startEventStream = useCallback((id: string) => {
    if (eventSourceRef.current) return;
    try {
      const source = api.openPostApproveRunStream(id);
      eventSourceRef.current = source;
      source.addEventListener("post_approval_run", (event) => {
        const message = JSON.parse((event as MessageEvent).data || "{}");
        const streamedRun = (message.run || null) as PostApprovalRun | null;
        if (!streamedRun) return;
        setRun(streamedRun);
        setLoading(false);
        setError(null);
        if (streamedRun.status === "COMPLETED" || streamedRun.status === "FAILED") {
          stopPolling();
          if (streamedRun.status === "COMPLETED") onCompleted?.();
        }
      });
      source.onerror = () => {
        if (eventSourceRef.current) {
          eventSourceRef.current.close();
          eventSourceRef.current = null;
        }
        if (!intervalRef.current) {
          startPolling(id);
        }
      };
    } catch {
      if (!intervalRef.current) {
        startPolling(id);
      }
    }
  }, [onCompleted, startPolling, stopPolling]);

  useEffect(() => {
    if (!enabled || !packetId) return;
    void api.getPostApproveRun(packetId).then(res => {
      if (res.run) {
        const polledRun = res.run as unknown as PostApprovalRun;
        setRun(polledRun);
        if (
          polledRun.status === "QUEUED" ||
          polledRun.status === "INGESTING" ||
          polledRun.status === "RECONCILING"
        ) {
          startEventStream(packetId);
        }
      }
    }).catch(() => {});
  }, [enabled, packetId, startEventStream]);

  useEffect(() => {
    return () => stopPolling();
  }, [stopPolling]);

  return {
    run,
    setRun,
    loading,
    error,
    startPolling,
    stopPolling,
  };
}
