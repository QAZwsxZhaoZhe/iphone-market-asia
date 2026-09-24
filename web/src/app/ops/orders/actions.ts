"use server";

import { randomUUID } from "node:crypto";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { api } from "@/lib/api";

function text(formData: FormData, key: string): string {
  return String(formData.get(key) ?? "").trim();
}

function messageFrom(error: unknown): string {
  return error instanceof Error ? error.message : "操作失敗";
}

function finish(notice: string, error = false): never {
  revalidatePath("/ops/orders");
  revalidatePath("/account/orders");
  const query = new URLSearchParams({
    [error ? "error" : "notice"]: notice,
  });
  redirect(`/ops/orders?${query.toString()}`);
}

export async function fulfillOrderAction(formData: FormData): Promise<void> {
  const orderId = text(formData, "order_id");
  const status = text(formData, "status");
  if (status !== "processing" && status !== "shipped") {
    finish("無效的履約狀態", true);
  }
  try {
    await api.fulfillOrder(
      orderId,
      status,
      text(formData, "note"),
    );
    finish(status === "shipped" ? "訂單已標記為已發貨" : "訂單已進入備貨");
  } catch (error) {
    finish(messageFrom(error), true);
  }
}

export async function refundOrderAction(formData: FormData): Promise<void> {
  const orderId = text(formData, "order_id");
  const reason = text(formData, "reason");
  const idempotencyKey =
    text(formData, "idempotency_key") || randomUUID();
  try {
    const refund = await api.refundOrder(
      orderId,
      reason,
      idempotencyKey,
    );
    finish(
      refund.status === "succeeded"
        ? "退款已完成並寫入總帳"
        : `退款已提交，狀態：${refund.status}`,
    );
  } catch (error) {
    finish(messageFrom(error), true);
  }
}

export async function restockOrderAction(formData: FormData): Promise<void> {
  const orderId = text(formData, "order_id");
  try {
    await api.restockOrder(orderId);
    finish("退款商品已完成庫存歸位並重新上架");
  } catch (error) {
    finish(messageFrom(error), true);
  }
}
