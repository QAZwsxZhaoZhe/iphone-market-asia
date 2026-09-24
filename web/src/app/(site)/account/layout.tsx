import { redirect } from "next/navigation";
import type { ReactNode } from "react";

import { api } from "@/lib/api";

export default async function AccountLayout({
  children,
}: {
  children: ReactNode;
}) {
  const principal = await api.currentPrincipal().catch(() => null);
  if (!principal?.user_id) {
    redirect("/login?next=/account/orders");
  }
  if (principal.internal) {
    redirect("/ops");
  }
  return children;
}
