"""Пароли и сессионная кука. Секрет подписи берётся из окружения и в код не пишется."""

from __future__ import annotations

import hashlib
import hmac
import secrets

from fastapi import HTTPException, Request, Response

from app.config import get_settings

COOKIE_NAME = "seo_session"
_ITERATIONS = 200_000


def hash_password(password: str) -> tuple[str, str]:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _ITERATIONS)
    return salt.hex(), digest.hex()


def verify_password(password: str, salt_hex: str, digest_hex: str) -> bool:
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode(),
        bytes.fromhex(salt_hex),
        _ITERATIONS,
    )
    return hmac.compare_digest(digest.hex(), digest_hex)


def _secret() -> bytes:
    settings = get_settings()
    material = settings.session_secret or settings.admin_password
    if not material:
        raise HTTPException(status_code=500, detail="Не задан секрет сессии")
    return material.encode()


def write_session(response: Response, user_id: int) -> None:
    payload = str(user_id)
    signature = hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()
    response.set_cookie(
        COOKIE_NAME,
        f"{payload}.{signature}",
        httponly=True,
        samesite="lax",
        path="/",
        max_age=60 * 60 * 24 * 14,
    )


def clear_session(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")


def read_session_user_id(request: Request) -> int | None:
    token = request.cookies.get(COOKIE_NAME)
    if not token or "." not in token:
        return None
    payload, signature = token.split(".", 1)
    if not payload.isdigit():
        return None
    try:
        expected = hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()
    except HTTPException:
        return None
    if not hmac.compare_digest(expected, signature):
        return None
    return int(payload)
