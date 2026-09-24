import { NextResponse, type NextRequest } from "next/server";

import { SESSION_COOKIE_NAME } from "@/lib/session-config";

export function proxy(request: NextRequest) {
  const hasSession = Boolean(
    request.cookies.get(SESSION_COOKIE_NAME)?.value,
  );
  if (!hasSession) {
    const internalPath =
      request.nextUrl.pathname === "/ops" ||
      request.nextUrl.pathname.startsWith("/ops/") ||
      request.nextUrl.pathname === "/m" ||
      request.nextUrl.pathname.startsWith("/m/");
    const loginUrl = new URL(
      internalPath ? "/staff/login" : "/login",
      request.url,
    );
    loginUrl.searchParams.set(
      "next",
      `${request.nextUrl.pathname}${request.nextUrl.search}`,
    );
    return NextResponse.redirect(loginUrl);
  }
  return NextResponse.next();
}

export const config = {
  matcher: [
    "/ops/:path*",
    "/m/:path*",
    "/account/:path*",
    "/seller/:path*",
  ],
};
