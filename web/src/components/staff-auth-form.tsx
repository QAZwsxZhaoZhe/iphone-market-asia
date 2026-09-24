"use client";

import { AlertCircle, KeyRound, LoaderCircle } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

type StaffAuthFormProps = {
  nextPath: string;
};

export function StaffAuthForm({ nextPath }: StaffAuthFormProps) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formData = new FormData(event.currentTarget);

    setSubmitting(true);
    setError(null);
    try {
      const response = await fetch("/api/staff/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email: String(formData.get("email") ?? ""),
          password: String(formData.get("password") ?? ""),
        }),
      });
      const body = (await response.json().catch(() => ({}))) as {
        detail?: string;
      };
      if (!response.ok) {
        throw new Error(body.detail ?? "員工登入服務暫時無法使用");
      }
      router.replace(nextPath);
      router.refresh();
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : "員工登入服務暫時無法使用",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form className="auth-form" onSubmit={onSubmit}>
      <div className="field">
        <label htmlFor="staff-email">員工電郵</label>
        <input
          autoComplete="username"
          className="input"
          id="staff-email"
          maxLength={320}
          name="email"
          required
          type="email"
        />
      </div>

      <div className="field">
        <label htmlFor="staff-password">密碼</label>
        <input
          autoComplete="current-password"
          className="input"
          id="staff-password"
          minLength={10}
          name="password"
          required
          type="password"
        />
      </div>

      {error ? (
        <div className="form-alert form-alert--error" role="alert">
          <AlertCircle size={16} aria-hidden="true" />
          {error}
        </div>
      ) : null}

      <button
        className="button button--primary auth-form__submit"
        disabled={submitting}
        type="submit"
      >
        {submitting ? (
          <LoaderCircle className="spin" size={16} aria-hidden="true" />
        ) : (
          <KeyRound size={16} aria-hidden="true" />
        )}
        {submitting ? "驗證中" : "進入營運系統"}
      </button>
    </form>
  );
}
