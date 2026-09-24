import { randomUUID } from "node:crypto";

import {
  AlertTriangle,
  ArrowLeft,
  BatteryCharging,
  CheckCircle2,
  CreditCard,
  PackageCheck,
  ShieldCheck,
  Smartphone,
  Store,
  Wrench,
} from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { ErrorState } from "@/components/states";
import { SubmitButton } from "@/components/submit-button";
import { ApiError, api } from "@/lib/api";
import { formatDateTime, formatHKD } from "@/lib/format";
import type { Meta, StoreListing } from "@/lib/types";

import { placeOrderAction } from "./actions";

export const dynamic = "force-dynamic";

type SearchParams = Promise<{
  error?: string | string[];
}>;

function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

const FALLBACK_DISTRICTS = [
  { value: "中西區", label: "中西區" },
  { value: "灣仔", label: "灣仔" },
  { value: "東區", label: "東區" },
  { value: "南區", label: "南區" },
  { value: "油尖旺", label: "油尖旺" },
  { value: "深水埗", label: "深水埗" },
  { value: "九龍城", label: "九龍城" },
  { value: "黃大仙", label: "黃大仙" },
  { value: "觀塘", label: "觀塘" },
  { value: "葵青", label: "葵青" },
  { value: "荃灣", label: "荃灣" },
  { value: "屯門", label: "屯門" },
  { value: "元朗", label: "元朗" },
  { value: "北區", label: "北區" },
  { value: "大埔", label: "大埔" },
  { value: "沙田", label: "沙田" },
  { value: "西貢", label: "西貢" },
  { value: "離島", label: "離島" },
];

export async function generateMetadata({
  params,
}: {
  params: Promise<{ id: string }>;
}): Promise<Metadata> {
  const { id } = await params;
  try {
    const listing = await api.storeListing(id);
    return {
      title: listing.title,
      description: `${listing.variant.model} ${listing.variant.storage_label} · ${formatHKD(listing.price_hkd)}`,
    };
  } catch {
    return { title: "平台商品" };
  }
}

export default async function StoreListingPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: SearchParams;
}) {
  const [{ id }, query] = await Promise.all([params, searchParams]);
  let listing: StoreListing;
  try {
    listing = await api.storeListing(id);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      notFound();
    }
    return (
      <div className="page">
        <ErrorState
          description={
            error instanceof Error
              ? error.message
              : "平台商品資料暫時無法讀取。"
          }
        />
      </div>
    );
  }
  const meta = await api.meta().catch<Meta | null>(() => null);
  const districts = meta?.districts.length
    ? meta.districts
    : FALLBACK_DISTRICTS;

  const image = listing.images[0];
  const idempotencyKey = randomUUID();
  const reportEntries = Object.entries(listing.inspection_report).filter(
    ([, value]) => typeof value === "string" || typeof value === "number",
  );

  return (
    <div className="page">
      <div className="result-bar">
        <Link className="button button--ghost button--small" href="/store">
          <ArrowLeft size={14} aria-hidden="true" />
          返回平台商店
        </Link>
        <span>上架於 {formatDateTime(listing.published_at)}</span>
      </div>

      {first(query.error) ? (
        <div className="ops-banner ops-banner--error" role="alert">
          <AlertTriangle size={17} aria-hidden="true" />
          {first(query.error)}
        </div>
      ) : null}

      <div className="store-detail">
        <section className="store-detail__gallery">
          {image ? (
            <img alt={listing.title} src={image} />
          ) : (
            <div className="store-detail__placeholder">
              <Smartphone size={88} strokeWidth={1.15} aria-hidden="true" />
            </div>
          )}
        </section>

        <section className="store-detail__summary">
          <div className="listing-row__meta">
            <span className="badge badge--source">平台商店</span>
            <span className="badge badge--condition">
              {listing.inventory.condition_grade} 級
            </span>
            <span className="chip">{listing.variant.storage_label}</span>
          </div>

          <h1>{listing.title}</h1>
          <p className="store-detail__model">
            {listing.variant.model} · {listing.variant.storage_label}
          </p>
          <div className="store-detail__price">
            <strong>{formatHKD(listing.price_hkd)}</strong>
            <span>HKD</span>
          </div>

          <div className="store-detail__merchant">
            <span className="store-detail__merchant-icon">
              <Store size={18} aria-hidden="true" />
            </span>
            <div>
              <span className="subtext">銷售商家</span>
              <strong>{listing.merchant.display_name}</strong>
            </div>
          </div>

          <div className="store-detail__assurances">
            <span>
              <CheckCircle2 size={16} aria-hidden="true" />
              {listing.warranty_days} 日保養
            </span>
            <span>
              <ShieldCheck size={16} aria-hidden="true" />
              平台代收貨款
            </span>
          </div>

          <div className="payment-callout">
            <ShieldCheck size={19} aria-hidden="true" />
            <div>
              <strong>付款及結算保障</strong>
              <p>
                買家付款由持牌支付服務處理；確認收貨後，平台安排向商家結算。
              </p>
            </div>
          </div>

          <form action={placeOrderAction} className="checkout-form">
            <input name="listing_id" type="hidden" value={listing.id} />
            <input
              name="idempotency_key"
              type="hidden"
              value={idempotencyKey}
            />
            <div className="checkout-form__heading">
              <div>
                <strong>送貨資料</strong>
                <span>提交後將跳轉至支付服務完成付款。</span>
              </div>
              <CreditCard size={18} aria-hidden="true" />
            </div>
            <div className="checkout-form__fields">
              <div className="field">
                <label htmlFor="checkout-recipient">收件人</label>
                <input
                  autoComplete="name"
                  className="input"
                  id="checkout-recipient"
                  maxLength={120}
                  name="recipient_name"
                  required
                />
              </div>
              <div className="field">
                <label htmlFor="checkout-phone">聯絡電話</label>
                <input
                  autoComplete="tel"
                  className="input"
                  id="checkout-phone"
                  maxLength={40}
                  minLength={5}
                  name="phone"
                  required
                />
              </div>
              <div className="field field--wide">
                <label htmlFor="checkout-email">電子郵件</label>
                <input
                  autoComplete="email"
                  className="input"
                  id="checkout-email"
                  maxLength={320}
                  name="email"
                  required
                  type="email"
                />
              </div>
              <div className="field field--wide">
                <label htmlFor="checkout-line1">地址</label>
                <input
                  autoComplete="address-line1"
                  className="input"
                  id="checkout-line1"
                  maxLength={200}
                  name="line1"
                  required
                />
              </div>
              <div className="field field--wide">
                <label htmlFor="checkout-line2">樓層及單位</label>
                <input
                  autoComplete="address-line2"
                  className="input"
                  id="checkout-line2"
                  maxLength={200}
                  name="line2"
                />
              </div>
              <div className="field">
                <label htmlFor="checkout-district">地區</label>
                <select
                  className="select"
                  id="checkout-district"
                  name="district"
                  required
                >
                  {districts.map((district) => (
                    <option key={district.value} value={district.value}>
                      {district.label}
                    </option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label htmlFor="checkout-region">區域</label>
                <input
                  className="input"
                  defaultValue="香港"
                  id="checkout-region"
                  name="region"
                  required
                />
              </div>
            </div>
            <div className="checkout-form__action">
              <span>
                合計 <strong>{formatHKD(listing.price_hkd)}</strong>
              </span>
              <SubmitButton accent>建立訂單並付款</SubmitButton>
            </div>
          </form>
        </section>
      </div>

      <div className="store-detail__content">
        <div>
          <section className="panel">
            <header className="panel__header">
              <h2>驗機與機況</h2>
              <span className="subtext">
                <PackageCheck size={14} aria-hidden="true" />
                平台資料
              </span>
            </header>
            <div className="panel__body">
              <dl className="store-facts">
                <div>
                  <dt>成色等級</dt>
                  <dd>{listing.inventory.condition_grade} 級</dd>
                </div>
                <div>
                  <dt>電池健康度</dt>
                  <dd>
                    <BatteryCharging size={15} aria-hidden="true" />
                    {listing.inventory.battery_health_pct === null
                      ? "未提供"
                      : `${listing.inventory.battery_health_pct}%`}
                  </dd>
                </div>
                <div>
                  <dt>維修記錄</dt>
                  <dd>
                    <Wrench size={15} aria-hidden="true" />
                    {listing.inventory.repair_history.length
                      ? `${listing.inventory.repair_history.length} 項`
                      : "無已登記項目"}
                  </dd>
                </div>
                <div>
                  <dt>隨附配件</dt>
                  <dd>
                    {listing.inventory.accessories.length
                      ? listing.inventory.accessories.join("、")
                      : "無配件"}
                  </dd>
                </div>
              </dl>
            </div>
          </section>

          <section className="panel section-stack">
            <header className="panel__header">
              <h2>商品說明</h2>
            </header>
            <div className="panel__body store-description">
              <p>{listing.description || "商家暫未提供額外商品說明。"}</p>
            </div>
          </section>
        </div>

        <aside className="side-stack">
          <section className="panel">
            <header className="panel__header">
              <h2>驗機報告</h2>
            </header>
            {reportEntries.length ? (
              <div className="panel__body">
                <dl className="report-list">
                  {reportEntries.map(([key, value]) => (
                    <div key={key}>
                      <dt>{key}</dt>
                      <dd>{String(value)}</dd>
                    </div>
                  ))}
                </dl>
              </div>
            ) : (
              <div className="panel__body">
                <p className="subtext">此商品未附加報告摘要。</p>
              </div>
            )}
          </section>
        </aside>
      </div>
    </div>
  );
}
