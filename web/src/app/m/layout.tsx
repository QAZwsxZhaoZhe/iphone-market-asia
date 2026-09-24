import type { Metadata, Viewport } from "next";
import { redirect } from "next/navigation";
import type { ReactNode } from "react";

import { MobileOpsShell } from "@/components/mobile-ops-shell";
import { api } from "@/lib/api";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "手機營運台",
  description: "香港二手 iPhone 平台手機端內部營運工具。",
  robots: {
    index: false,
    follow: false,
  },
};

export const viewport: Viewport = {
  themeColor: "#172554",
  viewportFit: "cover",
};

export default async function MobileOpsLayout({
  children,
}: {
  children: ReactNode;
}) {
  const principal = await api.currentPrincipal().catch(() => null);
  if (!principal) {
    redirect("/login?next=/m");
  }
  if (!principal.internal) {
    redirect("/login?error=forbidden&next=/");
  }

  return (
    <MobileOpsShell email={principal.email ?? "內部使用者"}>
      {children}
    </MobileOpsShell>
  );
}
