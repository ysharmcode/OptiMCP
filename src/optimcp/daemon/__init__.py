"""Self-hosted always-on OptiMCP verification daemon."""

from __future__ import annotations

from optimcp.daemon.app import create_app
from optimcp.daemon.auth import AuthError, auth_required, is_loopback_host
from optimcp.daemon.cli import main

__all__ = [
    "AuthError",
    "auth_required",
    "create_app",
    "is_loopback_host",
    "main",
]
