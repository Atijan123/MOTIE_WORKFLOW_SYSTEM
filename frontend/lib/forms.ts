// What a server action tells the form after it ran.
import { ApiError } from "./api";

export type FormState = { error?: string; done?: string };

/** Text from a form field, trimmed; "" when it's missing. */
export function text(data: FormData, name: string): string {
  const value = data.get(name);
  return typeof value === "string" ? value.trim() : "";
}

/** The API's explanation for a failed call, for the form to show. Other errors are rethrown. */
export function failed(error: unknown): FormState {
  if (error instanceof ApiError) return { error: error.message };
  throw error; // includes Next's redirect(), which works by throwing
}
