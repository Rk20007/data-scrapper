import { NextRequest, NextResponse } from "next/server";

import { backendUrl, TOKEN_COOKIE } from "@/lib/api";

async function proxy(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const token = req.cookies.get(TOKEN_COOKIE)?.value;
  if (!token) return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
  const { path } = await ctx.params;
  const target = `${backendUrl()}/api/${path.map(encodeURIComponent).join("/")}${req.nextUrl.search}`;
  const headers: Record<string, string> = { Authorization: `Bearer ${token}` };
  const ctype = req.headers.get("content-type");
  if (ctype) headers["Content-Type"] = ctype;
  const hasBody = !["GET", "HEAD"].includes(req.method);
  const res = await fetch(target, {
    method: req.method,
    headers,
    body: hasBody ? await req.arrayBuffer() : undefined,
    cache: "no-store",
  });
  return new NextResponse(res.body, {
    status: res.status,
    headers: { "Content-Type": res.headers.get("content-type") ?? "application/json" },
  });
}

export { proxy as GET, proxy as POST, proxy as PUT, proxy as PATCH, proxy as DELETE };
