"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { api } from "@/lib/api";

function text(formData: FormData, key: string): string {
  return String(formData.get(key) ?? "").trim();
}

function messageFrom(error: unknown): string {
  return error instanceof Error ? error.message : "操作失敗";
}

function finish(orderId: string, notice: string, error = false): never {
  revalidatePath("/account/orders");
  revalidatePath(`/account/orders/${orderId}`);
  const query = new URLSearchParams({
    [error ? "error" : "notice"]: notice,
  });
  redirect(`/account/orders/${orderId}?${query.toString()}`);
}

export async function payOrderAction(formData: FormData): Promise<void> {
  const orderId = text(formData, "order_id");
  if (!orderId) {
    redirect("/account/orders?error=缺少訂單識別碼");
  }

  let checkoutUrl: string | null;
  try {
    const intent = await api.createPaymentIntent(orderId);
    checkoutUrl = intent.checkout_url;
  } catch (error) {
    finish(orderId, messageFrom(error), true);
  }

  if (checkoutUrl) {
    redirect(checkoutUrl);
  }
  finish(orderId, "付款請求已建立。");
}

export async function cancelOrderAction(formData: FormData): Promise<void> {
  const orderId = text(formData, "order_id");
  try {
    await api.cancelOrder(orderId, text(formData, "reason"));
    finish(orderId, "訂單已取消，商品已重新開放購買。");
  } catch (error) {
    finish(orderId, messageFrom(error), true);
  }
}

export async function confirmReceiptAction(formData: FormData): Promise<void> {
  const orderId = text(formData, "order_id");
  try {
    await api.confirmReceipt(orderId);
    finish(orderId, "已確認收貨，平台將安排向商家結算。");
  } catch (error) {
    finish(orderId, messageFrom(error), true);
  }
}
