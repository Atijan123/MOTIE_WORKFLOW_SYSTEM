import { ActingBanner } from "@/components/ActingBanner";
import { NavLink } from "@/components/NavLink";
import { TopBar } from "@/components/TopBar";
import { api } from "@/lib/api";
import { mayViewStatistics, requireUser } from "@/lib/session";
import type { ActingNow, CaseSummary } from "@/lib/types";

// Every staff page: header with the post, the acting banner, and the menu.
export default async function StaffLayout({ children }: { children: React.ReactNode }) {
  const me = await requireUser("staff");
  const [acting, queue, outgoing] = await Promise.all([
    api<ActingNow[]>("/acting"),
    api<CaseSummary[]>("/cases/queue"),
    api<CaseSummary[]>("/cases/queue?status=signed"),
  ]);
  // Signed letters wait in Records' queue for dispatch: they get their own tab.
  const toDispatch = outgoing.filter((c) => c.available_actions.some((a) => a.to_status === "sent_to_gra"));
  const work = queue.filter((c) => !toDispatch.some((d) => d.id === c.id));
  return (
    <>
      <TopBar subtitle="ETLS Services · Staff" who={me.position_titles.join(", ") || me.full_name} home="/staff" />
      <ActingBanner acting={acting} />
      <div className="shell">
        <nav aria-label="Staff menu" className="side-nav">
          <NavLink href="/staff" exact>
            My queue {work.length ? <span className="count">{work.length}</span> : null}
          </NavLink>
          {toDispatch.length || me.positions.includes("records_officer") ? (
            <NavLink href="/staff/outgoing">
              Outgoing {toDispatch.length ? <span className="count">{toDispatch.length}</span> : null}
            </NavLink>
          ) : null}
          <NavLink href="/staff/absences">Absences</NavLink>
          {me.roles.includes("admin") ? <NavLink href="/staff/lists">Lists</NavLink> : null}
          {me.roles.includes("signatory_admin") ? <NavLink href="/staff/signatories">Signatories</NavLink> : null}
          {mayViewStatistics(me) ? <NavLink href="/staff/statistics">Statistics</NavLink> : null}
        </nav>
        <main className="staff-main">{children}</main>
      </div>
    </>
  );
}
