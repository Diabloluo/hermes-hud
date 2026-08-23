"""Hermes HUD — 本地时序存储 (telemetry.db)。

只保存分钟级指标、事故聚合和短摘要，绝不保存完整消息/日志/对话正文。
保留期默认：指标 30 天，事故 90 天。所有写入都在独立的小 sqlite 文件，
不触碰 state.db。

路径：~/.hermes/hud/telemetry.db（$HERMES_HOME 优先）
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger(__name__)

DEFAULT_HOME = Path.home() / ".hermes"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS metrics (
    ts INTEGER NOT NULL,            -- epoch seconds
    kind TEXT NOT NULL,             -- e.g. sys / channel / incident
    name TEXT NOT NULL,             -- metric name
    value REAL NOT NULL,
    meta TEXT                       -- small JSON, <= 512 chars
);
CREATE INDEX IF NOT EXISTS idx_metrics_ts ON metrics(ts);
CREATE INDEX IF NOT EXISTS idx_metrics_kind_name ON metrics(kind, name, ts);

CREATE TABLE IF NOT EXISTS incidents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint TEXT NOT NULL,      -- 事故指纹
    severity TEXT NOT NULL,         -- critical / warn
    title TEXT NOT NULL,
    detail TEXT,                    -- 短摘要（已脱敏）
    first_seen INTEGER NOT NULL,
    last_seen INTEGER NOT NULL,
    count INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'active'   -- active / recovered
);
CREATE INDEX IF NOT EXISTS idx_incidents_status ON incidents(status, last_seen);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""

METRIC_RETENTION_DAYS = 30
INCIDENT_RETENTION_DAYS = 90


class TelemetryStore:
    """轻量 sqlite 封装。每个方法独立开连接，失败不抛出到上层采集器。"""

    def __init__(self, db_path: Optional[Path] = None):
        if db_path is None:
            # 与 collectors.HERMES_HOME 一致：$HERMES_HOME/hud/telemetry.db
            home = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))
            db_path = Path(home) / "hud" / "telemetry.db"
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=5)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_schema(self) -> None:
        try:
            with self._connect() as conn:
                conn.executescript(_SCHEMA)
        except Exception as exc:  # pragma: no cover
            log.warning("HUD telemetry schema init failed: %s", exc)

    # -- 写入 --------------------------------------------------------------

    def record_metric(self, kind: str, name: str, value: float, meta: Optional[dict] = None) -> None:
        try:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO metrics(ts, kind, name, value, meta) VALUES(?,?,?,?,?)",
                    (int(time.time()), kind, name, float(value),
                     json.dumps(meta)[:512] if meta else None),
                )
        except Exception as exc:
            log.debug("HUD metric write failed: %s", exc)

    def record_metrics_batch(self, kind: str, items: list[tuple[str, float, Optional[dict]]]) -> None:
        """批量写同一类指标（一次事务）。items = [(name, value, meta), ...]"""
        if not items:
            return
        now = int(time.time())
        try:
            with self._connect() as conn:
                conn.executemany(
                    "INSERT INTO metrics(ts, kind, name, value, meta) VALUES(?,?,?,?,?)",
                    [(now, kind, n, v, json.dumps(m)[:512] if m else None) for n, v, m in items],
                )
        except Exception as exc:
            log.debug("HUD metric batch write failed: %s", exc)

    def upsert_incident(self, fingerprint: str, severity: str, title: str,
                        detail: str, now: Optional[int] = None) -> None:
        now = now or int(time.time())
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT id, count, status FROM incidents WHERE fingerprint=?",
                    (fingerprint,),
                ).fetchone()
                if row:
                    conn.execute(
                        "UPDATE incidents SET last_seen=?, count=count+1, status='active', "
                        "severity=?, title=?, detail=? WHERE id=?",
                        (now, severity, title[:200], detail[:400], row[0]),
                    )
                else:
                    conn.execute(
                        "INSERT INTO incidents(fingerprint, severity, title, detail, first_seen, last_seen, count, status)"
                        " VALUES(?,?,?,?,?,?,1,'active')",
                        (fingerprint, severity, title[:200], detail[:400], now, now),
                    )
        except Exception as exc:
            log.debug("HUD incident write failed: %s", exc)

    def recover_incident(self, fingerprint: str, now: Optional[int] = None) -> None:
        now = now or int(time.time())
        try:
            with self._connect() as conn:
                conn.execute(
                    "UPDATE incidents SET status='recovered', last_seen=? WHERE fingerprint=? AND status='active'",
                    (now, fingerprint),
                )
        except Exception as exc:
            log.debug("HUD incident recover failed: %s", exc)

    # -- 读取 --------------------------------------------------------------

    def query_metrics(self, kind: str, name: Optional[str] = None,
                      since: Optional[int] = None, limit: int = 2000) -> list[dict]:
        q = "SELECT ts, kind, name, value, meta FROM metrics WHERE kind=?"
        args: list[Any] = [kind]
        if name:
            q += " AND name=?"
            args.append(name)
        if since:
            q += " AND ts>=?"
            args.append(since)
        q += " ORDER BY ts DESC LIMIT ?"
        args.append(limit)
        try:
            with self._connect() as conn:
                rows = conn.execute(q, args).fetchall()
            out = []
            for ts, k, n, v, m in rows:
                out.append({"ts": ts, "kind": k, "name": n, "value": v,
                            "meta": json.loads(m) if m else None})
            out.reverse()
            return out
        except Exception as exc:
            log.debug("HUD metric read failed: %s", exc)
            return []

    def list_incidents(self, active_only: bool = False, limit: int = 200) -> list[dict]:
        q = "SELECT id, fingerprint, severity, title, detail, first_seen, last_seen, count, status FROM incidents"
        if active_only:
            q += " WHERE status='active'"
        q += " ORDER BY last_seen DESC LIMIT ?"
        try:
            with self._connect() as conn:
                rows = conn.execute(q, (limit,)).fetchall()
            return [
                {"id": r[0], "fingerprint": r[1], "severity": r[2], "title": r[3],
                 "detail": r[4], "first_seen": r[5], "last_seen": r[6],
                 "count": r[7], "status": r[8]}
                for r in rows
            ]
        except Exception as exc:
            log.debug("HUD incident read failed: %s", exc)
            return []

    # -- 维护 --------------------------------------------------------------

    def prune(self) -> dict:
        """按保留期清理，返回清理统计。"""
        now = int(time.time())
        cut_metric = now - METRIC_RETENTION_DAYS * 86400
        cut_incident = now - INCIDENT_RETENTION_DAYS * 86400
        try:
            with self._connect() as conn:
                m = conn.execute("DELETE FROM metrics WHERE ts<?", (cut_metric,)).rowcount
                i = conn.execute("DELETE FROM incidents WHERE last_seen<? AND status='recovered'",
                                 (cut_incident,)).rowcount
            return {"metrics_deleted": m, "recovered_incidents_deleted": i}
        except Exception as exc:
            log.debug("HUD prune failed: %s", exc)
            return {}

    def stats(self) -> dict:
        try:
            with self._connect() as conn:
                metrics = conn.execute("SELECT COUNT(*) FROM metrics").fetchone()[0]
                incidents = conn.execute("SELECT COUNT(*) FROM incidents").fetchone()[0]
                active = conn.execute("SELECT COUNT(*) FROM incidents WHERE status='active'").fetchone()[0]
            size = self.db_path.stat().st_size if self.db_path.exists() else 0
            return {"metrics_rows": metrics, "incidents": incidents,
                    "active_incidents": active, "db_bytes": size}
        except Exception as exc:
            return {"error": str(exc)}
