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
    count INTEGER NOT NULL DEFAULT 1,      -- 观测次数（保留兼容，同 observations）
    status TEXT NOT NULL DEFAULT 'active', -- active / recovered / pending_recovery
    observations INTEGER NOT NULL DEFAULT 1,   -- 观测到事故存在的次数
    state_changes INTEGER NOT NULL DEFAULT 1   -- 实质状态变化次数（severity/title/detail）
);
CREATE INDEX IF NOT EXISTS idx_incidents_status ON incidents(status, last_seen);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""

# 平滑迁移：v1.0.0 已存在的 telemetry.db 缺 observations/state_changes 列
_MIGRATIONS = [
    "ALTER TABLE incidents ADD COLUMN observations INTEGER NOT NULL DEFAULT 1",
    "ALTER TABLE incidents ADD COLUMN state_changes INTEGER NOT NULL DEFAULT 1",
]

METRIC_RETENTION_DAYS = 30
INCIDENT_RETENTION_DAYS = 90
MAINTENANCE_INTERVAL_S = 24 * 3600  # 每天最多一次


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
                # 平滑迁移旧库（列已存在时忽略）
                for sql in _MIGRATIONS:
                    try:
                        conn.execute(sql)
                    except Exception:
                        pass
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
        """upsert 事故观测。

        count/observations：每次观测 +1（注意：这是“观测次数”，不是真实
        “事故触发次数”——触发语义请用 state_changes / severity 变化，
        由告警脚本与 UI 依据 state_changes 判定恶化）。
        state_changes：仅当 severity/title/detail 发生实质变化时 +1。
        """
        now = now or int(time.time())
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT id, count, status, severity, title, detail FROM incidents WHERE fingerprint=?",
                    (fingerprint,),
                ).fetchone()
                if row:
                    old_sev, old_title, old_detail = row[3], row[4], row[5]
                    changed = (old_sev != severity or old_title != title
                               or (old_detail or "") != (detail or ""))
                    conn.execute(
                        "UPDATE incidents SET last_seen=?, count=count+1, "
                        "observations=observations+1, "
                        "state_changes=state_changes+? , "
                        "status='active', severity=?, title=?, detail=? WHERE id=?",
                        (now, 1 if changed else 0, severity, title[:200], detail[:400], row[0]),
                    )
                else:
                    conn.execute(
                        "INSERT INTO incidents(fingerprint, severity, title, detail, first_seen, last_seen, count, status, observations, state_changes)"
                        " VALUES(?,?,?,?,?,?,1,'active',1,1)",
                        (fingerprint, severity, title[:200], detail[:400], now, now),
                    )
        except Exception as exc:
            log.debug("HUD incident write failed: %s", exc)

    def recover_incident(self, fingerprint: str, now: Optional[int] = None) -> None:
        now = now or int(time.time())
        try:
            with self._connect() as conn:
                conn.execute(
                    "UPDATE incidents SET status='recovered', last_seen=? WHERE fingerprint=? AND status IN ('active','pending_recovery')",
                    (now, fingerprint),
                )
        except Exception as exc:
            log.debug("HUD incident recover failed: %s", exc)

    def mark_pending_recovery(self, fingerprint: str, now: Optional[int] = None) -> None:
        """恢复通知尝试中：保持 active 语义但标记 pending_recovery。

        只有当通知渠道确认成功（或主动放弃）后才会被 recover_incident
        置为 recovered —— 禁止“没发出去却标已恢复”。
        """
        now = now or int(time.time())
        try:
            with self._connect() as conn:
                conn.execute(
                    "UPDATE incidents SET status='pending_recovery', last_seen=? "
                    "WHERE fingerprint=? AND status='active'",
                    (now, fingerprint),
                )
        except Exception as exc:
            log.debug("HUD incident pending_recovery failed: %s", exc)

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
        q = ("SELECT id, fingerprint, severity, title, detail, first_seen, last_seen, "
             "count, status, observations, state_changes FROM incidents")
        if active_only:
            q += " WHERE status IN ('active','pending_recovery')"
        q += " ORDER BY last_seen DESC LIMIT ?"
        try:
            with self._connect() as conn:
                rows = conn.execute(q, (limit,)).fetchall()
            return [
                {"id": r[0], "fingerprint": r[1], "severity": r[2], "title": r[3],
                 "detail": r[4], "first_seen": r[5], "last_seen": r[6],
                 "count": r[7], "status": r[8], "observations": r[9],
                 "state_changes": r[10]}
                for r in rows
            ]
        except Exception as exc:
            log.debug("HUD incident read failed: %s", exc)
            return []

    # -- 维护 --------------------------------------------------------------

    def maintenance(self) -> dict:
        """低频维护：每天最多一次执行 prune。

        最近执行时间记录在 meta 表（重启后依然生效），绝不每个 snapshot 都跑。
        """
        now = int(time.time())
        try:
            with self._connect() as conn:
                row = conn.execute("SELECT value FROM meta WHERE key='last_prune'").fetchone()
            last = int(row[0]) if row and row[0] else 0
            if last and now - last < MAINTENANCE_INTERVAL_S:
                return {"pruned": False, "next_in_s": int(MAINTENANCE_INTERVAL_S - (now - last))}
            result = self.prune()
            try:
                with self._connect() as conn:
                    conn.execute(
                        "INSERT OR REPLACE INTO meta(key, value) VALUES('last_prune', ?)",
                        (str(now),),
                    )
            except Exception as exc:
                log.debug("HUD maintenance meta write failed: %s", exc)
            result["pruned"] = True
            result["last_prune"] = now
            return result
        except Exception as exc:
            log.debug("HUD maintenance failed: %s", exc)
            return {"error": str(exc)}

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
