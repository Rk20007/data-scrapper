"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/", label: "Dashboard" },
  { href: "/leads", label: "Leads" },
  { href: "/leads?kind=tender", label: "Tenders" },
  { href: "/companies", label: "Companies" },
  { href: "/emails", label: "Email queue" },
  { href: "/sources", label: "Sources" },
  { href: "/settings", label: "Settings" },
];

export default function Nav() {
  const path = usePathname();
  async function logout() {
    await fetch("/api/session", { method: "DELETE" });
    window.location.href = "/login";
  }
  return (
    <aside className="sidebar">
      <div className="brand">
        Lead Engine
        <small>Bhiwadi · Neemrana belt</small>
      </div>
      <nav className="nav">
        {LINKS.map((l) => {
          const base = l.href.split("?")[0];
          const active = base === "/" ? path === "/" : path.startsWith(base) && !l.href.includes("?");
          return (
            <Link key={l.href} href={l.href} className={active ? "active" : ""}>
              {l.label}
            </Link>
          );
        })}
      </nav>
      <div className="spacer" />
      <button className="btn sm" onClick={logout}>
        Sign out
      </button>
    </aside>
  );
}
