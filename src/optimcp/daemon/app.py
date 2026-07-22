"""Starlette/FastAPI HTTP app for the OptiMCP verification daemon."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from optimcp.daemon.auth import AuthError, auth_required, check_request_token, extract_bearer
from optimcp.daemon.dashboard import render_dashboard
from optimcp.daemon.rate_limit import RateLimitExceeded, TokenRateLimiter, default_limit_per_minute
from optimcp.monitor.models import DaemonConfig, RulesetRecord
from optimcp.monitor.service import MonitorService, RulesetNotFound
from optimcp.monitor.store import MonitorStore


class CheckBody(BaseModel):
    ruleset_id: str
    document: Dict[str, Any]
    correlation_id: Optional[str] = None


class AppState:
    def __init__(
        self,
        service: MonitorService,
        config: DaemonConfig,
        *,
        host: str,
        require_auth: bool,
        expected_token: Optional[str],
        rate_limiter: TokenRateLimiter,
    ) -> None:
        self.service = service
        self.config = config
        self.host = host
        self.require_auth = require_auth
        self.expected_token = expected_token
        self.rate_limiter = rate_limiter


def create_app(
    *,
    service: Optional[MonitorService] = None,
    config: Optional[DaemonConfig] = None,
    host: str = "127.0.0.1",
    allow_unauthenticated_localhost: Optional[bool] = None,
) -> FastAPI:
    store = (service.store if service else None) or MonitorStore()
    svc = service or MonitorService(store=store)
    cfg = config or store.load_config()
    require_auth, expected = auth_required(
        host,
        cfg,
        allow_unauthenticated_localhost=allow_unauthenticated_localhost,
    )
    state = AppState(
        svc,
        cfg,
        host=host,
        require_auth=require_auth,
        expected_token=expected,
        rate_limiter=TokenRateLimiter(default_limit_per_minute()),
    )

    app = FastAPI(
        title="OptiMCP daemon",
        version="0.2.0",
        description="Always-on verification layer over agent structured emissions.",
    )
    app.state.optimcp = state  # type: ignore[attr-defined]

    def _auth(authorization: Optional[str]) -> None:
        try:
            check_request_token(
                authorization, state.expected_token, required=state.require_auth
            )
        except AuthError as exc:
            raise HTTPException(
                status_code=exc.status_code,
                detail={"error": "unauthorized", "message": exc.message},
            ) from exc

    def _rate_limit(authorization: Optional[str]) -> None:
        key = extract_bearer(authorization) or "anonymous"
        try:
            state.rate_limiter.check(key)
        except RateLimitExceeded as exc:
            raise HTTPException(
                status_code=429,
                detail={
                    "error": "rate_limit_exceeded",
                    "message": str(exc),
                    "limit_per_minute": exc.limit_per_minute,
                },
            ) from exc

    @app.get("/health")
    def health() -> Dict[str, Any]:
        return {"ok": True, "service": "optimcp-daemon"}

    @app.get("/v1/rulesets")
    def list_rulesets(authorization: Optional[str] = Header(default=None)) -> Dict[str, Any]:
        _auth(authorization)
        return {
            "rulesets": [r.model_dump(mode="json") for r in state.service.list_rulesets()]
        }

    @app.put("/v1/rulesets/{ruleset_id}")
    def put_ruleset(
        ruleset_id: str,
        body: RulesetRecord,
        authorization: Optional[str] = Header(default=None),
    ) -> Dict[str, Any]:
        _auth(authorization)
        record = body.model_copy(update={"id": ruleset_id})
        saved = state.service.register_ruleset(record)
        return saved.model_dump(mode="json")

    @app.post("/v1/check")
    def check(
        body: CheckBody,
        authorization: Optional[str] = Header(default=None),
    ):
        _auth(authorization)
        _rate_limit(authorization)
        try:
            result = state.service.verify(
                body.ruleset_id,
                body.document,
                source="http",
                correlation_id=body.correlation_id,
            )
        except RulesetNotFound as exc:
            raise HTTPException(
                status_code=404,
                detail={"error": "ruleset_not_found", "ruleset_id": str(exc)},
            ) from exc
        payload = result.model_dump_report()
        if result.refused:
            return JSONResponse(status_code=422, content=payload)
        return payload

    @app.post("/v1/ingest")
    def ingest(
        body: CheckBody,
        authorization: Optional[str] = Header(default=None),
    ):
        return check(body, authorization)

    @app.get("/v1/violations")
    def violations(
        authorization: Optional[str] = Header(default=None),
        ruleset_id: Optional[str] = Query(default=None),
        limit: int = Query(default=100, ge=1, le=1000),
    ) -> Dict[str, Any]:
        _auth(authorization)
        rows = state.service.store.list_violations(ruleset_id=ruleset_id, limit=limit)
        return {"violations": [r.model_dump(mode="json") for r in rows]}

    @app.get("/dashboard", response_class=HTMLResponse)
    def dashboard(authorization: Optional[str] = Header(default=None)):
        _auth(authorization)
        stats = state.service.store.stats()
        viol = state.service.store.list_violations(limit=50)
        return HTMLResponse(render_dashboard(stats, viol))

    return app
