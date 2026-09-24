"use client";

import { LoaderCircle, LogOut } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

type SessionActionsProps = {
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

export function SessionActions({ email, roles }: SessionActionsProps) {
  const router = useRouter();
  const [signingOut, setSigningOut] = useState(false);

  async function signOut() {
    setSigningOut(true);
    try {
      await fetch("/api/auth/logout", { method: "POST" });
      router.replace("/");
      router.refresh();
    } finally {
      setSigningOut(false);
    }
  }

  const roleLabel = roles.map((role) => ROLE_LABELS[role] ?? role).join(" / ");

  return (
    <div className="session-actions">
      <span className="session-actions__identity">
        <strong>{email}</strong>
        <span>{roleLabel}</span>
      </span>
      <button
        aria-label="登出"
        className="icon-button"
        disabled={signingOut}
        onClick={signOut}
        title="登出"
        type="button"
      >
        {signingOut ? (
          <LoaderCircle className="spin" size={16} aria-hidden="true" />
        ) : (
          <LogOut size={16} aria-hidden="true" />
        )}
      </button>
    </div>
  );
}
