from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from . import models
from .settings import PlatformSettings


ROLE_BUYER = "buyer"
ROLE_MERCHANT = "merchant"
ROLE_ANALYST = "analyst"
ROLE_OPERATOR = "operator"
ROLE_ADMIN = "admin"

STAFF_ROLES = (ROLE_ADMIN, ROLE_OPERATOR, ROLE_ANALYST)
VALID_ROLES = frozenset(
    {
        ROLE_BUYER,
        ROLE_MERCHANT,
        ROLE_ANALYST,
        ROLE_OPERATOR,
        ROLE_ADMIN,
    }
)
ACTIVE_USER_STATUSES = frozenset({"active"})
PASSWORD_ITERATIONS = 300_000


class IdentityError(ValueError):
    pass


def normalize_email(value: str) -> str:
    email = value.strip().lower()
    if len(email) > 320 or "@" not in email:
        raise IdentityError("電子郵件格式無效")
    local, domain = email.rsplit("@", 1)
    if not local or not domain or "." not in domain:
        raise IdentityError("電子郵件格式無效")
    return email


def hash_password(
    password: str,
    *,
    iterations: int = PASSWORD_ITERATIONS,
) -> str:
    if len(password) < 10:
        raise IdentityError("密碼至少需要 10 個字元")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
    )
    return f"pbkdf2_sha256${iterations}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations_text, salt_hex, digest_hex = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = int(iterations_text)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
    except (ValueError, TypeError):
        return False
    actual = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
    )
    return hmac.compare_digest(actual, expected)


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_user(
    session: Session,
    *,
    email: str,
    password: str,
    display_name: str,
    roles: Iterable[str] = (ROLE_BUYER,),
    status: str = "active",
) -> models.User:
    normalized_email = normalize_email(email)
    selected_roles = _normalize_roles(roles)
    if not selected_roles:
        raise IdentityError("使用者至少需要一個角色")
    existing = session.scalar(
        select(models.User).where(models.User.email == normalized_email)
    )
    if existing is not None:
        raise IdentityError("此電子郵件已註冊")
    user = models.User(
        id=str(uuid.uuid4()),
        email=normalized_email,
        display_name=display_name.strip()[:120] or normalized_email.split("@")[0],
        password_hash=hash_password(password),
        status=status,
    )
    session.add(user)
    session.flush()
    for role in selected_roles:
        session.add(models.UserRole(user_id=user.id, role=role))
    session.flush()
    return get_user(session, user.id)


def authenticate_user(
    session: Session,
    *,
    email: str,
    password: str,
) -> models.User | None:
    try:
        normalized_email = normalize_email(email)
    except IdentityError:
        return None
    user = session.scalar(
        select(models.User)
        .options(selectinload(models.User.roles))
        .where(models.User.email == normalized_email)
    )
    if (
        user is None
        or user.status not in ACTIVE_USER_STATUSES
        or not verify_password(password, user.password_hash)
    ):
        return None
    user.last_login_at = datetime.now(timezone.utc)
    session.flush()
    return user


def issue_session(
    session: Session,
    *,
    user: models.User,
    ttl_hours: int,
    user_agent: str | None = None,
    ip_address: str | None = None,
) -> tuple[models.AuthSession, str]:
    raw_token = secrets.token_urlsafe(48)
    now = datetime.now(timezone.utc)
    auth_session = models.AuthSession(
        id=str(uuid.uuid4()),
        user_id=user.id,
        token_hash=hash_session_token(raw_token),
        user_agent=(user_agent or "")[:500] or None,
        ip_hash=(
            hashlib.sha256(ip_address.encode("utf-8")).hexdigest()
            if ip_address
            else None
        ),
        created_at=now,
        last_seen_at=now,
        expires_at=now + timedelta(hours=max(1, ttl_hours)),
    )
    session.add(auth_session)
    session.flush()
    return auth_session, raw_token


def user_for_session_token(
    session: Session,
    token: str,
) -> models.User | None:
    if not token:
        return None
    token_hash = hash_session_token(token)
    now = datetime.now(timezone.utc)
    auth_session = session.scalar(
        select(models.AuthSession)
        .options(
            selectinload(models.AuthSession.user).selectinload(models.User.roles)
        )
        .where(
            models.AuthSession.token_hash == token_hash,
            models.AuthSession.revoked_at.is_(None),
            models.AuthSession.expires_at > now,
        )
    )
    if auth_session is None or auth_session.user.status not in ACTIVE_USER_STATUSES:
        return None
    auth_session.last_seen_at = now
    return auth_session.user


def revoke_session(session: Session, token: str) -> bool:
    if not token:
        return False
    auth_session = session.scalar(
        select(models.AuthSession).where(
            models.AuthSession.token_hash == hash_session_token(token),
            models.AuthSession.revoked_at.is_(None),
        )
    )
    if auth_session is None:
        return False
    auth_session.revoked_at = datetime.now(timezone.utc)
    session.flush()
    return True


def ensure_bootstrap_admin(
    session: Session,
    settings: PlatformSettings,
) -> models.User | None:
    email = settings.bootstrap_admin_email.strip()
    password = settings.bootstrap_admin_password
    if not email or not password:
        return None
    normalized_email = normalize_email(email)
    user = session.scalar(
        select(models.User)
        .options(selectinload(models.User.roles))
        .where(models.User.email == normalized_email)
    )
    if user is None:
        return create_user(
            session,
            email=normalized_email,
            password=password,
            display_name=settings.bootstrap_admin_name or "Platform Admin",
            roles=(ROLE_ADMIN,),
        )
    if ROLE_ADMIN not in roles_for_user(user):
        session.add(models.UserRole(user_id=user.id, role=ROLE_ADMIN))
        session.flush()
        return get_user(session, user.id)
    return user


def get_user(session: Session, user_id: str) -> models.User:
    user = session.scalar(
        select(models.User)
        .options(selectinload(models.User.roles))
        .where(models.User.id == user_id)
    )
    if user is None:
        raise IdentityError("使用者不存在")
    return user


def ensure_user_role(
    session: Session,
    *,
    user_id: str,
    role: str,
) -> models.User:
    selected_role = role.strip().lower()
    if selected_role not in VALID_ROLES:
        raise IdentityError("不支援的角色")
    user = get_user(session, user_id)
    if selected_role not in roles_for_user(user):
        session.add(models.UserRole(user_id=user.id, role=selected_role))
        session.flush()
        return get_user(session, user.id)
    return user


def list_users(
    session: Session,
    *,
    limit: int = 100,
) -> list[models.User]:
    return list(
        session.scalars(
            select(models.User)
            .options(selectinload(models.User.roles))
            .order_by(models.User.created_at.desc())
            .limit(max(1, min(limit, 500)))
        )
    )


def roles_for_user(user: models.User) -> tuple[str, ...]:
    return tuple(sorted(role.role for role in user.roles))


def internal_user(user: models.User, internal_roles: Iterable[str]) -> bool:
    return bool(set(roles_for_user(user)).intersection(internal_roles))


def user_count(session: Session) -> int:
    return int(session.scalar(select(func.count(models.User.id))) or 0)


def _normalize_roles(roles: Iterable[str]) -> tuple[str, ...]:
    normalized = tuple(sorted({str(role).strip().lower() for role in roles if role}))
    invalid = sorted(set(normalized) - VALID_ROLES)
    if invalid:
        raise IdentityError(f"不支援的角色：{', '.join(invalid)}")
    return normalized
