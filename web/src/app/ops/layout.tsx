import { redirect } from "next/navigation";
import type { ReactNode } from "react";

import { api } from "@/lib/api";

export default async function OpsLayout({ children }: { children: ReactNode }) {
  const principal = await api.currentPrincipal().catch(() => null);
  if (!principal) {
    redirect("/login?next=/ops");
  }
  if (!principal.internal) {
    redirect("/login?error=forbidden&next=/");
  }
  return children;
}
