"use client";

import { AlertCircle, LoaderCircle, LogIn, UserPlus } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

type AuthFormProps = {
  mode: "login" | "register";
  nextPath: string;
  registrationEnabled: boolean;
};

export function AuthForm({
  mode,
  nextPath,
  registrationEnabled,
}: AuthFormProps) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const isRegister = mode === "register";

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (isRegister && !registrationEnabled) {
      return;
    }
    const formData = new FormData(event.currentTarget);
    const payload = {
      email: String(formData.get("email") ?? ""),
      password: String(formData.get("password") ?? ""),
      display_name: String(formData.get("display_name") ?? ""),
    };

    setSubmitting(true);
    setError(null);
    try {
      const response = await fetch(`/api/auth/${mode}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const body = (await response.json().catch(() => ({}))) as {
        detail?: string;
      };
      if (!response.ok) {
        throw new Error(body.detail ?? "帳戶服務暫時無法使用");
      }
      router.replace(nextPath);
      router.refresh();
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : "帳戶服務暫時無法使用",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form className="auth-form" onSubmit={onSubmit}>
      {isRegister ? (
        <div className="field">
          <label htmlFor="display_name">顯示名稱</label>
          <input
            autoComplete="name"
            className="input"
            id="display_name"
            maxLength={120}
            name="display_name"
            required
            type="text"
          />
        </div>
      ) : null}

      <div className="field">
        <label htmlFor="email">電子郵件</label>
        <input
          autoComplete="email"
          className="input"
          id="email"
          maxLength={320}
          name="email"
          required
          type="email"
        />
      </div>

      <div className="field">
        <label htmlFor="password">密碼</label>
        <input
          autoComplete={isRegister ? "new-password" : "current-password"}
          className="input"
          id="password"
          minLength={10}
          name="password"
          required
          type="password"
        />
        <span className="field-hint">
          {isRegister ? "至少 10 個字元" : "使用註冊時的密碼"}
        </span>
      </div>

      {error ? (
        <div className="form-alert form-alert--error" role="alert">
          <AlertCircle size={16} aria-hidden="true" />
          {error}
        </div>
      ) : null}

      <button
        className="button button--primary auth-form__submit"
        disabled={submitting || (isRegister && !registrationEnabled)}
        type="submit"
      >
        {submitting ? (
          <LoaderCircle className="spin" size={16} aria-hidden="true" />
        ) : isRegister ? (
          <UserPlus size={16} aria-hidden="true" />
        ) : (
          <LogIn size={16} aria-hidden="true" />
        )}
        {submitting ? "處理中" : isRegister ? "建立買家帳戶" : "登入"}
      </button>
    </form>
  );
}
