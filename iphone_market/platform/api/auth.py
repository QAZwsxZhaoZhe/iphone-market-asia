from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
from typing import Any, Callable

import httpx
import jwt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from ..identity import (
    get_user,
    internal_user,
    roles_for_user,
    user_for_session_token,
)
from ..settings import PlatformSettings, get_settings
from .deps import get_session


@dataclass(frozen=True)
class Principal:
    subject: str
    roles: tuple[str, ...]
    internal: bool = False
    user_id: str | None = None
    email: str | None = None
    auth_method: str = "none"


_JWKS_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


def authenticate_request(
    request: Request,
    session: Session = Depends(get_session),
) -> Principal:
    settings = request.app.state.settings
    platform_key = request.headers.get("X-Platform-Key", "")
    if platform_key:
        return _authenticate_platform_key(platform_key, settings)

    token = _bearer_token(request)
    if token:
        user = user_for_session_token(session, token)
        if user is not None:
            return _principal_from_user(user, settings)
        if settings.auth_mode == "oidc":
            return _authenticate_oidc_token(token, settings)
        if settings.auth_mode == "api_key":
            return _authenticate_platform_key(token, settings)

    if settings.auth_mode == "disabled":
        return Principal(
            "local-development",
            settings.internal_roles,
            True,
            auth_method="development",
        )
    raise _unauthorized("缺少有效登入凭证")


def bearer_token(request: Request) -> str:
    return _bearer_token(request)


def _authenticate_platform_key(
    token: str,
    settings: PlatformSettings,
) -> Principal:
    if (
        settings.auth_mode != "api_key"
        or not settings.api_key
        or not secrets.compare_digest(token, settings.api_key)
    ):
        raise _unauthorized("内部 API Key 无效")
    return Principal(
        "api-key",
        ("admin",),
        True,
        auth_method="api_key",
    )


def _authenticate_oidc_token(
    token: str,
    settings: PlatformSettings,
) -> Principal:
    try:
        claims = _decode_oidc_token(token, settings)
        roles = _roles_from_claims(claims, settings.oidc_roles_claim)
        internal = bool(set(roles) & set(settings.internal_roles))
        if not internal:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="账号没有内部平台角色",
            )
        return Principal(
            str(claims.get("sub") or "unknown"),
            roles,
            True,
            email=(
                str(claims.get("email")).strip()
                if claims.get("email")
                else None
            ),
            auth_method="oidc",
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise _unauthorized(f"OIDC Token 校验失败：{type(exc).__name__}") from exc


def _principal_from_user(
    user,
    settings: PlatformSettings,
) -> Principal:
    roles = roles_for_user(user)
    return Principal(
        subject=user.email,
        roles=roles,
        internal=internal_user(user, settings.internal_roles),
        user_id=user.id,
        email=user.email,
        auth_method="session",
    )


def require_internal(
    *allowed_roles: str,
) -> Callable[[Principal], Principal]:
    def dependency(
        principal: Principal = Depends(authenticate_request),
    ) -> Principal:
        if not principal.internal:
            raise _unauthorized("该接口仅供内部人员使用")
        if allowed_roles and not set(principal.roles).intersection(allowed_roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="当前角色无权执行此操作",
            )
        return principal

    return dependency


def _bearer_token(request: Request) -> str:
    header = request.headers.get("Authorization", "")
    scheme, _, value = header.partition(" ")
    if scheme.lower() != "bearer":
        return ""
    return value.strip()


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _decode_oidc_token(
    token: str,
    settings: PlatformSettings,
) -> dict[str, Any]:
    try:
        header = jwt.get_unverified_header(token)
        key_id = header.get("kid")
        jwks = _get_jwks(settings.oidc_jwks_url)
        key = _select_jwk(jwks, key_id)
        public_key = jwt.algorithms.RSAAlgorithm.from_jwk(key)
        return jwt.decode(
            token,
            key=public_key,
            algorithms=["RS256"],
            audience=settings.oidc_audience or None,
            issuer=settings.oidc_issuer or None,
            options={"verify_aud": bool(settings.oidc_audience)},
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise _unauthorized(f"OIDC Token 校验失败：{type(exc).__name__}") from exc


def _get_jwks(url: str) -> dict[str, Any]:
    if not url:
        raise _unauthorized("OIDC_JWKS_URL 未配置")
    now = time.time()
    cached = _JWKS_CACHE.get(url)
    if cached and cached[0] > now:
        return cached[1]
    try:
        response = httpx.get(url, timeout=10)
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        raise _unauthorized(f"无法获取 OIDC JWKS：{type(exc).__name__}") from exc
    _JWKS_CACHE[url] = (now + 300, payload)
    return payload


def _select_jwk(jwks: dict[str, Any], key_id: str | None) -> dict[str, Any]:
    keys = jwks.get("keys") or []
    if key_id:
        for key in keys:
            if key.get("kid") == key_id:
                return key
    if len(keys) == 1:
        return keys[0]
    raise _unauthorized("OIDC JWKS 中找不到匹配的签名密钥")


def _roles_from_claims(
    claims: dict[str, Any],
    claim_name: str,
) -> tuple[str, ...]:
    value: Any = claims.get(claim_name)
    if value is None and claim_name != "realm_access.roles":
        value = claims.get("realm_access", {}).get("roles")
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list):
        return tuple(str(item) for item in value)
    return ()
