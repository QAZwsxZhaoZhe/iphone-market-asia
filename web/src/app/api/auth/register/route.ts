import { NextResponse } from "next/server";

import { api, ApiError } from "@/lib/api";
import {
  SESSION_COOKIE_NAME,
  SESSION_MAX_AGE_SECONDS,
} from "@/lib/session-config";

export async function POST(request: Request) {
  let payload: {
    email?: unknown;
    password?: unknown;
    display_name?: unknown;
  };
  try {
    payload = (await request.json()) as typeof payload;
  } catch {
    return NextResponse.json({ detail: "註冊資料格式錯誤" }, { status: 400 });
  }

  const email = typeof payload.email === "string" ? payload.email.trim() : "";
  const password =
    typeof payload.password === "string" ? payload.password : "";
  const displayName =
    typeof payload.display_name === "string"
      ? payload.display_name.trim()
      : "";
  if (!email || !password || !displayName) {
    return NextResponse.json(
      { detail: "請填寫名稱、電子郵件和密碼" },
      { status: 400 },
    );
  }

  try {
    const session = await api.register({
      email,
      password,
      display_name: displayName,
    });
    const response = NextResponse.json({ user: session.user }, { status: 201 });
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
      error instanceof Error ? error.message : "註冊服務暫時無法使用";
    return NextResponse.json({ detail }, { status });
  }
}
