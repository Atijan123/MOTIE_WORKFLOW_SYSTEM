"use server";
// Phone scanning (step 13g): each photo goes to the API as it's taken; the
// API turns it upright, shrinks it and keeps it as a page; Finish joins the
// pages into one PDF. Nothing is kept on the phone.
import { revalidatePath } from "next/cache";

import { apiFetch } from "@/lib/api";

export type ScanState = { pages: number[]; error?: string; done?: string };

async function pagesFrom(response: Response): Promise<ScanState> {
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const error = typeof body?.detail === "string" ? body.detail : "That didn’t work. Please try again.";
    return { pages: [], error };
  }
  return { pages: (body as { page_no: number }[]).map((p) => p.page_no) };
}

const base = (caseId: number, type: string) => `/cases/${caseId}/documents/${encodeURIComponent(type)}/scan`;

/** A photo as the next page, or as page `retake` taken again. */
export async function addPage(caseId: number, type: string, retake: number | null, data: FormData): Promise<ScanState> {
  const photo = data.get("photo");
  if (!(photo instanceof File) || photo.size === 0) return { pages: [], error: "No photo was taken." };
  const response = await apiFetch(retake ? `${base(caseId, type)}/pages/${retake}` : `${base(caseId, type)}/pages`, {
    method: retake ? "PUT" : "POST",
    body: Buffer.from(await photo.arrayBuffer()),
    headers: { "Content-Type": "application/octet-stream" },
  });
  return pagesFrom(response);
}

export async function removePage(caseId: number, type: string, pageNo: number): Promise<ScanState> {
  return pagesFrom(await apiFetch(`${base(caseId, type)}/pages/${pageNo}`, { method: "DELETE" }));
}

export async function cancelScan(caseId: number, type: string): Promise<ScanState> {
  await apiFetch(base(caseId, type), { method: "DELETE" });
  return { pages: [] };
}

/** Join the pages into one PDF, stored as this document; the page re-renders with it. */
export async function finishScan(caseId: number, type: string, page: string): Promise<ScanState> {
  const response = await apiFetch(`${base(caseId, type)}/finish`, { method: "POST" });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    return { pages: [], error: typeof body.detail === "string" ? body.detail : "The PDF couldn’t be made. Please try again." };
  }
  revalidatePath(page);
  return { pages: [], done: "Scanned and saved as one PDF." };
}
