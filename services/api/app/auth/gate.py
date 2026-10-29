"""Who may spend model tokens. A cached brief, or one already being made, is
served to anyone. A new brief is made for: a signed-in user with quota left
today, or anyone for an address in the test set (eval/addresses.json), so
the demo dropdown works without an account. Both count toward the global
daily cap, which is the gateway budget's belt."""

import json
from dataclasses import dataclass
from functools import lru_cache

from app.auth.session import Sessions, User
from app.auth.usage import UsageStore
from app.config import REPO_ROOT, Settings
from app.geocode import normalise
from app.telemetry import log_event

TEST_SET = REPO_ROOT / "eval" / "addresses.json"


@lru_cache(maxsize=1)
def test_set_addresses() -> frozenset[str]:
    if not TEST_SET.exists():
        return frozenset()
    with open(TEST_SET, encoding="utf-8") as f:
        rows = json.load(f).get("addresses", [])
    return frozenset(normalise(r["address"]) for r in rows if isinstance(r.get("address"), str))


class GateDenied(Exception):
    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


@dataclass
class Gate:
    settings: Settings
    sessions: Sessions | None
    usage: UsageStore

    @property
    def on(self) -> bool:
        return self.sessions is not None

    async def remaining(self, user: User) -> int:
        used = await self.usage.count_user_today(user.subject)
        return max(0, self.settings.quota_per_user_day - used)

    async def admit(self, address: str, user: User | None) -> User | None:
        """Raise GateDenied, or return who to charge (None for a test-set run)."""
        if not self.on:
            return None
        if await self.usage.count_global_today() >= self.settings.quota_global_day:
            log_event("gate_denied", reason="global_quota")
            raise GateDenied(429, "quota_exceeded_today")
        if normalise(address) in test_set_addresses():
            return None
        if user is None:
            log_event("gate_denied", reason="sign_in")
            raise GateDenied(401, "sign_in_required")
        if await self.remaining(user) <= 0:
            log_event("gate_denied", reason="user_quota")
            raise GateDenied(429, "quota_exceeded_user")
        return user

    async def charge(self, user: User | None, brief_id: str) -> None:
        if not self.on:
            return
        await self.usage.record(
            user.subject if user else None, user.email if user else None, brief_id
        )
        log_event("brief_charged", brief_id=brief_id, signed_in=user is not None)
