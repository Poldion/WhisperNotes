"""Anmeldung im Dashboard (siehe app/auth.py)."""

import asyncio

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

from ..auth import COOKIE, SESSION_SECONDS, auth_required, check_secret, is_authenticated, login_secret
from ..i18n import tr
from ..jobs import JobError

router = APIRouter(prefix="/api/auth", tags=["auth"])


class Login(BaseModel):
    password: str


def set_session_cookie(request: Request, response: Response) -> None:
    secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    response.set_cookie(COOKIE, request.app.state.signer.issue(), max_age=SESSION_SECONDS, httponly=True,
                        samesite="lax", secure=secure, path="/")


@router.get("/status")
async def status(request: Request):
    settings = request.app.state.settings
    return {"required": auth_required(settings),
            "authenticated": is_authenticated(request.scope, settings, request.app.state.signer)}


@router.post("/login", status_code=204)
async def login(request: Request, body: Login, response: Response):
    settings = request.app.state.settings
    if not auth_required(settings):
        return
    if not check_secret(body.password, login_secret(settings)):
        await asyncio.sleep(1.0)  # bremst Durchprobieren
        raise JobError(401, tr(settings.language, "Passwort falsch."))
    set_session_cookie(request, response)


@router.post("/logout", status_code=204)
async def logout(response: Response):
    response.delete_cookie(COOKIE, path="/")
