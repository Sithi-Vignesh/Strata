import type { HealthResponse, SqlProfileResponse } from "../types/api";

export class StrataApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = "StrataApiError";
  }
}

export async function getHealth(): Promise<HealthResponse> {
  return requestJson<HealthResponse>("/health");
}

export async function executeSqlProfile(sql: string): Promise<SqlProfileResponse> {
  return requestJson<SqlProfileResponse>("/api/sql/profile", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sql }),
  });
}

export async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, init);
  } catch {
    throw new StrataApiError(0, "NETWORK_ERROR", "Could not reach the Strata backend.");
  }
  const payload = await parseJsonSafely(response);

  if (!response.ok) {
    const detail = extractErrorDetail(payload);
    throw new StrataApiError(
      response.status,
      detail?.code ?? `HTTP_${response.status}`,
      detail?.message ?? `Request failed with status ${response.status}.`,
    );
  }

  return payload as T;
}

async function parseJsonSafely(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    return undefined;
  }
}

function extractErrorDetail(payload: unknown): { code: string; message: string } | undefined {
  if (isRecord(payload) && Array.isArray(payload.detail)) {
    return { code: "REQUEST_VALIDATION_ERROR", message: "The request was invalid." };
  }
  if (!isRecord(payload) || !isRecord(payload.detail)) {
    return undefined;
  }

  const { code, message } = payload.detail;
  return typeof code === "string" && typeof message === "string" ? { code, message } : undefined;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}
