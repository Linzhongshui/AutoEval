export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string) {
    super(message);
  }
}

export async function apiGet<T>(path: string, signal?: AbortSignal): Promise<T> {
  return (await apiGetPage<T>(path, signal)).data;
}

export async function apiGetPage<T>(path: string, signal?: AbortSignal): Promise<{ data: T; next_offset: number | null }> {
  const response = await fetch(`/api/autoeval/v1${path}`, {
    signal,
    headers: { Accept: "application/json" },
  });
  const body = await response.json();
  if (!response.ok) {
    throw new ApiError(response.status, body.error?.code || "HTTP_ERROR", body.error?.message || "请求失败");
  }
  return { data: body.data as T, next_offset: body.next_offset ?? null };
}

export async function apiPost<T>(path: string, payload?: unknown, key?: string): Promise<T> {
  const response = await fetch(`/api/autoeval/v1${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(key ? { "Idempotency-Key": key } : {}) },
    body: payload === undefined ? undefined : JSON.stringify(payload),
  });
  const body = await response.json();
  if (!response.ok) throw new ApiError(response.status, body.error?.code || "HTTP_ERROR", body.error?.message || "请求失败");
  return body.data as T;
}

export interface BackendCapabilities {
  workspace_mode: "single";
  subject: string;
  evaluation_enabled: boolean;
  analysis_enabled: boolean;
  customer_ssh_enabled: boolean;
}
