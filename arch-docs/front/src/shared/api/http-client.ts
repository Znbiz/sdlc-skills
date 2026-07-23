import { env } from "../config/env";
import { ApiError, apiErrorFromResponse, transportError } from "../errors/api-error";

export interface RequestOptions {
  query?: Record<string, string | number | undefined>;
  signal?: AbortSignal;
}

function buildUrl(path: string, query?: RequestOptions["query"]): string {
  const url = new URL(`${env.apiBasePath}${path}`, window.location.origin);
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined) url.searchParams.set(key, String(value));
    }
  }
  return url.toString();
}

async function request<TResponse>(method: string, path: string, body?: unknown, options?: RequestOptions): Promise<TResponse> {
  let response: Response;
  try {
    response = await fetch(buildUrl(path, options?.query), {
      method,
      headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal: options?.signal,
    });
  } catch {
    throw transportError();
  }

  if (!response.ok) {
    throw await apiErrorFromResponse(response);
  }

  if (response.status === 204) {
    return undefined as TResponse;
  }

  return (await response.json()) as TResponse;
}

export const httpClient = {
  get: <TResponse>(path: string, options?: RequestOptions) => request<TResponse>("GET", path, undefined, options),
  post: <TResponse>(path: string, body?: unknown, options?: RequestOptions) => request<TResponse>("POST", path, body ?? {}, options),
  put: <TResponse>(path: string, body?: unknown, options?: RequestOptions) => request<TResponse>("PUT", path, body ?? {}, options),
  patch: <TResponse>(path: string, body?: unknown, options?: RequestOptions) => request<TResponse>("PATCH", path, body ?? {}, options),
  delete: <TResponse>(path: string, options?: RequestOptions) => request<TResponse>("DELETE", path, undefined, options),
};

export function sseUrl(path: string, query?: RequestOptions["query"]): string {
  return buildUrl(path, query);
}

export { ApiError };
