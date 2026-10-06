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

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
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
  if (!isRecord(payload) || !isRecord(payload.detail)) {
    return undefined;
  }

  const { code, message } = payload.detail;
  return typeof code === "string" && typeof message === "string" ? { code, message } : undefined;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}
