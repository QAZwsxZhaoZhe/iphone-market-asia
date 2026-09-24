import { ArrowLeft, ServerCog, ShieldCheck } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";

import { StaffAuthForm } from "@/components/staff-auth-form";
import { api } from "@/lib/api";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "內部員工登入",
  robots: { index: false, follow: false },
};

type SearchParams = Promise<{
  next?: string | string[];
  error?: string | string[];
}>;

function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

function safeStaffNextPath(value: string | undefined): string {
  if (!value || !value.startsWith("/") || value.startsWith("//")) {
    return "/ops";
  }
  const path = value.split("?")[0];
  if (path === "/ops" || path.startsWith("/ops/")) {
    return value;
  }
  if (path === "/m" || path.startsWith("/m/")) {
    return value;
  }
  return "/ops";
}

export default async function StaffLoginPage({
  searchParams,
}: {
  searchParams: SearchParams;
}) {
  const params = await searchParams;
  const nextPath = safeStaffNextPath(first(params.next));
  const principal = await api.currentPrincipal().catch(() => null);
  if (principal?.internal) {
    redirect(nextPath);
  }

  return (
    <main className="staff-login">
      <section className="staff-login__context">
        <div className="staff-login__brand">
          <span aria-hidden="true">
            <ServerCog size={20} />
          </span>
          <div>
            <strong>HK PHONE ERP</strong>
            <small>內部營運系統</small>
          </div>
        </div>

        <div className="staff-login__message">
          <span className="eyebrow">Internal access</span>
          <h1>員工專用入口</h1>
          <p>
            商品、訂單、結算、來源健康與內部帳戶只在此營運系統處理。
          </p>
        </div>

        <div className="staff-login__roles">
          <span>
            <ShieldCheck size={15} aria-hidden="true" />
            管理員
          </span>
          <span>營運</span>
          <span>分析</span>
        </div>
      </section>

      <section className="staff-login__panel">
        <div className="staff-login__card">
          <header>
            <span className="eyebrow">Staff sign in</span>
            <h2>登入營運台</h2>
            <p>公開買家帳戶不能登入此入口。</p>
          </header>

          {first(params.error) === "forbidden" ? (
            <div className="form-alert form-alert--error" role="alert">
              此帳戶沒有內部系統權限。
            </div>
          ) : null}

          <StaffAuthForm nextPath={nextPath} />

          <Link className="staff-login__back" href="/">
            <ArrowLeft size={15} aria-hidden="true" />
            返回公開網站
          </Link>
        </div>
      </section>
    </main>
  );
}
