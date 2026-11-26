// Sending one document to the API, for both apps' server actions (A2, and
// Records' walk-in screen, step 13b). Server-side only (it uses the login cookie).
import { revalidatePath } from "next/cache";

import { apiFetch } from "./api";
import type { FormState } from "./forms";

/** Upload the form's "file" as document `type` of the case; `page` is re-rendered afterwards. */
export async function upload(caseId: number, type: string, page: string, data: FormData): Promise<FormState> {
  const file = data.get("file");
  if (!(file instanceof File) || file.size === 0) return { error: "Choose a file first." };
  // The API takes the file as the raw body and checks its type from the content.
  const response = await apiFetch(`/cases/${caseId}/documents/${type}?filename=${encodeURIComponent(file.name)}`, {
    method: "POST",
    body: Buffer.from(await file.arrayBuffer()),
    headers: { "Content-Type": "application/octet-stream" },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    return { error: typeof body.detail === "string" ? body.detail : "The upload didn’t work. Please try again." };
  }
  revalidatePath(page);
  return { done: `${file.name} uploaded.` };
}
