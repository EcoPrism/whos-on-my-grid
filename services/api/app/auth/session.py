"""The session: an HS256 JWT in an HttpOnly cookie. Same origin as the page,
so no token ever reaches JavaScript. POSTs also carry X-Requested-With, a
second belt against cross-site requests beside SameSite=Lax."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import Request, Response

COOKIE = "grid_session"
REQUESTED_WITH = "grid"


@dataclass(frozen=True)
class User:
    subject: str
    email: str


class Sessions:
    def __init__(self, secret: str, *, days: int = 30, secure: bool = True) -> None:
        if not secret or len(secret) < 32:
            raise RuntimeError("GRID_SESSION_SECRET must be at least 32 characters")
        self.secret = secret
        self.days = days
        self.secure = secure

    def issue(self, user: User) -> str:
        now = datetime.now(UTC)
        return jwt.encode(
            {
                "sub": user.subject,
                "email": user.email,
                "iat": int(now.timestamp()),
                "exp": int((now + timedelta(days=self.days)).timestamp()),
            },
            self.secret,
            algorithm="HS256",
        )

    def read(self, token: str | None) -> User | None:
        if not token:
            return None
        try:
            claims = jwt.decode(
                token, self.secret, algorithms=["HS256"], options={"require": ["exp", "sub"]}
            )
        except jwt.InvalidTokenError:
            return None
        email = claims.get("email")
        if not isinstance(email, str):
            return None
        return User(subject=str(claims["sub"]), email=email)

    def user_of(self, request: Request) -> User | None:
        return self.read(request.cookies.get(COOKIE))

    def set_cookie(self, response: Response, user: User) -> None:
        response.set_cookie(
            COOKIE,
            self.issue(user),
            max_age=self.days * 86_400,
            httponly=True,
            secure=self.secure,
            samesite="lax",
            path="/",
        )

    def clear_cookie(self, response: Response) -> None:
        response.delete_cookie(COOKIE, path="/", httponly=True, secure=self.secure, samesite="lax")


def same_site_post(request: Request) -> bool:
    """A browser POST from our page carries the header; a cross-site form cannot."""
    return request.headers.get("x-requested-with") == REQUESTED_WITH
