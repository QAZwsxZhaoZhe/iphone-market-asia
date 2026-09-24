import { NextResponse } from "next/server";

import { api } from "@/lib/api";
import { getSessionToken } from "@/lib/session";
import { SESSION_COOKIE_NAME } from "@/lib/session-config";

export async function POST() {
  const token = await getSessionToken();
  if (token) {
    try {
      await api.logout(token);
    } catch {
      // Clearing the local session is still the correct user-visible outcome.
    }
  }

  const response = NextResponse.json({ ok: true });
  response.cookies.set({
    name: SESSION_COOKIE_NAME,
    value: "",
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge: 0,
  });
  return response;
}
