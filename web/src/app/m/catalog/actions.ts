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

function listValue(formData: FormData, key: string): string[] {
  return text(formData, key)
    .split(/[\n,，]+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function finish(notice: string, error = false): never {
  revalidatePath("/m");
  revalidatePath("/m/catalog");
  revalidatePath("/store");
  const query = new URLSearchParams({
    [error ? "error" : "notice"]: notice,
  });
  redirect(`/m/catalog?${query.toString()}`);
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
