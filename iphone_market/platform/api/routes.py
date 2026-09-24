from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    status,
)
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from ...config import ACTIVE_SOURCE_BY_KEY, PHONE_VARIANTS
from .. import commerce, payments, repository
from ..identity import (
    IdentityError,
    create_user,
    authenticate_user,
    ensure_user_role,
    issue_session,
    list_users,
    revoke_session,
    roles_for_user,
)
from ..regions import district_options
from ..services import MarketAnalyticsService
from ..settings import PlatformSettings
from ..tasks import collect_source_task, maintenance_task
from .auth import Principal, authenticate_request, bearer_token, require_internal
from .deps import get_search_index, get_session
from .schemas import (
    ActionAccepted,
    AuditPublic,
    CancelOrderRequest,
    DeadLetterPublic,
    FulfillOrderRequest,
    InventoryItemCreate,
    InventoryItemPublic,
    InternalOrderPublic,
    LedgerJournalPublic,
    LoginRequest,
    ListingPage,
    ListingPublic,
    MerchantApply,
    MerchantCreate,
    MerchantPublic,
    MerchantStatusUpdate,
    OrderCreateRequest,
    OrderPublic,
    PaymentIntentPublic,
    PaymentWebhookAck,
    PrincipalPublic,
    QuickSellerListingCreate,
    RawCapturePublic,
    RefundCreateRequest,
    RefundPublic,
    RegisterRequest,
    SellerQuickListingCreate,
    SellerListingCreate,
    SessionPublic,
    SnapshotPublic,
    SourceHealthPublic,
    SourceRunPublic,
    StaffUserCreate,
    StoreListingPage,
    StoreListingPublic,
    TaskAccepted,
    UserPublic,
)


public_router = APIRouter(tags=["public"])
internal_router = APIRouter(prefix="/internal/v1", tags=["internal"])

SessionDep = Annotated[Session, Depends(get_session)]
InternalReader = Annotated[
    Principal,
    Depends(require_internal("admin", "operator", "analyst")),
]
InternalOperator = Annotated[
    Principal,
    Depends(require_internal("admin", "operator")),
]
AdminOnly = Annotated[Principal, Depends(require_internal("admin"))]
Authenticated = Annotated[Principal, Depends(authenticate_request)]


def _settings(request: Request) -> PlatformSettings:
    return request.app.state.settings


def _buyer_user_id(principal: Principal) -> str:
    if not principal.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="此操作需要買家帳戶",
        )
    return principal.user_id


def _public_user_id(principal: Principal) -> str:
    if principal.internal or not principal.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="此操作需要一般使用者帳戶",
        )
    return principal.user_id


def _seller_merchant_or_404(
    session: Session,
    principal: Principal,
):
    merchant = commerce.get_owned_merchant(
        session,
        owner_user_id=_public_user_id(principal),
    )
    if merchant is None:
        raise HTTPException(status_code=404, detail="尚未申請成為賣家")
    return merchant


@public_router.get("/healthz")
def healthz(request: Request) -> dict[str, str]:
    return {
        "status": "ok",
        "environment": _settings(request).environment,
        "timezone": "Asia/Hong_Kong",
    }


@public_router.post(
    "/v1/auth/register",
    response_model=SessionPublic,
    status_code=status.HTTP_201_CREATED,
)
def register(
    payload: RegisterRequest,
    request: Request,
    session: SessionDep,
) -> dict[str, Any]:
    if not _settings(request).allow_public_registration:
        raise HTTPException(status_code=403, detail="目前未開放公開註冊")
    try:
        user = create_user(
            session,
            email=payload.email,
            password=payload.password,
            display_name=payload.display_name,
            roles=("buyer",),
        )
    except IdentityError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    auth_session, token = issue_session(
        session,
        user=user,
        ttl_hours=_settings(request).session_ttl_hours,
        user_agent=request.headers.get("User-Agent"),
        ip_address=request.client.host if request.client else None,
    )
    repository.record_audit(
        session,
        actor=user.email,
        action="auth.register",
        resource_type="user",
        resource_id=user.id,
    )
    return {
        "token": token,
        "expires_at": auth_session.expires_at,
        "user": _user_payload(user),
    }


@public_router.post("/v1/auth/login", response_model=SessionPublic)
def login(
    payload: LoginRequest,
    request: Request,
    session: SessionDep,
) -> dict[str, Any]:
    user = authenticate_user(
        session,
        email=payload.email,
        password=payload.password,
    )
    if user is None:
        raise HTTPException(status_code=401, detail="電子郵件或密碼錯誤")
    auth_session, token = issue_session(
        session,
        user=user,
        ttl_hours=_settings(request).session_ttl_hours,
        user_agent=request.headers.get("User-Agent"),
        ip_address=request.client.host if request.client else None,
    )
    repository.record_audit(
        session,
        actor=user.email,
        action="auth.login",
        resource_type="user",
        resource_id=user.id,
    )
    return {
        "token": token,
        "expires_at": auth_session.expires_at,
        "user": _user_payload(user),
    }


@public_router.get("/v1/auth/me", response_model=PrincipalPublic)
def current_user(principal: Authenticated) -> dict[str, Any]:
    return {
        "subject": principal.subject,
        "roles": list(principal.roles),
        "internal": principal.internal,
        "user_id": principal.user_id,
        "email": principal.email,
        "auth_method": principal.auth_method,
    }


@public_router.post("/v1/auth/logout")
def logout(
    request: Request,
    principal: Authenticated,
    session: SessionDep,
) -> dict[str, bool]:
    revoked = revoke_session(session, bearer_token(request))
    if principal.user_id:
        repository.record_audit(
            session,
            actor=principal.subject,
            action="auth.logout",
            resource_type="user",
            resource_id=principal.user_id,
        )
    return {"revoked": revoked}


@public_router.get("/v1/listings", response_model=ListingPage)
def list_listings(
    request: Request,
    session: SessionDep,
    q: str | None = None,
    model: str | None = None,
    storage_gb: int | None = Query(None, ge=1),
    district: str | None = None,
    source_key: str | None = None,
    condition: str = "used",
    listing_status: str | None = "active",
    min_price: float | None = Query(None, ge=0),
    max_price: float | None = Query(None, ge=0),
    fresh_within_hours: int | None = Query(None, ge=1),
    cursor: str | None = None,
    limit: int | None = Query(None, ge=1),
) -> dict[str, Any]:
    settings = _settings(request)
    if min_price is not None and max_price is not None and min_price > max_price:
        raise HTTPException(status_code=422, detail="最低价格不能高于最高价格")
    selected_limit = min(
        limit or settings.default_page_size,
        settings.max_page_size,
    )
    listing_ids = None
    if q:
        listing_ids = get_search_index(request).search_ids(
            query=q,
            model=model,
            storage_gb=storage_gb,
            district=district,
            source_key=source_key,
            condition=condition,
            listing_status=listing_status,
            min_price=min_price,
            max_price=max_price,
            limit=5000,
        )
    try:
        return repository.list_listings(
            session,
            query=q,
            model=model,
            storage_gb=storage_gb,
            district=district,
            source_key=source_key,
            condition=condition,
            listing_status=listing_status,
            min_price=min_price,
            max_price=max_price,
            fresh_within_hours=fresh_within_hours,
            listing_ids=listing_ids,
            cursor=cursor,
            limit=selected_limit,
            max_limit=settings.max_page_size,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@public_router.get("/v1/listings/{listing_id}", response_model=ListingPublic)
def get_listing(listing_id: int, session: SessionDep) -> dict[str, Any]:
    listing = repository.get_listing(session, listing_id)
    if listing is None:
        raise HTTPException(status_code=404, detail="商品不存在")
    payload = repository._listing_payload(
        listing,
        cluster_id=repository.cluster_id_for_listing(session, listing.id),
    )
    return payload


@public_router.get(
    "/v1/listings/{listing_id}/history",
    response_model=list[SnapshotPublic],
)
def get_listing_history(
    listing_id: int,
    session: SessionDep,
    limit: int = Query(180, ge=1, le=1000),
) -> list[dict[str, Any]]:
    listing = repository.get_listing(session, listing_id)
    if listing is None:
        raise HTTPException(status_code=404, detail="商品不存在")
    return [
        {
            "observed_at": snapshot.observed_at,
            "collected_date": snapshot.collected_date,
            "status": snapshot.status,
            "condition": snapshot.condition,
            "district": snapshot.district,
            "price_native": _float(snapshot.price_native),
            "currency": snapshot.currency,
            "price_hkd": _float(snapshot.price_hkd),
        }
        for snapshot in repository.listing_history(
            session,
            listing_id,
            limit=limit,
        )
    ]


@public_router.get("/v1/market/summary")
def market_summary(
    request: Request,
    session: SessionDep,
    model: str | None = None,
    storage_gb: int | None = Query(None, ge=1),
    district: str | None = None,
    source_key: str | None = None,
) -> dict[str, Any]:
    return MarketAnalyticsService(_settings(request)).market_summary(
        session,
        model=model,
        storage_gb=storage_gb,
        district=district,
        source_key=source_key,
    )


@public_router.get("/v1/valuations")
def valuations(
    request: Request,
    session: SessionDep,
    model: str | None = None,
    storage_gb: int | None = Query(None, ge=1),
    lookback_days: int = Query(45, ge=1, le=365),
    limit: int = Query(50, ge=1, le=200),
) -> dict[str, Any] | list[dict[str, Any]]:
    if bool(model) != (storage_gb is not None):
        raise HTTPException(
            status_code=422,
            detail="model 和 storage_gb 必须同时提供",
        )
    service = MarketAnalyticsService(_settings(request))
    if model and storage_gb is not None:
        try:
            return service.valuation(
                session,
                model=model,
                storage_gb=storage_gb,
                lookback_days=lookback_days,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    return [
        _valuation_payload(row)
        for row in repository.recent_valuations(
            session,
            model=model,
            storage_gb=storage_gb,
            limit=limit,
        )
    ]


@public_router.get("/v1/opportunities")
def opportunities(
    request: Request,
    session: SessionDep,
    model: str = Query(...),
    storage_gb: int = Query(..., ge=1),
    limit: int = Query(20, ge=1, le=100),
    fee_pct: float | None = Query(None, ge=0, le=40),
) -> dict[str, Any]:
    try:
        return MarketAnalyticsService(_settings(request)).opportunities(
            session,
            model=model,
            storage_gb=storage_gb,
            limit=limit,
            fee_pct=fee_pct,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@public_router.get("/v1/sources", response_model=list[SourceHealthPublic])
def sources(session: SessionDep) -> list[dict[str, Any]]:
    return repository.source_health(session)


@public_router.get("/v1/meta")
def metadata(request: Request) -> dict[str, Any]:
    return {
        "market": "香港",
        "currency": "HKD",
        "timezone": "Asia/Hong_Kong",
        "auth": {
            "public_registration": _settings(request).allow_public_registration,
        },
        "districts": district_options(),
        "variants": [
            {
                "id": repository.variant_id(item.model, item.storage_gb),
                "model": item.model,
                "generation": item.generation,
                "family": item.family,
                "storage_gb": item.storage_gb,
                "storage_label": item.storage_label,
            }
            for item in PHONE_VARIANTS
        ],
    }


@public_router.get("/v1/store/listings", response_model=StoreListingPage)
def store_listings(
    session: SessionDep,
    model: str | None = None,
    storage_gb: int | None = Query(None, ge=1),
    condition_grade: str | None = None,
    min_price: float | None = Query(None, ge=0),
    max_price: float | None = Query(None, ge=0),
    offset: int = Query(0, ge=0),
    limit: int = Query(30, ge=1, le=100),
) -> dict[str, Any]:
    if min_price is not None and max_price is not None and min_price > max_price:
        raise HTTPException(status_code=422, detail="最低價格不能高於最高價格")
    items, total = commerce.store_listings(
        session,
        model=model,
        storage_gb=storage_gb,
        condition_grade=condition_grade,
        min_price=min_price,
        max_price=max_price,
        offset=offset,
        limit=limit,
    )
    return {
        "items": [commerce.seller_listing_payload(item) for item in items],
        "total": total,
        "offset": offset,
        "limit": limit,
    }


@public_router.get(
    "/v1/store/listings/{listing_id}",
    response_model=StoreListingPublic,
)
def store_listing(
    listing_id: str,
    session: SessionDep,
) -> dict[str, Any]:
    listing = commerce.get_store_listing(session, listing_id)
    if listing is None:
        raise HTTPException(status_code=404, detail="銷售商品不存在")
    return commerce.seller_listing_payload(listing)


@public_router.get(
    "/v1/seller/profile",
    response_model=MerchantPublic | None,
)
def seller_profile(
    session: SessionDep,
    principal: Authenticated,
) -> dict[str, Any] | None:
    merchant = commerce.get_owned_merchant(
        session,
        owner_user_id=_public_user_id(principal),
    )
    return commerce.merchant_payload(merchant) if merchant else None


@public_router.post(
    "/v1/seller/apply",
    response_model=MerchantPublic,
)
def seller_apply(
    payload: MerchantApply,
    session: SessionDep,
    principal: Authenticated,
) -> dict[str, Any]:
    user_id = _public_user_id(principal)
    try:
        merchant = commerce.apply_merchant(
            session,
            owner_user_id=user_id,
            legal_name=payload.legal_name,
            display_name=payload.display_name,
            merchant_type=payload.merchant_type,
        )
        ensure_user_role(session, user_id=user_id, role="merchant")
    except (commerce.CommerceError, IdentityError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    repository.record_audit(
        session,
        actor=principal.subject,
        action="seller.apply",
        resource_type="merchant",
        resource_id=merchant.id,
    )
    return commerce.merchant_payload(merchant)


@public_router.get(
    "/v1/seller/listings",
    response_model=list[StoreListingPublic],
)
def seller_listings(
    session: SessionDep,
    principal: Authenticated,
    listing_status: str | None = Query(None, alias="status"),
    limit: int = Query(100, ge=1, le=200),
) -> list[dict[str, Any]]:
    merchant = _seller_merchant_or_404(session, principal)
    return [
        commerce.seller_listing_payload(listing)
        for listing in commerce.list_seller_listings(
            session,
            merchant_id=merchant.id,
            status=listing_status,
            limit=limit,
        )
    ]


@public_router.post(
    "/v1/seller/listings/quick",
    response_model=StoreListingPublic,
    status_code=status.HTTP_201_CREATED,
)
def seller_quick_create_listing(
    payload: SellerQuickListingCreate,
    session: SessionDep,
    principal: Authenticated,
) -> dict[str, Any]:
    merchant = _seller_merchant_or_404(session, principal)
    try:
        listing = commerce.quick_create_seller_listing(
            session,
            merchant_id=merchant.id,
            phone_variant_id=payload.phone_variant_id,
            condition_grade=payload.condition_grade,
            price_hkd=payload.price_hkd,
            battery_health_pct=payload.battery_health_pct,
            title=payload.title,
            description=payload.description,
            warranty_days=payload.warranty_days,
            images=payload.images,
        )
    except commerce.CommerceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    repository.record_audit(
        session,
        actor=principal.subject,
        action="seller_listing.quick_create",
        resource_type="seller_listing",
        resource_id=listing.id,
        details={"merchant_id": merchant.id},
    )
    return commerce.seller_listing_payload(listing)


@public_router.get("/v1/seller/orders", response_model=list[OrderPublic])
def seller_orders(
    session: SessionDep,
    principal: Authenticated,
    order_status: str | None = Query(None, alias="status"),
    limit: int = Query(100, ge=1, le=500),
) -> list[dict[str, Any]]:
    merchant = _seller_merchant_or_404(session, principal)
    return [
        payments.order_payload(order)
        for order in payments.list_merchant_orders(
            session,
            merchant_id=merchant.id,
            status=order_status,
            limit=limit,
        )
    ]


@public_router.post(
    "/v1/seller/orders/{order_id}/fulfill",
    response_model=OrderPublic,
)
def seller_fulfill_order(
    order_id: str,
    payload: FulfillOrderRequest,
    session: SessionDep,
    principal: Authenticated,
) -> dict[str, Any]:
    merchant = _seller_merchant_or_404(session, principal)
    try:
        order = payments.fulfill_merchant_order(
            session,
            merchant_id=merchant.id,
            order_id=order_id,
            target_status=payload.status,
            actor=f"merchant:{merchant.id}",
            note=payload.note,
        )
    except payments.OrderError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    repository.record_audit(
        session,
        actor=principal.subject,
        action="seller_order.fulfill",
        resource_type="order",
        resource_id=order.id,
        details={"merchant_id": merchant.id, "status": payload.status},
    )
    return payments.order_payload(order)


@public_router.post(
    "/v1/store/orders",
    response_model=OrderPublic,
    status_code=status.HTTP_201_CREATED,
)
def create_store_order(
    payload: OrderCreateRequest,
    session: SessionDep,
    principal: Authenticated,
    idempotency_key: Annotated[
        str | None,
        Header(alias="Idempotency-Key"),
    ] = None,
) -> dict[str, Any]:
    key = (idempotency_key or payload.idempotency_key or "").strip()
    if not key:
        raise HTTPException(
            status_code=422,
            detail="需要 Idempotency-Key 才能建立訂單",
        )
    try:
        order = payments.place_order(
            session,
            buyer_user_id=_buyer_user_id(principal),
            listing_id=payload.listing_id,
            idempotency_key=key,
            contact=payload.contact.model_dump(),
            shipping_address=payload.shipping_address.model_dump(),
        )
    except payments.OrderError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    repository.record_audit(
        session,
        actor=principal.subject,
        action="order.create",
        resource_type="order",
        resource_id=order.id,
        details={"order_number": order.order_number},
    )
    return payments.order_payload(order)


@public_router.get("/v1/orders", response_model=list[OrderPublic])
def buyer_orders(
    session: SessionDep,
    principal: Authenticated,
    limit: int = Query(100, ge=1, le=200),
) -> list[dict[str, Any]]:
    return [
        payments.order_payload(order)
        for order in payments.list_buyer_orders(
            session,
            buyer_user_id=_buyer_user_id(principal),
            limit=limit,
        )
    ]


@public_router.get("/v1/orders/{order_id}", response_model=OrderPublic)
def buyer_order(
    order_id: str,
    session: SessionDep,
    principal: Authenticated,
) -> dict[str, Any]:
    order = payments.get_buyer_order(
        session,
        buyer_user_id=_buyer_user_id(principal),
        order_id=order_id,
    )
    if order is None:
        raise HTTPException(status_code=404, detail="訂單不存在")
    return payments.order_payload(order)


@public_router.post(
    "/v1/orders/{order_id}/cancel",
    response_model=OrderPublic,
)
def cancel_order(
    order_id: str,
    payload: CancelOrderRequest,
    session: SessionDep,
    principal: Authenticated,
) -> dict[str, Any]:
    try:
        order = payments.cancel_order(
            session,
            buyer_user_id=_buyer_user_id(principal),
            order_id=order_id,
            reason=payload.reason,
        )
    except payments.OrderError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    repository.record_audit(
        session,
        actor=principal.subject,
        action="order.cancel",
        resource_type="order",
        resource_id=order.id,
    )
    return payments.order_payload(order)


@public_router.post(
    "/v1/orders/{order_id}/payment-intent",
    response_model=PaymentIntentPublic,
)
def create_order_payment_intent(
    order_id: str,
    request: Request,
    session: SessionDep,
    principal: Authenticated,
) -> dict[str, Any]:
    try:
        intent = payments.create_payment_intent(
            session,
            _settings(request),
            buyer_user_id=_buyer_user_id(principal),
            order_id=order_id,
        )
    except payments.OrderError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return payments.payment_intent_payload(intent)


@public_router.post(
    "/v1/orders/{order_id}/confirm-receipt",
    response_model=OrderPublic,
)
def confirm_order_receipt(
    order_id: str,
    session: SessionDep,
    principal: Authenticated,
) -> dict[str, Any]:
    try:
        order = payments.confirm_receipt(
            session,
            buyer_user_id=_buyer_user_id(principal),
            order_id=order_id,
        )
    except payments.OrderError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    repository.record_audit(
        session,
        actor=principal.subject,
        action="order.confirm_receipt",
        resource_type="order",
        resource_id=order.id,
    )
    return payments.order_payload(order)


@public_router.get("/v1/payments/mock/checkout/{reference}")
def mock_checkout(
    reference: str,
    request: Request,
    session: SessionDep,
    signature: str = Query(...),
) -> RedirectResponse:
    settings = _settings(request)
    try:
        payments.verify_mock_checkout(
            settings,
            reference=reference,
            signature=signature,
        )
        order = payments.complete_mock_payment(
            session,
            settings,
            reference=reference,
        )
    except payments.PaymentVerificationError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except payments.OrderError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    separator = "&" if "?" in settings.payment_return_url else "?"
    target = (
        f"{settings.payment_return_url}{separator}"
        f"order={order.id}&status=paid"
    )
    return RedirectResponse(target, status_code=status.HTTP_303_SEE_OTHER)


@public_router.post(
    "/v1/payments/{provider}/webhook",
    response_model=PaymentWebhookAck,
)
async def payment_webhook(
    provider: str,
    request: Request,
    session: SessionDep,
) -> dict[str, Any]:
    raw_body = await request.body()
    try:
        event, duplicate = payments.process_webhook(
            session,
            _settings(request),
            provider_key=provider,
            raw_body=raw_body,
            headers=request.headers,
        )
    except payments.PaymentVerificationError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except payments.OrderError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "event_id": event.id,
        "provider_event_id": event.provider_event_id,
        "status": event.status,
        "duplicate": duplicate,
    }


@internal_router.get("/sources", response_model=list[SourceHealthPublic])
def internal_sources(
    session: SessionDep,
    _principal: InternalReader,
) -> list[dict[str, Any]]:
    return repository.source_health(session)


@internal_router.get("/users", response_model=list[UserPublic])
def internal_users(
    session: SessionDep,
    _principal: AdminOnly,
    limit: int = Query(100, ge=1, le=500),
) -> list[dict[str, Any]]:
    return [_user_payload(user) for user in list_users(session, limit=limit)]


@internal_router.post(
    "/users",
    response_model=UserPublic,
    status_code=status.HTTP_201_CREATED,
)
def internal_create_user(
    payload: StaffUserCreate,
    session: SessionDep,
    principal: AdminOnly,
) -> dict[str, Any]:
    try:
        user = create_user(
            session,
            email=payload.email,
            password=payload.password,
            display_name=payload.display_name,
            roles=payload.roles,
        )
    except IdentityError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    repository.record_audit(
        session,
        actor=principal.subject,
        action="user.create",
        resource_type="user",
        resource_id=user.id,
        details={"roles": list(roles_for_user(user))},
    )
    return _user_payload(user)


@internal_router.get("/merchants", response_model=list[MerchantPublic])
def internal_merchants(
    session: SessionDep,
    _principal: InternalReader,
    limit: int = Query(100, ge=1, le=500),
) -> list[dict[str, Any]]:
    return [
        commerce.merchant_payload(merchant)
        for merchant in commerce.list_merchants(session, limit=limit)
    ]


@internal_router.post(
    "/merchants",
    response_model=MerchantPublic,
    status_code=status.HTTP_201_CREATED,
)
def internal_create_merchant(
    payload: MerchantCreate,
    session: SessionDep,
    principal: InternalOperator,
) -> dict[str, Any]:
    try:
        merchant = commerce.create_merchant(
            session,
            legal_name=payload.legal_name,
            display_name=payload.display_name,
            merchant_type=payload.merchant_type,
            owner_user_id=payload.owner_user_id,
            commission_rate_bps=payload.commission_rate_bps,
            status=payload.status,
        )
    except commerce.CommerceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    repository.record_audit(
        session,
        actor=principal.subject,
        action="merchant.create",
        resource_type="merchant",
        resource_id=merchant.id,
    )
    return commerce.merchant_payload(merchant)


@internal_router.post(
    "/merchants/{merchant_id}/status",
    response_model=MerchantPublic,
)
def internal_update_merchant_status(
    merchant_id: str,
    payload: MerchantStatusUpdate,
    session: SessionDep,
    principal: InternalOperator,
) -> dict[str, Any]:
    try:
        merchant = commerce.update_merchant_status(
            session,
            merchant_id=merchant_id,
            status=payload.status,
        )
    except commerce.CommerceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    repository.record_audit(
        session,
        actor=principal.subject,
        action="merchant.status",
        resource_type="merchant",
        resource_id=merchant.id,
        details={"status": merchant.status},
    )
    return commerce.merchant_payload(merchant)


@internal_router.get("/inventory", response_model=list[InventoryItemPublic])
def internal_inventory(
    session: SessionDep,
    _principal: InternalReader,
    merchant_id: str | None = None,
    item_status: str | None = Query(None, alias="status"),
    limit: int = Query(100, ge=1, le=500),
) -> list[dict[str, Any]]:
    return [
        commerce.inventory_payload(item)
        for item in commerce.list_inventory(
            session,
            merchant_id=merchant_id,
            status=item_status,
            limit=limit,
        )
    ]


@internal_router.post(
    "/inventory",
    response_model=InventoryItemPublic,
    status_code=status.HTTP_201_CREATED,
)
def internal_create_inventory(
    payload: InventoryItemCreate,
    session: SessionDep,
    principal: InternalOperator,
) -> dict[str, Any]:
    try:
        item = commerce.create_inventory_item(
            session,
            merchant_id=payload.merchant_id,
            phone_variant_id=payload.phone_variant_id,
            sku=payload.sku,
            condition_grade=payload.condition_grade,
            battery_health_pct=payload.battery_health_pct,
            repair_history=payload.repair_history,
            accessories=payload.accessories,
            cost_hkd=payload.cost_hkd,
            status=payload.status,
        )
    except commerce.CommerceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    repository.record_audit(
        session,
        actor=principal.subject,
        action="inventory.create",
        resource_type="inventory_item",
        resource_id=item.id,
        details={"sku": item.sku, "merchant_id": item.merchant_id},
    )
    return commerce.inventory_payload(item)


@internal_router.get(
    "/seller-listings",
    response_model=list[StoreListingPublic],
)
def internal_seller_listings(
    session: SessionDep,
    _principal: InternalReader,
    merchant_id: str | None = None,
    item_status: str | None = Query(None, alias="status"),
    limit: int = Query(100, ge=1, le=500),
) -> list[dict[str, Any]]:
    return [
        commerce.seller_listing_payload(listing)
        for listing in commerce.list_seller_listings(
            session,
            merchant_id=merchant_id,
            status=item_status,
            limit=limit,
        )
    ]


@internal_router.post(
    "/seller-listings",
    response_model=StoreListingPublic,
    status_code=status.HTTP_201_CREATED,
)
def internal_create_seller_listing(
    payload: SellerListingCreate,
    session: SessionDep,
    principal: InternalOperator,
) -> dict[str, Any]:
    try:
        listing = commerce.create_seller_listing(
            session,
            merchant_id=payload.merchant_id,
            inventory_item_id=payload.inventory_item_id,
            title=payload.title,
            description=payload.description,
            price_hkd=payload.price_hkd,
            warranty_days=payload.warranty_days,
            inspection_report=payload.inspection_report,
            images=payload.images,
            slug=payload.slug,
        )
    except commerce.CommerceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    repository.record_audit(
        session,
        actor=principal.subject,
        action="seller_listing.create",
        resource_type="seller_listing",
        resource_id=listing.id,
    )
    return commerce.seller_listing_payload(listing)


@internal_router.post(
    "/seller-listings/quick",
    response_model=StoreListingPublic,
    status_code=status.HTTP_201_CREATED,
)
def internal_quick_create_seller_listing(
    payload: QuickSellerListingCreate,
    session: SessionDep,
    principal: InternalOperator,
) -> dict[str, Any]:
    try:
        listing = commerce.quick_create_seller_listing(
            session,
            merchant_id=payload.merchant_id,
            phone_variant_id=payload.phone_variant_id,
            condition_grade=payload.condition_grade,
            price_hkd=payload.price_hkd,
            battery_health_pct=payload.battery_health_pct,
            title=payload.title,
            description=payload.description,
            warranty_days=payload.warranty_days,
            images=payload.images,
        )
    except commerce.CommerceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    repository.record_audit(
        session,
        actor=principal.subject,
        action="seller_listing.quick_create",
        resource_type="seller_listing",
        resource_id=listing.id,
        details={"merchant_id": listing.merchant_id},
    )
    return commerce.seller_listing_payload(listing)


@internal_router.post(
    "/seller-listings/{listing_id}/publish",
    response_model=StoreListingPublic,
)
def internal_publish_seller_listing(
    listing_id: str,
    session: SessionDep,
    principal: InternalOperator,
) -> dict[str, Any]:
    try:
        listing = commerce.publish_seller_listing(session, listing_id)
    except commerce.CommerceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    repository.record_audit(
        session,
        actor=principal.subject,
        action="seller_listing.publish",
        resource_type="seller_listing",
        resource_id=listing.id,
    )
    return commerce.seller_listing_payload(listing)


@internal_router.get("/orders", response_model=list[InternalOrderPublic])
def internal_orders(
    session: SessionDep,
    _principal: InternalReader,
    order_status: str | None = Query(None, alias="status"),
    limit: int = Query(100, ge=1, le=500),
) -> list[dict[str, Any]]:
    return [
        payments.order_payload(order, include_buyer=True)
        for order in payments.list_internal_orders(
            session,
            status=order_status,
            limit=limit,
        )
    ]


@internal_router.post(
    "/orders/{order_id}/fulfill",
    response_model=InternalOrderPublic,
)
def internal_fulfill_order(
    order_id: str,
    payload: FulfillOrderRequest,
    session: SessionDep,
    principal: InternalOperator,
) -> dict[str, Any]:
    try:
        order = payments.fulfill_order(
            session,
            order_id=order_id,
            target_status=payload.status,
            actor=principal.subject,
            note=payload.note,
        )
    except payments.OrderError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    repository.record_audit(
        session,
        actor=principal.subject,
        action="order.fulfill",
        resource_type="order",
        resource_id=order.id,
        details={"status": payload.status},
    )
    return payments.order_payload(order, include_buyer=True)


@internal_router.post(
    "/orders/{order_id}/refund",
    response_model=RefundPublic,
)
def internal_refund_order(
    order_id: str,
    payload: RefundCreateRequest,
    request: Request,
    session: SessionDep,
    principal: InternalOperator,
    idempotency_key: Annotated[
        str | None,
        Header(alias="Idempotency-Key"),
    ] = None,
) -> dict[str, Any]:
    key = (idempotency_key or payload.idempotency_key or "").strip()
    if not key:
        raise HTTPException(
            status_code=422,
            detail="需要 Idempotency-Key 才能退款",
        )
    try:
        refund = payments.request_refund(
            session,
            _settings(request),
            order_id=order_id,
            idempotency_key=key,
            reason=payload.reason,
            actor=principal.subject,
        )
    except payments.OrderError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    repository.record_audit(
        session,
        actor=principal.subject,
        action="order.refund",
        resource_type="order",
        resource_id=order_id,
        details={"refund_id": refund.id, "status": refund.status},
    )
    return payments.refund_payload(refund)


@internal_router.post(
    "/orders/{order_id}/restock",
    response_model=InternalOrderPublic,
)
def internal_restock_order(
    order_id: str,
    session: SessionDep,
    principal: InternalOperator,
) -> dict[str, Any]:
    try:
        order = payments.restock_refunded_order(
            session,
            order_id=order_id,
            actor=principal.subject,
        )
    except payments.OrderError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    repository.record_audit(
        session,
        actor=principal.subject,
        action="order.restock",
        resource_type="order",
        resource_id=order.id,
        details={"reason": "return_received_restocked"},
    )
    return payments.order_payload(order, include_buyer=True)


@internal_router.get("/ledger", response_model=list[LedgerJournalPublic])
def internal_ledger(
    session: SessionDep,
    _principal: InternalReader,
    order_id: str | None = None,
    limit: int = Query(100, ge=1, le=500),
) -> list[dict[str, Any]]:
    return [
        payments.journal_payload(journal)
        for journal in payments.list_ledger_journals(
            session,
            order_id=order_id,
            limit=limit,
        )
    ]


@internal_router.get("/runs", response_model=list[SourceRunPublic])
def internal_runs(
    session: SessionDep,
    _principal: InternalReader,
    source_key: str | None = None,
    limit: int = Query(50, ge=1, le=200),
) -> list[dict[str, Any]]:
    return [
        {
            "id": row.id,
            "source_key": row.source_key,
            "external_run_id": row.external_run_id,
            "status": row.status,
            "started_at": row.started_at,
            "finished_at": row.finished_at,
            "listing_count": row.listing_count,
            "query_count": row.query_count,
            "error": row.error,
            "attempt": row.attempt,
            "metadata": row.metadata_json,
        }
        for row in repository.recent_runs(
            session,
            source_key=source_key,
            limit=limit,
        )
    ]


@internal_router.get("/dead-letters", response_model=list[DeadLetterPublic])
def internal_dead_letters(
    session: SessionDep,
    _principal: InternalReader,
    limit: int = Query(100, ge=1, le=500),
) -> list[dict[str, Any]]:
    return [
        {
            "id": row.id,
            "task_id": row.task_id,
            "task_name": row.task_name,
            "args_json": row.args_json,
            "kwargs_json": row.kwargs_json,
            "error": row.error,
            "retry_count": row.retry_count,
            "created_at": row.created_at,
        }
        for row in repository.dead_letters(session, limit=limit)
    ]


@internal_router.get("/audit", response_model=list[AuditPublic])
def internal_audit(
    session: SessionDep,
    _principal: InternalReader,
    limit: int = Query(100, ge=1, le=500),
) -> list[dict[str, Any]]:
    return [
        {
            "id": row.id,
            "actor": row.actor,
            "action": row.action,
            "resource_type": row.resource_type,
            "resource_id": row.resource_id,
            "details": row.details,
            "created_at": row.created_at,
        }
        for row in repository.audit_entries(session, limit=limit)
    ]


@internal_router.get("/raw-captures", response_model=list[RawCapturePublic])
def internal_raw_captures(
    session: SessionDep,
    _principal: InternalReader,
    listing_id: int | None = None,
    source_key: str | None = None,
    limit: int = Query(100, ge=1, le=500),
) -> list[dict[str, Any]]:
    return [
        {
            "id": row.id,
            "source_key": row.source_key,
            "listing_id": row.listing_id,
            "captured_at": row.captured_at,
            "storage_uri": row.storage_uri,
            "sha256": row.sha256,
            "size_bytes": row.size_bytes,
            "content_type": row.content_type,
            "expires_at": row.expires_at,
            "metadata": row.metadata_json,
        }
        for row in repository.raw_captures(
            session,
            listing_id=listing_id,
            source_key=source_key,
            limit=limit,
        )
    ]


@internal_router.post(
    "/sources/{source_key}/collect",
    response_model=TaskAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
def enqueue_source_collection(
    source_key: str,
    session: SessionDep,
    principal: InternalOperator,
    run_date: str | None = None,
    limit: int | None = Query(None, ge=1, le=200),
) -> dict[str, str]:
    if source_key not in ACTIVE_SOURCE_BY_KEY:
        raise HTTPException(status_code=404, detail="来源不存在或当前未启用")
    task = collect_source_task.apply_async(
        args=(source_key, run_date, limit),
        queue="collection",
    )
    repository.record_audit(
        session,
        actor=principal.subject,
        action="source.collect.enqueue",
        resource_type="source",
        resource_id=source_key,
        details={"task_id": task.id, "run_date": run_date, "limit": limit},
    )
    return {"task_id": task.id, "status": "queued"}


@internal_router.post(
    "/clusters/rebuild",
    response_model=ActionAccepted,
)
def rebuild_clusters(
    session: SessionDep,
    principal: InternalOperator,
) -> dict[str, Any]:
    count = repository.rebuild_clusters(session)
    repository.record_audit(
        session,
        actor=principal.subject,
        action="clusters.rebuild",
        resource_type="listing_cluster",
        details={"cluster_count": count},
    )
    return {"status": "ok", "detail": "跨来源聚类已重建", "count": count}


@internal_router.post(
    "/maintenance/run",
    response_model=TaskAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
def run_maintenance(
    session: SessionDep,
    principal: InternalOperator,
) -> dict[str, str]:
    task = maintenance_task.apply_async(queue="maintenance")
    repository.record_audit(
        session,
        actor=principal.subject,
        action="maintenance.enqueue",
        resource_type="platform",
        details={"task_id": task.id},
    )
    return {"task_id": task.id, "status": "queued"}


def _user_payload(user) -> dict[str, Any]:
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "roles": list(roles_for_user(user)),
        "status": user.status,
        "created_at": user.created_at,
        "last_login_at": user.last_login_at,
    }


def _float(value: Any) -> float | None:
    if value is None:
        return None
    return round(float(value), 2)


def _valuation_payload(row) -> dict[str, Any]:
    return {
        "id": row.id,
        "market": row.market,
        "model": row.model,
        "storage_gb": row.storage_gb,
        "as_of_date": row.as_of_date,
        "method": row.method,
        "status": row.status,
        "fair_range_hkd": {
            "low": _float(row.fair_low_hkd),
            "mid": _float(row.fair_mid_hkd),
            "high": _float(row.fair_high_hkd),
        },
        "guidance_hkd": {
            "suggested_purchase_max": _float(row.suggested_purchase_hkd),
            "suggested_resale": _float(row.suggested_resale_hkd),
        },
        "confidence": {
            "level": row.confidence_level,
            "sample_count": row.sample_count,
        },
    }
