"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

type MobileNavLinkProps = {
  href: string;
  icon: ReactNode;
  children: ReactNode;
};

export function MobileNavLink({
  href,
  icon,
  children,
}: MobileNavLinkProps) {
  const pathname = usePathname();
  const active =
    href === "/m"
      ? pathname === href
      : href === "/m/catalog"
        ? pathname.startsWith("/m/catalog") &&
          pathname !== "/m/catalog/new"
        : pathname === href || pathname.startsWith(`${href}/`);

  return (
    <Link
      aria-current={active ? "page" : undefined}
      className="mobile-tab"
      data-active={active ? "true" : "false"}
      href={href}
    >
      {icon}
      <span>{children}</span>
    </Link>
  );
}
