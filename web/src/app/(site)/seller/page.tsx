import {
  AlertTriangle,
  ArrowRight,
  Boxes,
  CheckCircle2,
  Clock3,
  PackageCheck,
  Settings2,
  Store,
} from "lucide-react";
import Link from "next/link";

import { SubmitButton } from "@/components/submit-button";
import { api } from "@/lib/api";
import { formatHKD } from "@/lib/format";
import type { Merchant } from "@/lib/types";

import { applySellerAction } from "./actions";

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

export default async function SellerPage({
  searchParams,
}: {
  searchParams: SearchParams;
}) {
  const params = await searchParams;
  const profile = await safe(api.sellerProfile());

  if (!profile) {
    return (
      <div className="page">
        <header className="page-header">
          <div>
            <span className="eyebrow">Seller onboarding</span>
            <h1>申請成為賣家</h1>
            <p>提交店鋪基本資料，審核通過後即可快速上架及處理銷售訂單。</p>
          </div>
        </header>
        <SellerBanners params={params} />
        <section className="panel">
          <header className="panel__header">
            <h2>開店資料</h2>
            <span className="subtext">
              <Settings2 size={13} aria-hidden="true" />
              平台代收貨款
            </span>
          </header>
          <div className="panel__body">
            <form action={applySellerAction} className="catalog-form">
              <div className="field">
                <label htmlFor="seller-display-name">店鋪名稱</label>
                <input
                  autoComplete="organization"
                  className="input"
                  id="seller-display-name"
                  maxLength={120}
                  name="display_name"
                  required
                />
              </div>
              <div className="field">
                <label htmlFor="seller-legal-name">商業登記名稱</label>
                <input
                  autoComplete="organization"
                  className="input"
                  id="seller-legal-name"
                  maxLength={180}
                  name="legal_name"
                  required
                />
              </div>
              <div className="field">
                <label htmlFor="seller-merchant-type">賣家類型</label>
                <select
                  className="select"
                  defaultValue="business"
                  id="seller-merchant-type"
                  name="merchant_type"
                >
                  <option value="business">B2C 商家</option>
                  <option value="individual">個人賣家</option>
                </select>
              </div>
              <div className="catalog-form__action">
                <SubmitButton>提交審核</SubmitButton>
              </div>
            </form>
          </div>
        </section>
      </div>
    );
  }

  const [listings, orders] = await Promise.all([
    safe(api.sellerListings()),
    safe(api.sellerOrders()),
  ]);
  const listingRows = listings ?? [];
  const orderRows = orders ?? [];
  const activeListings = listingRows.filter(
    (listing) => listing.status === "active",
  ).length;
  const paidOrders = orderRows.filter((order) =>
    ["paid", "processing", "shipped"].includes(order.status),
  ).length;
  const salesValue = orderRows
    .filter((order) => order.status !== "cancelled")
    .reduce((total, order) => total + order.merchant_net_hkd, 0);

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <span className="eyebrow">Seller workspace</span>
          <h1>{profile.display_name}</h1>
          <p>{merchantStatusDescription(profile)}</p>
        </div>
        {profile.status === "active" ? (
          <Link className="button" href="/seller/listings/new">
            <Store size={15} aria-hidden="true" />
            快速上架
          </Link>
        ) : null}
      </header>

      <SellerBanners params={params} />
      <MerchantStatusBanner merchant={profile} />

      <section className="metrics-grid" aria-label="賣家摘要">
        <article className="metric">
          <span className="metric__label">
            <Boxes size={13} /> 上架商品
          </span>
          <strong className="metric__value">{activeListings}</strong>
          <span className="metric__note">共 {listingRows.length} 件商品</span>
        </article>
        <article className="metric">
          <span className="metric__label">
            <PackageCheck size={13} /> 待履約訂單
          </span>
          <strong className="metric__value">{paidOrders}</strong>
          <span className="metric__note">已付款至已發貨</span>
        </article>
        <article className="metric">
          <span className="metric__label">
            <Store size={13} /> 商品總值
          </span>
          <strong className="metric__value">
            {formatHKD(
              listingRows.reduce(
                (total, listing) => total + (listing.price_hkd ?? 0),
                0,
              ),
            )}
          </strong>
          <span className="metric__note">目前商品標價合計</span>
        </article>
        <article className="metric">
          <span className="metric__label">
            <CheckCircle2 size={13} /> 預估商家收入
          </span>
          <strong className="metric__value">{formatHKD(salesValue)}</strong>
          <span className="metric__note">已扣除平台佣金</span>
        </article>
      </section>

      <section className="panel">
        <header className="panel__header">
          <h2>店鋪資料</h2>
          <span className="subtext mono">{profile.id.slice(0, 8)}</span>
        </header>
        <div className="panel__body">
          <dl className="seller-facts">
            <div>
              <dt>類型</dt>
              <dd>{merchantTypeLabel(profile)}</dd>
            </div>
            <div>
              <dt>商業名稱</dt>
              <dd>{profile.legal_name}</dd>
            </div>
            <div>
              <dt>平台佣金</dt>
              <dd>{(profile.commission_rate_bps / 100).toFixed(2)}%</dd>
            </div>
            <div>
              <dt>審核狀態</dt>
              <dd>{merchantStatusLabel(profile.status)}</dd>
            </div>
          </dl>
        </div>
      </section>

      <section className="panel">
        <header className="panel__header">
          <h2>下一步</h2>
          <span className="subtext">賣家工作流程</span>
        </header>
        <div className="seller-links">
          <Link href="/seller/listings">
            <strong>管理我的商品</strong>
            <span>{listingRows.length} 件商品</span>
            <ArrowRight size={15} aria-hidden="true" />
          </Link>
          <Link href="/seller/orders">
            <strong>處理銷售訂單</strong>
            <span>{paidOrders} 筆待履約</span>
            <ArrowRight size={15} aria-hidden="true" />
          </Link>
        </div>
      </section>
    </div>
  );
}

function SellerBanners({
  params,
}: {
  params: {
    notice?: string | string[];
    error?: string | string[];
  };
}) {
  return (
    <>
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
    </>
  );
}

function MerchantStatusBanner({ merchant }: { merchant: Merchant }) {
  if (merchant.status === "active") {
    return null;
  }
  if (merchant.status === "pending") {
    return (
      <div className="seller-callout" role="status">
        <Clock3 size={18} aria-hidden="true" />
        <div>
          <strong>開店申請審核中</strong>
          <span>審核通過前可以查看中心，但暫時不能發布商品。</span>
        </div>
      </div>
    );
  }
  return (
    <div className="seller-callout seller-callout--warning" role="alert">
      <AlertTriangle size={18} aria-hidden="true" />
      <div>
        <strong>
          {merchant.status === "suspended" ? "店鋪已暫停" : "店鋪已關閉"}
        </strong>
        <span>現有商品不會在公開商店展示，新的上架操作會被拒絕。</span>
      </div>
    </div>
  );
}

function merchantTypeLabel(merchant: Merchant): string {
  return merchant.merchant_type === "individual" ? "個人賣家" : "B2C 商家";
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

function merchantStatusDescription(merchant: Merchant): string {
  if (merchant.status === "pending") {
    return "店鋪資料已提交，審核通過後即可開始上架。";
  }
  if (merchant.status === "suspended") {
    return "店鋪目前暫停營運，現有銷售訂單仍可繼續處理。";
  }
  if (merchant.status === "closed") {
    return "店鋪已關閉，請聯絡平台人員處理後續安排。";
  }
  return "管理商品、訂單及履約狀態。";
}
