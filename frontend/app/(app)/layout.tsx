import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import Nav from "@/components/Nav";
import { TOKEN_COOKIE } from "@/lib/api";

// Auth gate for every dashboard page (runs on the Node.js server, not Edge middleware).
export default async function AppLayout({ children }: { children: React.ReactNode }) {
  if (!(await cookies()).get(TOKEN_COOKIE)) redirect("/login");
  return (
    <div className="shell">
      <Nav />
      <main className="main">{children}</main>
    </div>
  );
}
