"""Sign-in and usage. The gate only guards generating a *new* brief: viewing
one, or running a test-set address, never needs sign-in. See gate.py."""

from app.auth.identity import (
    FakeVerifier,
    GoogleVerifier,
    Identity,
    IdentityError,
    IdentityVerifier,
)
from app.auth.session import Sessions, User, same_site_post
from app.auth.usage import MemoryUsageStore, TableUsageStore, UsageStore
from app.config import Settings


def get_verifier(settings: Settings) -> IdentityVerifier | None:
    if settings.auth_provider == "off":
        return None
    if settings.auth_provider == "google":
        return GoogleVerifier(settings.google_client_id)
    if settings.auth_provider == "fake":
        return FakeVerifier()
    raise RuntimeError(
        f"GRID_AUTH_PROVIDER must be 'off', 'google' or 'fake', got {settings.auth_provider!r}"
    )


def get_sessions(settings: Settings) -> Sessions | None:
    if settings.auth_provider == "off":
        return None
    return Sessions(
        settings.session_secret, days=settings.session_days, secure=settings.cookie_secure
    )


def get_usage_store(settings: Settings) -> UsageStore:
    if settings.usage_store == "table":
        return TableUsageStore(settings.storage_account)
    if settings.usage_store == "memory":
        return MemoryUsageStore()
    raise RuntimeError(
        f"GRID_USAGE_STORE must be 'memory' or 'table', got {settings.usage_store!r}"
    )


__all__ = [
    "FakeVerifier",
    "GoogleVerifier",
    "Identity",
    "IdentityError",
    "IdentityVerifier",
    "MemoryUsageStore",
    "Sessions",
    "TableUsageStore",
    "UsageStore",
    "User",
    "get_sessions",
    "get_usage_store",
    "get_verifier",
    "same_site_post",
]
