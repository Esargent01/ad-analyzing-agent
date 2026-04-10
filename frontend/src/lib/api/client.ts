/**
 * Fetch wrapper for the Ad Creative Agent dashboard backend.
 *
 * - Always sends cookies (credentials: "include") so the HttpOnly session
 *   cookie rides along on every request.
 * - Copies the readable `csrf_token` cookie into the `X-CSRF-Token` header
 *   on state-changing verbs (double-submit CSRF pattern).
 * - On 401 responses, dispatches a global `auth:unauthenticated` event so
 *   the router can kick the user back to `/sign-in`.
 */

import { getCsrfToken } from "@/lib/auth";

// Default to same-origin (empty string) so production builds hit the Vercel
// /api/* proxy rewrite without needing a build-time env var. Local dev sets
// VITE_API_BASE_URL=http://localhost:8000 in frontend/.env.local to point at
// the backend running outside Vite's dev server.
const API_BASE_URL: string = (import.meta.env.VITE_API_BASE_URL ?? "").replace(
  /\/$/,
  "",
);

export class ApiError extends Error {
  status: number;
  detail: unknown;

  constructor(status: number, detail: unknown, message?: string) {
    super(message ?? `API error ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

const STATE_CHANGING = new Set(["POST", "PUT", "PATCH", "DELETE"]);

type JsonBody = Record<string, unknown> | unknown[];

export interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: JsonBody;
  /** If true, suppress the global 401 redirect (used by /api/me probe). */
  suppressAuthRedirect?: boolean;
  /** AbortSignal for cancellation (wired into TanStack Query). */
  signal?: AbortSignal;
}

async function parseBody(response: Response): Promise<unknown> {
  if (response.status === 204) return null;
  const contentType = response.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) {
    return response.json();
  }
  return response.text();
}

export async function apiRequest<T>(
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const method = options.method ?? "GET";
  const headers: Record<string, string> = {
    Accept: "application/json",
  };

  let body: BodyInit | undefined;
  if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(options.body);
  }

  if (STATE_CHANGING.has(method)) {
    const csrf = getCsrfToken();
    if (csrf) {
      headers["X-CSRF-Token"] = csrf;
    }
  }

  const url = path.startsWith("http")
    ? path
    : `${API_BASE_URL}${path.startsWith("/") ? path : `/${path}`}`;

  const response = await fetch(url, {
    method,
    credentials: "include",
    headers,
    body,
    signal: options.signal,
  });

  if (response.status === 401 && !options.suppressAuthRedirect) {
    // Let the router / auth layout hear about the logout so it can
    // redirect — avoids importing react-router into this module.
    if (typeof window !== "undefined") {
      window.dispatchEvent(new Event("auth:unauthenticated"));
    }
  }

  if (!response.ok) {
    const detail = await parseBody(response).catch(() => null);
    throw new ApiError(response.status, detail);
  }

  const parsed = (await parseBody(response)) as T;
  return parsed;
}

export const api = {
  get: <T>(path: string, opts?: Omit<RequestOptions, "method" | "body">) =>
    apiRequest<T>(path, { ...opts, method: "GET" }),
  post: <T>(
    path: string,
    body?: JsonBody,
    opts?: Omit<RequestOptions, "method" | "body">,
  ) => apiRequest<T>(path, { ...opts, method: "POST", body }),
  delete: <T>(path: string, opts?: Omit<RequestOptions, "method" | "body">) =>
    apiRequest<T>(path, { ...opts, method: "DELETE" }),
};

export { API_BASE_URL };
