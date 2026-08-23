#!/usr/bin/env python3
"""§七 性能验收（隔离环境，不碰真实数据/网络）。

模拟：
  A. 1 REST 客户端 + 1 WebSocket 客户端，每 2 秒请求一次快照，连续 10 分钟。
  B. 3 个页面并发（3 客户端各 2 秒间隔）60 秒，验证 telemetry 写入不倍增。

统计：snapshot 请求数 / 实际 collector 次数 / telemetry 写入周期 / DB rows 增量。

用法：python3 tests/performance_verify.py [--seconds 600]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "dashboard"))
sys.path.insert(0, str(ROOT))

from dashboard import plugin_api  # noqa: E402
from dashboard.hud import storage  # noqa: E402

# 隔离 telemetry（绝不碰真实 ~/.hermes/hud）
_tmp = Path(tempfile.mkdtemp(prefix="hud-perf-"))
plugin_api.store = storage.TelemetryStore(db_path=_tmp / "telemetry.db")

collector_calls = {"n": 0}
telemetry_writes = {"n": 0}


def _fake_build_snapshot() -> dict:
    """mock collectors：每次调用计数，返回 rules 可评估的最小快照。"""
    collector_calls["n"] += 1
    now = time.time()
    return {
        "collected_at": now,
        "generated_at_iso": "2026-08-23T00:00:00",
        "tz": "UTC",
        "gateway": {"error": None, "pid": 1, "alive": True, "state": "running",
                    "start_time": now - 100, "updated_at": now - 5,
                    "active_agents": 0, "code_version": "v", "heartbeat_age": 5,
                    "platforms": {"telegram": {"state": "connected",
                                               "heartbeat_age": 5}}},
        "system": {"error": None, "cpu_percent": 5.0, "load_avg": [1, 1, 1],
                   "memory": {"percent": 20.0, "used": 1, "total": 8},
                   "disk_free_percent": 60.0},
        "db": {"error": None, "db_size_bytes": 100, "wal_bytes": 10,
               "today_sessions": {"input_tokens": 10, "estimated_cost_usd": 0.01,
                                  "aux_est_cost": 0.0, "aux_actual_cost": 0.0}},
        "active_sessions": [{"id": "s1", "idle_seconds": 1, "running_seconds": 1}],
        "cron": {"error": None, "jobs": [], "summary": {}},
        "executions": {"error": None, "executions": [], "summary": {}},
        "logs": {"error": None, "files": {}},
        "errors": {"error": None, "count_30m": 0, "incidents": []},
        "memory": {"error": None, "mem_used": 1, "mem_total": 8},
        "launchd": {"error": None, "managed": True, "status": "managed"},
        "dashboard": {"error": None, "procs": []},
    }


def _fake_evaluate(snap: dict) -> dict:
    return {"overall": "normal",
            "counts": {"critical": 0, "warning": 0, "normal": 5},
            "checks": [], "incidents": [], "evaluated_at": time.time()}


plugin_api.collectors.build_snapshot = _fake_build_snapshot
plugin_api.rules.evaluate_snapshot = _fake_evaluate

_orig_batch = plugin_api.store.record_metrics_batch


def _counting_batch(kind, items):
    telemetry_writes["n"] += 1
    return _orig_batch(kind, items)


plugin_api.store.record_metrics_batch = _counting_batch


async def _client(name: str, duration: float) -> int:
    """模拟一个客户端：每 2 秒请求一次快照。"""
    n = 0
    end = time.time() + duration
    while time.time() < end:
        await plugin_api._get_snapshot()
        n += 1
        await asyncio.sleep(2)
    return n


def _rows() -> int:
    return plugin_api.store.stats()["metrics_rows"]


async def run_10min(duration: float) -> dict:
    rows_before = _rows()
    rest_n, ws_n = await asyncio.gather(
        _client("REST", duration), _client("WS", duration))
    return {
        "scenario": "1 REST + 1 WS",
        "duration_s": int(duration),
        "rest_requests": rest_n,
        "ws_requests": ws_n,
        "total_requests": rest_n + ws_n,
        "actual_collector_runs": collector_calls["n"],
        "telemetry_write_cycles": telemetry_writes["n"],
        "db_rows_before": rows_before,
        "db_rows_after": _rows(),
        "db_rows_delta": _rows() - rows_before,
    }


async def run_3pages(duration: float) -> dict:
    collector_calls["n"] = 0
    telemetry_writes["n"] = 0
    rows_before = _rows()
    n1, n2, n3 = await asyncio.gather(
        _client("p1", duration), _client("p2", duration), _client("p3", duration))
    return {
        "scenario": "3 pages concurrent",
        "duration_s": int(duration),
        "requests": [n1, n2, n3],
        "actual_collector_runs": collector_calls["n"],
        "telemetry_write_cycles": telemetry_writes["n"],
        "db_rows_delta": _rows() - rows_before,
    }


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=int, default=600)
    ap.add_argument("--pages-seconds", type=int, default=60)
    args = ap.parse_args()

    r10 = await run_10min(args.seconds)
    print("=== 10min result ===")
    print(json.dumps(r10, ensure_ascii=False, indent=1))

    # 3 页面并发
    # 先清 telemetry 限频计时器，保证并发段重新开始计数
    plugin_api._last_telemetry_ts = 0.0
    r3 = await run_3pages(args.pages_seconds)
    print("=== 3pages result ===")
    print(json.dumps(r3, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    asyncio.run(main())
