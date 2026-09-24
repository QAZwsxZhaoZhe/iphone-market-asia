"use client";

import { LoaderCircle, Play } from "lucide-react";
import { useFormStatus } from "react-dom";

type SubmitButtonProps = {
  children: string;
  accent?: boolean;
  small?: boolean;
};

export function SubmitButton({
  children,
  accent = false,
  small = false,
}: SubmitButtonProps) {
  const { pending } = useFormStatus();
  return (
    <button
      className={[
        "button",
        accent ? "button--accent" : "button--ghost",
        small ? "button--small" : "",
      ]
        .filter(Boolean)
        .join(" ")}
      disabled={pending}
      type="submit"
    >
      {pending ? (
        <LoaderCircle className="spin" size={14} aria-hidden="true" />
      ) : (
        <Play size={14} aria-hidden="true" />
      )}
      {pending ? "處理中" : children}
    </button>
  );
}
