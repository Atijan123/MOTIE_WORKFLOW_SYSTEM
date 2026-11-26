import type { Metadata } from "next";

import { ActionForm, SubmitButton } from "@/components/ActionForm";
import { api } from "@/lib/api";
import { dayRange, todayIso } from "@/lib/dates";
import { requireUser } from "@/lib/session";
import type { AbsenceView, Choices, CoverForPost } from "@/lib/types";

import { cancelAbsence, recordAbsenceFor, recordMyAbsence, revokeDelegation } from "./actions";

export const metadata: Metadata = { title: "Absences and delegations" };

// [CONFIRM] Who may record for others (backend/app/core/workflow/absence.py RECORDER_ROLE).
const RECORDER_ROLE = "absence_recorder";

// S11 (docs/design/Absences.dc.html): record my absence (optionally handing my
// files to another post), see who acts for me, record for someone else if I'm
// allowed to, and the list of everyone away now or soon.
export default async function Absences() {
  const me = await requireUser("staff");
  const [cover, absences, choices] = await Promise.all([
    api<CoverForPost[]>("/acting/for-me"),
    api<AbsenceView[]>("/absences/current"),
    api<Choices>("/acting/options"),
  ]);
  const workflowName = (code: string | null) =>
    code === null ? "all services" : choices.workflows.find((w) => w.code === code)?.name ?? code;
  const today = todayIso();
  const isRecorder = me.roles.includes(RECORDER_ROLE);
  const anyReason = absences.some((a) => a.reason);

  return (
    <>
      <h1 className="title">Absences and delegations</h1>

      {cover.length ? (
        <section className="card" aria-labelledby="away">
          <h2 id="away">I will be away</h2>
          {cover.map((post) => (
            <CoverText key={post.position} post={post} workflowName={workflowName} />
          ))}
          {/* A select's label is separate (htmlFor), not wrapped around it: wrapped, browsers
              add the chosen option to its name ("For All services"). */}
          <ActionForm action={recordMyAbsence} className="stack-lg" aria-label="Record my absence">
            <div className="grid-3">
              <label className="field">
                From
                <input type="date" name="starts_on" min={today} defaultValue={today} required />
              </label>
              <label className="field">
                To
                <input type="date" name="ends_on" min={today} required />
              </label>
              <label className="field">
                Reason (optional)
                <input name="reason" maxLength={500} placeholder="Only you and the recorders see it" />
              </label>
            </div>
            <fieldset>
              <legend>Or delegate to a different post (optional)</legend>
              <div className="grid-3">
                {cover.length > 1 ? (
                  <div className="field">
                    <label htmlFor="from_position">From my post</label>
                    <select id="from_position" name="from_position">
                      {cover.map((p) => (
                        <option key={p.position} value={p.position}>
                          {p.title}
                        </option>
                      ))}
                    </select>
                  </div>
                ) : (
                  <input type="hidden" name="from_position" value={cover[0].position} />
                )}
                <div className="field">
                  <label htmlFor="to_position">Delegate to</label>
                  <select id="to_position" name="to_position" defaultValue="">
                    <option value="">No, use the succession order</option>
                    {choices.posts
                      .filter((p) => !cover.some((c) => c.position === p.code))
                      .map((p) => (
                        <option key={p.code} value={p.code}>
                          {p.title}
                          {p.holders.length ? "" : " (vacant)"}
                        </option>
                      ))}
                  </select>
                </div>
                <div className="field">
                  <label htmlFor="workflow">For</label>
                  <select id="workflow" name="workflow" defaultValue="">
                    <option value="">All services</option>
                    {choices.workflows.map((w) => (
                      <option key={w.code} value={w.code}>
                        {w.name}
                      </option>
                    ))}
                  </select>
                </div>
              </div>
            </fieldset>
            <div className="row">
              <SubmitButton>Record my absence</SubmitButton>
            </div>
          </ActionForm>
        </section>
      ) : null}

      {isRecorder ? (
        <section className="card" aria-labelledby="for-someone">
          <div className="stack">
            <h2 id="for-someone">Record for someone else</h2>
            <p className="small muted">Only for offices allowed to record absences. Recorded as entered by you.</p>
          </div>
          <ActionForm action={recordAbsenceFor} className="stack-lg" aria-label="Record an absence for someone else">
            <div className="grid-2">
              <div className="field">
                <label htmlFor="user_id">Who is away</label>
                <select id="user_id" name="user_id" required defaultValue="">
                  <option value="" disabled>
                    Choose the post
                  </option>
                  {choices.posts.flatMap((p) =>
                    p.holders.map((h) => (
                      <option key={`${p.code}-${h.user_id}`} value={h.user_id}>
                        {p.title}: {h.name}
                      </option>
                    )),
                  )}
                </select>
              </div>
              <label className="field">
                Reason (optional)
                <input name="reason" maxLength={500} />
              </label>
              <label className="field">
                From
                <input type="date" name="starts_on" min={today} defaultValue={today} required />
              </label>
              <label className="field">
                To
                <input type="date" name="ends_on" min={today} required />
              </label>
            </div>
            <div className="row">
              <SubmitButton>Record absence</SubmitButton>
            </div>
          </ActionForm>
        </section>
      ) : null}

      <section className="card card-flush" aria-labelledby="current">
        <h2 className="card-head" id="current">
          Current and upcoming absences
        </h2>
        <p className="small muted" style={{ padding: "12px 16px 0" }}>
          Who acts is worked out for the first day of each absence, or today if it has started.
        </p>
        {absences.length ? (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Who</th>
                  <th>Post</th>
                  <th>Dates</th>
                  <th>Who acts</th>
                  <th>Recorded by</th>
                  {anyReason ? <th>Reason</th> : null}
                  <th>
                    <span className="visually-hidden">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {absences.map((a) => (
                  <tr key={a.id}>
                    <td>{a.person}</td>
                    <td>{a.posts.join(", ")}</td>
                    <td>{dayRange(a.starts_on, a.ends_on)}</td>
                    <td>
                      <WhoActs absence={a} workflowName={workflowName} />
                    </td>
                    <td>{a.recorded_by_self ? "Themselves" : a.recorded_by}</td>
                    {anyReason ? <td>{a.reason ?? ""}</td> : null}
                    <td>
                      {a.may_cancel ? (
                        <ActionForm action={cancelAbsence.bind(null, a.id)} aria-label={`Cancel the absence of ${a.person}`}>
                          <SubmitButton className="btn btn-small">{a.starts_on <= today ? "End early" : "Cancel"}</SubmitButton>
                        </ActionForm>
                      ) : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="muted" style={{ padding: 16 }}>
            Nobody is recorded as away.
          </p>
        )}
      </section>
    </>
  );
}

const BASIS: Record<AbsenceView["who_acts"][number]["basis"], string> = {
  delegation: "delegation",
  succession: "succession",
  signatory: "authorised signatories",
  same_post: "same post",
};

/** "Deputy Permanent Secretary, … (Dev Deputy PS), succession", one line per stand-in. */
function WhoActs({ absence, workflowName }: { absence: AbsenceView; workflowName: (code: string | null) => string }) {
  if (!absence.who_acts.length) return <span className="warn-text">Nobody at work to act (succession order or signatories list)</span>;
  return (
    <div className="stack">
      {absence.who_acts.map((w) => (
        <span key={`${w.position}-${w.basis}`}>
          {w.title}
          {w.holders.length ? ` (${w.holders.join(", ")})` : ""}
          <span className="muted">
            , {BASIS[w.basis]}
            {w.workflows ? `, for ${w.workflows.map(workflowName).join(" and ")}` : ""}
          </span>
        </span>
      ))}
    </div>
  );
}

/** "While you are away, …": my delegations (with Revoke), else the succession order. */
function CoverText({ post, workflowName }: { post: CoverForPost; workflowName: (code: string | null) => string }) {
  return (
    <div className="stack-lg">
      {post.delegations.map((d) => (
        <ActionForm action={revokeDelegation.bind(null, d.id)} className="notice notice-info" key={d.id} aria-label={`Delegation to the ${d.to_title}`}>
          <div className="spread">
            <span>
              Your files as {post.title} for {workflowName(d.workflow)} are delegated to the <strong>{d.to_title}</strong>,{" "}
              {dayRange(d.starts_on, d.ends_on)}.
            </span>
            <SubmitButton className="btn btn-small">Revoke</SubmitButton>
          </div>
        </ActionForm>
      ))}
      {post.succession.length ? (
        <div className="stack">
          <span>
            While you are away{post.delegations.length ? " and nothing is delegated" : ""}:
          </span>
          <ul className="small" style={{ margin: 0, paddingLeft: 20 }}>
            {post.succession.map((s) => (
              <li key={s.workflow}>
                {workflowName(s.workflow)}:{" "}
                {s.signatories
                  ? s.signatories.length
                    ? `any officer on the authorised signatories list can sign (${s.signatories.join(", ")})`
                    : "the authorised signatories list is empty, so nobody can sign: ask the Director's office"
                  : `under the agreed succession order, ${s.line
                      .map((stand) => `the ${stand.title}${stand.holders.length ? ` (${stand.holders.join(", ")})` : " (vacant)"}`)
                      .join(", then ")}`}
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <span className="small muted">
          No succession order covers your post as {post.title}: delegate to another post if your files must move while you are away.
        </span>
      )}
    </div>
  );
}
