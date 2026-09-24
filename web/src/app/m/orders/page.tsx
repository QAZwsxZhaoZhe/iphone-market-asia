import {
  AlertTriangle,
  CheckCircle2,
  PackageCheck,
  ReceiptText,
  RotateCcw,
  Truck,
} from "lucide-react";
import Link from "next/link";

import { OrderStatus } from "@/components/order-status";
import { SubmitButton } from "@/components/submit-button";
import { EmptyState, ErrorState } from "@/components/states";
import { api } from "@/lib/api";
import { formatDateTime, formatHKD } from "@/lib/format";
import type { InternalOrder } from "@/lib/types";

import {
  fulfillOrderAction,
  refundOrderAction,
  restockOrderAction,
} from "./actions";

export const dynamic = "force-dynamic";

type SearchParams = Promise<{
  status?: string | string[];
  notice?: string | string[];
  error?: string | string[];
}>;

const ORDER_FILTERS = [
  { value: "", label: "全部" },
  { value: "pending_payment", label: "待付款" },
  { value: "paid", label: "已付款" },
  { value: "processing", label: "備貨中" },
  { value: "shipped", label: "已發貨" },
  { value: "refund_pending", label: "退款中" },
  { value: "refunded", label: "已退款" },
];

const REFUNDABLE = new Set([
  "paid",
  "processing",
  "shipped",
  "completed",
]);

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

async function safe<T>(promise: Promise<T>): Promise<T | null> {
  try {
    return await promise;
  } catch {
    return null;
  }
}

export default async function MobileOrdersPage({
  searchParams,
}: {
  searchParams: SearchParams;
}) {
  const params = await searchParams;
  const status = first(params.status) ?? "";
  const principal = await api.currentPrincipal().catch(() => null);
  const canOperate = Boolean(
    principal?.roles.some((role) => role === "admin" || role === "operator"),
  );
  const orders = await safe(api.internalOrders(status || undefined, 200));

  if (!orders) {
    return (
      <div className="mobile-page">
        <ErrorState
          description="請稍後重試，或前往電腦端營運台查看。"
          title="無法讀取訂單"
        />
      </div>
    );
  }

  const unpaid = orders.filter(
    (order) => order.status === "pending_payment",
  ).length;
  const fulfillment = orders.filter((order) =>
    ["paid", "processing", "shipped"].includes(order.status),
  ).length;
  const refunds = orders.filter((order) =>
    ["refund_pending", "refunded"].includes(order.status),
  ).length;

  return (
    <div className="mobile-page">
      <header className="mobile-page-header">
        <div>
          <span className="eyebrow">Order operations</span>
          <h1>訂單</h1>
          <p>處理備貨、發貨、退款及退款後的庫存歸位。</p>
        </div>
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

      <section className="mobile-metrics" aria-label="訂單摘要">
        <article className="mobile-metric">
          <span className="mobile-metric__icon mobile-metric__icon--warning">
            <ReceiptText size={18} aria-hidden="true" />
          </span>
          <div>
            <strong>{unpaid}</strong>
            <span>待付款</span>
          </div>
        </article>
        <article className="mobile-metric">
          <span className="mobile-metric__icon">
            <Truck size={18} aria-hidden="true" />
          </span>
          <div>
            <strong>{fulfillment}</strong>
            <span>待履約</span>
          </div>
        </article>
        <article className="mobile-metric">
          <span className="mobile-metric__icon">
            <RotateCcw size={18} aria-hidden="true" />
          </span>
          <div>
            <strong>{refunds}</strong>
            <span>退款相關</span>
          </div>
        </article>
        <article className="mobile-metric">
          <span className="mobile-metric__icon">
            <PackageCheck size={18} aria-hidden="true" />
          </span>
          <div>
            <strong>{orders.length}</strong>
            <span>篩選結果</span>
          </div>
        </article>
      </section>

      <nav className="mobile-filter-scroll" aria-label="訂單狀態篩選">
        {ORDER_FILTERS.map((filter) => (
          <Link
            className="mobile-filter-chip"
            data-active={status === filter.value}
            href={
              filter.value
                ? `/m/orders?status=${encodeURIComponent(filter.value)}`
                : "/m/orders"
            }
            key={filter.value || "all"}
          >
            {filter.label}
          </Link>
        ))}
      </nav>

      {orders.length ? (
        <div className="mobile-order-list mobile-order-list--full">
          {orders.map((order) => (
            <MobileOrderCard
              canOperate={canOperate}
              key={order.id}
              order={order}
            />
          ))}
        </div>
      ) : (
        <EmptyState
          description="目前篩選條件下沒有訂單。"
          title="沒有訂單"
        />
      )}
    </div>
  );
}

function MobileOrderCard({
  order,
  canOperate,
}: {
  order: InternalOrder;
  canOperate: boolean;
}) {
  const restocked = order.events.some(
    (event) => event.reason === "return_received_restocked",
  );

  return (
    <article className="mobile-order-card">
      <header className="mobile-order-card__head">
        <div>
          <span className="mono">{order.order_number}</span>
          <small>{formatDateTime(order.created_at)}</small>
        </div>
        <OrderStatus value={order.status} />
      </header>

      <div className="mobile-order-card__item">
        <h2>{order.item.title}</h2>
        <strong>{formatHKD(order.total_hkd)}</strong>
      </div>

      <dl className="mobile-order-card__facts">
        <div>
          <dt>買家</dt>
          <dd>{order.buyer.display_name}</dd>
        </div>
        <div>
          <dt>聯絡</dt>
          <dd>{valueFrom(order.contact, "phone")}</dd>
        </div>
        <div>
          <dt>商家</dt>
          <dd>{order.merchant.display_name}</dd>
        </div>
        <div>
          <dt>商家應收</dt>
          <dd>{formatHKD(order.merchant_net_hkd)}</dd>
        </div>
      </dl>

      {canOperate ? (
        <div className="mobile-order-actions">
          {order.status === "paid" ? (
            <form action={fulfillOrderAction}>
              <input name="order_id" type="hidden" value={order.id} />
              <input name="status" type="hidden" value="processing" />
              <input name="note" type="hidden" value="mobile_processing" />
              <SubmitButton small>開始備貨</SubmitButton>
            </form>
          ) : null}
          {["paid", "processing"].includes(order.status) ? (
            <form action={fulfillOrderAction}>
              <input name="order_id" type="hidden" value={order.id} />
              <input name="status" type="hidden" value="shipped" />
              <input name="note" type="hidden" value="mobile_shipped" />
              <SubmitButton small>標記已發貨</SubmitButton>
            </form>
          ) : null}
          {order.status === "refunded" && !restocked ? (
            <form action={restockOrderAction}>
              <input name="order_id" type="hidden" value={order.id} />
              <SubmitButton small>庫存歸位</SubmitButton>
            </form>
          ) : null}
          {order.status === "refunded" && restocked ? (
            <span className="subtext">庫存已重新上架</span>
          ) : null}
          {REFUNDABLE.has(order.status) ? (
            <details className="mobile-refund">
              <summary>退款</summary>
              <form action={refundOrderAction}>
                <input name="order_id" type="hidden" value={order.id} />
                <div className="field">
                  <label htmlFor={`refund-reason-${order.id}`}>退款原因</label>
                  <input
                    className="input"
                    defaultValue="平台退款"
                    id={`refund-reason-${order.id}`}
                    minLength={2}
                    name="reason"
                    required
                  />
                </div>
                <SubmitButton small>確認退款</SubmitButton>
              </form>
            </details>
          ) : null}
          {!["paid", "processing", "shipped", "completed"].includes(
            order.status,
          ) && order.status !== "refunded" ? (
            <span className="subtext">此狀態目前沒有可執行操作。</span>
          ) : null}
        </div>
      ) : null}
    </article>
  );
}
