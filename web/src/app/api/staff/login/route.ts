import { NextResponse } from "next/server";

import { api, ApiError } from "@/lib/api";
import {
  SESSION_COOKIE_NAME,
  SESSION_MAX_AGE_SECONDS,
} from "@/lib/session-config";

export async function POST(request: Request) {
  let payload: { email?: unknown; password?: unknown };
  try {
    payload = (await request.json()) as typeof payload;
  } catch {
    return NextResponse.json({ detail: "登入資料格式錯誤" }, { status: 400 });
  }

  const email = typeof payload.email === "string" ? payload.email.trim() : "";
  const password =
    typeof payload.password === "string" ? payload.password : "";
  if (!email || !password) {
    return NextResponse.json({ detail: "請輸入員工電郵和密碼" }, { status: 400 });
  }

  try {
    const session = await api.login({ email, password });
    const principal = await api.currentPrincipal(session.token);
    if (!principal.internal) {
      await api.logout(session.token).catch(() => null);
      return NextResponse.json(
        { detail: "此帳戶沒有內部系統權限" },
        { status: 403 },
      );
    }

    const response = NextResponse.json({ user: session.user });
    response.cookies.set({
      name: SESSION_COOKIE_NAME,
      value: session.token,
      httpOnly: true,
      secure: process.env.NODE_ENV === "production",
      sameSite: "lax",
      path: "/",
      maxAge: SESSION_MAX_AGE_SECONDS,
    });
    return response;
  } catch (error) {
    const status = error instanceof ApiError ? error.status : 500;
    const detail =
      error instanceof Error ? error.message : "員工登入服務暫時無法使用";
    return NextResponse.json({ detail }, { status });
  }
}
