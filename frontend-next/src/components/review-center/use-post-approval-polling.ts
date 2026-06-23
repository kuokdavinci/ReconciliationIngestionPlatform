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

  const stopPolling = useCallback(() => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
  }, []);

  const startPolling = useCallback((id: string) => {
    if (intervalRef.current) return;
    setLoading(true);
    setError(null);

    const tick = async () => {
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
      }
    };

    void tick();
    intervalRef.current = setInterval(() => { void tick(); }, 1500);
  }, [stopPolling, onCompleted]);

  useEffect(() => {
    if (!enabled || !packetId) return;
    void api.getPostApproveRun(packetId).then(res => {
      if (res.run) setRun(res.run as unknown as PostApprovalRun);
    }).catch(() => {});
  }, [enabled, packetId]);

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
