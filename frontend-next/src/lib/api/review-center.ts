import { get, post } from "./client";
import { normalizePacket } from "./review-center-normalizer";
import type { RawStreamPage, ReviewPacket } from "@/types/review-center";

export interface ReviewPacketsResponse {
  packets: ReviewPacket[];
}

export interface ReviewPacketDetailResponse {
  packet: ReviewPacket;
}

export interface ApiOkResponse {
  ok: boolean;
  [key: string]: unknown;
}

export async function listReviewPackets(partner?: string, status?: string) {
  const response = await get<{ packets: Record<string, unknown>[] }>("/review-packets", { partner, status });
  return {
    packets: Array.isArray(response.packets) ? response.packets.map(normalizePacket) : [],
  };
}

export async function getReviewPacket(packetId: string) {
  const response = await get<{ packet: Record<string, unknown> }>(`/review-packets/${packetId}`);
  return {
    packet: normalizePacket(response.packet ?? {}),
  };
}

export async function getReviewPacketRawRecords(packetId: string, offset = 0, limit = 50) {
  return get<RawStreamPage>(`/review-packets/${packetId}/raw-records`, { offset, limit });
}

export async function approveActivate(packetId: string, reviewedBy: string, scopeType?: string) {
  return post<ApiOkResponse>(`/review-packets/${packetId}/approve-activate`, { reviewedBy, scopeType });
}

export async function approveKeepCurrent(packetId: string, reviewedBy: string, scopeType?: string) {
  return post<ApiOkResponse>(`/review-packets/${packetId}/approve-keep-current`, { reviewedBy, scopeType });
}

export async function rejectPacket(packetId: string, reviewedBy: string) {
  return post<ApiOkResponse>(`/review-packets/${packetId}/reject`, { reviewedBy });
}

export async function sendToStudio(packetId: string, reviewedBy: string) {
  return post<ApiOkResponse>(`/review-packets/${packetId}/send-to-studio`, { reviewedBy });
}

export async function classifyScope(packetId: string) {
  return post<Record<string, unknown>>(`/review-packets/${packetId}/classify-scope-llm`);
}

export async function setScope(packetId: string, scopeType: string) {
  return post<ApiOkResponse>(`/review-packets/${packetId}/scope`, { scopeType });
}

export async function validateRuntime(packetId: string) {
  return post<ApiOkResponse>(`/review-packets/${packetId}/validate-runtime`);
}

export async function generateAiMapping(packetId: string) {
  return post<Record<string, unknown>>(`/review-packets/${packetId}/generate-ai-mapping`);
}

export async function getPostApproveRun(packetId: string) {
  return get<{ run: Record<string, unknown> | null }>(`/review-packets/${packetId}/post-approve-run`);
}

export function openPostApproveRunStream(packetId: string) {
  return new EventSource(`/api/v1/review-packets/${packetId}/post-approve-run/stream`);
}

export async function saveDraftMapping(
  packetId: string,
  payload: {
    sheetName: string;
    startRow: number;
    fieldMappings: Array<{
      path: string;
      column: number | null;
      type: string;
      required: boolean;
      constant?: string | null;
      sourceField?: string;
      mapping?: Record<string, string> | null;
    }>;
  }
) {
  return post<ApiOkResponse>(`/review-packets/${packetId}/save-draft-mapping`, payload);
}
