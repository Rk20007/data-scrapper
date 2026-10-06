import { NextRequest, NextResponse } from "next/server";

import { backendUrl, TOKEN_COOKIE } from "@/lib/api";

export async function POST(req: NextRequest) {
  const body = await req.json().catch(() => ({}));
  const res = await fetch(`${backendUrl()}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email: body.email ?? "", password: body.password ?? "" }),
  });
  if (!res.ok) return NextResponse.json({ detail: "Invalid email or password" }, { status: 401 });
  const { access_token } = await res.json();
  const out = NextResponse.json({ ok: true });
  out.cookies.set(TOKEN_COOKIE, access_token, {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.COOKIE_SECURE === "true",
    path: "/",
    maxAge: 60 * 60 * 24,
  });
  return out;
}

export async function DELETE() {
  const out = NextResponse.json({ ok: true });
  out.cookies.delete(TOKEN_COOKIE);
  return out;
}
