import {
  ArrowRight,
  BatteryCharging,
  ShieldCheck,
  Smartphone,
  Store,
} from "lucide-react";
import Link from "next/link";

import { formatHKD } from "@/lib/format";
import type { StoreListing } from "@/lib/types";

function merchantTypeLabel(type: StoreListing["merchant"]["type"]): string {
  if (type === "platform") {
    return "平台自營";
  }
  if (type === "individual") {
    return "個人賣家";
  }
  return "認證商家";
}

export function StoreListingCard({ listing }: { listing: StoreListing }) {
  const image = listing.images[0];

  return (
    <article className="store-card">
      <Link
        aria-label={listing.title}
        className="store-card__media"
        href={`/store/${listing.slug}`}
      >
        {image ? (
          <img alt={listing.title} loading="lazy" src={image} />
        ) : (
          <span className="store-card__placeholder" aria-hidden="true">
            <Smartphone size={42} strokeWidth={1.5} />
          </span>
        )}
        <span className="store-card__grade">
          {listing.inventory.condition_grade} 級
        </span>
      </Link>

      <div className="store-card__body">
        <div className="store-card__merchant">
          <Store size={13} aria-hidden="true" />
          <span>{listing.merchant.display_name}</span>
          <span className="store-card__merchant-type">
            {merchantTypeLabel(listing.merchant.type)}
          </span>
        </div>

        <h2>
          <Link href={`/store/${listing.slug}`}>{listing.title}</Link>
        </h2>

        <div className="store-card__facts">
          <span>
            <ShieldCheck size={14} aria-hidden="true" />
            保養 {listing.warranty_days} 日
          </span>
          <span>
            <BatteryCharging size={14} aria-hidden="true" />
            {listing.inventory.battery_health_pct === null
              ? "電池待檢"
              : `電池 ${listing.inventory.battery_health_pct}%`}
          </span>
        </div>

        <div className="store-card__footer">
          <div>
            <span className="store-card__price">
              {formatHKD(listing.price_hkd)}
            </span>
            <span className="subtext">
              {listing.variant.model} · {listing.variant.storage_label}
            </span>
          </div>
          <Link
            aria-label={`查看 ${listing.title}`}
            className="button button--ghost button--small"
            href={`/store/${listing.slug}`}
          >
            詳情 <ArrowRight size={13} aria-hidden="true" />
          </Link>
        </div>
      </div>
    </article>
  );
}
