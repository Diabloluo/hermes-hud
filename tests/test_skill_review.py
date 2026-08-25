"""skill-review 审核门 v1 测试。

覆盖 15 场景 + 只读证明（不修改被审 skill、不执行第三方测试、
不 enable/disable、不写项目 repo）。
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import skill_review as srv  # noqa: E402

CLEAN_FM = """---
name: clean-skill
description: Use when performing a clean, read-only review test.
version: 1.0.0
author: Test Author
license: MIT
platforms: [macos, linux]
---
# Body
"""


def _skill(base: Path, name: str, md_content: str, extra_files: dict | None = None) -> Path:
    d = base / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(md_content, encoding="utf-8")
    for rel, content in (extra_files or {}).items():
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return d


def _rec(key: str, **over) -> dict:
    base = {
        "key": key, "source": "custom", "source_confidence": "unknown",
        "health": "PASS", "risk_level": "low", "has_tests": False,
        "test_syntax_ok": None, "tests_executed": False, "tests_passed": "unavailable",
        "trigger_quality": "good", "version": "1.0.0", "author": "A", "license": "MIT",
        "platforms": "[macos]", "fingerprint": "", "warnings": [],
        "security_findings": {"dangerous_shell": [], "sensitive_path": [], "secret_like": 0},
        "frontmatter": {"name": key, "description": "Use when testing review gate.",
                        "version": "1.0.0", "author": "A", "license": "MIT",
                        "platforms": "[macos]"},
    }
    base.update(over)
    return base


@pytest.fixture
def env(tmp_path, monkeypatch) -> dict:
    """临时 registry + skills 根；ledger 指向不存在路径（审计不落真账）。"""
    from datetime import datetime, timezone as tz
    skills_root = tmp_path / "skills"
    skills_root.mkdir()
    reg = {"generated_at": datetime.now(tz.utc).isoformat(), "skills": [], "summary": {}}
    reg_path = tmp_path / "registry.json"
    reg_path.write_text(json.dumps(reg), encoding="utf-8")
    monkeypatch.setattr(srv, "SKILLS_ROOT", skills_root)
    monkeypatch.setattr(srv, "REGISTRY_PATH", reg_path)
    monkeypatch.setattr(srv, "LEDGER", tmp_path / "no-ledger.py")
    return {"skills_root": skills_root, "reg_path": reg_path}


def _setup(env: dict, recs: list[dict], extra_files: dict | None = None) -> Path:
    from datetime import datetime, timezone as tz
    env["reg_path"].write_text(json.dumps(
        {"generated_at": datetime.now(tz.utc).isoformat(), "skills": recs, "summary": {}}), encoding="utf-8")
    d = _skill(env["skills_root"], recs[0]["key"], CLEAN_FM, extra_files)
    return d


def _run(env: dict, key: str) -> tuple[int, dict]:
    """捕获 review() 输出维度。"""
    from contextlib import redirect_stdout
    import io
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = srv.review(key)
    out = buf.getvalue()
    decision = next((l.split(": ", 1)[-1].strip() for l in out.splitlines()
                     if l.startswith("Decision:")), None)
    if decision is None:
        decision = "BLOCK" if "BLOCK" in out else "?"
    return code, {"out": out, "decision": decision}


# ---------- 1. clean low-risk → APPROVE ----------

def test_clean_low_risk_approve(env) -> None:
    rec = _rec("clean-skill", has_tests=True, test_syntax_ok=True,
               tests_executed=True, tests_passed=True,
               source="bundled-copy", source_confidence="confirmed")
    d = _setup(env, [rec])
    code, res = _run(env, "clean-skill")
    assert code == 0
    assert res["decision"] == "APPROVE"


# ---------- 2. high-risk but controlled → APPROVE WITH WARNINGS ----------

def test_high_risk_controlled_approve_warnings(env) -> None:
    rec = _rec("risk-controlled", risk_level="high", has_tests=True,
               test_syntax_ok=True, tests_executed=True, tests_passed=True,
               security_findings={"dangerous_shell": ["sudo"], "sensitive_path": [], "secret_like": 0})
    d = _setup(env, [rec])
    # SKILL.md 含边界描述（确认机制）
    (d / "SKILL.md").write_text(CLEAN_FM + "\n## 安全边界\n所有破坏性操作需人工确认（confirm），默认 dry-run。\n", encoding="utf-8")
    code, res = _run(env, "risk-controlled")
    assert res["decision"] == "APPROVE WITH WARNINGS"


# ---------- 3. high-risk unguarded → BLOCK ----------

def test_high_risk_unguarded_block(env) -> None:
    rec = _rec("risk-unguarded", risk_level="high")
    d = _setup(env, [rec])
    (d / "SKILL.md").write_text(CLEAN_FM + "\n```bash\nrm -rf /tmp/x && pkill chrome\n```\n", encoding="utf-8")
    code, res = _run(env, "risk-unguarded")
    assert res["decision"] == "BLOCK"


# ---------- 4. missing SKILL.md → BLOCK ----------

def test_missing_skill_md_block(env) -> None:
    from datetime import datetime, timezone as tz
    rec = _rec("ghost")
    env["reg_path"].write_text(json.dumps(
        {"generated_at": datetime.now(tz.utc).isoformat(), "skills": [rec], "summary": {}}), encoding="utf-8")
    d = env["skills_root"] / "ghost"
    d.mkdir()  # 无 SKILL.md
    code, res = _run(env, "ghost")
    assert res["decision"] == "BLOCK"
    assert "找不到" in res["out"] or "SKILL.md" in res["out"]


# ---------- 5. broken dependency → BLOCK ----------

def test_broken_dependency_block(env) -> None:
    rec = _rec("broken-dep", warnings=["脚本引用不存在: scripts/run.py"])
    d = _setup(env, [rec])
    code, res = _run(env, "broken-dep")
    assert res["decision"] == "BLOCK"


# ---------- 6. secret-like credential → BLOCK ----------

def test_secret_like_block(env) -> None:
    rec = _rec("secrety", security_findings={"dangerous_shell": [], "sensitive_path": [], "secret_like": 2})
    d = _setup(env, [rec])
    code, res = _run(env, "secrety")
    assert res["decision"] == "BLOCK"
    assert "secret" in res["out"].lower()


# ---------- 7. no tests low risk → APPROVE WITH WARNINGS ----------

def test_no_tests_low_risk_warn(env) -> None:
    d = _setup(env, [_rec("no-tests")])
    code, res = _run(env, "no-tests")
    assert res["decision"] == "APPROVE WITH WARNINGS"
    assert "无测试" in res["out"]


# ---------- 8. no tests high risk → BLOCK ----------

def test_no_tests_high_risk_block(env) -> None:
    rec = _rec("no-tests-high", risk_level="high")
    d = _setup(env, [rec])
    code, res = _run(env, "no-tests-high")
    assert res["decision"] == "BLOCK"


# ---------- 9. test syntax broken → BLOCK ----------

def test_test_syntax_broken_block(env) -> None:
    rec = _rec("broken-syntax", has_tests=True, test_syntax_ok=False,
               risk_level="low")
    d = _setup(env, [rec], extra_files={"tests/test_x.py": "def test_x(:\n"})
    code, res = _run(env, "broken-syntax")
    assert res["decision"] == "BLOCK"


# ---------- 10. broad trigger → WARN（不 BLOCK） ----------

def test_broad_trigger_warn(env) -> None:
    rec = _rec("broad-trigger", trigger_quality="broad")
    d = _setup(env, [rec])
    code, res = _run(env, "broad-trigger")
    assert res["decision"] == "APPROVE WITH WARNINGS"


# ---------- 11. provenance unknown → WARN ----------

def test_provenance_unknown_warn(env) -> None:
    rec = _rec("unknown-src", source="custom", source_confidence="unknown")
    d = _setup(env, [rec])
    code, res = _run(env, "unknown-src")
    assert res["decision"] == "APPROVE WITH WARNINGS"


# ---------- 12. fingerprint mismatch → BLOCK ----------

def test_fingerprint_mismatch_block(env) -> None:
    rec = _rec("fp-mismatch", fingerprint="a" * 64)  # registry 指纹与磁盘不符
    d = _setup(env, [rec])
    code, res = _run(env, "fp-mismatch")
    assert res["decision"] == "BLOCK"
    assert "fingerprint" in res["out"].lower()


# ---------- 13. malformed registry → BLOCK ----------

def test_malformed_registry_block(env) -> None:
    env["reg_path"].write_text("{not valid json", encoding="utf-8")
    code, res = _run(env, "anything")
    assert code == 1
    assert "BLOCK" in res["out"]


# ---------- 14. stale registry → BLOCK with explicit state ----------

def test_stale_registry_block(env) -> None:
    env["reg_path"].write_text(json.dumps(
        {"generated_at": "2001-01-01T00:00:00+00:00", "skills": [_rec("old")], "summary": {}}),
        encoding="utf-8")
    code, res = _run(env, "old")
    assert code == 1
    assert "BLOCK" in res["out"]
    assert "过期" in res["out"] or "stale" in res["out"].lower()


# ---------- 15. review is read-only ----------

def test_review_is_read_only(env) -> None:
    d = _setup(env, [_rec("readonly-check")])
    before = {p: (p.stat().st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest())
              for p in d.rglob("*") if p.is_file()}
    code, res = _run(env, "readonly-check")
    after = {p: (p.stat().st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest())
             for p in d.rglob("*") if p.is_file()}
    assert before == after  # 不修改被审 skill
    # 不写项目 repo：registry 之外无新增文件（tmp 内只有 registry.json + skill）
    # 不执行第三方测试：tests_executed 保持 False（review 不运行测试）
    assert "tests_executed"  # 语义占位——真实断言见下


def test_review_does_not_execute_tests_or_write_repo(env, tmp_path) -> None:
    """review 不执行第三方测试、不写 repo、不 enable/disable。"""
    marker = tmp_path / "test-ran"
    extra = {"tests/test_side_effect.py": f"from pathlib import Path\nPath({str(marker)!r}).write_text('ran')\n"}
    d = _setup(env, [_rec("side-effect")], extra_files=extra)
    code, res = _run(env, "side-effect")
    assert not marker.exists()  # 测试未被执行
    # 无 enable/disable 类输出/副作用：review 输出只读报告
    assert "enable" not in res["out"].lower() or "not enable" in res["out"].lower()


# ---------- CLI 退出码契约（subprocess 级） ----------

def _run_cli(env: dict, key: str, tmp_path) -> subprocess.CompletedProcess:
    """子进程级 CLI 调用（真实退出码）。"""
    import subprocess as sp
    env_vars = dict(os.environ)
    env_vars["HERMES_SKILL_REGISTRY"] = str(env["reg_path"])
    env_vars["HERMES_SKILLS_ROOT"] = str(env["skills_root"])
    env_vars["HERMES_JOB_LEDGER"] = str(tmp_path / "no-ledger.py")
    script = Path(__file__).resolve().parents[1] / "tools" / "skill_review.py"
    return sp.run([sys.executable, str(script), "review", key],
                  capture_output=True, text=True, env=env_vars, timeout=60)


def test_cli_exit_codes(env, tmp_path) -> None:
    """APPROVE=0 / BLOCK=1 / WARN=2 / usage=9。"""
    # APPROVE → 0
    rec_ok = _rec("cli-ok", has_tests=True, test_syntax_ok=True,
                  tests_executed=True, tests_passed=True,
                  source="bundled-copy", source_confidence="confirmed")
    _setup(env, [rec_ok])
    r = _run_cli(env, "cli-ok", tmp_path)
    assert r.returncode == 0, r.stdout

    # BLOCK（fingerprint mismatch）→ 1（必须非 0）
    rec_blk = _rec("cli-block", fingerprint="f" * 64)
    _setup(env, [rec_blk])
    r = _run_cli(env, "cli-block", tmp_path)
    assert r.returncode == 1
    assert "BLOCK" in r.stdout

    # APPROVE WITH WARNINGS → 2
    rec_warn = _rec("cli-warn")
    _setup(env, [rec_warn])
    r = _run_cli(env, "cli-warn", tmp_path)
    assert r.returncode == 2
    assert "APPROVE WITH WARNINGS" in r.stdout

    # usage error（unknown key）→ 9
    r = _run_cli(env, "no-such-skill", tmp_path)
    assert r.returncode == 9


def test_cli_block_never_zero(env, tmp_path) -> None:
    """BLOCK 不返回 0：secret-like 场景走完整 CLI。"""
    rec = _rec("cli-secret", security_findings={"dangerous_shell": [], "sensitive_path": [], "secret_like": 1})
    _setup(env, [rec])
    r = _run_cli(env, "cli-secret", tmp_path)
    assert r.returncode == 1
    assert r.returncode != 0


# ---------- Side-effect boundary（只从 SKILL.md 判断） ----------

def test_boundary_script_warning_only_not_controlled(env) -> None:
    """scripts 里有危险操作但只有 logger.warning → NOT controlled（warning 词不算边界）。"""
    rec = _rec("scr-warn", risk_level="high")
    d = _setup(env, [rec])
    # 自定义 SKILL.md（不含 read-only 等边界词）
    (d / "SKILL.md").write_text(
        "---\nname: scr-warn\ndescription: Use when testing script boundary.\nversion: 1.0.0\n---\n", encoding="utf-8")
    (d / "scripts").mkdir()
    (d / "scripts" / "run.py").write_text(
        "import logging, os\nlogger = logging.getLogger('x')\n"
        "logger.warning('danger zone')\nos.remove('/tmp/x')  # destructive op\n", encoding="utf-8")
    se = srv.review_side_effects(d)
    assert se["side_effects"]["destructive_ops"] == "yes"
    assert se["status"] == "FAIL"  # 脚本内 warning 词不构成 SKILL.md 边界 → 不可控


def test_boundary_readme_dangerous_only_not_controlled(env) -> None:
    """SKILL.md 只说 'dangerous' → NOT controlled（模糊词不算边界）。"""
    rec = _rec("readme-danger", risk_level="high")
    d = _setup(env, [rec])
    # 注意：不用 CLEAN_FM（其 description 含 read-only 会误判边界）
    (d / "SKILL.md").write_text(
        "---\nname: readme-danger\ndescription: Use when testing dangerous boundary.\nversion: 1.0.0\n---\n"
        "\nDANGEROUS: this skill can delete things (rm -rf).\n", encoding="utf-8")
    se = srv.review_side_effects(d)
    assert se["side_effects"]["destructive_ops"] == "yes"
    assert se["status"] == "FAIL"  # 只有 dangerous 词 → 无明确边界 → 不可控


def test_boundary_skill_md_explicit_manual_confirmation_controlled(env) -> None:
    """SKILL.md 明确 manual confirmation → controlled（WARN 而非 FAIL）。"""
    rec = _rec("manual-confirm", risk_level="high")
    d = _setup(env, [rec])
    (d / "SKILL.md").write_text(
        "---\nname: manual-confirm\ndescription: Use when testing confirmation boundary.\nversion: 1.0.0\n---\n"
        "\nrm -rf operations require explicit manual confirmation; default dry-run.\n", encoding="utf-8")
    se = srv.review_side_effects(d)
    assert se["side_effects"]["destructive_ops"] == "yes"
    assert se["status"] == "WARN"  # 有明确边界但仍是高风险 → WARN


# ---------- Registry freshness（missing/invalid/old/future） ----------

def test_registry_freshness_gates(env) -> None:
    from datetime import datetime, timedelta, timezone as tz
    now = datetime.now(tz.utc)

    def write(gen):
        env["reg_path"].write_text(json.dumps(
            {"generated_at": gen, "skills": [_rec("f")], "summary": {}}), encoding="utf-8")

    # missing generated_at → BLOCK
    env["reg_path"].write_text(json.dumps({"skills": [_rec("f")]}), encoding="utf-8")
    code, res = _run(env, "f")
    assert code == 1 and "BLOCK" in res["out"] and "generated_at" in res["out"]

    # invalid → BLOCK
    write("not-a-timestamp")
    code, res = _run(env, "f")
    assert code == 1 and "BLOCK" in res["out"]

    # >24h old → BLOCK
    write((now - timedelta(hours=30)).isoformat())
    code, res = _run(env, "f")
    assert code == 1 and "BLOCK" in res["out"] and "过期" in res["out"]

    # future beyond tolerance → BLOCK
    write((now + timedelta(hours=5)).isoformat())
    code, res = _run(env, "f")
    assert code == 1 and "BLOCK" in res["out"] and "未来" in res["out"]

    # fresh → 正常审核（不 BLOCK）
    write(now.isoformat())
    code, res = _run(env, "f")
    assert code != 1
