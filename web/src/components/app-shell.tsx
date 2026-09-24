import {
  Activity,
  BarChart3,
  Database,
  LayoutDashboard,
  LogIn,
  ReceiptText,
  Search,
  ShoppingBag,
  Smartphone,
} from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { NavLink } from "@/components/nav-link";
import { SessionActions } from "@/components/session-actions";
import { api } from "@/lib/api";

export async function AppShell({ children }: { children: ReactNode }) {
  const principal = await api.currentPrincipal().catch(() => null);

  return (
    <>
      <header className="site-header">
        <div className="site-header__inner">
          <Link className="brand" href="/">
            <span className="brand__mark" aria-hidden="true">
              <Smartphone size={18} strokeWidth={2.2} />
            </span>
            <span className="brand__copy">
              <span className="brand__name">HK PHONE INDEX</span>
              <span className="brand__caption">全港二手手機數據聚合</span>
            </span>
          </Link>

          <nav className="site-nav" aria-label="主要導覽">
            <NavLink href="/store" icon={<ShoppingBag size={16} />}>
              商店
            </NavLink>
            <NavLink href="/" icon={<Search size={16} />}>
              搜尋
            </NavLink>
            <NavLink href="/market" icon={<BarChart3 size={16} />}>
              行情
            </NavLink>
            <NavLink href="/sources" icon={<Database size={16} />}>
              來源
            </NavLink>
            {principal?.email ? (
              <NavLink
                href="/account/orders"
                icon={<ReceiptText size={16} />}
              >
                訂單
              </NavLink>
            ) : null}
            {principal?.internal ? (
              <NavLink href="/ops" icon={<LayoutDashboard size={16} />}>
                營運台
              </NavLink>
            ) : null}
          </nav>

          <div className="header-actions">
            <div className="header-meta" aria-label="資料時區">
              <span className="live-dot" aria-hidden="true" />
              <Activity size={14} aria-hidden="true" />
              HKT · HKD
            </div>
            {principal?.email ? (
              <SessionActions
                email={principal.email}
                roles={principal.roles}
              />
            ) : (
              <Link className="session-login" href="/login">
                <LogIn size={16} aria-hidden="true" />
                <span>登入</span>
              </Link>
            )}
          </div>
        </div>
      </header>
      <main>{children}</main>
    </>
  );
}
