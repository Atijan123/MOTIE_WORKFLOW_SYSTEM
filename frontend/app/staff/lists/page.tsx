import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { ActionForm, SubmitButton } from "@/components/ActionForm";
import { api } from "@/lib/api";
import { requireUser } from "@/lib/session";

import { addListItem, renameListItem, setListItemActive, type ListKind } from "./actions";

export const metadata: Metadata = { title: "Lists" };

type Item = { id: number; name: string; active: boolean; sort_order: number };

const TITLES: Record<ListKind, { title: string; hint: string }> = {
  countries: { title: "Exporter countries", hint: "Offered in “Country” on the facility letter form." },
  units: { title: "Units", hint: "Offered in “Unit” next to the quantity." },
};

// The lists the facility letter form picks from, for admins (migration 0039).
// No delete: an entry is switched off, so applications that used it still read right.
export default async function Lists() {
  const me = await requireUser("staff");
  if (!me.roles.includes("admin")) notFound();
  const lists = await api<Record<ListKind, Item[]>>("/etls/lists");
  return (
    <>
      <div className="stack">
        <h1 className="title">Lists</h1>
        <p className="muted">
          What the facility letter form offers. Switching an entry off stops new applications using it; applications that
          already did keep it. Renaming doesn’t change applications already saved.
        </p>
      </div>
      {(Object.keys(TITLES) as ListKind[]).map((kind) => (
        <section className="card card-flush" aria-labelledby={`list-${kind}`} key={kind}>
          <div className="card-head stack">
            <h2 id={`list-${kind}`} style={{ fontSize: 16 }}>
              {TITLES[kind].title}
            </h2>
            <span className="small muted" style={{ fontWeight: 400 }}>
              {TITLES[kind].hint}
            </span>
          </div>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Offered</th>
                  <th>
                    <span className="visually-hidden">Switch on or off</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {lists[kind].map((item) => (
                  <tr key={item.id} className={item.active ? undefined : "muted"}>
                    <td>
                      <ActionForm action={renameListItem.bind(null, kind, item.id)} className="row" aria-label={`Rename ${item.name}`}>
                        <input name="name" defaultValue={item.name} required maxLength={100} aria-label={`Name of ${item.name}`} style={{ maxWidth: 280 }} />
                        <SubmitButton className="btn btn-small">Rename</SubmitButton>
                      </ActionForm>
                    </td>
                    <td>{item.active ? "Yes" : "No, switched off"}</td>
                    <td>
                      <ActionForm action={setListItemActive.bind(null, kind, item.id, !item.active)} aria-label={`Switch ${item.name} ${item.active ? "off" : "on"}`}>
                        <SubmitButton className="btn btn-small">{item.active ? "Switch off" : "Switch back on"}</SubmitButton>
                      </ActionForm>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <ActionForm action={addListItem.bind(null, kind)} className="row row-end" aria-label={`Add to ${TITLES[kind].title}`}>
            <div style={{ padding: 16, display: "flex", gap: 12, alignItems: "flex-end", flexWrap: "wrap" }}>
              <label className="field">
                New entry
                <input name="name" required maxLength={100} />
              </label>
              <SubmitButton className="btn">Add</SubmitButton>
            </div>
          </ActionForm>
        </section>
      ))}
    </>
  );
}
