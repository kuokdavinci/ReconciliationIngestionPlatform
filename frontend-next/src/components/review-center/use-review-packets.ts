import { useCallback, useEffect, useMemo, useState } from "react";
import * as api from "@/lib/api/review-center";
import type { ReviewPacket } from "@/types/review-center";

export function getPendingPackets(packets: ReviewPacket[]): ReviewPacket[] {
  return [...packets]
    .filter((packet) => String(packet.status).toUpperCase() === "PENDING")
    .sort((a, b) => String(b.createdAt || "").localeCompare(String(a.createdAt || "")));
}

export function getVisiblePackets(packets: ReviewPacket[]): ReviewPacket[] {
  return [...packets]
    .filter((packet) => (
      String(packet.status).toUpperCase() === "PENDING"
      || String(packet.qualityGateStatus).toUpperCase() === "FAIL"
    ))
    .sort((a, b) => String(b.createdAt || "").localeCompare(String(a.createdAt || "")));
}

export function selectReviewPacketId({
  packets,
  currentId,
  requestedId,
}: {
  packets: ReviewPacket[];
  currentId?: string | null;
  requestedId?: string | null;
}): string | null {
  if (requestedId && packets.some((packet) => packet._id === requestedId)) {
    return requestedId;
  }

  if (currentId && packets.some((packet) => packet._id === currentId)) {
    return currentId;
  }

  return packets[0]?._id ?? null;
}

export function useReviewPackets(requestedId?: string | null) {
  const [packets, setPackets] = useState<ReviewPacket[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedPacketDetail, setSelectedPacketDetail] = useState<ReviewPacket | null>(null);
  const [loading, setLoading] = useState(true);

  const refreshPackets = useCallback(async () => {
    try {
      const response = await api.listReviewPackets();
      const visible = getVisiblePackets(response.packets ?? []);
      setPackets(visible);
      setSelectedId((current) => selectReviewPacketId({ packets: visible, currentId: current, requestedId }));
      return visible;
    } catch {
      setPackets([]);
      setSelectedId(null);
      return [];
    } finally {
      setLoading(false);
    }
  }, [requestedId]);

  useEffect(() => {
    let cancelled = false;

    async function bootstrap() {
      try {
        const response = await api.listReviewPackets();
        if (cancelled) return;
        const visible = getVisiblePackets(response.packets ?? []);
        setPackets(visible);
        setSelectedId((current) => selectReviewPacketId({ packets: visible, currentId: current, requestedId }));
      } catch {
        if (cancelled) return;
        setPackets([]);
        setSelectedId(null);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    void bootstrap();

    // Polling every 12 seconds to fetch new review packets automatically
    const intervalId = setInterval(() => {
      void refreshPackets();
    }, 12000);

    return () => {
      cancelled = true;
      clearInterval(intervalId);
    };
  }, [requestedId, refreshPackets]);

  useEffect(() => {
    if (!selectedId) return;
    const fallback = packets.find((packet) => packet._id === selectedId) ?? null;
    api.getReviewPacket(selectedId)
      .then((response) => setSelectedPacketDetail(response.packet))
      .catch(() => setSelectedPacketDetail(fallback));
  }, [packets, selectedId]);

  const selectedPacket = useMemo(() => {
    if (!selectedId) return null;
    if (selectedPacketDetail?._id === selectedId) return selectedPacketDetail;
    return packets.find((packet) => packet._id === selectedId) ?? null;
  }, [packets, selectedId, selectedPacketDetail]);

  return {
    packets,
    selectedId,
    selectedPacket,
    loading,
    setSelectedId,
    refreshPackets,
  };
}
