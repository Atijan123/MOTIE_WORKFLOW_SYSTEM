// Calls to the FastAPI backend. Server-side only (server components, server
// actions, route handlers): the browser never talks to the API directly and
// never sees the login token, which lives in an httpOnly cookie.
import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { signInAgainPath } from "./auth-redirect";

export const SESSION_COOKIE = "motie_session";
// Inside Compose the API is "api:8000"; the browser can't reach it, on purpose.
const API_URL = process.env.API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

type Options = { method?: string; json?: unknown; body?: BodyInit; headers?: Record<string, string> };

/** The raw response, for files. Redirects to the login page if the session has ended. */
export async function apiFetch(path: string, options: Options = {}): Promise<Response> {
  const token = (await cookies()).get(SESSION_COOKIE)?.value;
  const headers: Record<string, string> = { ...options.headers };
  if (token) headers.Authorization = `Bearer ${token}`;
  let body = options.body;
  if (options.json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(options.json);
  }
  const response = await fetch(API_URL + path, { method: options.method ?? "GET", headers, body, cache: "no-store" });
  const signIn = signInAgainPath(response.status, path, Boolean(token));
  if (signIn) redirect(signIn);
  return response;
}

/** JSON from the API; throws ApiError with the API's own explanation on failure. */
export async function api<T>(path: string, options: Options = {}): Promise<T> {
  const response = await apiFetch(path, options);
  if (!response.ok) throw new ApiError(response.status, await errorText(response));
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

/** The same, but null for 404 (e.g. a case that isn't yours, or isn't there). */
export async function apiOrNull<T>(path: string): Promise<T | null> {
  try {
    return await api<T>(path);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

// Field names in the API's 422 errors, as the form labels them.
const FIELD_LABELS: Record<string, string> = {
  importer_name: "Business name",
  importer_address: "Address",
  product: "Product",
  hs_code: "HS code",
  quantity: "Quantity",
  unit: "Unit",
  exporter_name: "Exporter",
  exporter_country: "Country",
  exporter_etls_approval_number: "Exporter’s ETLS approval number",
  product_approval_numbers: "Product approval numbers",
  certificates_of_origin: "Certificates of origin",
  issued_on: "Issue date",
  number: "Number",
  password: "Password",
};

/** One readable sentence from an API error body. */
async function errorText(response: Response): Promise<string> {
  try {
    const body = await response.json();
    if (typeof body.detail === "string") return body.detail;
    if (Array.isArray(body.detail)) {
      // FastAPI's validation errors: [{loc: ["body", "quantity"], msg: "..."}]
      return body.detail
        .map((e: { loc?: (string | number)[]; msg: string }) => {
          const field = (e.loc ?? []).filter((p) => typeof p === "string" && p !== "body" && p !== "form").pop();
          const label = field ? FIELD_LABELS[field as string] ?? field : null;
          return label ? `${label}: ${e.msg.replace(/^Value error, /, "")}` : e.msg;
        })
        .join(". ");
    }
  } catch {
    // not JSON
  }
  return `Something went wrong (error ${response.status}). Please try again.`;
}
