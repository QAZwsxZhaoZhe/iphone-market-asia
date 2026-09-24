import {
  AlertTriangle,
  Boxes,
  CheckCircle2,
  CircleDollarSign,
  Inbox,
  PackageCheck,
  PackageSearch,
  PlusCircle,
  ReceiptText,
  ShieldCheck,
} from "lucide-react";
import Link from "next/link";

import { OrderStatus } from "@/components/order-status";
import { EmptyState, ErrorState } from "@/components/states";
import { api } from "@/lib/api";
import { formatHKD, formatRelative } from "@/lib/format";
import type {
  DeadLetter,
  InternalOrder,
  InventoryItem,
  SourceHealth,
  StoreListing,
} from "@/lib/types";

export const dynamic = "force-dynamic";

type SearchParams = Promise<{
  notice?: string | string[];
  error?: string | string[];
}>;

function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

async function safe<T>(promise: Promise<T>): Promise<{
  data: T | null;
  error: string | null;
}> {
  try {
    return { data: await promise, error: null };
  } catch (error) {
    return {
      data: null,
      error: error instanceof Error ? error.message : "無法讀取資料",
    };
  }
}

export default async function MobileHomePage({
  searchParams,
}: {
  searchParams: SearchParams;
}) {
  const params = await searchParams;
  const [ordersResult, inventoryResult, listingsResult, sourcesResult, deadResult] =
    await Promise.all([
      safe(api.internalOrders(undefined, 100)),
      safe(api.internalInventory(200)),
      safe(api.internalSellerListings(200)),
      safe(api.internalSources()),
      safe(api.internalDeadLetters(30)),
    ]);

  const errors = [
    ordersResult.error,
    inventoryResult.error,
    listingsResult.error,
    sourcesResult.error,
    deadResult.error,
  ].filter(Boolean) as string[];

  if (errors.length === 5) {
    return (
      <div className="mobile-page">
        <ErrorState
          description={errors[0]}
          title="手機營運台暫時無法連線"
        />
      </div>
    );
  }

  const orders = ordersResult.data ?? [];
  const inventory = inventoryResult.data ?? [];
  const listings = listingsResult.data ?? [];
  const sources = sourcesResult.data ?? [];
  const deadLetters = deadResult.data ?? [];
  const fulfillmentOrders = orders.filter((order) =>
    ["paid", "processing", "shipped"].includes(order.status),
  );
  const activeListings = listings.filter((listing) => listing.status === "active");
  const availableInventory = inventory.filter((item) =>
    ["inspection", "available"].includes(item.status),
  );
  const sourceIssues = sources.filter((source) =>
    ["failed", "partial", "stale"].includes(source.status),
  );

  return (
    <div className="mobile-page">
      <header className="mobile-page-header mobile-page-header--hero">
        <div>
          <span className="eyebrow">Operations overview</span>
          <h1>今日營運</h1>
          <p>先處理訂單與異常，再進入商品或採集工作。</p>
        </div>
        <span className="mobile-secure-chip">
          <ShieldCheck size={14} aria-hidden="true" />
          內部
        </span>
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

      <section className="mobile-metrics" aria-label="營運摘要">
        <article className="mobile-metric">
          <span className="mobile-metric__icon">
            <PackageCheck size={18} aria-hidden="true" />
          </span>
          <div>
            <strong>{fulfillmentOrders.length}</strong>
            <span>待履約訂單</span>
          </div>
        </article>
        <article className="mobile-metric">
          <span className="mobile-metric__icon">
            <Boxes size={18} aria-hidden="true" />
          </span>
          <div>
            <strong>{availableInventory.length}</strong>
            <span>可上架庫存</span>
          </div>
        </article>
        <article className="mobile-metric">
          <span className="mobile-metric__icon">
            <PackageSearch size={18} aria-hidden="true" />
          </span>
          <div>
            <strong>{activeListings.length}</strong>
            <span>已發布商品</span>
          </div>
        </article>
        <article className="mobile-metric">
          <span className="mobile-metric__icon mobile-metric__icon--warning">
            <Inbox size={18} aria-hidden="true" />
          </span>
          <div>
            <strong>{deadLetters.length + sourceIssues.length}</strong>
            <span>待處理異常</span>
          </div>
        </article>
      </section>

      <section className="mobile-section" aria-labelledby="mobile-quick-title">
        <header className="mobile-section__header">
          <div>
            <span className="eyebrow">Frequent actions</span>
            <h2 id="mobile-quick-title">常用操作</h2>
          </div>
        </header>
        <div className="mobile-quick-grid">
          <Link className="mobile-quick-action" href="/m/catalog/new">
            <span>
              <PlusCircle size={21} aria-hidden="true" />
            </span>
            <strong>快速上架</strong>
            <small>語音或手動填寫</small>
          </Link>
          <Link
            className="mobile-quick-action"
            href="/m/orders?status=paid"
          >
            <span>
              <TruckIcon />
            </span>
            <strong>處理訂單</strong>
            <small>{fulfillmentOrders.length} 筆待跟進</small>
          </Link>
          <Link className="mobile-quick-action" href="/m/catalog">
            <span>
              <PackageSearch size={21} aria-hidden="true" />
            </span>
            <strong>查看商品</strong>
            <small>{listings.length} 筆記錄</small>
          </Link>
          <Link className="mobile-quick-action" href="/m/profile#system">
            <span>
              <CircleDollarSign size={21} aria-hidden="true" />
            </span>
            <strong>系統維護</strong>
            <small>來源與採集狀態</small>
          </Link>
        </div>
      </section>

      <section className="mobile-section" aria-labelledby="mobile-recent-orders">
        <header className="mobile-section__header">
          <div>
            <span className="eyebrow">Recent orders</span>
            <h2 id="mobile-recent-orders">最近訂單</h2>
          </div>
          <Link className="mobile-text-link" href="/m/orders">
            查看全部
          </Link>
        </header>
        {orders.length ? (
          <div className="mobile-order-list">
            {orders.slice(0, 5).map((order) => (
              <article className="mobile-order-row" key={order.id}>
                <div className="mobile-order-row__head">
                  <span className="mono">{order.order_number}</span>
                  <OrderStatus value={order.status} />
                </div>
                <strong>{order.item.title}</strong>
                <div className="mobile-order-row__meta">
                  <span>{order.buyer.display_name}</span>
                  <span>{formatRelative(order.created_at)}</span>
                  <span className="mono">{formatHKD(order.total_hkd)}</span>
                </div>
              </article>
            ))}
          </div>
        ) : (
          <EmptyState
            description="首筆訂單建立後會顯示在這裡。"
            title="尚無訂單"
          />
        )}
      </section>

      <section className="mobile-section" aria-labelledby="mobile-source-health">
        <header className="mobile-section__header">
          <div>
            <span className="eyebrow">Source health</span>
            <h2 id="mobile-source-health">來源概況</h2>
          </div>
          <Link className="mobile-text-link" href="/m/profile#system">
            詳細資料
          </Link>
        </header>
        <div className="mobile-summary-strip">
          <div>
            <strong>{sources.length}</strong>
            <span>已註冊來源</span>
          </div>
          <div>
            <strong>{sourceIssues.length}</strong>
            <span>需要跟進</span>
          </div>
          <div>
            <strong>{deadLetters.length}</strong>
            <span>死信任務</span>
          </div>
        </div>
      </section>
    </div>
  );
}

function TruckIcon() {
  return <ReceiptText size={21} aria-hidden="true" />;
}
