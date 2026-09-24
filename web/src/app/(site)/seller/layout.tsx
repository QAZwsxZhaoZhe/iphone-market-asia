import { Boxes, ClipboardList, PlusCircle, Store } from "lucide-react";
import Link from "next/link";
import { redirect } from "next/navigation";
import type { ReactNode } from "react";

import { api } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function SellerLayout({
  children,
}: {
  children: ReactNode;
}) {
  const principal = await api.currentPrincipal().catch(() => null);
  if (!principal?.user_id) {
    redirect("/login?next=/seller");
  }
  if (principal.internal) {
    redirect("/ops");
  }

  return (
    <div className="seller-shell">
      <nav className="seller-subnav" aria-label="賣家中心導覽">
        <Link href="/seller">
          <Store size={15} aria-hidden="true" />
          賣家中心
        </Link>
        <Link href="/seller/listings">
          <Boxes size={15} aria-hidden="true" />
          我的商品
        </Link>
        <Link href="/seller/listings/new">
          <PlusCircle size={15} aria-hidden="true" />
          快速上架
        </Link>
        <Link href="/seller/orders">
          <ClipboardList size={15} aria-hidden="true" />
          銷售訂單
        </Link>
      </nav>
      {children}
    </div>
  );
}
