import {
  Activity,
  BarChart3,
  Building2,
  Database,
  MapPinned,
} from "lucide-react";

import { EmptyState, ErrorState } from "@/components/states";
import { api } from "@/lib/api";
import {
  formatDateTime,
  formatHKD,
  formatNumber,
} from "@/lib/format";
import type { MarketSummary } from "@/lib/types";

export const dynamic = "force-dynamic";

export default async function MarketPage() {
  let summary: MarketSummary;
  try {
    summary = await api.marketSummary({});
  } catch (error) {
    return (
      <div className="page">
        <ErrorState
          description={
            error instanceof Error
              ? error.message
              : "市場統計暫時無法讀取。"
          }
        />
      </div>
    );
  }

  const maxSupply = Math.max(
    1,
    ...summary.supply_by_district.map((item) => item.count),
  );

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <span className="eyebrow">Market overview</span>
          <h1>全港行情</h1>
          <p>
            按 HKD 統計活躍在售二手機，呈現供應、價格分位、來源與 18 區覆蓋。
          </p>
        </div>
        <span className="subtext">更新於 {formatDateTime(summary.as_of)}</span>
      </header>

      <section className="metrics-grid" aria-label="市場核心指標">
        <article className="metric">
          <span className="metric__label">
            <Activity size={13} /> 活躍供應
          </span>
          <strong className="metric__value">
            {formatNumber(summary.metrics.count)}
          </strong>
          <span className="metric__note">符合公開條件的商品</span>
        </article>
        <article className="metric">
          <span className="metric__label">
            <BarChart3 size={13} /> 中位價
          </span>
          <strong className="metric__value">
            {formatHKD(summary.metrics.median)}
          </strong>
          <span className="metric__note">
            P25 {formatHKD(summary.metrics.p25)} · P75{" "}
            {formatHKD(summary.metrics.p75)}
          </span>
        </article>
        <article className="metric">
          <span className="metric__label">
            <Database size={13} /> 已覆蓋來源
          </span>
          <strong className="metric__value">
            {formatNumber(summary.source_count)}
          </strong>
          <span className="metric__note">已觀測到活躍商品</span>
        </article>
        <article className="metric">
          <span className="metric__label">
            <MapPinned size={13} /> 地區覆蓋
          </span>
          <strong className="metric__value">
            {summary.district_coverage}/18
          </strong>
          <span className="metric__note">可映射到標準行政區</span>
        </article>
      </section>

      <div className="dashboard-grid">
        <section className="panel">
          <header className="panel__header">
            <h2>18 區供應</h2>
            <span className="subtext">按活躍商品數</span>
          </header>
          <div className="panel__body">
            <div className="bar-list">
              {summary.supply_by_district.map((item) => (
                <div className="bar-row" key={item.district}>
                  <span>{item.district}</span>
                  <div className="bar-track">
                    <div
                      className="bar-fill"
                      style={{
                        width: `${Math.max(
                          item.count ? 4 : 0,
                          (item.count / maxSupply) * 100,
                        )}%`,
                      }}
                    />
                  </div>
                  <strong>{item.count}</strong>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section className="panel">
          <header className="panel__header">
            <h2>來源供應</h2>
            <span className="subtext">活躍商品中位價</span>
          </header>
          {summary.by_source.length ? (
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>來源</th>
                    <th>供應</th>
                    <th>中位價</th>
                  </tr>
                </thead>
                <tbody>
                  {summary.by_source.map((item) => (
                    <tr key={item.key}>
                      <td className="mono">{item.key}</td>
                      <td>{formatNumber(item.count)}</td>
                      <td>{formatHKD(item.median)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="panel__body">
              <EmptyState
                description="來源採集或公開商品資料尚未就緒。"
                title="暫無來源統計"
              />
            </div>
          )}
        </section>
      </div>

      <section className="panel section-stack">
        <header className="panel__header">
          <h2>機型與容量行情</h2>
          <span className="subtext">
            <Building2 size={13} aria-hidden="true" /> 同款供應與價格分位
          </span>
        </header>
        {summary.by_variant.length ? (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>機型 / 容量</th>
                  <th>供應</th>
                  <th>最低</th>
                  <th>P25</th>
                  <th>中位價</th>
                  <th>P75</th>
                  <th>最高</th>
                </tr>
              </thead>
              <tbody>
                {summary.by_variant.map((item) => {
                  const [model, storage] = item.key.split(":");
                  const storageLabel =
                    Number(storage) >= 1024
                      ? `${Number(storage) / 1024}TB`
                      : `${storage}GB`;
                  return (
                    <tr key={item.key}>
                      <td>
                        <strong>{model}</strong>{" "}
                        <span className="subtext">{storageLabel}</span>
                      </td>
                      <td className="mono">{formatNumber(item.count)}</td>
                      <td>{formatHKD(item.min)}</td>
                      <td>{formatHKD(item.p25)}</td>
                      <td>
                        <strong>{formatHKD(item.median)}</strong>
                      </td>
                      <td>{formatHKD(item.p75)}</td>
                      <td>{formatHKD(item.max)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="panel__body">
            <EmptyState
              description="暫未取得可計算的活躍商品價格。"
              title="尚無機型行情"
            />
          </div>
        )}
      </section>
    </div>
  );
}
