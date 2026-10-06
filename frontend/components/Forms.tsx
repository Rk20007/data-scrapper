"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { callApi } from "@/lib/client";
import { CLUSTERS } from "@/lib/format";

function useSubmit() {
  const router = useRouter();
  const [err, setErr] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  async function run(fn: () => Promise<string | void>) {
    setBusy(true);
    setErr(null);
    setOk(null);
    try {
      const msg = await fn();
      if (msg) setOk(msg);
      router.refresh();
      return true;
    } catch (e) {
      setErr((e as Error).message);
      return false;
    } finally {
      setBusy(false);
    }
  }
  return { err, ok, busy, run };
}

function formData(e: React.FormEvent<HTMLFormElement>) {
  return Object.fromEntries(
    [...new FormData(e.currentTarget).entries()].map(([k, v]) => [k, typeof v === "string" && v.trim() === "" ? null : v]),
  );
}

export function AddCompanyForm() {
  const s = useSubmit();
  return (
    <form
      className="filters"
      onSubmit={async (e) => {
        e.preventDefault();
        const form = e.currentTarget;
        const data = formData(e);
        if (await s.run(async () => { await callApi("/companies", "POST", data); return "Added"; })) form.reset();
      }}
    >
      <label className="field">Company name<input name="name" required /></label>
      <label className="field">Website<input name="website" placeholder="https://…" /></label>
      <label className="field">Cluster
        <select name="cluster" defaultValue="">
          <option value="">—</option>
          {CLUSTERS.map((c) => <option key={c}>{c}</option>)}
        </select>
      </label>
      <label className="field">Industry<input name="industry" /></label>
      <button className="btn primary" disabled={s.busy}>Add company</button>
      {s.ok && <span className="small muted">{s.ok}</span>}
      {s.err && <span className="error">{s.err}</span>}
    </form>
  );
}

export function ImportCsvForm() {
  const s = useSubmit();
  return (
    <form
      className="row"
      onSubmit={async (e) => {
        e.preventDefault();
        const fd = new FormData(e.currentTarget);
        await s.run(async () => {
          const r = await callApi<{ imported: number }>("/companies/import", "POST", fd);
          return `Imported ${r.imported}`;
        });
      }}
    >
      <input type="file" name="file" accept=".csv" required />
      <button className="btn" disabled={s.busy}>Import CSV</button>
      <span className="small muted">columns: name, website, cluster, industry</span>
      {s.ok && <span className="small muted">{s.ok}</span>}
      {s.err && <span className="error">{s.err}</span>}
    </form>
  );
}

export function AddContactForm({ companyId }: { companyId: number }) {
  const s = useSubmit();
  return (
    <form
      className="filters"
      onSubmit={async (e) => {
        e.preventDefault();
        const form = e.currentTarget;
        const data = { ...formData(e), company_id: companyId };
        if (await s.run(async () => { await callApi("/contacts", "POST", data); return "Added"; })) form.reset();
      }}
    >
      <label className="field">Name<input name="name" /></label>
      <label className="field">Title<input name="title" placeholder="e.g. Head – Projects" /></label>
      <label className="field">Email<input name="email" type="email" /></label>
      <label className="field">Phone<input name="phone" /></label>
      <label className="field">Public source URL<input name="source_url" placeholder="where you found it" /></label>
      <button className="btn" disabled={s.busy}>Add contact</button>
      {s.err && <span className="error">{s.err}</span>}
    </form>
  );
}

export function AddSourceForm() {
  const s = useSubmit();
  const [kind, setKind] = useState("news_rss");
  return (
    <form
      className="filters"
      onSubmit={async (e) => {
        e.preventDefault();
        const form = e.currentTarget;
        const d = formData(e) as Record<string, string | null>;
        const config: Record<string, unknown> = {};
        if (d.query) config.query = d.query;
        if (kind === "listing") config.only_documents = d.only_documents === "on";
        const payload = { name: d.name, kind, url: d.url, config, interval_minutes: Number(d.interval_minutes ?? 360) };
        if (await s.run(async () => { await callApi("/sources", "POST", payload); return "Added"; })) form.reset();
      }}
    >
      <label className="field">Name<input name="name" required /></label>
      <label className="field">Kind
        <select value={kind} onChange={(e) => setKind(e.target.value)}>
          <option value="news_rss">News query (Google News RSS)</option>
          <option value="search">Web search query</option>
          <option value="listing">Notice / listing page</option>
          <option value="tender_table">Tender table page</option>
        </select>
      </label>
      {(kind === "news_rss" || kind === "search") && (
        <label className="field">Query<input name="query" placeholder='"Neemrana" warehouse' required={kind === "search"} /></label>
      )}
      {(kind === "listing" || kind === "tender_table" || kind === "news_rss") && (
        <label className="field">URL{kind === "news_rss" ? " (optional RSS feed)" : ""}<input name="url" required={kind !== "news_rss"} /></label>
      )}
      {kind === "listing" && (
        <label className="field">Only document links<input type="checkbox" name="only_documents" /></label>
      )}
      <label className="field">Every (min)<input name="interval_minutes" type="number" min={30} defaultValue={360} style={{ width: 90 }} /></label>
      <button className="btn primary" disabled={s.busy}>Add source</button>
      {s.err && <span className="error">{s.err}</span>}
    </form>
  );
}

export function SuppressionForm() {
  const s = useSubmit();
  return (
    <form
      className="filters"
      onSubmit={async (e) => {
        e.preventDefault();
        const form = e.currentTarget;
        const data = formData(e);
        if (await s.run(async () => { await callApi("/suppressions", "POST", data); return "Added"; })) form.reset();
      }}
    >
      <label className="field">Email<input name="email" type="email" /></label>
      <label className="field">or whole domain<input name="domain" placeholder="example.com" /></label>
      <label className="field">Note<input name="note" /></label>
      <button className="btn">Suppress</button>
      {s.err && <span className="error">{s.err}</span>}
    </form>
  );
}
