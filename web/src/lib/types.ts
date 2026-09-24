export type Listing = {
  id: number;
  source_key: string;
  source_name: string;
  title: string;
  url: string;
  model: string | null;
  generation: number | null;
  family: string | null;
  storage_gb: number | null;
  storage_label: string | null;
  condition: string;
  listing_status: string;
  district: string | null;
  location: string | null;
  price_native: number | null;
  currency: string;
  price_hkd: number | null;
  fx_date: string | null;
  valuation_hkd: number | null;
  valuation_low_hkd: number | null;
  valuation_high_hkd: number | null;
  valuation_confidence: string | null;
  first_seen_at: string;
  last_seen_at: string;
  freshness_seconds: number | null;
  cluster_id: number | null;
};

export type ListingPage = {
  items: Listing[];
  next_cursor: string | null;
  total: number;
  limit: number;
};

export type Snapshot = {
  observed_at: string;
  collected_date: string;
  status: string;
  condition: string;
  district: string | null;
  price_native: number | null;
  currency: string;
  price_hkd: number | null;
};

export type SourceHealth = {
  source_key: string;
  source_name: string;
  market: string;
  active: boolean;
  status: string;
  listing_count: number;
  active_listing_count: number;
  query_count: number;
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
  last_success_at: string | null;
  freshness_seconds: number | null;
  cadence_seconds: number;
};

export type SourceRun = {
  id: number;
  source_key: string;
  external_run_id: string;
  status: string;
  started_at: string;
  finished_at: string | null;
  listing_count: number;
  query_count: number;
  error: string | null;
  attempt: number;
  metadata: Record<string, unknown>;
};

export type AuditEntry = {
  id: number;
  actor: string;
  action: string;
  resource_type: string;
  resource_id: string | null;
  details: Record<string, unknown>;
  created_at: string;
};

export type DeadLetter = {
  id: number;
  task_id: string;
  task_name: string;
  args_json: unknown[];
  kwargs_json: Record<string, unknown>;
  error: string;
  retry_count: number;
  created_at: string;
};

export type VariantMeta = {
  id: string;
  model: string;
  generation: number;
  family: string;
  storage_gb: number;
  storage_label: string;
};

export type Meta = {
  market: string;
  currency: string;
  timezone: string;
  auth: {
    public_registration: boolean;
  };
  districts: Array<{ value: string; label: string }>;
  variants: VariantMeta[];
};

export type PriceMetrics = {
  count: number;
  min: number | null;
  p25: number | null;
  median: number | null;
  p75: number | null;
  max: number | null;
};

export type MarketSummary = {
  as_of: string;
  filters: Record<string, string | number | null>;
  metrics: PriceMetrics;
  source_count: number;
  district_coverage: number;
  supply_by_district: Array<{ district: string; count: number }>;
  by_district: Array<{ key: string } & PriceMetrics>;
  by_variant: Array<{ key: string } & PriceMetrics>;
  by_source: Array<{ key: string } & PriceMetrics>;
};

export type ActionAccepted = {
  task_id?: string;
  status: string;
  detail?: string;
  count?: number;
};

export type User = {
  id: string;
  email: string;
  display_name: string;
  roles: string[];
  status: string;
  created_at: string;
  last_login_at: string | null;
};

export type Principal = {
  subject: string;
  roles: string[];
  internal: boolean;
  user_id: string | null;
  email: string | null;
  auth_method: string;
};

export type SessionResult = {
  token: string;
  token_type: string;
  expires_at: string;
  user: User;
};

export type Merchant = {
  id: string;
  owner_user_id: string | null;
  merchant_type: "platform" | "business" | "individual";
  legal_name: string;
  display_name: string;
  status: "pending" | "active" | "suspended" | "closed";
  commission_rate_bps: number;
  created_at: string;
};

export type InventoryItem = {
  id: string;
  merchant_id: string;
  phone_variant_id: string;
  sku: string;
  model: string;
  storage_gb: number;
  storage_label: string;
  condition_grade: string;
  battery_health_pct: number | null;
  repair_history: Array<Record<string, unknown>>;
  accessories: string[];
  cost_hkd: number | null;
  status: string;
  listing_id: string | null;
  created_at: string;
};

export type StoreVariant = {
  id: string;
  model: string;
  generation: number;
  family: string;
  storage_gb: number;
  storage_label: string;
};

export type StoreListing = {
  id: string;
  slug: string;
  title: string;
  description: string;
  price_hkd: number | null;
  status: string;
  warranty_days: number;
  images: string[];
  inspection_report: Record<string, unknown>;
  published_at: string | null;
  merchant: {
    id: string;
    display_name: string;
    type: "platform" | "business" | "individual";
  };
  variant: StoreVariant;
  inventory: {
    condition_grade: string;
    battery_health_pct: number | null;
    repair_history: Array<Record<string, unknown>>;
    accessories: string[];
  };
};

export type StoreListingPage = {
  items: StoreListing[];
  total: number;
  offset: number;
  limit: number;
};

export type OrderEvent = {
  id: number;
  from_status: string | null;
  to_status: string;
  actor: string;
  reason: string | null;
  created_at: string;
};

export type PaymentIntent = {
  id: string;
  provider: string;
  provider_reference: string;
  status: string;
  amount_hkd: number;
  currency: string;
  checkout_url: string | null;
  created_at: string;
  completed_at: string | null;
};

export type Refund = {
  id: string;
  status: string;
  amount_hkd: number;
  currency: string;
  reason: string;
  provider: string;
  provider_reference: string | null;
  requested_at: string;
  processed_at: string | null;
};

export type Settlement = {
  id: string;
  status: string;
  gross_hkd: number;
  commission_hkd: number;
  net_hkd: number;
  provider_reference: string | null;
  created_at: string;
  paid_at: string | null;
};

export type Order = {
  id: string;
  order_number: string;
  status: string;
  payment_status: string;
  fulfillment_status: string;
  currency: string;
  item_price_hkd: number;
  shipping_fee_hkd: number;
  total_hkd: number;
  commission_rate_bps: number;
  commission_hkd: number;
  merchant_net_hkd: number;
  contact: Record<string, unknown>;
  shipping_address: Record<string, unknown>;
  merchant: {
    id: string;
    display_name: string;
  };
  item: {
    listing_id: string;
    slug: string;
    title: string;
    image: string | null;
    model: string | null;
    storage_label: string | null;
    condition_grade: string | null;
  };
  payment_intent: PaymentIntent | null;
  refund: Refund | null;
  settlement: Settlement | null;
  paid_at: string | null;
  fulfilled_at: string | null;
  completed_at: string | null;
  cancelled_at: string | null;
  refunded_at: string | null;
  cancellation_reason: string | null;
  created_at: string;
  updated_at: string;
  events: OrderEvent[];
};

export type InternalOrder = Order & {
  buyer: User;
};

export type LedgerEntry = {
  id: number;
  account_code: string;
  account_name: string;
  account_type: string;
  merchant_id: string | null;
  debit_hkd: number;
  credit_hkd: number;
};

export type LedgerJournal = {
  id: string;
  order_id: string | null;
  event_type: string;
  memo: string;
  created_at: string;
  entries: LedgerEntry[];
};
