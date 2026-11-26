import { TopBar } from "@/components/TopBar";
import { requireUser } from "@/lib/session";

// Every applicant page: the header with their name and "Sign out".
export default async function ApplicantLayout({ children }: { children: React.ReactNode }) {
  const me = await requireUser("applicant");
  return (
    <>
      <TopBar who={me.full_name} home="/applications" />
      {children}
    </>
  );
}
