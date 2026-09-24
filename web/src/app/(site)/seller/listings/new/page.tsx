import { AlertTriangle, CheckCircle2, Zap } from "lucide-react";
import { redirect } from "next/navigation";

import { QuickListingForm } from "@/components/quick-listing-form";
import { EmptyState, ErrorState } from "@/components/states";
import { api } from "@/lib/api";
import type { Meta } from "@/lib/types";

import { quickCreateMyListingAction } from "../../actions";

export const dynamic = "force-dynamic";

type SearchParams = Promise<{
  notice?: string | string[];
  error?: string | string[];
}>;

function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

export default async function NewSellerListingPage({
  searchParams,
}: {
  searchParams: SearchParams;
}) {
  const params = await searchParams;
  const profile = await api.sellerProfile().catch(() => null);
  if (!profile) {
    redirect("/seller");
  }

  let meta: Meta;
  try {
    meta = await api.meta();
  } catch (error) {
    return (
      <div className="page">
        <ErrorState
          description={
            error instanceof Error ? error.message : "無法讀取機型資料。"
          }
          title="上架資料暫時無法讀取"
        />
      </div>
    );
  }

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <span className="eyebrow">Quick listing</span>
          <h1>快速上架</h1>
          <p>填寫核心資料即可建立商品、庫存及公開銷售頁。</p>
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

      <section className="panel">
        <header className="panel__header">
          <h2>商品資料</h2>
          <span className="subtext">
            <Zap size={13} aria-hidden="true" />
            可直接使用語音填寫
          </span>
        </header>
        <div className="panel__body">
          {profile.status === "active" && meta.variants.length ? (
            <QuickListingForm
              action={quickCreateMyListingAction}
              merchants={[profile]}
              showMerchantSelector={false}
              variants={meta.variants}
            />
          ) : (
            <EmptyState
              description={
                profile.status === "active"
                  ? "目前沒有可上架的機型資料。"
                  : "店鋪審核通過後才能發布商品。"
              }
              title="目前無法上架"
            />
          )}
        </div>
      </section>
    </div>
  );
}
