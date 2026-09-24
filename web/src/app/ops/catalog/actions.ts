"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { api } from "@/lib/api";

function messageFrom(error: unknown): string {
  return error instanceof Error ? error.message : "操作失敗";
}

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

function integerValue(formData: FormData, key: string, fallback = 0): number {
  const value = numberValue(formData, key);
  return value === null ? fallback : Math.round(value);
}

function listValue(formData: FormData, key: string): string[] {
  return text(formData, key)
    .split(/[\n,，]+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function finish(notice: string, error = false): never {
  revalidatePath("/ops/catalog");
  revalidatePath("/store");
  const query = new URLSearchParams({
    [error ? "error" : "notice"]: notice,
  });
  redirect(`/ops/catalog?${query.toString()}`);
}

async function runAction(action: () => Promise<string>): Promise<void> {
  let notice: string;
  let isError = false;
  try {
    notice = await action();
  } catch (error) {
    notice = messageFrom(error);
    isError = true;
  }
  finish(notice, isError);
}

export async function createMerchantAction(formData: FormData): Promise<void> {
  return runAction(async () => {
    const commissionPct = numberValue(formData, "commission_pct") ?? 10;
    const ownerUserId = text(formData, "owner_user_id");
    const merchant = await api.createMerchant({
      legal_name: text(formData, "legal_name"),
      display_name: text(formData, "display_name"),
      merchant_type: text(formData, "merchant_type") || "business",
      owner_user_id: ownerUserId || null,
      commission_rate_bps: Math.round(commissionPercent(commissionPct) * 100),
      status: text(formData, "status") || "active",
    });
    return `已建立商家 ${merchant.display_name}`;
  });
}

export async function updateMerchantStatusAction(
  formData: FormData,
): Promise<void> {
  return runAction(async () => {
    const status = text(formData, "status");
    if (!["pending", "active", "suspended", "closed"].includes(status)) {
      throw new Error("商家狀態無效");
    }
    const merchant = await api.updateMerchantStatus(
      text(formData, "merchant_id"),
      status as "pending" | "active" | "suspended" | "closed",
    );
    return `已更新 ${merchant.display_name} 為${merchantStatusLabel(status)}`;
  });
}

export async function createInventoryAction(formData: FormData): Promise<void> {
  return runAction(async () => {
    const batteryHealth = numberValue(formData, "battery_health_pct");
    const cost = numberValue(formData, "cost_hkd");
    const item = await api.createInventory({
      merchant_id: text(formData, "merchant_id"),
      phone_variant_id: text(formData, "phone_variant_id"),
      sku: text(formData, "sku"),
      condition_grade: text(formData, "condition_grade") || "B",
      battery_health_pct: batteryHealth,
      repair_history: [],
      accessories: listValue(formData, "accessories"),
      cost_hkd: cost,
      status: text(formData, "status") || "available",
    });
    return `已建立庫存 ${item.sku}`;
  });
}

export async function createSellerListingAction(
  formData: FormData,
): Promise<void> {
  return runAction(async () => {
    const notes = text(formData, "inspection_notes");
    const listing = await api.createSellerListing({
      merchant_id: text(formData, "merchant_id"),
      inventory_item_id: text(formData, "inventory_item_id"),
      title: text(formData, "title"),
      description: text(formData, "description"),
      price_hkd: numberValue(formData, "price_hkd") ?? 0,
      warranty_days: integerValue(formData, "warranty_days"),
      inspection_report: notes ? { notes } : {},
      images: listValue(formData, "images"),
      slug: text(formData, "slug") || null,
    });
    return `已建立銷售頁 ${listing.title}`;
  });
}

export async function quickCreateSellerListingAction(
  formData: FormData,
): Promise<void> {
  return runAction(async () => {
    const listing = await api.quickCreateSellerListing({
      merchant_id: text(formData, "merchant_id"),
      phone_variant_id: text(formData, "phone_variant_id"),
      condition_grade: text(formData, "condition_grade") || "B",
      price_hkd: numberValue(formData, "price_hkd") ?? 0,
      battery_health_pct: numberValue(formData, "battery_health_pct"),
      images: listValue(formData, "images"),
    });
    return `已快速上架 ${listing.title}`;
  });
}

export async function publishSellerListingAction(
  formData: FormData,
): Promise<void> {
  return runAction(async () => {
    const listing = await api.publishSellerListing(
      text(formData, "listing_id"),
    );
    return `已發布 ${listing.title}`;
  });
}

function commissionPercent(value: number): number {
  return Math.max(0, Math.min(value, 50));
}

function merchantStatusLabel(status: string): string {
  return (
    {
      pending: "待審核",
      active: "已核准",
      suspended: "已暫停",
      closed: "已關閉",
    }[status] ?? status
  );
}
