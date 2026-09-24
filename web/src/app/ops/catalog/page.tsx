import {
  AlertTriangle,
  Boxes,
  CheckCircle2,
  CircleDollarSign,
  PackagePlus,
  ShieldCheck,
  Store,
  Zap,
} from "lucide-react";
import Link from "next/link";

import { QuickListingForm } from "@/components/quick-listing-form";
import { SubmitButton } from "@/components/submit-button";
import { EmptyState } from "@/components/states";
import { api } from "@/lib/api";
import { formatDateTime, formatHKD } from "@/lib/format";
import type {
  InventoryItem,
  Merchant,
  Meta,
  StoreListing,
  User,
} from "@/lib/types";

import {
  createMerchantAction,
  publishSellerListingAction,
  quickCreateSellerListingAction,
  updateMerchantStatusAction,
} from "./actions";

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

export default async function CatalogPage({
  searchParams,
}: {
  searchParams: SearchParams;
}) {
  const params = await searchParams;
  const principal = await api.currentPrincipal().catch(() => null);
  const canOperate = Boolean(
    principal?.roles.some((role) => role === "admin" || role === "operator"),
  );
  const isAdmin = Boolean(principal?.roles.includes("admin"));

  const [meta, merchants, inventory, listings, users] = await Promise.all([
    safe(api.meta()),
    safe(api.internalMerchants()),
    safe(api.internalInventory()),
    safe(api.internalSellerListings()),
    isAdmin ? safe(api.internalUsers()) : Promise.resolve([] as User[]),
  ]);

  const merchantRows = merchants ?? [];
  const inventoryRows = inventory ?? [];
  const listingRows = listings ?? [];
  const userRows = users ?? [];
  const variants = meta?.variants ?? [];
  const activeMerchants = merchantRows.filter(
    (merchant) => merchant.status === "active",
  );

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <span className="eyebrow">Commerce operations</span>
          <h1>商品目錄</h1>
          <p>
            管理平台自營及商家商品，從庫存、驗機資料到公開銷售頁保持同一條資料鏈。
          </p>
        </div>
        <Link className="button button--ghost" href="/ops">
          返回營運台
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

      <section className="metrics-grid" aria-label="商品目錄摘要">
        <article className="metric">
          <span className="metric__label">
            <Store size={13} /> 商家
          </span>
          <strong className="metric__value">{merchantRows.length}</strong>
          <span className="metric__note">
            {activeMerchants.length} 個可上架
          </span>
        </article>
        <article className="metric">
          <span className="metric__label">
            <Boxes size={13} /> 庫存
          </span>
          <strong className="metric__value">{inventoryRows.length}</strong>
          <span className="metric__note">
            {inventoryRows.filter((item) => item.listing_id).length} 件已建立銷售頁
          </span>
        </article>
        <article className="metric">
          <span className="metric__label">
            <CircleDollarSign size={13} /> 銷售頁
          </span>
          <strong className="metric__value">{listingRows.length}</strong>
          <span className="metric__note">
            {listingRows.filter((item) => item.status === "active").length} 件已發布
          </span>
        </article>
        <article className="metric">
          <span className="metric__label">
            <ShieldCheck size={13} /> 驗機資料
          </span>
          <strong className="metric__value">
            {
              inventoryRows.filter(
                (item) => item.battery_health_pct !== null,
              ).length
            }
          </strong>
          <span className="metric__note">已登記電池健康度</span>
        </article>
      </section>

      {canOperate ? (
        <div className="section-stack">
          <section className="panel">
            <header className="panel__header">
              <h2>快速上架</h2>
              <span className="subtext">
                <Zap size={13} aria-hidden="true" /> 填寫核心資料，直接發布
              </span>
            </header>
            <div className="panel__body">
              {activeMerchants.length && variants.length ? (
                <QuickListingForm
                  action={quickCreateSellerListingAction}
                  merchants={activeMerchants}
                  variants={variants}
                />
              ) : (
                <EmptyState
                  description="先展開下方的進階設定，建立至少一個已核准商家。"
                  title="尚未具備快速上架條件"
                />
              )}
            </div>
          </section>

          <details className="advanced-panel">
            <summary>進階管理</summary>
            <div className="section-stack">
          <section className="panel">
            <header className="panel__header">
              <h2>建立商家</h2>
              <span className="subtext">
                <PackagePlus size={13} aria-hidden="true" /> B2C 商家檔案
              </span>
            </header>
            <div className="panel__body">
              <form action={createMerchantAction} className="catalog-form">
                <div className="field">
                  <label htmlFor="merchant-display-name">店鋪名稱</label>
                  <input
                    className="input"
                    id="merchant-display-name"
                    maxLength={120}
                    name="display_name"
                    required
                  />
                </div>
                <div className="field">
                  <label htmlFor="merchant-legal-name">法定名稱</label>
                  <input
                    className="input"
                    id="merchant-legal-name"
                    maxLength={180}
                    name="legal_name"
                    required
                  />
                </div>
                <div className="field">
                  <label htmlFor="merchant-type">類型</label>
                  <select
                    className="select"
                    defaultValue="platform"
                    id="merchant-type"
                    name="merchant_type"
                  >
                    <option value="platform">平台自營</option>
                    <option value="business">B2C 商家</option>
                    <option value="individual">個人賣家預留</option>
                  </select>
                </div>
                <div className="field">
                  <label htmlFor="merchant-status">狀態</label>
                  <select
                    className="select"
                    defaultValue="active"
                    id="merchant-status"
                    name="status"
                  >
                    <option value="active">已核准</option>
                    <option value="pending">待審核</option>
                    <option value="suspended">已暫停</option>
                  </select>
                </div>
                <div className="field">
                  <label htmlFor="commission-pct">佣金 %</label>
                  <input
                    className="input"
                    defaultValue="10"
                    id="commission-pct"
                    max="50"
                    min="0"
                    name="commission_pct"
                    step="0.1"
                    type="number"
                  />
                </div>
                {isAdmin ? (
                  <div className="field">
                    <label htmlFor="owner-user-id">擁有人</label>
                    <select
                      className="select"
                      defaultValue=""
                      id="owner-user-id"
                      name="owner_user_id"
                    >
                      <option value="">暫不指派</option>
                      {userRows.map((user) => (
                        <option key={user.id} value={user.id}>
                          {user.display_name} · {user.email}
                        </option>
                      ))}
                    </select>
                  </div>
                ) : null}
                <div className="catalog-form__action">
                  <SubmitButton>建立商家</SubmitButton>
                </div>
              </form>
            </div>
          </section>

            </div>
          </details>
        </div>
      ) : null}

      <div className="section-stack">
        <section className="panel">
          <header className="panel__header">
            <h2>商家</h2>
            <span className="subtext">首版以 B2C 商家及平台自營為主</span>
          </header>
          {merchantRows.length ? (
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>店鋪</th>
                    <th>類型</th>
                    <th>狀態</th>
                    <th>佣金</th>
                    <th>建立時間</th>
                    {canOperate ? <th>操作</th> : null}
                  </tr>
                </thead>
                <tbody>
                  {merchantRows.map((merchant) => (
                    <tr key={merchant.id}>
                      <td>
                        <strong>{merchant.display_name}</strong>
                        <div className="subtext">{merchant.legal_name}</div>
                      </td>
                      <td>{merchantTypeLabel(merchant)}</td>
                      <td>{merchantStatusLabel(merchant.status)}</td>
                      <td className="mono">
                        {(merchant.commission_rate_bps / 100).toFixed(2)}%
                      </td>
                      <td className="mono">
                        {formatDateTime(merchant.created_at)}
                      </td>
                      {canOperate ? (
                        <td>
                          <div className="table-actions">
                            {merchant.status !== "active" ? (
                              <form action={updateMerchantStatusAction}>
                                <input
                                  name="merchant_id"
                                  type="hidden"
                                  value={merchant.id}
                                />
                                <input
                                  name="status"
                                  type="hidden"
                                  value="active"
                                />
                                <SubmitButton small>
                                  {merchant.status === "pending"
                                    ? "核准"
                                    : "恢復"}
                                </SubmitButton>
                              </form>
                            ) : null}
                            {merchant.status === "active" ? (
                              <form action={updateMerchantStatusAction}>
                                <input
                                  name="merchant_id"
                                  type="hidden"
                                  value={merchant.id}
                                />
                                <input
                                  name="status"
                                  type="hidden"
                                  value="suspended"
                                />
                                <SubmitButton small>暫停</SubmitButton>
                              </form>
                            ) : null}
                            {merchant.status === "suspended" ? (
                              <form action={updateMerchantStatusAction}>
                                <input
                                  name="merchant_id"
                                  type="hidden"
                                  value={merchant.id}
                                />
                                <input
                                  name="status"
                                  type="hidden"
                                  value="closed"
                                />
                                <SubmitButton small>關閉</SubmitButton>
                              </form>
                            ) : null}
                          </div>
                        </td>
                      ) : null}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="panel__body">
              <EmptyState
                description="建立第一個平台自營或 B2C 商家後，即可快速上架。"
                title="尚未建立商家"
              />
            </div>
          )}
        </section>

        <section className="panel">
          <header className="panel__header">
            <h2>庫存</h2>
            <span className="subtext">內部成本只在營運台顯示</span>
          </header>
          {inventoryRows.length ? (
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>SKU</th>
                    <th>商品</th>
                    <th>成色 / 電池</th>
                    <th>成本</th>
                    <th>狀態</th>
                    <th>銷售頁</th>
                  </tr>
                </thead>
                <tbody>
                  {inventoryRows.map((item) => (
                    <tr key={item.id}>
                      <td className="mono">{item.sku}</td>
                      <td>
                        {item.model} {item.storage_label}
                      </td>
                      <td>
                        {item.condition_grade} ·{" "}
                        {item.battery_health_pct !== null
                          ? `${item.battery_health_pct}%`
                          : "未記錄"}
                      </td>
                      <td className="mono">
                        {item.cost_hkd !== null
                          ? formatHKD(item.cost_hkd)
                          : "未記錄"}
                      </td>
                      <td>{inventoryStatusLabel(item.status)}</td>
                      <td>
                        {item.listing_id ? (
                          <span className="subtext">
                            {item.listing_id.slice(0, 8)}
                          </span>
                        ) : (
                          "未建立"
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="panel__body">
              <EmptyState
                description="快速上架後，庫存與銷售頁會自動建立並互相關聯。"
                title="尚無庫存"
              />
            </div>
          )}
        </section>

        <section className="panel">
          <header className="panel__header">
            <h2>銷售商品</h2>
            <span className="subtext">草稿通過驗機後才可公開發布</span>
          </header>
          {listingRows.length ? (
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>商品</th>
                    <th>商家</th>
                    <th>售價</th>
                    <th>狀態</th>
                    <th>保養</th>
                    <th>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {listingRows.map((listing) => (
                    <tr key={listing.id}>
                      <td>
                        <strong>{listing.title}</strong>
                        <div className="subtext">
                          {listing.variant.model} ·{" "}
                          {listing.variant.storage_label}
                        </div>
                      </td>
                      <td>{listing.merchant.display_name}</td>
                      <td className="mono">{formatHKD(listing.price_hkd)}</td>
                      <td>{listingStatusLabel(listing.status)}</td>
                      <td>{listing.warranty_days} 日</td>
                      <td>
                        {listing.status === "active" ? (
                          <Link
                            className="button button--ghost button--small"
                            href={`/store/${listing.id}`}
                          >
                            查看
                          </Link>
                        ) : canOperate ? (
                          <form action={publishSellerListingAction}>
                            <input
                              name="listing_id"
                              type="hidden"
                              value={listing.id}
                            />
                            <SubmitButton small>發布</SubmitButton>
                          </form>
                        ) : (
                          <span className="subtext">草稿</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="panel__body">
              <EmptyState
                description="使用快速上架後，商品會直接顯示在這裡及公開商店。"
                title="尚無銷售商品"
              />
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

function merchantTypeLabel(merchant: Merchant): string {
  if (merchant.merchant_type === "platform") {
    return "平台自營";
  }
  if (merchant.merchant_type === "individual") {
    return "個人賣家";
  }
  return "B2C 商家";
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

function inventoryStatusLabel(status: InventoryItem["status"]): string {
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

function listingStatusLabel(status: StoreListing["status"]): string {
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
