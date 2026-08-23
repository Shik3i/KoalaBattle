"""Shared-secret bearer-token auth for the KoalaBattle API.

KoalaBattle is a single-operator, mostly-local app: there is no concept of
multiple users, so this is deliberately NOT a login system. It is one shared
secret (``KOALABATTLE_API_TOKEN``) checked against the ``Authorization:
Bearer <token>`` header. When the token is unset, the guard is a no-op and
every request is allowed through — this preserves the existing
local-dev-friendly default of running with zero configuration — but a single
warning is logged so the gap is not silent.
"""

from __future__ import annotations

import logging

from fastapi import Header, HTTPException, WebSocket, status

from koalabattle.config import Settings

LOGGER = logging.getLogger(__name__)

_NO_AUTH_WARNING = (
    "KOALABATTLE_API_TOKEN is not set - the API is running with NO authentication. "
    "Anyone who can reach this port can create/cancel/delete matches, configure "
    "providers (arbitrary base_url - SSRF risk), read full match/prompt data, and "
    "trigger video/TTS jobs. Set KOALABATTLE_API_TOKEN to require a bearer token."
)


def _extract_bearer(authorization: str | None) -> str | None:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    return authorization[len("Bearer ") :].strip()


class ApiTokenGuard:
    """Bound to one FastAPI app instance (one resolved ``Settings``).

    Used two ways:
      * as a FastAPI dependency (``Depends(guard)``) on HTTP routes, and
      * via :meth:`check_websocket` for the websocket routes, which cannot
        rely on the ``Authorization`` header the way browsers use it.
    """

    def __init__(self, settings: Settings) -> None:
        self.token = (settings.api_token or "").strip() or None
        if self.token is None:
            LOGGER.warning(_NO_AUTH_WARNING)

    async def __call__(self, authorization: str | None = Header(default=None)) -> None:
        if self.token is None:
            return
        provided = _extract_bearer(authorization)
        if provided is None or provided != self.token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="missing or invalid bearer token",
                headers={"WWW-Authenticate": "Bearer"},
            )

    def check_websocket(self, websocket: WebSocket) -> bool:
        """True if the connection may proceed.

        WebSocket clients generally can't set custom headers, so the token is
        accepted as a ``?token=`` query parameter instead.
        """
        if self.token is None:
            return True
        return websocket.query_params.get("token") == self.token
