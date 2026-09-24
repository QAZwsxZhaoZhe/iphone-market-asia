"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { api } from "@/lib/api";

function text(formData: FormData, key: string): string {
  return String(formData.get(key) ?? "").trim();
}

function numberValue(formData: FormData, key: string): number | null {
  const value = text(formData, key);
  if (!value) {
    return null;
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function listValue(formData: FormData, key: string): string[] {
  return text(formData, key)
    .split(/[\n,，]+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function messageFrom(error: unknown): string {
  return error instanceof Error ? error.message : "操作失敗";
}

function finish(path: string, notice: string, error = false): never {
  revalidatePath("/seller");
  revalidatePath("/seller/listings");
  revalidatePath("/seller/orders");
  const query = new URLSearchParams({
    [error ? "error" : "notice"]: notice,
  });
  redirect(`${path}?${query.toString()}`);
}

export async function applySellerAction(formData: FormData): Promise<void> {
  const merchantType = text(formData, "merchant_type");
  if (merchantType !== "business" && merchantType !== "individual") {
    finish("/seller", "請選擇有效的賣家類型", true);
  }
  try {
    const merchant = await api.applySeller({
      legal_name: text(formData, "legal_name"),
      display_name: text(formData, "display_name"),
      merchant_type: merchantType,
    });
    finish("/seller", `已提交 ${merchant.display_name} 的開店申請`);
  } catch (error) {
    finish("/seller", messageFrom(error), true);
  }
}

export async function quickCreateMyListingAction(
  formData: FormData,
): Promise<void> {
  try {
    const listing = await api.quickCreateMyListing({
      phone_variant_id: text(formData, "phone_variant_id"),
      condition_grade: text(formData, "condition_grade") || "B",
      price_hkd: numberValue(formData, "price_hkd") ?? 0,
      battery_health_pct: numberValue(formData, "battery_health_pct"),
      images: listValue(formData, "images"),
    });
    finish("/seller/listings", `已上架 ${listing.title}`);
  } catch (error) {
    finish("/seller/listings/new", messageFrom(error), true);
  }
}

export async function fulfillSellerOrderAction(
  formData: FormData,
): Promise<void> {
  const orderId = text(formData, "order_id");
  const status = text(formData, "status");
  if (status !== "processing" && status !== "shipped") {
    finish("/seller/orders", "無效的履約狀態", true);
  }
  try {
    await api.fulfillMyOrder(orderId, status, text(formData, "note"));
    finish(
      "/seller/orders",
      status === "shipped" ? "訂單已標記為已發貨" : "訂單已進入備貨",
    );
  } catch (error) {
    finish("/seller/orders", messageFrom(error), true);
  }
}
