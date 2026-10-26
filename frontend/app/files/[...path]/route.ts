// Downloads (uploaded documents, signed letters, the letter preview), passed
// through from the API with the user's login. Only these exact shapes of
// path are passed on, so this can't be used to reach any other API endpoint.
import { apiFetch } from "@/lib/api";

const ALLOWED = [
  /^cases\/\d+\/documents\/\d+\/file$/,
  /^etls\/facility-letters\/\d+\/letter\.pdf$/,
  /^etls\/facility-letters\/\d+\/letter-preview\.pdf$/,
  /^etls\/facility-letters\/\d+\/letters\/\d+\/file$/,
];

// Headers from the API worth keeping: what it is, how to show it, and its checksum.
const PASS = ["content-type", "content-disposition", "x-checksum-sha256", "x-letter-status", "x-content-type-options"];

export async function GET(_: Request, { params }: { params: Promise<{ path: string[] }> }) {
  const path = (await params).path.join("/");
  if (!ALLOWED.some((pattern) => pattern.test(path))) return new Response("Not found", { status: 404 });
  const upstream = await apiFetch(`/${path}`);
  if (!upstream.ok) {
    const body = await upstream.json().catch(() => ({}));
    return new Response(typeof body.detail === "string" ? body.detail : "Not available", {
      status: upstream.status,
      headers: { "Content-Type": "text/plain; charset=utf-8" },
    });
  }
  const headers = new Headers({ "Cache-Control": "private, no-store" });
  for (const name of PASS) {
    const value = upstream.headers.get(name);
    if (value) headers.set(name, value);
  }
  return new Response(upstream.body, { status: 200, headers });
}
