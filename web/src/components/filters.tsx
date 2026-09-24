import { RotateCcw, Search } from "lucide-react";
import Link from "next/link";

import type { Meta, SourceHealth } from "@/lib/types";

type FilterValues = {
  q?: string;
  model?: string;
  storage_gb?: number;
  district?: string;
  source_key?: string;
  min_price?: number;
  max_price?: number;
  fresh_within_hours?: number;
};

export function ListingFilters({
  meta,
  sources,
  values,
}: {
  meta: Meta | null;
  sources: SourceHealth[];
  values: FilterValues;
}) {
  const models = Array.from(
    new Set((meta?.variants ?? []).map((variant) => variant.model)),
  );
  const storageOptions = Array.from(
    new Set((meta?.variants ?? []).map((variant) => variant.storage_gb)),
  ).sort((left, right) => left - right);

  return (
    <form className="filter-panel" action="/" method="get">
      <div className="filter-grid">
        <div className="field field--wide">
          <label htmlFor="q">關鍵字</label>
          <input
            className="input"
            defaultValue={values.q}
            id="q"
            name="q"
            placeholder="型號、容量、繁中或英文別名"
            type="search"
          />
        </div>

        <div className="field">
          <label htmlFor="model">機型</label>
          <select
            className="select"
            defaultValue={values.model ?? ""}
            id="model"
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
          <label htmlFor="storage_gb">容量</label>
          <select
            className="select"
            defaultValue={values.storage_gb ?? ""}
            id="storage_gb"
            name="storage_gb"
          >
            <option value="">全部容量</option>
            {storageOptions.map((storage) => (
              <option key={storage} value={storage}>
                {storage >= 1024
                  ? `${storage / 1024}TB`
                  : `${storage}GB`}
              </option>
            ))}
          </select>
        </div>

        <div className="field">
          <label htmlFor="district">地區</label>
          <select
            className="select"
            defaultValue={values.district ?? ""}
            id="district"
            name="district"
          >
            <option value="">全港 18 區</option>
            {(meta?.districts ?? []).map((district) => (
              <option key={district.value} value={district.value}>
                {district.label}
              </option>
            ))}
          </select>
        </div>

        <div className="field">
          <label htmlFor="source_key">來源</label>
          <select
            className="select"
            defaultValue={values.source_key ?? ""}
            id="source_key"
            name="source_key"
          >
            <option value="">全部來源</option>
            {sources.map((source) => (
              <option key={source.source_key} value={source.source_key}>
                {source.source_name}
              </option>
            ))}
          </select>
        </div>

        <div className="field">
          <label htmlFor="max_price">最高價格</label>
          <input
            className="input"
            defaultValue={values.max_price}
            id="max_price"
            min="0"
            name="max_price"
            placeholder="HKD"
            step="100"
            type="number"
          />
        </div>

        <div className="filter-actions">
          <button className="button button--primary" type="submit">
            <Search size={15} aria-hidden="true" />
            搜尋
          </button>
          <Link className="button button--ghost" href="/">
            <RotateCcw size={15} aria-hidden="true" />
            重設
          </Link>
        </div>
      </div>
    </form>
  );
}
