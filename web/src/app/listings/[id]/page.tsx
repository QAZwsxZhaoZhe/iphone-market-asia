import {
  ArrowLeft,
  Clock3,
  ExternalLink,
  MapPin,
  ShieldCheck,
} from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { EmptyState, ErrorState } from "@/components/states";
import { ApiError, api } from "@/lib/api";
import {
  conditionLabel,
  formatDateTime,
  formatHKD,
  formatRelative,
  statusLabel,
} from "@/lib/format";
import type { Listing, Snapshot } from "@/lib/types";

export const dynamic = "force-dynamic";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ id: string }>;
}): Promise<Metadata> {
  const { id } = await params;
  try {
    const listing = await api.listing(Number(id));
    return {
      title: listing.title,
      description: `${listing.model ?? "iPhone"} ${listing.storage_label ?? ""} · ${formatHKD(listing.price_hkd)}`,
    };
  } catch {
    return { title: "商品詳情" };
  }
}

export default async function ListingDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const listingId = Number(id);
  if (!Number.isInteger(listingId) || listingId < 1) {
    notFound();
  }

  let listing: Listing;
  let history: Snapshot[];
  try {
    [listing, history] = await Promise.all([
      api.listing(listingId),
      api.history(listingId),
    ]);
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
              : "商品資料暫時無法讀取。"
          }
        />
      </div>
    );
  }

  const latestPrice = history[0]?.price_hkd;
  const oldestPrice = history[history.length - 1]?.price_hkd;
  const priceChange =
    latestPrice !== null &&
    latestPrice !== undefined &&
    oldestPrice !== null &&
    oldestPrice !== undefined
      ? latestPrice - oldestPrice
      : null;

  return (
    <div className="page">
      <div className="result-bar">
        <Link className="button button--ghost button--small" href="/">
          <ArrowLeft size={14} aria-hidden="true" />
          返回搜尋
        </Link>
        <span>最後核對 {formatRelative(listing.last_seen_at)}</span>
      </div>

      <div className="detail-grid">
        <div>
          <section className="detail-hero">
            <div className="listing-row__meta">
              <span className="badge badge--source">
                {listing.source_name}
              </span>
              <span className="badge badge--condition">
                {conditionLabel(listing.condition)}
              </span>
              <span className="chip">{statusLabel(listing.listing_status)}</span>
              {listing.model ? (
                <span className="chip">{listing.model}</span>
              ) : null}
              {listing.storage_label ? (
                <span className="chip">{listing.storage_label}</span>
              ) : null}
            </div>

            <h1>{listing.title}</h1>
            <div className="detail-hero__price">
              <span className="price">{formatHKD(listing.price_hkd)}</span>
              {listing.currency !== "HKD" && listing.price_native ? (
                <span className="subtext">
                  原平台價格：{listing.price_native.toLocaleString("zh-HK")}{" "}
                  {listing.currency}
                </span>
              ) : null}
            </div>

            <dl className="detail-facts">
              <div className="fact">
                <dt>地區</dt>
                <dd>
                  <MapPin size={14} aria-hidden="true" />{" "}
                  {listing.district ?? listing.location ?? "未標示"}
                </dd>
              </div>
              <div className="fact">
                <dt>首次發現</dt>
                <dd>{formatDateTime(listing.first_seen_at)}</dd>
              </div>
              <div className="fact">
                <dt>最後出現</dt>
                <dd>{formatDateTime(listing.last_seen_at)}</dd>
              </div>
              <div className="fact">
                <dt>估值區間</dt>
                <dd>
                  {formatHKD(listing.valuation_low_hkd)} –{" "}
                  {formatHKD(listing.valuation_high_hkd)}
                </dd>
              </div>
              <div className="fact">
                <dt>合理中位價</dt>
                <dd>{formatHKD(listing.valuation_hkd)}</dd>
              </div>
              <div className="fact">
                <dt>樣本置信度</dt>
                <dd>{listing.valuation_confidence ?? "未評級"}</dd>
              </div>
            </dl>

            <a
              className="button button--accent"
              href={listing.url}
              rel="noreferrer noopener"
              target="_blank"
            >
              查看原平台商品
              <ExternalLink size={15} aria-hidden="true" />
            </a>
          </section>

          <section className="panel section-stack">
            <header className="panel__header">
              <h2>價格與狀態歷史</h2>
              <span className="subtext">{history.length} 次觀測</span>
            </header>
            {history.length ? (
              <div className="panel__body records">
                {history.map((snapshot, index) => (
                  <div
                    className="record"
                    key={`${snapshot.observed_at}-${index}`}
                  >
                    <span className="record__time">
                      {formatDateTime(snapshot.observed_at)}
                    </span>
                    <span className="record__price">
                      {formatHKD(snapshot.price_hkd)}
                    </span>
                    <span className="record__details">
                      {statusLabel(snapshot.status)} ·{" "}
                      {conditionLabel(snapshot.condition)} ·{" "}
                      {snapshot.district ?? "地區未標示"}
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="panel__body">
                <EmptyState
                  description="尚未保存到可用的歷史觀測。"
                  title="沒有歷史快照"
                />
              </div>
            )}
          </section>
        </div>

        <aside className="side-stack">
          <section className="callout">
            <h2>價格參考</h2>
            <p>
              合理價由近期同款、同容量活躍商品計算。公開要價不代表已成交價，
              交易前仍需核驗機身、電池、維修與啟用鎖。
            </p>
          </section>

          <section className="panel">
            <header className="panel__header">
              <h2>觀測摘要</h2>
              <Clock3 size={16} aria-hidden="true" />
            </header>
            <div className="panel__body">
              <dl className="detail-facts">
                <div className="fact">
                  <dt>歷史觀測</dt>
                  <dd>{history.length} 次</dd>
                </div>
                <div className="fact">
                  <dt>價格變化</dt>
                  <dd>
                    {priceChange === null
                      ? "樣本不足"
                      : `${priceChange > 0 ? "+" : ""}${formatHKD(priceChange)}`}
                  </dd>
                </div>
                <div className="fact">
                  <dt>跨來源集群</dt>
                  <dd>
                    {listing.cluster_id ? (
                      <>
                        <ShieldCheck size={14} aria-hidden="true" />{" "}
                        Cluster {listing.cluster_id}
                      </>
                    ) : (
                      "未發現重複"
                    )}
                  </dd>
                </div>
              </dl>
            </div>
          </section>
        </aside>
      </div>
    </div>
  );
}
