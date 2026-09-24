import { Search } from "lucide-react";

import { ListingFilters } from "@/components/filters";
import { ListingCard } from "@/components/listing-card";
import { NextPageLink } from "@/components/pagination";
import { EmptyState, ErrorState } from "@/components/states";
import { api } from "@/lib/api";
import { formatNumber, parsePositiveInt } from "@/lib/format";
import type { ListingPage, Meta, SourceHealth } from "@/lib/types";

export const dynamic = "force-dynamic";

type SearchParams = Record<string, string | string[] | undefined>;

function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

export default async function ListingsPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const params = await searchParams;
  const filters = {
    q: first(params.q),
    model: first(params.model),
    storage_gb: parsePositiveInt(params.storage_gb),
    district: first(params.district),
    source_key: first(params.source_key),
    min_price: parsePositiveInt(params.min_price),
    max_price: parsePositiveInt(params.max_price),
    fresh_within_hours: parsePositiveInt(params.fresh_within_hours),
    cursor: first(params.cursor),
    limit: 24,
  };

  const [pageResult, metaResult, sourcesResult] = await Promise.allSettled([
    api.listings(filters),
    api.meta(),
    api.sources(),
  ]);

  const page: ListingPage | null =
    pageResult.status === "fulfilled" ? pageResult.value : null;
  const meta: Meta | null =
    metaResult.status === "fulfilled" ? metaResult.value : null;
  const sources: SourceHealth[] =
    sourcesResult.status === "fulfilled" ? sourcesResult.value : [];
  const error =
    pageResult.status === "rejected" ? pageResult.reason : null;

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <span className="eyebrow">Marketplace</span>
          <h1>全港二手手機</h1>
          <p>
            聚合已授權公開來源，統一換算港幣，配合同款活躍樣本估算合理價位。
          </p>
        </div>
      </header>

      <ListingFilters
        meta={meta}
        sources={sources}
        values={{
          q: filters.q,
          model: filters.model,
          storage_gb: filters.storage_gb,
          district: filters.district,
          source_key: filters.source_key,
          max_price: filters.max_price,
          fresh_within_hours: filters.fresh_within_hours,
        }}
      />

      {page ? (
        <>
          <div className="result-bar">
            <span>
              找到 <strong>{formatNumber(page.total)}</strong> 條符合條件記錄
            </span>
            <span>
              {filters.cursor ? "續頁結果" : "按最近觀測排序"} · 每次{" "}
              {page.limit} 條
            </span>
          </div>

          {page.items.length ? (
            <section className="listing-list" aria-label="商品搜尋結果">
              {page.items.map((listing) => (
                <ListingCard key={listing.id} listing={listing} />
              ))}
            </section>
          ) : (
            <EmptyState
              description="可以放寬價格、地區或容量條件，亦可直接使用較短的型號關鍵字。"
              title="沒有符合條件的商品"
            />
          )}

          {page.next_cursor ? (
            <NextPageLink cursor={page.next_cursor} params={params} />
          ) : null}
        </>
      ) : (
        <ErrorState
          description={
            error instanceof Error
              ? error.message
              : "公開搜尋服務暫時無法使用。"
          }
          title="搜尋結果暫時不可用"
        />
      )}
    </div>
  );
}
