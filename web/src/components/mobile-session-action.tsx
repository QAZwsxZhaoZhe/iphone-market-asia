"use client";

import { LoaderCircle, LogOut } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

type MobileSessionActionProps = {
  email: string;
  roles: string[];
};

const ROLE_LABELS: Record<string, string> = {
  admin: "管理員",
  operator: "營運",
  analyst: "分析",
  merchant: "商家",
  buyer: "買家",
};

export function MobileSessionAction({
  email,
  roles,
}: MobileSessionActionProps) {
  const router = useRouter();
  const [signingOut, setSigningOut] = useState(false);
  const roleLabel = roles.map((role) => ROLE_LABELS[role] ?? role).join(" / ");

  async function signOut() {
    setSigningOut(true);
    try {
      await fetch("/api/auth/logout", { method: "POST" });
      router.replace("/login?next=/m");
      router.refresh();
    } finally {
      setSigningOut(false);
    }
  }

  return (
    <section className="mobile-account-card">
      <div>
        <strong>{email}</strong>
        <span>{roleLabel}</span>
      </div>
      <button
        className="button button--ghost mobile-logout-button"
        disabled={signingOut}
        onClick={signOut}
        type="button"
      >
        {signingOut ? (
          <LoaderCircle className="spin" size={17} aria-hidden="true" />
        ) : (
          <LogOut size={17} aria-hidden="true" />
        )}
        {signingOut ? "正在登出" : "登出帳戶"}
      </button>
    </section>
  );
}
