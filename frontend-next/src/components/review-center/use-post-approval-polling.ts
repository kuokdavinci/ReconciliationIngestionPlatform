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
  const intervalRef = useRef<NodeJS.Timeout | null>(null);
  const inFlightRef = useRef(false);

  const stopPolling = useCallback(() => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
  }, []);

  const startPolling = useCallback((id: string) => {
    if (intervalRef.current) return;

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
            if (polledRun.status === "COMPLETED") {
              onCompleted?.();
            }
          }
        }
      } catch {
        // Keep polling after a transient API error.
      } finally {
        inFlightRef.current = false;
      }
    };

    void tick();
    intervalRef.current = setInterval(() => { void tick(); }, 500);
  }, [stopPolling, onCompleted]);

  useEffect(() => {
    if (!enabled || !packetId) return;
    startPolling(packetId);
  }, [enabled, packetId, startPolling]);

  useEffect(() => {
    return () => stopPolling();
  }, [stopPolling]);

  return {
    run,
    setRun,
    startPolling,
    stopPolling,
  };
}
