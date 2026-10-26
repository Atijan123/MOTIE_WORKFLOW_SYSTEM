import { dayRange } from "@/lib/dates";
import type { ActingNow } from "@/lib/types";

/** "You are acting for the Director of Industry & Investment (absent 20th–24th October)" (SCREENS.md global rules). */
export function ActingBanner({ acting }: { acting: ActingNow[] }) {
  return (
    <>
      {acting.map((a) => {
        const when =
          a.basis === "delegation" && a.delegation_starts_on && a.delegation_ends_on
            ? `delegated to you ${dayRange(a.delegation_starts_on, a.delegation_ends_on)}`
            : a.absences.map((ab) => `${ab.person} absent ${dayRange(ab.starts_on, ab.ends_on)}`).join("; ");
        return (
          <div className="acting-banner" role="status" key={a.position}>
            <strong>You are acting for the {a.title}</strong>
            <span>
              {when ? `(${when}). ` : ""}
              Your actions are recorded as acting for the {a.title}.
              {a.workflows ? " This covers some services only." : ""}
            </span>
          </div>
        );
      })}
    </>
  );
}
