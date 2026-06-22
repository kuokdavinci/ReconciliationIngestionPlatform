import { get, post } from "./client";

export interface MappingsResponse {
  mappings: Record<string, unknown>[];
}

export interface MappingVersionsResponse {
  versions: Record<string, unknown>[];
}

export async function listMappings(partner?: string) {
  return get<MappingsResponse>("/mappings", { partner });
}

export async function approveMapping(configId: string, reviewedBy: string) {
  return post<Record<string, unknown>>(`/mappings/${configId}/approve`, { reviewedBy });
}

export async function rejectMapping(configId: string, reviewedBy: string) {
  return post<Record<string, unknown>>(`/mappings/${configId}/reject`, { reviewedBy });
}

export async function aiGenerateMapping(partner: string, file: File) {
  const formData = new FormData();
  formData.append("file", file);
  const res = await fetch(`/api/v1/mapping/ai-generate?partner=${encodeURIComponent(partner)}`, {
    method: "POST",
    headers: { Accept: "application/json" },
    body: formData,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`API ${res.status}: ${text.slice(0, 200)}`);
  }
  return res.json();
}

export async function validateMapping(fieldMappings: unknown) {
  return post<Record<string, unknown>>("/mapping/validate", { fieldMappings });
}

export async function getMappingVersions(partner: string) {
  return get<MappingVersionsResponse>("/mapping/versions", { partner });
}

export async function getVersion(versionId: string) {
  return get<Record<string, unknown>>(`/mapping/version/${versionId}`);
}

import type { TestMappingResponse, HandoffResponse } from "@/types/mapping";

export async function testMapping(mapping: unknown, sampleRow: unknown[]): Promise<TestMappingResponse> {
  return post<TestMappingResponse>("/mapping/test", { mapping, sampleRow });
}

export async function handoffReview(draftId: string): Promise<HandoffResponse> {
  const res = await fetch(`/api/v1/review-packets/from-mapping/${encodeURIComponent(draftId)}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
      "X-Actor": (() => { try { return sessionStorage.getItem("actor")?.trim() || "Administrator"; } catch { return "Administrator"; } })(),
    },
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`API ${res.status}: ${text.slice(0, 200)}`);
  }
  return res.json();
}
