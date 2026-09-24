import { randomUUID } from "node:crypto";

import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  CircleDollarSign,
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
import {
  formatDateTime,
  formatHKD,
  ledgerEventLabel,
} from "@/lib/format";
import type { InternalOrder, LedgerJournal } from "@/lib/types";

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
  { value: "completed", label: "已完成" },
  { value: "refund_pending", label: "退款中" },
  { value: "refunded", label: "已退款" },
  { value: "cancelled", label: "已取消" },
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

export default async function OpsOrdersPage({
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
  const [ordersResult, ledgerResult] = await Promise.all([
    safe(api.internalOrders(status || undefined, 200)),
    safe(api.internalLedger(undefined, 100)),
  ]);

  if (!ordersResult.data && !ledgerResult.data) {
    return (
      <div className="page">
        <ErrorState
          description={ordersResult.error ?? ledgerResult.error ?? "無法讀取訂單"}
          title="訂單台無法連接內部資料"
        />
      </div>
    );
  }

  const orders = ordersResult.data ?? [];
  const journals = ledgerResult.data ?? [];
  const unpaid = orders.filter(
    (order) => order.status === "pending_payment",
  ).length;
  const fulfillment = orders.filter((order) =>
    ["paid", "processing", "shipped"].includes(order.status),
  ).length;
  const refunds = orders.filter((order) =>
    ["refund_pending", "refunded"].includes(order.status),
  ).length;
  const gross = journals
    .filter((journal) => journal.event_type === "payment_captured")
    .reduce(
      (total, journal) =>
        total +
        journal.entries.reduce((sum, entry) => sum + entry.debit_hkd, 0),
      0,
    );

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <span className="eyebrow">Order operations</span>
          <h1>訂單與結算</h1>
          <p>處理付款後履約、退款，並核對平台代收與商家結算總帳。</p>
        </div>
        <div className="ops-header-actions">
          <Link className="button button--ghost" href="/ops">
            返回營運台
          </Link>
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

      <section className="metrics-grid" aria-label="訂單摘要">
        <article className="metric">
          <span className="metric__label">
            <PackageCheck size={13} /> 待付款
          </span>
          <strong className="metric__value">{unpaid}</strong>
          <span className="metric__note">目前篩選範圍</span>
        </article>
        <article className="metric">
          <span className="metric__label">
            <Truck size={13} /> 待履約
          </span>
          <strong className="metric__value">{fulfillment}</strong>
          <span className="metric__note">已付款至已發貨</span>
        </article>
        <article className="metric">
          <span className="metric__label">
            <RotateCcw size={13} /> 退款
          </span>
          <strong className="metric__value">{refunds}</strong>
          <span className="metric__note">處理中及已完成</span>
        </article>
        <article className="metric">
          <span className="metric__label">
            <CircleDollarSign size={13} /> 代收總額
          </span>
          <strong className="metric__value">{formatHKD(gross)}</strong>
          <span className="metric__note">最近 {journals.length} 筆總帳分錄</span>
        </article>
      </section>

      <nav className="order-filter" aria-label="訂單狀態篩選">
        {ORDER_FILTERS.map((filter) => (
          <Link
            className="button button--ghost button--small"
            data-active={status === filter.value}
            href={
              filter.value
                ? `/ops/orders?status=${encodeURIComponent(filter.value)}`
                : "/ops/orders"
            }
            key={filter.value || "all"}
          >
            {filter.label}
          </Link>
        ))}
      </nav>

      <section className="panel">
        <header className="panel__header">
          <h2>訂單列表</h2>
          <span className="subtext">
            <ReceiptText size={13} aria-hidden="true" />
            {orders.length} 筆
          </span>
        </header>
        {orders.length ? (
          <div className="table-wrap">
            <table className="data-table order-table">
              <thead>
                <tr>
                  <th>訂單 / 買家</th>
                  <th>商品</th>
                  <th>金額</th>
                  <th>狀態</th>
                  <th>建立時間</th>
                  {canOperate ? <th>操作</th> : null}
                </tr>
              </thead>
              <tbody>
                {orders.map((order) => (
                  <OrderRow
                    canOperate={canOperate}
                    key={order.id}
                    order={order}
                  />
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="panel__body">
            <EmptyState
              description="目前篩選條件下沒有訂單。"
              title="沒有訂單"
            />
          </div>
        )}
      </section>

      <section className="panel section-stack">
        <header className="panel__header">
          <h2>總帳分錄</h2>
          <span className="subtext">
            付款、結算與退款使用同一組複式分錄
          </span>
        </header>
        {journals.length ? (
          <div className="ledger-list">
            {journals.map((journal) => (
              <Journal key={journal.id} journal={journal} />
            ))}
          </div>
        ) : (
          <div className="panel__body">
            <EmptyState
              description="首筆成功付款後會產生總帳分錄。"
              title="尚無總帳資料"
            />
          </div>
        )}
      </section>
    </div>
  );
}

function OrderRow({
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
    <tr>
      <td>
        <strong className="mono">{order.order_number}</strong>
        <div className="subtext">
          {order.buyer.display_name} · {order.buyer.email}
        </div>
      </td>
      <td>
        <span className="truncate" title={order.item.title}>
          {order.item.title}
        </span>
        <div className="subtext">
          {order.merchant.display_name} · {valueFrom(order.contact, "phone")}
        </div>
      </td>
      <td className="mono">
        {formatHKD(order.total_hkd)}
        <div className="subtext">
          商家 {formatHKD(order.merchant_net_hkd)}
        </div>
      </td>
      <td>
        <OrderStatus value={order.status} />
        <div className="subtext">
          {order.payment_status} / {order.fulfillment_status}
        </div>
      </td>
      <td className="mono">{formatDateTime(order.created_at)}</td>
      {canOperate ? (
        <td>
          <div className="table-actions">
            {order.status === "paid" ? (
              <form action={fulfillOrderAction}>
                <input name="order_id" type="hidden" value={order.id} />
                <input name="status" type="hidden" value="processing" />
                <input name="note" type="hidden" value="operator_processing" />
                <SubmitButton small>開始處理</SubmitButton>
              </form>
            ) : null}
            {["paid", "processing"].includes(order.status) ? (
              <form action={fulfillOrderAction}>
                <input name="order_id" type="hidden" value={order.id} />
                <input name="status" type="hidden" value="shipped" />
                <input name="note" type="hidden" value="operator_shipped" />
                <SubmitButton small>標記發貨</SubmitButton>
              </form>
            ) : null}
            {REFUNDABLE.has(order.status) ? (
              <form action={refundOrderAction} className="refund-form">
                <input name="order_id" type="hidden" value={order.id} />
                <input
                  name="idempotency_key"
                  type="hidden"
                  value={`refund:${order.id}:${randomUUID()}`}
                />
                <input
                  className="input input--compact"
                  defaultValue="平台退款"
                  minLength={2}
                  name="reason"
                  required
                />
                <SubmitButton small>退款</SubmitButton>
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
            {!["paid", "processing", "shipped", "completed"].includes(
              order.status,
            ) && order.status !== "refunded" ? (
              <span className="subtext">無可用操作</span>
            ) : null}
          </div>
        </td>
      ) : null}
    </tr>
  );
}

function Journal({ journal }: { journal: LedgerJournal }) {
  const debit = journal.entries.reduce(
    (total, entry) => total + entry.debit_hkd,
    0,
  );
  const credit = journal.entries.reduce(
    (total, entry) => total + entry.credit_hkd,
    0,
  );
  return (
    <details className="ledger-entry">
      <summary>
        <span className="ledger-entry__type">
          {ledgerEventLabel(journal.event_type)}
        </span>
        <span>{journal.memo}</span>
        <span className="mono">{formatHKD(debit)}</span>
        <ArrowRight size={14} aria-hidden="true" />
      </summary>
      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th>科目</th>
              <th>類型</th>
              <th>借方</th>
              <th>貸方</th>
            </tr>
          </thead>
          <tbody>
            {journal.entries.map((entry) => (
              <tr key={entry.id}>
                <td>
                  <strong>{entry.account_name}</strong>
                  <div className="subtext mono">
                    {entry.account_code}
                  </div>
                </td>
                <td>{entry.account_type}</td>
                <td className="mono">
                  {entry.debit_hkd ? formatHKD(entry.debit_hkd) : "—"}
                </td>
                <td className="mono">
                  {entry.credit_hkd ? formatHKD(entry.credit_hkd) : "—"}
                </td>
              </tr>
            ))}
            <tr>
              <td colSpan={2}>
                <strong>合計</strong>
              </td>
              <td className="mono">{formatHKD(debit)}</td>
              <td className="mono">{formatHKD(credit)}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div className="ledger-entry__meta">
        <span>{formatDateTime(journal.created_at)}</span>
        <span className="mono">{journal.order_id ?? "無訂單"}</span>
      </div>
    </details>
  );
}
