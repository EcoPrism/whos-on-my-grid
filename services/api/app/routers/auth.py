"""Sign in with Google, see who you are, sign out. Routes 404 when the gate
is off, so a local run on fixtures has no auth surface at all."""

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.auth import IdentityError, IdentityVerifier, Sessions, User, same_site_post
from app.auth.gate import Gate
from app.telemetry import log_event

router = APIRouter(prefix="/api/auth")


class GoogleBody(BaseModel):
    credential: str = Field(min_length=10, max_length=4096)


def _sessions(request: Request) -> Sessions:
    sessions: Sessions | None = request.app.state.sessions
    if sessions is None:
        raise HTTPException(404, "auth_off")
    return sessions


def _gate(request: Request) -> Gate:
    return request.app.state.gate


async def describe(request: Request, user: User | None) -> dict | None:
    if user is None:
        return None
    return {"email": user.email, "remaining": await _gate(request).remaining(user)}


@router.post("/google")
async def sign_in_google(body: GoogleBody, request: Request, response: Response) -> dict:
    sessions = _sessions(request)
    if not same_site_post(request):
        raise HTTPException(403, "cross_site")
    verifier: IdentityVerifier = request.app.state.verifier
    try:
        identity = await verifier.verify(body.credential)
    except IdentityError as exc:
        log_event("sign_in_rejected", reason=str(exc)[:120])
        raise HTTPException(401, "invalid_credential") from exc
    user = User(subject=identity.subject, email=identity.email)
    await _gate(request).usage.touch_user(user.subject, user.email)
    sessions.set_cookie(response, user)
    log_event("sign_in")
    return await describe(request, user) or {}


@router.get("/me")
async def me(request: Request) -> dict | None:
    sessions = _sessions(request)
    return await describe(request, sessions.user_of(request))


@router.post("/logout")
async def logout(request: Request, response: Response) -> dict:
    sessions = _sessions(request)
    if not same_site_post(request):
        raise HTTPException(403, "cross_site")
    sessions.clear_cookie(response)
    return {"ok": True}
