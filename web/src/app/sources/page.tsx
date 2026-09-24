import { Clock3, Database, RefreshCw } from "lucide-react";

import { EmptyState, ErrorState } from "@/components/states";
import { api } from "@/lib/api";
import {
  formatDateTime,
  formatNumber,
  formatRelative,
  freshnessLabel,
  statusLabel,
  statusTone,
} from "@/lib/format";
import type { SourceHealth } from "@/lib/types";

export const dynamic = "force-dynamic";

export default async function SourcesPage() {
  let sources: SourceHealth[];
  try {
    sources = await api.sources();
  } catch (error) {
    return (
      <div className="page">
        <ErrorState
          description={
            error instanceof Error
              ? error.message
              : "來源健康資料暫時不可讀取。"
          }
          title="來源狀態暫時不可用"
        />
      </div>
    );
  }

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <span className="eyebrow">Data coverage</span>
          <h1>來源覆蓋與新鮮度</h1>
          <p>
            顯示每個已授權來源的最近運行、活躍商品、查詢量與最後成功時間。
          </p>
        </div>
      </header>

      {sources.length ? (
        <section className="source-grid">
          {sources.map((source) => (
            <article className="source-card" key={source.source_key}>
              <div className="source-card__head">
                <div>
                  <span className="eyebrow">{source.market}</span>
                  <h2>{source.source_name}</h2>
                  <span className="subtext mono">{source.source_key}</span>
                </div>
                <span
                  className={`status tone-${statusTone(source.status)}`}
                  title={source.error ?? undefined}
                >
                  {statusLabel(source.status)}
                </span>
              </div>

              <div className="source-card__stats">
                <div>
                  <span>活躍商品</span>
                  <strong>{formatNumber(source.active_listing_count)}</strong>
                </div>
                <div>
                  <span>最近採集</span>
                  <strong>{formatNumber(source.listing_count)}</strong>
                </div>
                <div>
                  <span>查詢次數</span>
                  <strong>{formatNumber(source.query_count)}</strong>
                </div>
              </div>

              <div className="source-card__footer">
                <span>
                  <Clock3 size={13} aria-hidden="true" />{" "}
                  {formatRelative(source.last_success_at)}
                </span>
                <span>
                  新鮮度 {freshnessLabel(source.freshness_seconds)}
                </span>
              </div>
              <div className="source-card__footer" style={{ marginTop: 6 }}>
                <span>
                  <Database size={13} aria-hidden="true" /> 每{" "}
                  {Math.round(source.cadence_seconds / 3600)} 小時
                </span>
                <span>
                  <RefreshCw size={13} aria-hidden="true" />{" "}
                  {formatDateTime(source.finished_at)}
                </span>
              </div>

              {source.error ? (
                <p className="source-error">{source.error}</p>
              ) : null}
            </article>
          ))}
        </section>
      ) : (
        <EmptyState
          description="先執行資料庫 seed 及第一輪採集，來源狀態會顯示在這裡。"
          title="尚未註冊來源"
        />
      )}
    </div>
  );
}
