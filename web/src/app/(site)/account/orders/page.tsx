import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  CreditCard,
  PackageCheck,
  ReceiptText,
  RotateCcw,
  Truck,
} from "lucide-react";
import Link from "next/link";

import { OrderStatus } from "@/components/order-status";
import { EmptyState, ErrorState } from "@/components/states";
import { api } from "@/lib/api";
import { formatDateTime, formatHKD } from "@/lib/format";
import type { Order } from "@/lib/types";

export const dynamic = "force-dynamic";

type SearchParams = Promise<{
  notice?: string | string[];
  error?: string | string[];
}>;

function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

export default async function AccountOrdersPage({
  searchParams,
}: {
  searchParams: SearchParams;
}) {
  const params = await searchParams;
  let orders: Order[];
  try {
    orders = await api.orders();
  } catch (error) {
    return (
      <div className="page">
        <ErrorState
          description={
            error instanceof Error ? error.message : "訂單資料暫時無法讀取。"
          }
          title="無法讀取我的訂單"
        />
      </div>
    );
  }

  const paid = orders.filter((order) =>
    ["paid", "processing", "shipped", "completed"].includes(order.status),
  ).length;
  const active = orders.filter((order) =>
    ["pending_payment", "paid", "processing", "shipped"].includes(
      order.status,
    ),
  ).length;

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <span className="eyebrow">My orders</span>
          <h1>我的訂單</h1>
          <p>管理付款、取消、物流狀態及收貨確認。</p>
        </div>
        <Link className="button button--ghost" href="/store">
          <ReceiptText size={15} aria-hidden="true" />
          繼續選購
        </Link>
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

      <section className="metrics-grid" aria-label="訂單摘要">
        <article className="metric">
          <span className="metric__label">
            <ReceiptText size={13} /> 全部訂單
          </span>
          <strong className="metric__value">{orders.length}</strong>
          <span className="metric__note">最近 100 筆</span>
        </article>
        <article className="metric">
          <span className="metric__label">
            <CreditCard size={13} /> 已付款
          </span>
          <strong className="metric__value">{paid}</strong>
          <span className="metric__note">支付服務已確認收款</span>
        </article>
        <article className="metric">
          <span className="metric__label">
            <Truck size={13} /> 履約中
          </span>
          <strong className="metric__value">{active}</strong>
          <span className="metric__note">待付款、備貨或運送中</span>
        </article>
        <article className="metric">
          <span className="metric__label">
            <RotateCcw size={13} /> 退款
          </span>
          <strong className="metric__value">
            {
              orders.filter((order) =>
                ["refund_pending", "refunded"].includes(order.status),
              ).length
            }
          </strong>
          <span className="metric__note">處理中及已完成</span>
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
                    <span className="subtext mono">
                      {order.order_number}
                    </span>
                    <h2>{order.item.title}</h2>
                  </div>
                  <OrderStatus value={order.status} />
                </div>
                <div className="order-card__meta">
                  <span>{order.merchant.display_name}</span>
                  <span>{formatDateTime(order.created_at)}</span>
                  <span>
                    {order.item.model} {order.item.storage_label}
                  </span>
                </div>
              </div>
              <div className="order-card__side">
                <strong>{formatHKD(order.total_hkd)}</strong>
                <Link
                  className="button button--ghost button--small"
                  href={`/account/orders/${order.id}`}
                >
                  查看訂單
                  <ArrowRight size={14} aria-hidden="true" />
                </Link>
              </div>
            </article>
          ))}
        </section>
      ) : (
        <EmptyState
          description="在平台商店購買首件商品後，訂單會顯示在這裡。"
          title="尚未有訂單"
        />
      )}
    </div>
  );
}
