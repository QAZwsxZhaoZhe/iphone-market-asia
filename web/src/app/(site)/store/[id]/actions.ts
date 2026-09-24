"use server";

import { randomUUID } from "node:crypto";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { ApiError, api } from "@/lib/api";

function text(formData: FormData, key: string): string {
  return String(formData.get(key) ?? "").trim();
}

function messageFrom(error: unknown): string {
  return error instanceof Error ? error.message : "暫時無法建立訂單";
}

function fail(target: string, message: string): never {
  const query = new URLSearchParams({ error: message });
  redirect(`${target}?${query.toString()}`);
}

export async function placeOrderAction(formData: FormData): Promise<void> {
  const listingId = text(formData, "listing_id");
  const target = `/store/${encodeURIComponent(listingId)}`;
  if (!listingId) {
    fail("/store", "缺少商品識別碼");
  }

  const idempotencyKey =
    text(formData, "idempotency_key") || randomUUID();
  let orderId: string;
  try {
    const order = await api.createOrder({
      listing_id: listingId,
      idempotency_key: idempotencyKey,
      contact: {
        recipient_name: text(formData, "recipient_name"),
        phone: text(formData, "phone"),
        email: text(formData, "email"),
      },
      shipping_address: {
        line1: text(formData, "line1"),
        line2: text(formData, "line2"),
        district: text(formData, "district"),
        region: text(formData, "region") || "香港",
        country: "HK",
      },
    });
    orderId = order.id;
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      const query = new URLSearchParams({ next: target });
      redirect(`/login?${query.toString()}`);
    }
    fail(target, messageFrom(error));
  }

  let checkoutUrl: string | null = null;
  try {
    const intent = await api.createPaymentIntent(orderId);
    checkoutUrl = intent.checkout_url;
  } catch (error) {
    revalidatePath("/account/orders");
    const query = new URLSearchParams({ error: messageFrom(error) });
    redirect(`/account/orders/${orderId}?${query.toString()}`);
  }

  revalidatePath("/account/orders");
  if (checkoutUrl) {
    redirect(checkoutUrl);
  }
  const query = new URLSearchParams({
    notice: "訂單已建立，請繼續完成付款。",
  });
  redirect(`/account/orders/${orderId}?${query.toString()}`);
}
