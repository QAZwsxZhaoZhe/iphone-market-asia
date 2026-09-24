import {
  AlertTriangle,
  ArrowRight,
  Boxes,
  CheckCircle2,
  PlusCircle,
} from "lucide-react";
import Link from "next/link";
import { redirect } from "next/navigation";

import { EmptyState, ErrorState } from "@/components/states";
import { api } from "@/lib/api";
import { formatDateTime, formatHKD } from "@/lib/format";
import type { StoreListing } from "@/lib/types";

export const dynamic = "force-dynamic";

type SearchParams = Promise<{
  notice?: string | string[];
  error?: string | string[];
}>;

function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

export default async function SellerListingsPage({
  searchParams,
}: {
  searchParams: SearchParams;
}) {
  const params = await searchParams;
  const profile = await api.sellerProfile().catch(() => null);
  if (!profile) {
    redirect("/seller");
  }

  let listings: StoreListing[];
  try {
    listings = await api.sellerListings();
  } catch (error) {
    return (
      <div className="page">
        <ErrorState
          description={
            error instanceof Error ? error.message : "無法讀取賣家商品。"
          }
          title="商品資料暫時無法讀取"
        />
      </div>
    );
  }

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <span className="eyebrow">Seller listings</span>
          <h1>我的商品</h1>
          <p>{profile.display_name} 的商品及公開銷售狀態。</p>
        </div>
        {profile.status === "active" ? (
          <Link className="button" href="/seller/listings/new">
            <PlusCircle size={15} aria-hidden="true" />
            快速上架
          </Link>
        ) : null}
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
        <div className="seller-callout" role="status">
          <AlertTriangle size={18} aria-hidden="true" />
          <div>
            <strong>店鋪目前不可發布商品</strong>
            <span>商品會保留在賣家中心，審核恢復後可繼續營運。</span>
          </div>
        </div>
      ) : null}

      <section className="panel">
        <header className="panel__header">
          <h2>商品列表</h2>
          <span className="subtext">
            <Boxes size={13} aria-hidden="true" />
            {listings.length} 件
          </span>
        </header>
        {listings.length ? (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>商品</th>
                  <th>成色 / 電池</th>
                  <th>售價</th>
                  <th>狀態</th>
                  <th>發布時間</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {listings.map((listing) => (
                  <tr key={listing.id}>
                    <td>
                      <strong>{listing.title}</strong>
                      <div className="subtext">
                        {listing.variant.model} ·{" "}
                        {listing.variant.storage_label}
                      </div>
                    </td>
                    <td>
                      {listing.inventory.condition_grade} ·{" "}
                      {listing.inventory.battery_health_pct !== null
                        ? `${listing.inventory.battery_health_pct}%`
                        : "未記錄"}
                    </td>
                    <td className="mono">{formatHKD(listing.price_hkd)}</td>
                    <td>{listingStatusLabel(listing.status)}</td>
                    <td className="mono">
                      {listing.published_at
                        ? formatDateTime(listing.published_at)
                        : "未發布"}
                    </td>
                    <td>
                      {listing.status === "active" &&
                      profile.status === "active" ? (
                        <Link
                          className="button button--ghost button--small"
                          href={`/store/${listing.id}`}
                        >
                          查看
                          <ArrowRight size={13} aria-hidden="true" />
                        </Link>
                      ) : (
                        <span className="subtext">不可公開</span>
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
              description="審核通過後使用快速上架，商品會立即出現在這裡。"
              title="尚未上架商品"
            />
          </div>
        )}
      </section>
    </div>
  );
}

function listingStatusLabel(status: string): string {
  return (
    {
      draft: "草稿",
      active: "販售中",
      reserved: "已預留",
      sold: "已售出",
      archived: "已下架",
    }[status] ?? status
  );
}
