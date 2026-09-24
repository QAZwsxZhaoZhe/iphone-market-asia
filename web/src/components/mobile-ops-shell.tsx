import {
  CircleUserRound,
  House,
  Monitor,
  PackageSearch,
  PlusCircle,
  ReceiptText,
  Smartphone,
} from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { MobileNavLink } from "@/components/mobile-nav-link";

type MobileOpsShellProps = {
  children: ReactNode;
  email: string;
};

export function MobileOpsShell({ children, email }: MobileOpsShellProps) {
  return (
    <div className="mobile-ops">
      <header className="mobile-ops__appbar">
        <div className="mobile-appbar__brand">
          <span className="mobile-appbar__mark" aria-hidden="true">
            <Smartphone size={18} />
          </span>
          <span className="mobile-appbar__copy">
            <strong>HK PHONE OPS</strong>
            <span>{email}</span>
          </span>
        </div>
        <Link
          aria-label="切換至電腦端營運台"
          className="mobile-appbar__desktop"
          href="/ops"
          title="切換至電腦端營運台"
        >
          <Monitor size={18} aria-hidden="true" />
        </Link>
      </header>

      <div className="mobile-ops__content">{children}</div>

      <nav className="mobile-tabbar" aria-label="手機營運台導覽">
        <MobileNavLink href="/m" icon={<House size={20} />}>
          首頁
        </MobileNavLink>
        <MobileNavLink href="/m/catalog" icon={<PackageSearch size={20} />}>
          商品
        </MobileNavLink>
        <MobileNavLink href="/m/catalog/new" icon={<PlusCircle size={22} />}>
          上架
        </MobileNavLink>
        <MobileNavLink href="/m/orders" icon={<ReceiptText size={20} />}>
          訂單
        </MobileNavLink>
        <MobileNavLink href="/m/profile" icon={<CircleUserRound size={20} />}>
          我的
        </MobileNavLink>
      </nav>
    </div>
  );
}
