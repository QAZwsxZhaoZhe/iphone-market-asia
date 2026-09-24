import {
  AlertTriangle,
  Boxes,
  CheckCircle2,
  PackagePlus,
  PlusCircle,
  Store,
  Zap,
} from "lucide-react";
import Link from "next/link";

import { SubmitButton } from "@/components/submit-button";
import { EmptyState } from "@/components/states";
import { api } from "@/lib/api";
import { formatHKD, statusTone } from "@/lib/format";
import type {
  InventoryItem,
  Merchant,
  StoreListing,
} from "@/lib/types";

import { publishSellerListingAction } from "./actions";

export const dynamic = "force-dynamic";

type SearchParams = Promise<{
  notice?: string | string[];
  error?: string | string[];
}>;

function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

async function safe<T>(promise: Promise<T>): Promise<T | null> {
  try {
    return await promise;
  } catch {
    return null;
  }
}

export default async function MobileCatalogPage({
  searchParams,
}: {
  searchParams: SearchParams;
}) {
  const params = await searchParams;
  const principal = await api.currentPrincipal().catch(() => null);
  const canOperate = Boolean(
    principal?.roles.some((role) => role === "admin" || role === "operator"),
  );
  const [merchants, inventory, listings] = await Promise.all([
    safe(api.internalMerchants()),
    safe(api.internalInventory()),
    safe(api.internalSellerListings()),
  ]);
  const merchantRows = merchants ?? [];
  const inventoryRows = inventory ?? [];
  const listingRows = listings ?? [];
  const activeListings = listingRows.filter((listing) => listing.status === "active");
  const draftListings = listingRows.filter((listing) => listing.status === "draft");
  const stockedItems = inventoryRows.filter((item) =>
    ["inspection", "available"].includes(item.status),
  );

  return (
    <div className="mobile-page">
      <header className="mobile-page-header">
        <div>
          <span className="eyebrow">Catalog</span>
          <h1>商品目錄</h1>
          <p>管理庫存與銷售頁；上架使用最少必要資料。</p>
        </div>
        {canOperate ? (
          <Link className="mobile-primary-action" href="/m/catalog/new">
            <PlusCircle size={18} aria-hidden="true" />
            上架
          </Link>
        ) : null}
      </header>

      {first(params.notice) ? (
        <div className="mobile-banner" role="status">
          <CheckCircle2 size={18} aria-hidden="true" />
          <span>{first(params.notice)}</span>
        </div>
      ) : null}
      {first(params.error) ? (
        <div className="mobile-banner mobile-banner--error" role="alert">
          <AlertTriangle size={18} aria-hidden="true" />
          <span>{first(params.error)}</span>
        </div>
      ) : null}

      <section className="mobile-metrics" aria-label="商品摘要">
        <article className="mobile-metric">
          <span className="mobile-metric__icon">
            <Store size={18} aria-hidden="true" />
          </span>
          <div>
            <strong>{merchantRows.length}</strong>
            <span>商家</span>
          </div>
        </article>
        <article className="mobile-metric">
          <span className="mobile-metric__icon">
            <Boxes size={18} aria-hidden="true" />
          </span>
          <div>
            <strong>{stockedItems.length}</strong>
            <span>可用庫存</span>
          </div>
        </article>
        <article className="mobile-metric">
          <span className="mobile-metric__icon">
            <Zap size={18} aria-hidden="true" />
          </span>
          <div>
            <strong>{activeListings.length}</strong>
            <span>已發布</span>
          </div>
        </article>
        <article className="mobile-metric">
          <span className="mobile-metric__icon mobile-metric__icon--warning">
            <PackagePlus size={18} aria-hidden="true" />
          </span>
          <div>
            <strong>{draftListings.length}</strong>
            <span>待發布</span>
          </div>
        </article>
      </section>

      {canOperate ? (
        <Link className="mobile-catalog-callout" href="/m/catalog/new">
          <span>
            <Zap size={20} aria-hidden="true" />
          </span>
          <div>
            <strong>快速上架</strong>
            <small>只需商家、機型、成色及售價</small>
          </div>
          <span aria-hidden="true">›</span>
        </Link>
      ) : null}

      <section className="mobile-section" aria-labelledby="mobile-listings-title">
        <header className="mobile-section__header">
          <div>
            <span className="eyebrow">Selling listings</span>
            <h2 id="mobile-listings-title">銷售商品</h2>
          </div>
          <span className="mobile-count">{listingRows.length} 筆</span>
        </header>
        {listingRows.length ? (
          <div className="mobile-card-list">
            {listingRows.slice(0, 60).map((listing) => (
              <ListingCard
                canOperate={canOperate}
                key={listing.id}
                listing={listing}
              />
            ))}
          </div>
        ) : (
          <EmptyState
            description="使用快速上架建立第一件銷售商品。"
            title="尚無銷售商品"
          />
        )}
        {listingRows.length > 60 ? (
          <p className="mobile-list-note">
            已顯示最近 60 筆，完整操作請前往電腦端營運台。
          </p>
        ) : null}
      </section>

      <details className="mobile-details">
        <summary>
          <span>庫存資料</span>
          <span>{inventoryRows.length} 筆</span>
        </summary>
        <div className="mobile-details__body">
          {inventoryRows.length ? (
            <div className="mobile-card-list mobile-card-list--compact">
              {inventoryRows.slice(0, 60).map((item) => (
                <InventoryCard item={item} key={item.id} />
              ))}
            </div>
          ) : (
            <EmptyState
              description="快速上架後會自動建立庫存記錄。"
              title="尚無庫存"
            />
          )}
        </div>
      </details>

      <details className="mobile-details">
        <summary>
          <span>商家資料</span>
          <span>{merchantRows.length} 筆</span>
        </summary>
        <div className="mobile-details__body">
          {merchantRows.length ? (
            <div className="mobile-card-list mobile-card-list--compact">
              {merchantRows.map((merchant) => (
                <MerchantCard key={merchant.id} merchant={merchant} />
              ))}
            </div>
          ) : (
            <EmptyState
              description="先由電腦端建立至少一個已核准商家。"
              title="尚未建立商家"
            />
          )}
        </div>
      </details>
    </div>
  );
}

function ListingCard({
  listing,
  canOperate,
}: {
  listing: StoreListing;
  canOperate: boolean;
}) {
  return (
    <article className="mobile-catalog-card">
      <div className="mobile-catalog-card__head">
        <span className={`status tone-${statusTone(listing.status)}`}>
          {listingStatusLabel(listing.status)}
        </span>
        <strong>{formatHKD(listing.price_hkd)}</strong>
      </div>
      <h3>{listing.title}</h3>
      <p>
        {listing.variant.model} · {listing.variant.storage_label}
      </p>
      <div className="mobile-catalog-card__meta">
        <span>{listing.merchant.display_name}</span>
        <span>{listing.inventory.condition_grade} 級</span>
        <span>
          {listing.inventory.battery_health_pct !== null
            ? `電池 ${listing.inventory.battery_health_pct}%`
            : "電池未記錄"}
        </span>
      </div>
      <div className="mobile-inline-actions">
        {listing.status === "active" ? (
          <Link
            className="button button--ghost button--small"
            href={`/store/${listing.id}`}
          >
            查看公開頁
          </Link>
        ) : canOperate && listing.status === "draft" ? (
          <form action={publishSellerListingAction}>
            <input name="listing_id" type="hidden" value={listing.id} />
            <SubmitButton small>發布商品</SubmitButton>
          </form>
        ) : (
          <span className="subtext">目前狀態不可發布</span>
        )}
      </div>
    </article>
  );
}

function InventoryCard({ item }: { item: InventoryItem }) {
  return (
    <article className="mobile-compact-card">
      <div>
        <span className="mono">{item.sku}</span>
        <strong>
          {item.model} · {item.storage_label}
        </strong>
        <small>
          {item.condition_grade} 級 ·{" "}
          {item.battery_health_pct !== null
            ? `${item.battery_health_pct}%`
            : "電池未記錄"}
        </small>
      </div>
      <div className="mobile-compact-card__side">
        <span className="badge">{inventoryStatusLabel(item.status)}</span>
        <strong>{item.cost_hkd !== null ? formatHKD(item.cost_hkd) : "未記成本"}</strong>
      </div>
    </article>
  );
}

function MerchantCard({ merchant }: { merchant: Merchant }) {
  return (
    <article className="mobile-compact-card">
      <div>
        <strong>{merchant.display_name}</strong>
        <small>{merchant.legal_name}</small>
      </div>
      <div className="mobile-compact-card__side">
        <span className="badge">{merchantStatusLabel(merchant.status)}</span>
        <strong>{(merchant.commission_rate_bps / 100).toFixed(2)}%</strong>
      </div>
    </article>
  );
}

function listingStatusLabel(status: string): string {
  return (
    {
      draft: "草稿",
      active: "已發布",
      reserved: "已預留",
      sold: "已售出",
      archived: "已下架",
    }[status] ?? status
  );
}

function inventoryStatusLabel(status: string): string {
  return (
    {
      intake: "已入庫",
      inspection: "驗機中",
      available: "可上架",
      reserved: "已預留",
      sold: "已售出",
      returned: "已退回",
      archived: "已封存",
    }[status] ?? status
  );
}

function merchantStatusLabel(status: Merchant["status"]): string {
  return (
    {
      active: "已核准",
      pending: "待審核",
      suspended: "已暫停",
      closed: "已關閉",
    }[status] ?? status
  );
}
