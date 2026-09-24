import {
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  CreditCard,
  MapPin,
  PackageCheck,
  ReceiptText,
  ShieldCheck,
  Truck,
  UserRound,
} from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { OrderStatus } from "@/components/order-status";
import { SubmitButton } from "@/components/submit-button";
import { ErrorState } from "@/components/states";
import { ApiError, api } from "@/lib/api";
import {
  formatDateTime,
  formatHKD,
  fulfillmentStatusLabel,
  orderStatusLabel,
  paymentStatusLabel,
  statusTone,
} from "@/lib/format";
import type { Order } from "@/lib/types";

import {
  cancelOrderAction,
  confirmReceiptAction,
  payOrderAction,
} from "../actions";

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
  if (typeof value === "string" || typeof value === "number") {
    return String(value);
  }
  return "未提供";
}

function addressLines(order: Order): string[] {
  const address = order.shipping_address;
  return [
    valueFrom(address, "line1"),
    valueFrom(address, "line2"),
    [valueFrom(address, "district"), valueFrom(address, "region")]
      .filter((value) => value !== "未提供")
      .join(" · "),
  ].filter((value) => value && value !== "未提供");
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ id: string }>;
}): Promise<Metadata> {
  const { id } = await params;
  try {
    const order = await api.order(id);
    return { title: `訂單 ${order.order_number}` };
  } catch {
    return { title: "我的訂單" };
  }
}

export default async function AccountOrderPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: SearchParams;
}) {
  const [{ id }, query] = await Promise.all([params, searchParams]);
  let order: Order;
  try {
    order = await api.order(id);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      notFound();
    }
    return (
      <div className="page">
        <ErrorState
          description={
            error instanceof Error ? error.message : "訂單資料暫時無法讀取。"
          }
          title="無法讀取訂單"
        />
      </div>
    );
  }

  return (
    <div className="page">
      <div className="result-bar">
        <Link className="button button--ghost button--small" href="/account/orders">
          <ArrowLeft size={14} aria-hidden="true" />
          返回我的訂單
        </Link>
        <span>建立於 {formatDateTime(order.created_at)}</span>
      </div>

      {first(query.notice) ? (
        <div className="ops-banner" role="status">
          <CheckCircle2 size={17} aria-hidden="true" />
          {first(query.notice)}
        </div>
      ) : null}
      {first(query.error) ? (
        <div className="ops-banner ops-banner--error" role="alert">
          <AlertTriangle size={17} aria-hidden="true" />
          {first(query.error)}
        </div>
      ) : null}

      <div className="order-detail">
        <div className="section-stack">
          <section className="panel">
            <header className="panel__header">
              <div>
                <span className="subtext mono">{order.order_number}</span>
                <h2>訂單狀態</h2>
              </div>
              <OrderStatus value={order.status} />
            </header>
            <div className="panel__body">
              <div className="order-progress">
                <ProgressStep
                  label="建立訂單"
                  value={orderStatusLabel(order.status)}
                />
                <ProgressStep
                  label="付款"
                  value={paymentStatusLabel(order.payment_status)}
                  tone={statusTone(order.payment_status)}
                />
                <ProgressStep
                  label="履約"
                  value={fulfillmentStatusLabel(order.fulfillment_status)}
                  tone={statusTone(order.fulfillment_status)}
                />
              </div>

              <div className="order-actions">
                {order.status === "pending_payment" ? (
                  <>
                    <form action={payOrderAction}>
                      <input name="order_id" type="hidden" value={order.id} />
                      <SubmitButton accent>前往付款</SubmitButton>
                    </form>
                    <form action={cancelOrderAction} className="order-cancel-form">
                      <input name="order_id" type="hidden" value={order.id} />
                      <input
                        className="input"
                        defaultValue="買家取消"
                        name="reason"
                        placeholder="取消原因"
                      />
                      <SubmitButton small>取消訂單</SubmitButton>
                    </form>
                  </>
                ) : null}
                {order.status === "shipped" ? (
                  <form action={confirmReceiptAction}>
                    <input name="order_id" type="hidden" value={order.id} />
                    <SubmitButton accent>確認收貨</SubmitButton>
                  </form>
                ) : null}
              </div>
            </div>
          </section>

          <section className="panel">
            <header className="panel__header">
              <h2>商品</h2>
              <span className="subtext">
                <PackageCheck size={14} aria-hidden="true" />
                {order.merchant.display_name}
              </span>
            </header>
            <div className="panel__body order-item">
              <div className="order-item__media">
                {order.item.image ? (
                  <img alt={order.item.title} src={order.item.image} />
                ) : (
                  <PackageCheck size={42} aria-hidden="true" />
                )}
              </div>
              <div className="order-item__body">
                <h3>{order.item.title}</h3>
                <div className="listing-row__meta">
                  <span className="chip">
                    {order.item.condition_grade ?? "未分級"} 級
                  </span>
                  <span className="chip">
                    {order.item.model} {order.item.storage_label}
                  </span>
                </div>
                <Link
                  className="button button--ghost button--small"
                  href={`/store/${order.item.listing_id}`}
                >
                  查看商品
                </Link>
              </div>
            </div>
          </section>

          <section className="panel">
            <header className="panel__header">
              <h2>配送資料</h2>
            </header>
            <div className="panel__body contact-grid">
              <div>
                <span className="contact-grid__icon">
                  <UserRound size={17} aria-hidden="true" />
                </span>
                <div>
                  <span className="subtext">收件人</span>
                  <strong>{valueFrom(order.contact, "recipient_name")}</strong>
                  <p>{valueFrom(order.contact, "phone")}</p>
                  <p>{valueFrom(order.contact, "email")}</p>
                </div>
              </div>
              <div>
                <span className="contact-grid__icon">
                  <MapPin size={17} aria-hidden="true" />
                </span>
                <div>
                  <span className="subtext">送貨地址</span>
                  {addressLines(order).map((line) => (
                    <p key={line}>{line}</p>
                  ))}
                </div>
              </div>
            </div>
          </section>

          <section className="panel">
            <header className="panel__header">
              <h2>訂單歷程</h2>
            </header>
            <div className="panel__body">
              <div className="order-timeline">
                {order.events.map((event) => (
                  <article className="timeline-entry" key={event.id}>
                    <span className="timeline-entry__dot" aria-hidden="true" />
                    <div>
                      <strong>{orderStatusLabel(event.to_status)}</strong>
                      <span>{formatDateTime(event.created_at)}</span>
                      <p>{event.reason ?? event.actor}</p>
                    </div>
                  </article>
                ))}
              </div>
            </div>
          </section>
        </div>

        <aside className="side-stack">
          <section className="panel">
            <header className="panel__header">
              <h2>付款明細</h2>
              <CreditCard size={16} aria-hidden="true" />
            </header>
            <div className="panel__body">
              <dl className="price-summary">
                <div>
                  <dt>商品金額</dt>
                  <dd>{formatHKD(order.item_price_hkd)}</dd>
                </div>
                <div>
                  <dt>運費</dt>
                  <dd>{formatHKD(order.shipping_fee_hkd)}</dd>
                </div>
                <div className="price-summary__total">
                  <dt>付款總額</dt>
                  <dd>{formatHKD(order.total_hkd)}</dd>
                </div>
              </dl>
            </div>
          </section>

          {order.payment_intent ? (
            <section className="panel">
              <header className="panel__header">
                <h2>支付記錄</h2>
              </header>
              <div className="panel__body">
                <dl className="compact-list">
                  <div>
                    <dt>支付服務</dt>
                    <dd>{order.payment_intent.provider}</dd>
                  </div>
                  <div>
                    <dt>狀態</dt>
                    <dd>{paymentStatusLabel(order.payment_intent.status)}</dd>
                  </div>
                  <div>
                    <dt>參考編號</dt>
                    <dd className="mono">
                      {order.payment_intent.provider_reference}
                    </dd>
                  </div>
                </dl>
              </div>
            </section>
          ) : null}

          {order.settlement ? (
            <section className="panel">
              <header className="panel__header">
                <h2>商家結算</h2>
                <ShieldCheck size={16} aria-hidden="true" />
              </header>
              <div className="panel__body">
                <dl className="compact-list">
                  <div>
                    <dt>結算狀態</dt>
                    <dd>{order.settlement.status}</dd>
                  </div>
                  <div>
                    <dt>平台佣金</dt>
                    <dd>{formatHKD(order.settlement.commission_hkd)}</dd>
                  </div>
                  <div>
                    <dt>商家應收</dt>
                    <dd>{formatHKD(order.settlement.net_hkd)}</dd>
                  </div>
                </dl>
              </div>
            </section>
          ) : null}

          {order.refund ? (
            <section className="panel">
              <header className="panel__header">
                <h2>退款記錄</h2>
                <ReceiptText size={16} aria-hidden="true" />
              </header>
              <div className="panel__body">
                <dl className="compact-list">
                  <div>
                    <dt>退款狀態</dt>
                    <dd>{order.refund.status}</dd>
                  </div>
                  <div>
                    <dt>退款金額</dt>
                    <dd>{formatHKD(order.refund.amount_hkd)}</dd>
                  </div>
                  <div>
                    <dt>原因</dt>
                    <dd>{order.refund.reason}</dd>
                  </div>
                </dl>
              </div>
            </section>
          ) : null}

          <div className="callout">
            <h2>
              <Truck size={15} aria-hidden="true" /> 平台代收貨款
            </h2>
            <p>
              付款先由持牌支付服務代收；確認收貨後，平台才建立商家結算。
            </p>
          </div>
        </aside>
      </div>
    </div>
  );
}

function ProgressStep({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: string;
}) {
  return (
    <div className="order-progress__step">
      <span>{label}</span>
      <strong className={tone ? `text-${tone}` : undefined}>{value}</strong>
    </div>
  );
}
