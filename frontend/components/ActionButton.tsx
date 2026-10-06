"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { callApi } from "@/lib/client";

interface Props {
  path: string;
  method?: string;
  body?: unknown;
  children: React.ReactNode;
  variant?: "primary" | "danger" | "";
  size?: "sm" | "";
  confirm?: string;
  done?: string;
}

/** Fires an API call, shows errors inline and refreshes server data on success. */
export default function ActionButton({ path, method = "POST", body, children, variant = "", size = "", confirm, done }: Props) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  async function run() {
    if (confirm && !window.confirm(confirm)) return;
    setBusy(true);
    setMsg(null);
    try {
      await callApi(path, method, body);
      if (done) setMsg({ ok: true, text: done });
      router.refresh();
    } catch (e) {
      setMsg({ ok: false, text: (e as Error).message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <span className="row" style={{ gap: 6 }}>
      <button className={`btn ${variant} ${size}`} onClick={run} disabled={busy}>
        {busy ? "…" : children}
      </button>
      {msg && <span className={msg.ok ? "small muted" : "error"}>{msg.text}</span>}
    </span>
  );
}
