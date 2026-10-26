import { redirect } from "next/navigation";

import { getMe, homeFor } from "@/lib/session";

// "/" sends each person to their own home: applicants to their applications,
// staff to their queue.
export default async function Home() {
  const me = await getMe();
  redirect(me ? homeFor(me) : "/login");
}
