import { BadgeCheck, PackageSearch, ShieldCheck, Store } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";

import { StoreListingCard } from "@/components/store-listing-card";
import { EmptyState, ErrorState } from "@/components/states";
import { api } from "@/lib/api";
import { formatNumber, parsePositiveInt } from "@/lib/format";
import type { Meta, StoreListingPage } from "@/lib/types";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "平台商店",
  description: "選購經平台驗機、標示成色與保養的香港二手 iPhone。",
};

type SearchParams = Record<string, string | string[] | undefined>;

function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

function buildStoreHref(
  params: SearchParams,
  updates: Record<string, string | number | undefined>,
): string {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    const selected = first(value);
    if (selected) {
      query.set(key, selected);
    }
  });
  Object.entries(updates).forEach(([key, value]) => {
    if (value === undefined || value === "") {
      query.delete(key);
    } else {
      query.set(key, String(value));
    }
  });
  const serialized = query.toString();
  return serialized ? `/store?${serialized}` : "/store";
}

export default async function StorePage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const params = await searchParams;
  const limit = 24;
  const filters = {
    model: first(params.model),
    storage_gb: parsePositiveInt(params.storage_gb),
    condition_grade: first(params.condition_grade),
    min_price: parsePositiveInt(params.min_price),
    max_price: parsePositiveInt(params.max_price),
    offset: Math.max(0, parsePositiveInt(params.offset) ?? 0),
    limit,
  };

  const [pageResult, metaResult] = await Promise.allSettled([
    api.storeListings(filters),
    api.meta(),
  ]);

  const page: StoreListingPage | null =
    pageResult.status === "fulfilled" ? pageResult.value : null;
  const meta: Meta | null =
    metaResult.status === "fulfilled" ? metaResult.value : null;
  const error = pageResult.status === "rejected" ? pageResult.reason : null;
  const models = Array.from(
    new Set((meta?.variants ?? []).map((variant) => variant.model)),
  );
  const storageOptions = Array.from(
    new Map(
      (meta?.variants ?? []).map((variant) => [
        variant.storage_gb,
        variant.storage_label,
      ]),
    ),
  ).sort(([left], [right]) => left - right);

  const previousOffset = Math.max(0, filters.offset - limit);
  const nextOffset = filters.offset + limit;
  const hasNext = page ? nextOffset < page.total : false;

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <span className="eyebrow">Verified store</span>
          <h1>平台商店</h1>
          <p>
            香港二手 iPhone 平台自營及認證商家商品，成色、電池、維修記錄和保養一次看清。
          </p>
        </div>
        <div className="store-trust">
          <span>
            <BadgeCheck size={14} aria-hidden="true" />
            驗機資料
          </span>
          <span>
            <ShieldCheck size={14} aria-hidden="true" />
            平台代收貨款
          </span>
        </div>
      </header>

      <section className="filter-panel" aria-label="商店篩選">
        <form className="store-filter-grid" method="get">
          <div className="field">
            <label htmlFor="store-model">機型</label>
            <select
              className="select"
              defaultValue={filters.model ?? ""}
              id="store-model"
              name="model"
            >
              <option value="">全部機型</option>
              {models.map((model) => (
                <option key={model} value={model}>
                  {model}
                </option>
              ))}
            </select>
          </div>

          <div className="field">
            <label htmlFor="store-storage">容量</label>
            <select
              className="select"
              defaultValue={filters.storage_gb ?? ""}
              id="store-storage"
              name="storage_gb"
            >
              <option value="">全部容量</option>
              {storageOptions.map(([storage, label]) => (
                <option key={storage} value={storage}>
                  {label}
                </option>
              ))}
            </select>
          </div>

          <div className="field">
            <label htmlFor="store-grade">成色</label>
            <select
              className="select"
              defaultValue={filters.condition_grade ?? ""}
              id="store-grade"
              name="condition_grade"
            >
              <option value="">全部成色</option>
              {["A+", "A", "B", "C", "D"].map((grade) => (
                <option key={grade} value={grade}>
                  {grade} 級
                </option>
              ))}
            </select>
          </div>

          <div className="field">
            <label htmlFor="store-min-price">最低價 HKD</label>
            <input
              className="input"
              defaultValue={filters.min_price ?? ""}
              id="store-min-price"
              min="0"
              name="min_price"
              placeholder="不限"
              type="number"
            />
          </div>

          <div className="field">
            <label htmlFor="store-max-price">最高價 HKD</label>
            <input
              className="input"
              defaultValue={filters.max_price ?? ""}
              id="store-max-price"
              min="0"
              name="max_price"
              placeholder="不限"
              type="number"
            />
          </div>

          <div className="filter-actions">
            <button className="button button--primary" type="submit">
              套用篩選
            </button>
            <Link className="button button--ghost" href="/store">
              重設
            </Link>
          </div>
        </form>
      </section>

      {page ? (
        <>
          <div className="result-bar">
            <span>
              找到 <strong>{formatNumber(page.total)}</strong> 件平台在售商品
            </span>
            <span>
              {page.items.length
                ? `${page.offset + 1}–${page.offset + page.items.length}`
                : "0"}{" "}
              / {formatNumber(page.total)}
            </span>
          </div>

          {page.items.length ? (
            <section className="store-grid" aria-label="平台在售商品">
              {page.items.map((listing) => (
                <StoreListingCard key={listing.id} listing={listing} />
              ))}
            </section>
          ) : (
            <EmptyState
              description="可放寬機型、容量、成色或價格條件，亦可稍後再查看新上架商品。"
              title="目前沒有符合條件的商品"
            />
          )}

          {filters.offset > 0 || hasNext ? (
            <nav className="pagination" aria-label="商品分頁">
              <div className="store-pagination">
                {filters.offset > 0 ? (
                  <Link
                    className="button button--ghost"
                    href={buildStoreHref(params, { offset: previousOffset })}
                  >
                    上一頁
                  </Link>
                ) : null}
                {hasNext ? (
                  <Link
                    className="button button--ghost"
                    href={buildStoreHref(params, { offset: nextOffset })}
                  >
                    下一頁
                  </Link>
                ) : null}
              </div>
            </nav>
          ) : null}
        </>
      ) : (
        <ErrorState
          description={
            error instanceof Error
              ? error.message
              : "平台商店暫時無法使用。"
          }
          title="商店暫時不可用"
        />
      )}

      <section className="store-principles" aria-label="平台交易保障">
        <article>
          <PackageSearch size={20} aria-hidden="true" />
          <div>
            <h2>逐件驗機</h2>
            <p>成色、電池健康和維修記錄隨商品公開。</p>
          </div>
        </article>
        <article>
          <ShieldCheck size={20} aria-hidden="true" />
          <div>
            <h2>代收貨款</h2>
            <p>買家付款由持牌支付服務處理，確認收貨後安排結算。</p>
          </div>
        </article>
        <article>
          <Store size={20} aria-hidden="true" />
          <div>
            <h2>商家可追溯</h2>
            <p>每件商品均關聯平台自營或已核准商家。</p>
          </div>
        </article>
      </section>
    </div>
  );
}
