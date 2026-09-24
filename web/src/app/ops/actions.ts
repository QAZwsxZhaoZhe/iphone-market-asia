"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { api } from "@/lib/api";

function messageFrom(error: unknown): string {
  return error instanceof Error ? error.message : "操作失敗";
}

function finish(notice: string, error = false): never {
  revalidatePath("/ops");
  const query = new URLSearchParams({
    [error ? "error" : "notice"]: notice,
  });
  redirect(`/ops?${query.toString()}`);
}

export async function collectSourceAction(formData: FormData): Promise<void> {
  const sourceKey = String(formData.get("source_key") ?? "");
  if (!sourceKey) {
    finish("缺少來源識別碼", true);
  }
  try {
    const result = await api.enqueueCollection(sourceKey);
    finish(`已將 ${sourceKey} 加入採集隊列，任務 ${result.task_id}`);
  } catch (error) {
    finish(messageFrom(error), true);
  }
}

export async function rebuildClustersAction(): Promise<void> {
  try {
    const result = await api.rebuildClusters();
    finish(result.detail ?? `已重建 ${result.count ?? 0} 個集群`);
  } catch (error) {
    finish(messageFrom(error), true);
  }
}

export async function runMaintenanceAction(): Promise<void> {
  try {
    const result = await api.runMaintenance();
    finish(`維護任務已排隊，任務 ${result.task_id}`);
  } catch (error) {
    finish(messageFrom(error), true);
  }
}
