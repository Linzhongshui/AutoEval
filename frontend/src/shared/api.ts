import type { components } from "./types/api";

export type TaskStatistics = components["schemas"]["TaskStatistics"];

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public requestId: string | null = null,
  ) {
    super(message);
  }
}

// Non-JSON error bodies (gateway HTML, empty 502, truncated streams) degrade to
// the generic message instead of leaking a SyntaxError to callers.
async function readError(response: Response): Promise<ApiError> {
  let code = "HTTP_ERROR";
  let message = "请求失败";
  let requestId = response.headers.get("X-Request-ID");
  try {
    const body = await response.json();
    code = body?.error?.code || code;
    message = body?.error?.message || message;
    requestId = body?.request_id ?? requestId;
  } catch {
    /* keep fallbacks */
  }
  return new ApiError(response.status, code, message, requestId);
}

export async function apiGet<T>(path: string, signal?: AbortSignal): Promise<T> {
  return (await apiGetPage<T>(path, signal)).data;
}

type Page<T> = { data: T; next_offset: number | null; total?: number | null; statistics?: TaskStatistics };
// Share only in-flight reads. Completed responses are never cached, so polling and
// reads after a mutation remain fresh. Caller-owned abort signals stay isolated.
const pendingReads = new Map<string, Promise<Page<unknown>>>();
export async function apiGetPage<T>(path: string, signal?: AbortSignal): Promise<Page<T>> {
  const existing = !signal && pendingReads.get(path);
  if (existing) return existing as Promise<Page<T>>;
  const request = (async (): Promise<Page<T>> => {
    const response = await fetch(`/api/autoeval/v1${path}`, {
      signal, headers: { Accept: "application/json" },
    });
    if (!response.ok) throw await readError(response);
    const body = await response.json();
    return { data: body.data as T, next_offset: body.next_offset ?? null, total: body.total ?? null, statistics: body.statistics };
  })();
  if (signal) return request;
  pendingReads.set(path, request);
  try { return await request; }
  finally { if (pendingReads.get(path) === request) pendingReads.delete(path); }
}

export async function apiPost<T>(path: string, payload?: unknown, key?: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`/api/autoeval/v1${path}`, {
    method: "POST",
    signal,
    headers: { "Content-Type": "application/json", ...(key ? { "Idempotency-Key": key } : {}) },
    body: payload === undefined ? undefined : JSON.stringify(payload),
  });
  if (!response.ok) throw await readError(response);
  const body = await response.json();
  return body.data as T;
}

async function apiMutate<T>(method: "PATCH" | "PUT", path: string, payload?: unknown, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`/api/autoeval/v1${path}`, {
    method,
    signal,
    headers: { "Content-Type": "application/json" },
    body: payload === undefined ? undefined : JSON.stringify(payload),
  });
  if (!response.ok) throw await readError(response);
  const body = await response.json();
  return body.data as T;
}

export const apiPatch = <T>(path: string, payload?: unknown, signal?: AbortSignal) =>
  apiMutate<T>("PATCH", path, payload, signal);

export const apiPut = <T>(path: string, payload?: unknown, signal?: AbortSignal) =>
  apiMutate<T>("PUT", path, payload, signal);

export async function apiPostBlob(
  path: string,
  payload: unknown,
  signal?: AbortSignal,
): Promise<{ blob: Blob; filename: string }> {
  const response = await fetch(`/api/autoeval/v1${path}`, {
    method: "POST",
    signal,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw await readError(response);
  const disposition = response.headers.get("Content-Disposition") || "";
  const match = /filename\*?=(?:UTF-8''|")?([^";]+)/i.exec(disposition);
  return {
    blob: await response.blob(),
    filename: match ? decodeURIComponent(match[1]) : "autoeval-badcase.zip",
  };
}

export interface BackendCapabilities {
  workspace_mode: "single";
  subject: string;
  evaluation_enabled: boolean;
  analysis_enabled: boolean;
  customer_ssh_enabled: boolean;
}

// Small registry option sets are fetched across all pages so search is complete.
export async function apiGetOptions<T>(path: string, signal?: AbortSignal): Promise<{ data: T; next_offset: null }> {
  const url = new URL(path, "http://local");
  const rows: unknown[] = []; let offset: number | null = 0;
  while (offset !== null) {
    url.searchParams.set("offset", String(offset)); url.searchParams.set("limit", "100");
    const page: { data: unknown[]; next_offset: number | null } = await apiGetPage(url.pathname + url.search, signal);
    rows.push(...page.data);
    if (page.next_offset !== null && page.next_offset <= offset) throw Error("选项分页异常");
    offset = page.next_offset;
  }
  return { data: rows as T, next_offset: null };
}
