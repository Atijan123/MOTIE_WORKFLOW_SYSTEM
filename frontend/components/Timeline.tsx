import { longDate } from "@/lib/dates";
import { stepsAhead } from "@/lib/labels";
import type { TimelineEntry } from "@/lib/types";

const Tick = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#FFFFFF" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M5 12l5 5L20 7" />
  </svg>
);

/** The applicant's timeline: steps taken (with dates), the current one, and those ahead (greyed). */
export function Timeline({ entries, explanation }: { entries: TimelineEntry[]; explanation?: string | null }) {
  const current = entries.at(-1);
  const ahead = current ? stepsAhead(current.label) : [];
  const total = entries.length + ahead.length;
  return (
    <ol className="timeline">
      {entries.map((e, i) => {
        const isNow = i === entries.length - 1;
        const warn = isNow && (e.label.startsWith("Returned") || e.label === "Rejected");
        const last = i === total - 1;
        return (
          <li key={`${e.occurred_at}-${i}`}>
            <div className="tl-marks">
              <span className={`tl-dot ${isNow && !last ? (warn ? "warn" : "now") : "done"}`}>{isNow && !last ? null : <Tick />}</span>
              {last ? null : <span className={`tl-line ${isNow ? "" : "done"}`} />}
            </div>
            <div className="tl-text">
              <span className="tl-label">
                {e.label}
                {isNow && !last ? " (now)" : ""}
              </span>
              <span className="small muted">{longDate(e.occurred_at)}</span>
              {isNow && explanation ? <span className="small muted">{explanation}</span> : null}
              {e.message ? <span className="small warn-text">“{e.message}”</span> : null}
            </div>
          </li>
        );
      })}
      {ahead.map((label, i) => (
        <li key={label}>
          <div className="tl-marks">
            <span className="tl-dot" />
            {i === ahead.length - 1 ? null : <span className="tl-line" />}
          </div>
          <div className="tl-text tl-future">{label}</div>
        </li>
      ))}
    </ol>
  );
}
