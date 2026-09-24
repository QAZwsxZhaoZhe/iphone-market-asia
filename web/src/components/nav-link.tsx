"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

type NavLinkProps = {
  href: string;
  icon: ReactNode;
  children: ReactNode;
};

export function NavLink({ href, icon, children }: NavLinkProps) {
  const pathname = usePathname();
  const active =
    href === "/" ? pathname === href : pathname.startsWith(href);

  return (
    <Link
      className="nav-link"
      data-active={active ? "true" : "false"}
      href={href}
    >
      {icon}
      <span>{children}</span>
    </Link>
  );
}
