export type ApiErrorKind =
  | "transport"
  | "validation"
  | "not_found"
  | "forbidden"
  | "conflict"
  | "server"
  | "unknown";

export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  readonly status: number | null;
  readonly reasonCode: string | null;

  constructor(params: { message: string; kind: ApiErrorKind; status: number | null; reasonCode?: string | null }) {
    super(params.message);
    this.name = "ApiError";
    this.kind = params.kind;
    this.status = params.status;
    this.reasonCode = params.reasonCode ?? null;
  }
}

function kindFromStatus(status: number): ApiErrorKind {
  if (status === 404) return "not_found";
  if (status === 403) return "forbidden";
  if (status === 409) return "conflict";
  if (status === 422) return "validation";
  if (status >= 500) return "server";
  return "unknown";
}

export function safeErrorMessage(detail: unknown, fallback: string): string {
  if (typeof detail === "string" && detail.trim().length > 0) return detail;
  if (detail && typeof detail === "object" && "message" in detail && typeof (detail as { message?: unknown }).message === "string") {
    return (detail as { message: string }).message;
  }
  return fallback;
}

export function reasonCodeFromDetail(detail: unknown): string | null {
  if (detail && typeof detail === "object" && "reason_code" in detail) {
    const value = (detail as { reason_code?: unknown }).reason_code;
    return typeof value === "string" ? value : null;
  }
  return null;
}

export async function apiErrorFromResponse(response: Response): Promise<ApiError> {
  let detail: unknown = null;
  try {
    detail = await response.json();
  } catch {
    detail = null;
  }
  const detailPayload = detail && typeof detail === "object" && "detail" in detail ? (detail as { detail: unknown }).detail : detail;
  return new ApiError({
    message: safeErrorMessage(detailPayload, `Backend ответил статусом ${response.status}`),
    kind: kindFromStatus(response.status),
    status: response.status,
    reasonCode: reasonCodeFromDetail(detailPayload),
  });
}

export function transportError(): ApiError {
  return new ApiError({
    message: "Не удалось связаться с backend. Проверьте соединение и повторите попытку.",
    kind: "transport",
    status: null,
    reasonCode: null,
  });
}
