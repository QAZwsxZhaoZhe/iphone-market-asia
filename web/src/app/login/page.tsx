import { ShieldCheck, Store } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";

import { AuthForm } from "@/components/auth-form";
import { api } from "@/lib/api";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "登入或註冊",
  robots: { index: false, follow: false },
};

type SearchParams = Promise<{
  mode?: string | string[];
  next?: string | string[];
  error?: string | string[];
}>;

function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

function safeNextPath(value: string | undefined): string {
  if (!value || !value.startsWith("/") || value.startsWith("//")) {
    return "/";
  }
  return value;
}

export default async function LoginPage({
  searchParams,
}: {
  searchParams: SearchParams;
}) {
  const params = await searchParams;
  const nextPath = safeNextPath(first(params.next));
  const requestedMode = first(params.mode);
  const mode = requestedMode === "register" ? "register" : "login";
  const principal = await api.currentPrincipal().catch(() => null);
  if (principal) {
    redirect(nextPath);
  }

  const meta = await api.meta().catch(() => null);
  const registrationEnabled = meta?.auth.public_registration ?? false;
  const loginHref = `/login${nextPath !== "/" ? `?next=${encodeURIComponent(nextPath)}` : ""}`;
  const registerHref = `/login?mode=register${nextPath !== "/" ? `&next=${encodeURIComponent(nextPath)}` : ""}`;

  return (
    <div className="auth-page">
      <section className="auth-intro">
        <span className="eyebrow">HK Phone Exchange</span>
        <h1>買得清楚，賣得安心。</h1>
        <p>
          香港二手 iPhone 平台，以平台代收貨款、驗機資料和可追溯交易流程為核心。
        </p>
        <div className="auth-trust">
          <span>
            <ShieldCheck size={16} aria-hidden="true" />
            平台代收貨款
          </span>
          <span>
            <Store size={16} aria-hidden="true" />
            香港首發
          </span>
        </div>
      </section>

      <section className="auth-panel">
        <div className="auth-tabs" role="tablist" aria-label="帳戶操作">
          <Link
            aria-selected={mode === "login"}
            className="auth-tab"
            data-active={mode === "login"}
            href={loginHref}
            role="tab"
          >
            登入
          </Link>
          <Link
            aria-selected={mode === "register"}
            className="auth-tab"
            data-active={mode === "register"}
            href={registerHref}
            role="tab"
          >
            買家註冊
          </Link>
        </div>

        {first(params.error) === "forbidden" ? (
          <div className="form-alert form-alert--error" role="alert">
            此帳戶沒有營運台權限。
          </div>
        ) : null}

        {mode === "register" && !registrationEnabled ? (
          <div className="form-alert" role="status">
            公開註冊目前未開放，請使用現有帳戶登入。
          </div>
        ) : null}

        <AuthForm
          mode={mode}
          nextPath={nextPath}
          registrationEnabled={registrationEnabled}
        />
      </section>
    </div>
  );
}
