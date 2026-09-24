import { ServerCog, Smartphone } from "lucide-react";
import Link from "next/link";
import { redirect } from "next/navigation";
import type { ReactNode } from "react";

import { SessionActions } from "@/components/session-actions";
import { api } from "@/lib/api";

export default async function OpsLayout({ children }: { children: ReactNode }) {
  const principal = await api.currentPrincipal().catch(() => null);
  if (!principal) {
    redirect("/staff/login?next=/ops");
  }
  if (!principal.internal) {
    redirect("/staff/login?error=forbidden&next=/ops");
  }
  return (
    <div className="ops-shell">
      <header className="ops-topbar">
        <div className="ops-topbar__inner">
          <Link className="ops-brand" href="/ops">
            <span className="ops-brand__mark" aria-hidden="true">
              <ServerCog size={18} />
            </span>
            <span className="ops-brand__copy">
              <strong>HK PHONE ERP</strong>
              <small>內部營運系統</small>
            </span>
          </Link>

          <div className="ops-topbar__actions">
            <Link className="ops-topbar__mobile" href="/m">
              <Smartphone size={16} aria-hidden="true" />
              <span>手機端</span>
            </Link>
            <SessionActions
              email={principal.email ?? "內部使用者"}
              roles={principal.roles}
              signOutPath="/staff/login"
            />
          </div>
        </div>
      </header>
      <main className="ops-main">{children}</main>
    </div>
  );
}
