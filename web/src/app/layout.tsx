import type { Metadata } from "next";
import type { ReactNode } from "react";

import { AppShell } from "@/components/app-shell";
import "@/app/globals.css";

export const metadata: Metadata = {
  title: {
    default: "HK Phone Index｜香港二手手機行情",
    template: "%s｜HK Phone Index",
  },
  description: "香港二手手機公開資料聚合、估值、行情與來源健康監察。",
  robots: {
    index: true,
    follow: true,
  },
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="zh-Hant-HK">
      <body>
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
