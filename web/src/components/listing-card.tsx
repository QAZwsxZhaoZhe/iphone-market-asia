import {
  ArrowRight,
  Clock3,
  ExternalLink,
  MapPin,
  ShieldCheck,
} from "lucide-react";
import Link from "next/link";

import {
  conditionLabel,
  formatHKD,
  formatRelative,
  valuationDelta,
} from "@/lib/format";
import type { Listing } from "@/lib/types";

export function ListingCard({ listing }: { listing: Listing }) {
  const delta = valuationDelta(listing.price_hkd, listing.valuation_hkd);

  return (
    <article className="listing-row">
      <div className="listing-row__main">
        <div className="listing-row__meta">
          <span className="badge badge--source">{listing.source_name}</span>
          <span className="badge badge--condition">
            {conditionLabel(listing.condition)}
          </span>
          {listing.model ? (
            <span className="chip">{listing.model}</span>
          ) : null}
          {listing.storage_label ? (
            <span className="chip">{listing.storage_label}</span>
          ) : null}
        </div>
        <h2 className="listing-row__title">
          <Link href={`/listings/${listing.id}`}>{listing.title}</Link>
        </h2>
        <div className="listing-row__footer">
          <span className="truncate">
            <MapPin size={13} aria-hidden="true" />{" "}
            {listing.district ?? listing.location ?? "香港"}
          </span>
          <span>
            <Clock3 size={13} aria-hidden="true" />{" "}
            {formatRelative(listing.last_seen_at)}
          </span>
          {listing.cluster_id ? (
            <span>
              <ShieldCheck size={13} aria-hidden="true" /> 集群{" "}
              {listing.cluster_id}
            </span>
          ) : null}
        </div>
      </div>

      <div className="listing-row__price">
        <span className="price">{formatHKD(listing.price_hkd)}</span>
        {listing.currency !== "HKD" && listing.price_native ? (
          <span className="subtext">
            原價 {listing.price_native.toLocaleString("zh-HK")}{" "}
            {listing.currency}
          </span>
        ) : (
          <span className="subtext">港幣統計價</span>
        )}
      </div>

      <div className="valuation-box">
        <span className="subtext">
          合理中位價 {formatHKD(listing.valuation_hkd)}
        </span>
        {delta ? (
          <span className={`badge tone-${delta.tone}`}>{delta.label}</span>
        ) : (
          <span className="badge tone-neutral">估值樣本不足</span>
        )}
        <Link
          className="button button--ghost button--small"
          href={`/listings/${listing.id}`}
        >
          詳情 <ArrowRight size={13} aria-hidden="true" />
        </Link>
        <a
          className="subtext"
          href={listing.url}
          rel="noreferrer noopener"
          target="_blank"
        >
          前往原平台 <ExternalLink size={11} aria-hidden="true" />
        </a>
      </div>
    </article>
  );
}
