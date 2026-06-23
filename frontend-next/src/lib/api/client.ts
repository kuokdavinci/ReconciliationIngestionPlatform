import { getCurrentActor } from "@/lib/actor";

const BASE_URL = "/api/v1";

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      detail = body.detail || detail;
    } catch {
      const text = await res.text();
      detail = text.slice(0, 200) || detail;
    }
    throw new Error(detail);
  }
  return res.json();
}

function actorHeaders(): Record<string, string> {
  return { "X-Actor": getCurrentActor() };
}

export async function get<T>(path: string, params?: Record<string, string | number | undefined>): Promise<T> {
  let url = `${BASE_URL}${path}`;
  if (params) {
    const searchParams = new URLSearchParams();
    for (const [key, val] of Object.entries(params)) {
      if (val !== undefined && val !== "") searchParams.set(key, String(val));
    }
    const qs = searchParams.toString();
    if (qs) url += `?${qs}`;
  }
  const res = await fetch(url, {
    headers: { Accept: "application/json", ...actorHeaders() },
  });
  return handleResponse<T>(res);
}

export async function post<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
      ...actorHeaders(),
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  return handleResponse<T>(res);
}
