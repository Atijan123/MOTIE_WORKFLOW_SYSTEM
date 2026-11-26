import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { ActionForm, SubmitButton } from "@/components/ActionForm";
import { api } from "@/lib/api";
import { longDate } from "@/lib/dates";
import { requireUser } from "@/lib/session";
import type { Signatory, SignatoryCandidate, SignatoryList } from "@/lib/types";

import { addSignatory, removeSignatory } from "./actions";

export const metadata: Metadata = { title: "Authorised signatories" };

// [CONFIRM] The Director's office (backend/app/core/workflow/signatories.py ADMIN_ROLE).
const ADMIN_ROLE = "signatory_admin";

// S12 (docs/SCREENS.md): the Director's office keeps the list of named officers
// who may sign while the Director is recorded absent. Nobody is deleted: a
// removed officer stays in "Earlier signatories" with when and by whom.
export default async function Signatories() {
  const me = await requireUser("staff");
  if (!me.roles.includes(ADMIN_ROLE)) notFound();
  const [lists, candidates] = await Promise.all([
    api<SignatoryList[]>("/signatories"),
    api<SignatoryCandidate[]>("/signatories/candidates"),
  ]);
  return (
    <>
      <div className="stack">
        <h1 className="title">Authorised signatories</h1>
        <p className="muted">
          While the Director is recorded absent, every officer on a list sees the files waiting for the Director’s signature
          in their queue. The first to sign takes the file. Each signature records the officer’s name and that they signed in
          the Director’s absence. Cement facility letters are signed by the Minister or the Permanent Secretary only; no list
          applies to them.
        </p>
      </div>
      {lists.map((list) => (
        <ListCard key={list.code} list={list} candidates={candidates} myId={me.id} />
      ))}
    </>
  );
}

function ListCard({ list, candidates, myId }: { list: SignatoryList; candidates: SignatoryCandidate[]; myId: number }) {
  const onList = new Set(list.current.map((m) => m.user_id));
  // Not yourself: someone else in the office must add you (the API refuses it too).
  const addable = candidates.filter((c) => !onList.has(c.user_id) && c.user_id !== myId);
  const headingId = `list-${list.code}`;
  return (
    <section className="card card-flush" aria-labelledby={headingId}>
      <div className="card-head stack">
        <h2 id={headingId} style={{ fontSize: 16 }}>
          {list.name}
        </h2>
        <span className="small muted" style={{ fontWeight: 400 }}>
          Used for:{" "}
          {list.used_for.map((u) => `${u.workflow_name} (the ${u.position_title}’s step)`).join("; ")}
        </span>
      </div>

      {list.current.length ? (
        <div className="table-wrap">
          <table className="table" aria-label="Current signatories">
            <thead>
              <tr>
                <th>Officer</th>
                <th>Post</th>
                <th>Added</th>
                <th>Added by</th>
                <th>
                  <span className="visually-hidden">Remove</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {list.current.map((m) => (
                <tr key={m.id}>
                  <td>{m.name}</td>
                  <td>{posts(m)}</td>
                  <td>{longDate(m.added_at)}</td>
                  <td>{m.added_by}</td>
                  <td>
                    <ActionForm action={removeSignatory.bind(null, m.id, m.name)} aria-label={`Remove ${m.name}`}>
                      <SubmitButton className="btn btn-small">Remove</SubmitButton>
                    </ActionForm>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="warn-text" style={{ padding: 16 }}>
          Nobody is on this list: while the Director is away, nobody can sign these files.
        </p>
      )}

      {/* A select's label is separate (htmlFor), not wrapped around it (see S11). */}
      <ActionForm action={addSignatory.bind(null, list.code)} aria-label={`Add to ${list.name}`}>
        <div style={{ padding: 16, display: "flex", gap: 12, alignItems: "flex-end", flexWrap: "wrap" }}>
          <div className="field">
            <label htmlFor={`add-${list.code}`}>Add an officer</label>
            <select id={`add-${list.code}`} name="user_id" required defaultValue="">
              <option value="" disabled>
                Choose the officer
              </option>
              {addable.map((c) => (
                <option key={c.user_id} value={c.user_id}>
                  {c.name}
                  {c.posts.length ? ` (${c.posts.join(", ")})` : ""}
                </option>
              ))}
            </select>
          </div>
          <SubmitButton className="btn">Add</SubmitButton>
        </div>
      </ActionForm>

      {list.past.length ? (
        <details style={{ padding: "0 16px 16px" }}>
          <summary>Earlier signatories ({list.past.length})</summary>
          <div className="table-wrap">
            <table className="table" aria-label="Earlier signatories">
              <thead>
                <tr>
                  <th>Officer</th>
                  <th>Post</th>
                  <th>Added</th>
                  <th>Removed</th>
                  <th>Removed by</th>
                </tr>
              </thead>
              <tbody>
                {list.past.map((m) => (
                  <tr key={m.id}>
                    <td>{m.name}</td>
                    <td>{posts(m)}</td>
                    <td>
                      {longDate(m.added_at)} by {m.added_by}
                    </td>
                    <td>{longDate(m.removed_at!)}</td>
                    <td>{m.removed_by}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      ) : null}
    </section>
  );
}

function posts(m: Signatory): string {
  return m.posts.length ? m.posts.join(", ") : "No post";
}
