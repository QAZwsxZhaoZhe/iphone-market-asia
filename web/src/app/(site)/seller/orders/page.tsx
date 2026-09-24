import {
  AlertTriangle,
  CheckCircle2,
  ClipboardList,
  PackageCheck,
  Truck,
} from "lucide-react";
import { redirect } from "next/navigation";

import { OrderStatus } from "@/components/order-status";
import { SubmitButton } from "@/components/submit-button";
import { EmptyState, ErrorState } from "@/components/states";
import { api } from "@/lib/api";
import {
  formatDateTime,
  formatHKD,
} from "@/lib/format";
import type { Order } from "@/lib/types";

import { fulfillSellerOrderAction } from "../actions";

export const dynamic = "force-dynamic";

type SearchParams = Promise<{
  notice?: string | string[];
  error?: string | string[];
}>;

function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

function valueFrom(
  record: Record<string, unknown>,
  key: string,
): string {
  const value = record[key];
  return typeof value === "string" || typeof value === "number"
    ? String(value)
    : "未提供";
}

export default async function SellerOrdersPage({
  searchParams,
}: {
  searchParams: SearchParams;
}) {
  const params = await searchParams;
  const profile = await api.sellerProfile().catch(() => null);
  if (!profile) {
    redirect("/seller");
  }

  let orders: Order[];
  try {
    orders = await api.sellerOrders();
  } catch (error) {
    return (
      <div className="page">
        <ErrorState
          description={
            error instanceof Error ? error.message : "無法讀取銷售訂單。"
          }
          title="訂單資料暫時無法讀取"
        />
      </div>
    );
  }

  const paid = orders.filter((order) => order.status === "paid").length;
  const processing = orders.filter(
    (order) => order.status === "processing",
  ).length;
  const shipped = orders.filter((order) => order.status === "shipped").length;

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <span className="eyebrow">Seller orders</span>
          <h1>銷售訂單</h1>
          <p>處理已付款訂單的備貨及發貨狀態。</p>
        </div>
      </header>

      {first(params.notice) ? (
        <div className="ops-banner" role="status">
          <CheckCircle2 size={17} aria-hidden="true" />
          {first(params.notice)}
        </div>
      ) : null}
      {first(params.error) ? (
        <div className="ops-banner ops-banner--error" role="alert">
          <AlertTriangle size={17} aria-hidden="true" />
          {first(params.error)}
        </div>
      ) : null}
      {profile.status !== "active" ? (
        <div className="seller-callout seller-callout--warning" role="alert">
          <AlertTriangle size={18} aria-hidden="true" />
          <div>
            <strong>店鋪目前不可發布新商品</strong>
            <span>已付款訂單仍可繼續備貨及發貨。</span>
          </div>
        </div>
      ) : null}

      <section className="metrics-grid" aria-label="銷售訂單摘要">
        <article className="metric">
          <span className="metric__label">
            <ClipboardList size={13} /> 全部訂單
          </span>
          <strong className="metric__value">{orders.length}</strong>
          <span className="metric__note">最近 100 筆</span>
        </article>
        <article className="metric">
          <span className="metric__label">
            <PackageCheck size={13} /> 待備貨
          </span>
          <strong className="metric__value">{paid}</strong>
          <span className="metric__note">付款已確認</span>
        </article>
        <article className="metric">
          <span className="metric__label">
            <Truck size={13} /> 備貨中
          </span>
          <strong className="metric__value">{processing}</strong>
          <span className="metric__note">等待交付物流</span>
        </article>
        <article className="metric">
          <span className="metric__label">
            <Truck size={13} /> 已發貨
          </span>
          <strong className="metric__value">{shipped}</strong>
          <span className="metric__note">等待買家收貨</span>
        </article>
      </section>

      {orders.length ? (
        <section className="order-list">
          {orders.map((order) => (
            <article className="order-card" key={order.id}>
              <div className="order-card__media">
                {order.item.image ? (
                  <img alt={order.item.title} src={order.item.image} />
                ) : (
                  <PackageCheck size={38} aria-hidden="true" />
                )}
              </div>
              <div className="order-card__body">
                <div className="order-card__head">
                  <div>
                    <span className="subtext mono">{order.order_number}</span>
                    <h2>{order.item.title}</h2>
                  </div>
                  <OrderStatus value={order.status} />
                </div>
                <div className="order-card__meta">
                  <span>
                    {valueFrom(order.contact, "recipient_name")} ·{" "}
                    {valueFrom(order.contact, "phone")}
                  </span>
                  <span>
                    {valueFrom(order.shipping_address, "district")} ·{" "}
                    {valueFrom(order.shipping_address, "line1")}
                  </span>
                  <span>{formatDateTime(order.created_at)}</span>
                </div>
              </div>
              <div className="order-card__side">
                <strong>{formatHKD(order.total_hkd)}</strong>
                <span className="subtext">
                  商家收入 {formatHKD(order.merchant_net_hkd)}
                </span>
                <div className="table-actions">
                  {order.status === "paid" ? (
                    <form action={fulfillSellerOrderAction}>
                      <input name="order_id" type="hidden" value={order.id} />
                      <input name="status" type="hidden" value="processing" />
                      <input
                        name="note"
                        type="hidden"
                        value="seller_processing"
                      />
                      <SubmitButton small>開始備貨</SubmitButton>
                    </form>
                  ) : null}
                  {["paid", "processing"].includes(order.status) ? (
                    <form action={fulfillSellerOrderAction}>
                      <input name="order_id" type="hidden" value={order.id} />
                      <input name="status" type="hidden" value="shipped" />
                      <input
                        name="note"
                        type="hidden"
                        value="seller_shipped"
                      />
                      <SubmitButton small>標記發貨</SubmitButton>
                    </form>
                  ) : null}
                  {!["paid", "processing"].includes(order.status) ? (
                    <span className="subtext">目前無需賣家操作</span>
                  ) : null}
                </div>
              </div>
            </article>
          ))}
        </section>
      ) : (
        <EmptyState
          description="買家完成付款後，訂單會出現在這裡。"
          title="尚未有銷售訂單"
        />
      )}
    </div>
  );
}
