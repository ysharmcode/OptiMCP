"""Daemon bearer-token auth and loopback bind rules."""

from __future__ import annotations

import hmac
import os
from typing import Optional, Tuple

from optimcp.monitor.models import DaemonConfig

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


class AuthError(Exception):
    """Raised when daemon auth configuration or a request token is invalid."""

    def __init__(self, message: str, status_code: int = 401) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def is_loopback_host(host: str) -> bool:
    h = (host or "").strip().lower()
    if h in LOOPBACK_HOSTS:
        return True
    # IPv4 mapped / bare
    if h.startswith("127."):
        return True
    return False


def resolve_token(
    config: DaemonConfig,
    *,
    env: Optional[dict] = None,
) -> Optional[str]:
    """Env OPTIMCP_DAEMON_TOKEN wins over config.daemon_token."""
    env = env if env is not None else os.environ
    raw = env.get("OPTIMCP_DAEMON_TOKEN") or config.daemon_token
    if raw is None:
        return None
    raw = str(raw).strip()
    return raw or None


def auth_required(
    host: str,
    config: DaemonConfig,
    *,
    allow_unauthenticated_localhost: Optional[bool] = None,
    env: Optional[dict] = None,
) -> Tuple[bool, Optional[str]]:
    """Return (must_authenticate, expected_token).

    Raises :class:`AuthError` when a non-loopback bind has no token, or when
    loopback has no token and the explicit localhost opt-out is not set.
    """
    token = resolve_token(config, env=env)
    opt_out = (
        config.allow_unauthenticated_localhost
        if allow_unauthenticated_localhost is None
        else allow_unauthenticated_localhost
    )
    loopback = is_loopback_host(host)

    if token:
        return True, token

    if not loopback:
        raise AuthError(
            "OPTIMCP_DAEMON_TOKEN (or config daemon_token) is required when "
            f"binding to non-loopback host {host!r}. Refusing to start.",
            status_code=500,
        )

    if opt_out:
        return False, None

    raise AuthError(
        "OPTIMCP_DAEMON_TOKEN (or config daemon_token) is required. "
        "For loopback-only unauthenticated mode pass "
        "--allow-unauthenticated-localhost (or set "
        "allow_unauthenticated_localhost: true). Refusing to start.",
        status_code=500,
    )


def extract_bearer(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    parts = authorization.strip().split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip() or None


def check_request_token(
    authorization: Optional[str],
    expected: Optional[str],
    *,
    required: bool,
) -> None:
    """Raise AuthError(401) if the request is not authorized."""
    if not required:
        return
    if not expected:
        raise AuthError("daemon token not configured", status_code=401)
    presented = extract_bearer(authorization)
    if presented is None or not hmac.compare_digest(presented, expected):
        raise AuthError("invalid or missing bearer token", status_code=401)
