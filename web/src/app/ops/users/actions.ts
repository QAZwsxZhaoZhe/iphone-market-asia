"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { api } from "@/lib/api";

function text(formData: FormData, key: string): string {
  return String(formData.get(key) ?? "").trim();
}

function finish(notice: string, error = false): never {
  revalidatePath("/ops/users");
  const query = new URLSearchParams({
    [error ? "error" : "notice"]: notice,
  });
  redirect(`/ops/users?${query.toString()}`);
}

export async function createStaffUserAction(formData: FormData): Promise<void> {
  const role = text(formData, "role");
  if (!["admin", "operator", "analyst"].includes(role)) {
    finish("請選擇有效的內部角色", true);
  }

  try {
    const user = await api.createStaffUser({
      email: text(formData, "email"),
      password: text(formData, "password"),
      display_name: text(formData, "display_name"),
      roles: [role],
    });
    finish(`已建立員工帳戶 ${user.email}`);
  } catch (error) {
    finish(error instanceof Error ? error.message : "建立員工帳戶失敗", true);
  }
}
