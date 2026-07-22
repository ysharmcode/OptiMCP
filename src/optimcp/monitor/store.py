"""Filesystem ruleset registry + SQLite append-only check/violation log."""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

from optimcp.check.rules import Rule
from optimcp.monitor.hashing import document_hash
from optimcp.monitor.models import (
    CheckEvent,
    CheckSource,
    DaemonConfig,
    Policy,
    RulesetRecord,
    utc_now,
)

try:
    import yaml  # type: ignore
except ImportError:  # pragma: no cover - PyYAML optional; JSON fallback
    yaml = None


def default_home() -> Path:
    override = os.getenv("OPTIMCP_HOME")
    if override:
        return Path(override).expanduser().resolve()
    return (Path.home() / ".optimcp").resolve()


class MonitorStore:
    """Named rulesets on disk + SQLite audit log under ``home``."""

    def __init__(self, home: Optional[Path] = None) -> None:
        self.home = Path(home) if home is not None else default_home()
        self.rulesets_dir = self.home / "rulesets"
        self.db_path = self.home / "monitor.db"
        self.config_path = self.home / "config.yaml"
        self.rulesets_dir.mkdir(parents=True, exist_ok=True)
        self.home.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS checks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    ruleset_id TEXT NOT NULL,
                    ruleset_version INTEGER NOT NULL,
                    document_hash TEXT NOT NULL,
                    consistent INTEGER NOT NULL,
                    broken_rules TEXT NOT NULL,
                    unevaluable TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    source TEXT NOT NULL,
                    correlation_id TEXT,
                    policy TEXT NOT NULL,
                    refused INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_checks_ruleset
                    ON checks(ruleset_id, timestamp);
                CREATE INDEX IF NOT EXISTS idx_checks_hash
                    ON checks(document_hash);
                """
            )

    # ---- config ------------------------------------------------------------

    def load_config(self) -> DaemonConfig:
        if not self.config_path.exists():
            return DaemonConfig()
        text = self.config_path.read_text(encoding="utf-8")
        data = self._parse_mapping(text)
        return DaemonConfig.model_validate(data or {})

    def save_config(self, config: DaemonConfig) -> None:
        payload = config.model_dump(exclude_none=True)
        self.config_path.write_text(self._dump_mapping(payload), encoding="utf-8")

    @staticmethod
    def _parse_mapping(text: str) -> Dict[str, Any]:
        text = text.strip()
        if not text:
            return {}
        if yaml is not None:
            loaded = yaml.safe_load(text)
            return loaded if isinstance(loaded, dict) else {}
        return json.loads(text)

    @staticmethod
    def _dump_mapping(data: Dict[str, Any]) -> str:
        if yaml is not None:
            return yaml.safe_dump(data, sort_keys=False)
        return json.dumps(data, indent=2) + "\n"

    # ---- rulesets ----------------------------------------------------------

    def _ruleset_path(self, ruleset_id: str) -> Path:
        safe = ruleset_id.replace("/", "_").replace("\\", "_")
        return self.rulesets_dir / f"{safe}.yaml"

    def register_ruleset(self, record: RulesetRecord) -> RulesetRecord:
        path = self._ruleset_path(record.id)
        existing = self.get_ruleset(record.id)
        if existing is not None and record.version <= existing.version:
            record = record.model_copy(update={"version": existing.version + 1})
        payload = record.model_dump(mode="json")
        path.write_text(self._dump_mapping(payload), encoding="utf-8")
        return record

    def get_ruleset(self, ruleset_id: str) -> Optional[RulesetRecord]:
        path = self._ruleset_path(ruleset_id)
        if not path.exists():
            # also try .json
            alt = path.with_suffix(".json")
            if not alt.exists():
                return None
            path = alt
        data = self._parse_mapping(path.read_text(encoding="utf-8"))
        if "id" not in data:
            data["id"] = ruleset_id
        return RulesetRecord.model_validate(data)

    def list_rulesets(self) -> List[RulesetRecord]:
        out: List[RulesetRecord] = []
        for path in sorted(self.rulesets_dir.glob("*")):
            if path.suffix not in (".yaml", ".yml", ".json"):
                continue
            data = self._parse_mapping(path.read_text(encoding="utf-8"))
            if "id" not in data:
                data["id"] = path.stem
            out.append(RulesetRecord.model_validate(data))
        return out

    def delete_ruleset(self, ruleset_id: str) -> bool:
        path = self._ruleset_path(ruleset_id)
        removed = False
        for p in (path, path.with_suffix(".json")):
            if p.exists():
                p.unlink()
                removed = True
        return removed

    # ---- checks / violations -----------------------------------------------

    def append_check(self, event: CheckEvent) -> CheckEvent:
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO checks (
                    timestamp, ruleset_id, ruleset_version, document_hash,
                    consistent, broken_rules, unevaluable, summary,
                    source, correlation_id, policy, refused
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.timestamp.isoformat(),
                    event.ruleset_id,
                    event.ruleset_version,
                    event.document_hash,
                    1 if event.consistent else 0,
                    json.dumps(event.broken_rules),
                    json.dumps(event.unevaluable),
                    event.summary,
                    event.source,
                    event.correlation_id,
                    event.policy,
                    1 if event.refused else 0,
                ),
            )
            event.id = int(cur.lastrowid)
        return event

    def list_violations(
        self,
        *,
        ruleset_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[CheckEvent]:
        limit = max(1, min(int(limit), 1000))
        sql = "SELECT * FROM checks WHERE consistent = 0"
        params: List[Any] = []
        if ruleset_id:
            sql += " AND ruleset_id = ?"
            params.append(ruleset_id)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._row_to_event(r) for r in rows]

    def list_checks(
        self,
        *,
        ruleset_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[CheckEvent]:
        limit = max(1, min(int(limit), 1000))
        sql = "SELECT * FROM checks WHERE 1=1"
        params: List[Any] = []
        if ruleset_id:
            sql += " AND ruleset_id = ?"
            params.append(ruleset_id)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._row_to_event(r) for r in rows]

    @staticmethod
    def _row_to_event(row: sqlite3.Row) -> CheckEvent:
        from datetime import datetime

        ts = row["timestamp"]
        try:
            timestamp = datetime.fromisoformat(ts)
        except ValueError:
            timestamp = utc_now()
        return CheckEvent(
            id=row["id"],
            timestamp=timestamp,
            ruleset_id=row["ruleset_id"],
            ruleset_version=row["ruleset_version"],
            document_hash=row["document_hash"],
            consistent=bool(row["consistent"]),
            broken_rules=json.loads(row["broken_rules"]),
            unevaluable=json.loads(row["unevaluable"]),
            summary=row["summary"],
            source=row["source"],  # type: ignore[arg-type]
            correlation_id=row["correlation_id"],
            policy=row["policy"],  # type: ignore[arg-type]
            refused=bool(row["refused"]),
        )

    def stats(self) -> Dict[str, Any]:
        with self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) AS n FROM checks").fetchone()["n"]
            bad = conn.execute(
                "SELECT COUNT(*) AS n FROM checks WHERE consistent = 0"
            ).fetchone()["n"]
            by = conn.execute(
                """
                SELECT ruleset_id,
                       COUNT(*) AS checks,
                       SUM(CASE WHEN consistent = 0 THEN 1 ELSE 0 END) AS violations
                FROM checks
                GROUP BY ruleset_id
                """
            ).fetchall()
        return {
            "total_checks": total,
            "total_violations": bad,
            "by_ruleset": [
                {
                    "ruleset_id": r["ruleset_id"],
                    "checks": r["checks"],
                    "violations": r["violations"] or 0,
                }
                for r in by
            ],
        }


# Re-export helpers used by service
__all__ = [
    "MonitorStore",
    "default_home",
    "document_hash",
    "RulesetRecord",
    "Rule",
    "Policy",
    "CheckSource",
]
