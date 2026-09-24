import type {
  ActionAccepted,
  AuditEntry,
  DeadLetter,
  InventoryItem,
  InternalOrder,
  LedgerJournal,
  Listing,
  ListingPage,
  MarketSummary,
  Merchant,
  Meta,
  Order,
  PaymentIntent,
  Principal,
  Refund,
  SessionResult,
  Snapshot,
  SourceHealth,
  SourceRun,
  StoreListing,
  StoreListingPage,
  User,
} from "@/lib/types";
import { getSessionToken } from "@/lib/session";

const API_BASE_URL =
  process.env.PLATFORM_API_URL ?? "http://127.0.0.1:8000";

export class ApiError extends Error {
  status: number;

  constructor(message: string, status = 500) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

type QueryValue = string | number | boolean | null | undefined;
type ApiRequestOptions = RequestInit & {
  authenticated?: boolean;
  sessionToken?: string;
};

function buildQuery(params: Record<string, QueryValue>): string {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") {
      query.set(key, String(value));
    }
  });
  const serialized = query.toString();
  return serialized ? `?${serialized}` : "";
}

export async function apiFetch<T>(
  path: string,
  options: ApiRequestOptions = {},
): Promise<T> {
  const {
    authenticated = false,
    sessionToken,
    ...requestOptions
  } = options;
  const headers = new Headers(requestOptions.headers);
  headers.set("Accept", "application/json");
  if (authenticated || sessionToken) {
    const token = sessionToken ?? (await getSessionToken());
    if (!token) {
      throw new ApiError("請先登入", 401);
    }
    headers.set("Authorization", `Bearer ${token}`);
  }

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...requestOptions,
      headers,
      cache: "no-store",
    });
  } catch {
    throw new ApiError(`无法连接数据服务：${API_BASE_URL}`, 503);
  }

  if (!response.ok) {
    let detail = `请求失败（HTTP ${response.status}）`;
    try {
      const payload = (await response.json()) as { detail?: string };
      if (payload.detail) {
        detail = payload.detail;
      }
    } catch {
      // Keep the HTTP status fallback when the upstream response is not JSON.
    }
    throw new ApiError(detail, response.status);
  }

  return (await response.json()) as T;
}

export const api = {
  login(payload: { email: string; password: string }) {
    return apiFetch<SessionResult>("/v1/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  },
  register(payload: {
    email: string;
    password: string;
    display_name: string;
  }) {
    return apiFetch<SessionResult>("/v1/auth/register", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  },
  currentPrincipal(sessionToken?: string) {
    return apiFetch<Principal>("/v1/auth/me", {
      authenticated: true,
      sessionToken,
    });
  },
  logout(sessionToken?: string) {
    return apiFetch<{ revoked: boolean }>("/v1/auth/logout", {
      method: "POST",
      authenticated: true,
      sessionToken,
    });
  },
  listings(params: Record<string, QueryValue>) {
    return apiFetch<ListingPage>(`/v1/listings${buildQuery(params)}`);
  },
  listing(id: number) {
    return apiFetch<Listing>(`/v1/listings/${id}`);
  },
  history(id: number, limit = 180) {
    return apiFetch<Snapshot[]>(
      `/v1/listings/${id}/history${buildQuery({ limit })}`,
    );
  },
  meta() {
    return apiFetch<Meta>("/v1/meta");
  },
  sources() {
    return apiFetch<SourceHealth[]>("/v1/sources");
  },
  marketSummary(params: Record<string, QueryValue>) {
    return apiFetch<MarketSummary>(
      `/v1/market/summary${buildQuery(params)}`,
    );
  },
  storeListings(params: Record<string, QueryValue>) {
    return apiFetch<StoreListingPage>(
      `/v1/store/listings${buildQuery(params)}`,
    );
  },
  storeListing(id: string) {
    return apiFetch<StoreListing>(`/v1/store/listings/${id}`);
  },
  createOrder(payload: {
    listing_id: string;
    contact: {
      recipient_name: string;
      phone: string;
      email: string;
    };
    shipping_address: {
      line1: string;
      line2: string;
      district: string;
      region: string;
      country: string;
    };
    idempotency_key: string;
  }) {
    return apiFetch<Order>("/v1/store/orders", {
      method: "POST",
      authenticated: true,
      headers: {
        "Content-Type": "application/json",
        "Idempotency-Key": payload.idempotency_key,
      },
      body: JSON.stringify(payload),
    });
  },
  orders(limit = 100) {
    return apiFetch<Order[]>(`/v1/orders${buildQuery({ limit })}`, {
      authenticated: true,
    });
  },
  order(orderId: string) {
    return apiFetch<Order>(`/v1/orders/${orderId}`, {
      authenticated: true,
    });
  },
  cancelOrder(orderId: string, reason: string) {
    return apiFetch<Order>(`/v1/orders/${orderId}/cancel`, {
      method: "POST",
      authenticated: true,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason }),
    });
  },
  createPaymentIntent(orderId: string) {
    return apiFetch<PaymentIntent>(
      `/v1/orders/${orderId}/payment-intent`,
      {
        method: "POST",
        authenticated: true,
      },
    );
  },
  confirmReceipt(orderId: string) {
    return apiFetch<Order>(`/v1/orders/${orderId}/confirm-receipt`, {
      method: "POST",
      authenticated: true,
    });
  },
  internalSources() {
    return apiFetch<SourceHealth[]>("/internal/v1/sources", {
      authenticated: true,
    });
  },
  internalRuns(limit = 50) {
    return apiFetch<SourceRun[]>(
      `/internal/v1/runs${buildQuery({ limit })}`,
      { authenticated: true },
    );
  },
  internalAudit(limit = 50) {
    return apiFetch<AuditEntry[]>(
      `/internal/v1/audit${buildQuery({ limit })}`,
      { authenticated: true },
    );
  },
  internalDeadLetters(limit = 50) {
    return apiFetch<DeadLetter[]>(
      `/internal/v1/dead-letters${buildQuery({ limit })}`,
      { authenticated: true },
    );
  },
  internalUsers(limit = 100) {
    return apiFetch<User[]>(
      `/internal/v1/users${buildQuery({ limit })}`,
      { authenticated: true },
    );
  },
  createStaffUser(payload: {
    email: string;
    password: string;
    display_name: string;
    roles: string[];
  }) {
    return apiFetch<User>("/internal/v1/users", {
      method: "POST",
      authenticated: true,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  },
  internalMerchants(limit = 100) {
    return apiFetch<Merchant[]>(
      `/internal/v1/merchants${buildQuery({ limit })}`,
      { authenticated: true },
    );
  },
  createMerchant(payload: {
    legal_name: string;
    display_name: string;
    merchant_type: string;
    owner_user_id?: string | null;
    commission_rate_bps: number;
    status: string;
  }) {
    return apiFetch<Merchant>("/internal/v1/merchants", {
      method: "POST",
      authenticated: true,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  },
  internalInventory(limit = 200) {
    return apiFetch<InventoryItem[]>(
      `/internal/v1/inventory${buildQuery({ limit })}`,
      { authenticated: true },
    );
  },
  createInventory(payload: {
    merchant_id: string;
    phone_variant_id: string;
    sku: string;
    condition_grade: string;
    battery_health_pct?: number | null;
    repair_history?: Array<Record<string, unknown>>;
    accessories?: string[];
    cost_hkd?: number | null;
    status: string;
  }) {
    return apiFetch<InventoryItem>("/internal/v1/inventory", {
      method: "POST",
      authenticated: true,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  },
  internalSellerListings(limit = 200) {
    return apiFetch<StoreListing[]>(
      `/internal/v1/seller-listings${buildQuery({ limit })}`,
      { authenticated: true },
    );
  },
  internalOrders(status?: string, limit = 100) {
    return apiFetch<InternalOrder[]>(
      `/internal/v1/orders${buildQuery({ status, limit })}`,
      { authenticated: true },
    );
  },
  fulfillOrder(orderId: string, status: "processing" | "shipped", note: string) {
    return apiFetch<InternalOrder>(
      `/internal/v1/orders/${orderId}/fulfill`,
      {
        method: "POST",
        authenticated: true,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status, note }),
      },
    );
  },
  refundOrder(orderId: string, reason: string, idempotencyKey: string) {
    return apiFetch<Refund>(`/internal/v1/orders/${orderId}/refund`, {
      method: "POST",
      authenticated: true,
      headers: {
        "Content-Type": "application/json",
        "Idempotency-Key": idempotencyKey,
      },
      body: JSON.stringify({
        reason,
        idempotency_key: idempotencyKey,
      }),
    });
  },
  restockOrder(orderId: string) {
    return apiFetch<InternalOrder>(
      `/internal/v1/orders/${orderId}/restock`,
      {
        method: "POST",
        authenticated: true,
      },
    );
  },
  internalLedger(orderId?: string, limit = 100) {
    return apiFetch<LedgerJournal[]>(
      `/internal/v1/ledger${buildQuery({ order_id: orderId, limit })}`,
      { authenticated: true },
    );
  },
  createSellerListing(payload: {
    merchant_id: string;
    inventory_item_id: string;
    title: string;
    description: string;
    price_hkd: number;
    warranty_days: number;
    inspection_report: Record<string, unknown>;
    images: string[];
    slug?: string | null;
  }) {
    return apiFetch<StoreListing>("/internal/v1/seller-listings", {
      method: "POST",
      authenticated: true,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  },
  quickCreateSellerListing(payload: {
    merchant_id: string;
    phone_variant_id: string;
    condition_grade: string;
    price_hkd: number;
    battery_health_pct?: number | null;
    title?: string;
    description?: string;
    warranty_days?: number;
    images?: string[];
  }) {
    return apiFetch<StoreListing>("/internal/v1/seller-listings/quick", {
      method: "POST",
      authenticated: true,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  },
  publishSellerListing(listingId: string) {
    return apiFetch<StoreListing>(
      `/internal/v1/seller-listings/${listingId}/publish`,
      {
        method: "POST",
        authenticated: true,
      },
    );
  },
  enqueueCollection(sourceKey: string, limit = 30) {
    return apiFetch<ActionAccepted>(
      `/internal/v1/sources/${sourceKey}/collect${buildQuery({ limit })}`,
      { method: "POST", authenticated: true },
    );
  },
  rebuildClusters() {
    return apiFetch<ActionAccepted>("/internal/v1/clusters/rebuild", {
      method: "POST",
      authenticated: true,
    });
  },
  runMaintenance() {
    return apiFetch<ActionAccepted>("/internal/v1/maintenance/run", {
      method: "POST",
      authenticated: true,
    });
  },
};
