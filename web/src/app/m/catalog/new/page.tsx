import { ArrowLeft, Mic, Zap } from "lucide-react";
import Link from "next/link";

import { QuickListingForm } from "@/components/quick-listing-form";
import { EmptyState, ErrorState } from "@/components/states";
import { api } from "@/lib/api";

import { quickCreateSellerListingAction } from "../actions";

export const dynamic = "force-dynamic";

async function safe<T>(promise: Promise<T>): Promise<T | null> {
  try {
    return await promise;
  } catch {
    return null;
  }
}

export default async function MobileQuickListingPage() {
  const principal = await api.currentPrincipal().catch(() => null);
  const canOperate = Boolean(
    principal?.roles.some((role) => role === "admin" || role === "operator"),
  );
  const [meta, merchants] = await Promise.all([
    safe(api.meta()),
    safe(api.internalMerchants()),
  ]);
  const variants = meta?.variants ?? [];
  const activeMerchants = (merchants ?? []).filter(
    (merchant) => merchant.status === "active",
  );

  if (!canOperate) {
    return (
      <div className="mobile-page">
        <ErrorState
          description="目前帳戶只有唯讀權限，無法建立或發布商品。"
          title="沒有上架權限"
        />
      </div>
    );
  }

  return (
    <div className="mobile-page">
      <header className="mobile-page-header">
        <div>
          <Link className="mobile-back-link" href="/m/catalog">
            <ArrowLeft size={16} aria-hidden="true" />
            返回商品
          </Link>
          <span className="eyebrow">Quick listing</span>
          <h1>快速上架</h1>
          <p>只填必要資料，系統會自動建立庫存、標題及公開銷售頁。</p>
        </div>
      </header>

      <div className="mobile-feature-note">
        <span>
          <Mic size={19} aria-hidden="true" />
        </span>
        <div>
          <strong>支援語音填寫</strong>
          <p>說出機型、容量、成色、售價及電池健康度。</p>
        </div>
      </div>

      <section className="mobile-form-panel">
        <header>
          <Zap size={18} aria-hidden="true" />
          <div>
            <strong>必要資料</strong>
            <span>送出後商品會直接發布到公開商店</span>
          </div>
        </header>
        {activeMerchants.length && variants.length ? (
          <QuickListingForm
            action={quickCreateSellerListingAction}
            merchants={activeMerchants}
            variants={variants}
          />
        ) : (
          <EmptyState
            description="需要至少一個已核准商家及可用機型資料，請先到電腦端營運台設定。"
            title="尚未具備上架條件"
          />
        )}
      </section>
    </div>
  );
}
