"""Google sign-in: turn an id_token from Google Identity Services into a
verified (subject, email). The real verifier checks the RS256 signature
against Google's published keys (fetched with httpx, cached for an hour; an
unknown key id forces one refetch to absorb rotation), the issuer, the
audience and expiry, and requires a verified email.

The fake verifier (GRID_AUTH_PROVIDER=fake, tests only) accepts tokens of the
form "fake:<subject>:<email>" with no network."""

import time
from dataclasses import dataclass
from typing import Protocol

import httpx
import jwt

GOOGLE_ISSUERS = ("accounts.google.com", "https://accounts.google.com")
GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
JWKS_CACHE_TTL_S = 3600
JWKS_REFETCH_MIN_S = 60


class IdentityError(Exception):
    """The token failed verification: always a 401, never a 500."""


@dataclass(frozen=True)
class Identity:
    subject: str  # Google's stable `sub`, never the email
    email: str


class IdentityVerifier(Protocol):
    async def verify(self, token: str) -> Identity: ...


class GoogleVerifier:
    def __init__(self, client_id: str, *, jwks_url: str = GOOGLE_JWKS_URL) -> None:
        if not client_id:
            raise RuntimeError("GRID_GOOGLE_CLIENT_ID is required with GRID_AUTH_PROVIDER=google")
        self.client_id = client_id
        self.jwks_url = jwks_url
        self._keys: dict[str, object] = {}
        self._fetched_at = 0.0
        self._last_refetch = 0.0

    async def _fetch(self) -> None:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(self.jwks_url)
        r.raise_for_status()
        self._keys = {e["kid"]: jwt.PyJWK(e).key for e in r.json().get("keys", [])}
        self._fetched_at = self._last_refetch = time.monotonic()

    async def _key_for(self, kid: str) -> object:
        now = time.monotonic()
        stale = not self._keys or now - self._fetched_at > JWKS_CACHE_TTL_S
        # The kid comes from an unauthenticated header: refetch on an unknown
        # one at most once a minute, so random kids cannot hammer Google.
        unknown = kid not in self._keys and now - self._last_refetch > JWKS_REFETCH_MIN_S
        if stale or unknown:
            try:
                await self._fetch()
            except (httpx.HTTPError, KeyError, ValueError) as exc:
                raise IdentityError(f"could not fetch signing keys: {exc}") from exc
        key = self._keys.get(kid)
        if key is None:
            raise IdentityError("unknown signing key")
        return key

    async def verify(self, token: str) -> Identity:
        try:
            kid = jwt.get_unverified_header(token).get("kid", "")
            key = await self._key_for(kid)
            claims = jwt.decode(
                token,
                key=key,
                algorithms=["RS256"],
                audience=self.client_id,
                options={"require": ["exp", "iss", "sub", "aud"]},
            )
        except jwt.InvalidTokenError as exc:
            raise IdentityError(f"invalid token: {exc}") from exc
        if claims["iss"] not in GOOGLE_ISSUERS:
            raise IdentityError("wrong issuer")
        email = claims.get("email")
        if not isinstance(email, str) or claims.get("email_verified") is not True:
            raise IdentityError("email not verified")
        return Identity(subject=str(claims["sub"]), email=email.lower())


class FakeVerifier:
    async def verify(self, token: str) -> Identity:
        parts = token.split(":", 2)
        if len(parts) != 3 or parts[0] != "fake" or not parts[1] or "@" not in parts[2]:
            raise IdentityError("invalid token")
        return Identity(subject=parts[1], email=parts[2].lower())
