import Link from "next/link";

import { logout } from "@/app/login/actions";

/** The navy bar at the top of every page (docs/design/*). */
export function TopBar({ subtitle = "ETLS Services", who, home = "/" }: { subtitle?: string; who?: string; home?: string }) {
  return (
    <header className="topbar">
      <Link href={home} className="brand">
        <span className="brand-name">MOTIE</span>
        <span className="brand-sub">{subtitle}</span>
      </Link>
      {who ? (
        <div className="topbar-user">
          <span>{who}</span>
          <form action={logout}>
            <button type="submit" className="link-button">
              Sign out
            </button>
          </form>
        </div>
      ) : null}
    </header>
  );
}
