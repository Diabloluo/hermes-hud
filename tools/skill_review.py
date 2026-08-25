#!/usr/bin/env python3
"""skill-review — Hermes Skill 上线审核门 v1（只读审核，不自动修改）。

用法：
  skill-review review <skill-key>
  skill-review refresh   # 提示先运行 skill_registry scan

数据来源：~/.hermes/skill-registry/registry.json + ~/.hermes/skills/<...> 实际文件。
Registry 缺失或过期（>24h）→ BLOCK（不允许静默使用陈旧数据）。
决策：APPROVE / APPROVE WITH WARNINGS / BLOCK（机械规则，见 decision_engine）。
审计：写入 Job Ledger（~/.hermes/job-ledger/jobs.jsonl，只记事实不记敏感内容）；
ledger 失败不阻断审核，仅在报告标注。
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HOME = Path.home()
REGISTRY_PATH = HOME / ".hermes" / "skill-registry" / "registry.json"
SKILLS_ROOT = HOME / ".hermes" / "skills"
LEDGER = HOME / ".hermes" / "skills" / "job-ledger" / "scripts" / "ledger.py"
REVIEWER_VERSION = "v1"
STALE_AFTER_HOURS = 24

_DIMENSIONS = ["Provenance", "Metadata", "Trigger", "Dependencies",
               "Security", "Risk", "Tests", "Side Effects"]

# ---------- 输入 ----------

def load_registry() -> tuple[dict | None, str | None]:
    """返回 (registry, error)。缺失/损坏 → (None, reason)。"""
    if not REGISTRY_PATH.exists():
        return None, "registry 缺失"
    try:
        data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return None, f"registry 损坏（JSON 解析失败: {exc}）"
    if not isinstance(data, dict) or "skills" not in data:
        return None, "registry 结构异常（缺 skills 数组）"
    gen = data.get("generated_at", "")
    try:
        ts = datetime.fromisoformat(gen)
        age_h = (datetime.now(timezone.utc) - ts).total_seconds() / 3600
    except (ValueError, TypeError):
        age_h = None
    if age_h is not None and age_h > STALE_AFTER_HOURS:
        data["_stale"] = True
        data["_stale_age_h"] = round(age_h, 1)
    else:
        data["_stale"] = False
    return data, None


def find_skill_dir(key: str) -> Path | None:
    for md in SKILLS_ROOT.rglob("SKILL.md"):
        if md.parent.name == key:
            return md.parent
    return None


# ---------- 各维度 ----------

def _verdict(status: str, note: str = "") -> dict:
    return {"status": status, "note": note}


def review_provenance(rec: dict, skill_dir: Path) -> dict:
    source = rec.get("source", "unknown")
    conf = rec.get("source_confidence", "unknown")
    # fingerprint 异常：registry 记录的与当前重算不一致 → FAIL
    import importlib.util
    spec = importlib.util.spec_from_file_location("sr", str(Path(__file__).parent / "skill_registry.py"))
    assert spec is not None and spec.loader is not None
    sr = importlib.util.module_from_spec(spec)
    sys.modules["sr_prov"] = sr
    spec.loader.exec_module(sr)
    current_fp = sr.fingerprint_skill(skill_dir)
    stored_fp = rec.get("fingerprint", "")
    if stored_fp and current_fp != stored_fp:
        return _verdict("FAIL", f"fingerprint 不匹配（registry {stored_fp[:12]}… vs 当前 {current_fp[:12]}…）")
    if source in ("bundled", "bundled-copy") and conf == "confirmed":
        return _verdict("PASS", f"{source}/{conf}")
    if source == "custom-derived" and conf == "inferred":
        return _verdict("WARN", f"{source}/{conf}（本地修改过 bundled 副本）")
    if source == "third_party":
        return _verdict("WARN", "third_party 来源需人工确认")
    return _verdict("WARN", f"{source}/{conf}（来源证据不足）")


def review_metadata(rec: dict, skill_dir: Path) -> dict:
    md = skill_dir / "SKILL.md"
    if not md.exists():
        return _verdict("FAIL", "SKILL.md 缺失")
    fm = rec.get("frontmatter") or {}
    critical = []
    for k in ("name", "description"):
        if not fm.get(k):
            critical.append(k)
    if critical:
        return _verdict("FAIL", f"关键字段缺失: {', '.join(critical)}")
    optional = [k for k in ("version", "author", "license", "platforms") if not fm.get(k)]
    if optional:
        return _verdict("WARN", f"可选元数据缺失: {', '.join(optional)}")
    return _verdict("PASS", "元数据完整")


def review_trigger(rec: dict) -> dict:
    q = rec.get("trigger_quality", "ambiguous")
    if q == "good":
        return _verdict("PASS", "trigger 明确")
    if q == "overlapping":
        return _verdict("FAIL", "trigger 与已有 skill 高度重叠")
    return _verdict("WARN", f"trigger {q}（启发式，不单独 BLOCK）")


def review_dependencies(rec: dict, skill_dir: Path) -> dict:
    issues = []
    for w in rec.get("warnings", []) or []:
        if "脚本引用不存在" in w:
            issues.append(w)
    if issues:
        return _verdict("FAIL", "; ".join(issues))
    # scripts/*.py 的 import 检查（明显缺失 → FAIL）
    py_scripts = [p for p in skill_dir.rglob("*.py") if "__pycache__" not in p.parts]
    missing_imports = []
    for py in py_scripts:
        try:
            tree = ast.parse(py.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue  # 语法问题由 test gate 管
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    missing_imports.append(a.name)
            elif isinstance(node, ast.ImportFrom) and node.module:
                missing_imports.append(node.module)
    unimportable = []
    for mod in dict.fromkeys(missing_imports):
        base_mod = mod.split(".")[0]
        if base_mod in sys.stdlib_module_names:
            continue
        # 同目录/scripts 本地模块（如 test_x.py 里 import x）
        if (skill_dir / f"{base_mod}.py").exists() or (skill_dir / "scripts" / f"{base_mod}.py").exists():
            continue
        if importlib_available(base_mod):
            continue
        unimportable.append(mod)
    if unimportable:
        return _verdict("FAIL", f"Python 依赖缺失: {', '.join(unimportable)}")
    return _verdict("PASS", "依赖完整")


def importlib_available(mod: str) -> bool:
    import importlib.util
    return importlib.util.find_spec(mod) is not None


def review_security(rec: dict) -> dict:
    sf = rec.get("security_findings") or {}
    secret_like = sf.get("secret_like", 0)
    if secret_like:
        return _verdict("FAIL", f"疑似明文凭据（{secret_like} 处）")
    dangerous = sf.get("dangerous_shell", []) or []
    sensitive = sf.get("sensitive_path", []) or []
    if dangerous or sensitive:
        return _verdict("WARN", f"危险模式: {dangerous or 'sensitive_path'}（需人工确认边界）")
    return _verdict("PASS", "无安全发现")


def review_risk(rec: dict) -> dict:
    return _verdict(rec.get("risk_level", "low"), "registry risk_level")


def review_tests(rec: dict) -> dict:
    has = rec.get("has_tests", False)
    syn = rec.get("test_syntax_ok")
    executed = rec.get("tests_executed", False)
    passed = rec.get("tests_passed", "unavailable")
    risk = rec.get("risk_level", "low")
    if syn is False:
        return _verdict("FAIL", "测试语法损坏")
    if executed and passed != "unavailable" and passed is not True:
        return _verdict("FAIL", "已执行测试失败")
    if not has:
        if risk == "high":
            return _verdict("FAIL", "高风险且无测试")
        return _verdict("WARN", "无测试")
    if not executed:
        return _verdict("NOT_AVAILABLE", "有测试但未执行（默认不执行第三方测试）")
    if passed is True:
        return _verdict("PASS", "测试通过")
    return _verdict("NOT_AVAILABLE", f"tests_passed={passed}")


# ---------- Side Effect / Permission 模型 ----------

_SIDE_EFFECT_PATTERNS = {
    "filesystem_read": [r"open\([^)]*['\"]r", r"read_text", r"read_bytes", r"Path\([^)]*\)", r"\bls\b", r"cat "],
    "filesystem_write": [r"open\([^)]*['\"]w", r"write_text", r"write_bytes", r"\bmv\b", r"\bcp\b", r"mkdir", r"unlink", r"os\.remove"],
    "shell_exec": [r"subprocess", r"os\.system", r"Popen", r"\bbash\b", r"`[^`]*`"],
    "network_read": [r"urlopen", r"requests\.(get|head)", r"curl\s+http", r"wget"],
    "network_write": [r"requests\.(post|put|delete|patch)", r"-X\s+(POST|PUT|DELETE)", r"sendMessage"],
    "git_write": [r"git\s+push", r"git\s+commit"],
    "browser_control": [r"remote-debugging-port", r"\bcdp\b", r"osascript", r"chrome", r"browser"],
    "system_config": [r"launchctl", r"defaults\s+write", r"\.plist", r"chmod", r"sudo\s+(launchctl|systemctl)"],
    "credential_access": [r"\.env\b", r"TELEGRAM_BOT_TOKEN", r"api[_-]?key\s*[:=]", r"getenv\(['\"](TOKEN|KEY|SECRET)"],
    "destructive_ops": [r"rm\s+-rf", r"pkill", r"killall", r"delete[^a-z]"],
}


def review_side_effects(skill_dir: Path) -> dict:
    text_parts = []
    for md in skill_dir.rglob("*.md"):
        text_parts.append(md.read_text(encoding="utf-8", errors="replace"))
    for py in skill_dir.rglob("*.py"):
        if "__pycache__" in py.parts:
            continue
        text_parts.append(py.read_text(encoding="utf-8", errors="replace"))
    for sh in skill_dir.rglob("*.sh"):
        text_parts.append(sh.read_text(encoding="utf-8", errors="replace"))
    text = "\n".join(text_parts)

    declared = {}
    for name, pats in _SIDE_EFFECT_PATTERNS.items():
        declared[name] = "yes" if any(re.search(p, text, re.I) for p in pats) else "no"

    # 高风险 side effect 是否在 SKILL.md 中有明确边界/确认机制描述
    high_se = [k for k in ("destructive_ops", "credential_access", "system_config", "git_write")
               if declared.get(k) == "yes"]
    boundary_terms = ["确认", "confirm", "人工", "manual", "approve", "批准", "只读", "read-only",
                      "危险", "danger", "警告", "warn", "不自动", "fail-closed", "dry-run"]
    has_boundary = any(t in text.lower() for t in boundary_terms)
    verdict = _verdict("PASS", f"边界描述: {'有' if has_boundary else '无'}")
    if high_se and not has_boundary:
        verdict = _verdict("FAIL", f"高风险副作用无边界描述: {', '.join(high_se)}")
    elif high_se:
        verdict = _verdict("WARN", f"高风险副作用（有边界描述）: {', '.join(high_se)}")
    verdict["side_effects"] = declared
    return verdict


# ---------- 决策引擎（机械规则） ----------

def decision_engine(dims: dict) -> tuple[str, list[str]]:
    reasons = []
    blocks = []

    if dims["Provenance"]["status"] == "FAIL":
        blocks.append("provenance/fingerprint mismatch")
    if dims["Metadata"]["status"] == "FAIL":
        blocks.append("malformed skill / 关键元数据缺失")
    if dims["Trigger"]["status"] == "FAIL":
        blocks.append("trigger 高度重叠")
    if dims["Dependencies"]["status"] == "FAIL":
        blocks.append("missing core dependency")
    if dims["Security"]["status"] == "FAIL":
        blocks.append("secret leakage")
    if dims["Tests"]["status"] == "FAIL":
        blocks.append("test syntax broken / executed tests failed / high-risk no tests")
    if dims["Side Effects"]["status"] == "FAIL":
        blocks.append("uncontrolled destructive/credential/system/git side effect")

    if blocks:
        return "BLOCK", blocks

    warns = []
    for d in ("Provenance", "Metadata", "Trigger", "Dependencies", "Security", "Tests"):
        if dims[d]["status"] == "WARN":
            warns.append(dims[d]["note"])
    if dims["Side Effects"]["status"] == "WARN":
        warns.append(dims["Side Effects"]["note"])
    if dims["Tests"]["status"] == "NOT_AVAILABLE":
        warns.append("测试未执行")
    if warns:
        return "APPROVE WITH WARNINGS", warns

    return "APPROVE", ["全部维度 PASS"]


# ---------- 报告 ----------

def render_report(key: str, rec: dict, dims: dict, decision: str, reasons: list[str],
                  audit_note: str = "") -> str:
    lines = [
        "🧩 Skill Review",
        "",
        f"Skill: {key}",
        f"Version: {rec.get('version') or '(未声明)'}",
        f"Source: {rec.get('source')}/{rec.get('source_confidence')}",
        f"Fingerprint: {str(rec.get('fingerprint'))[:16]}…",
        "",
        f"Provenance: {dims['Provenance']['status']}",
        f"Metadata: {dims['Metadata']['status']}",
        f"Trigger: {dims['Trigger']['status']}",
        f"Dependencies: {dims['Dependencies']['status']}",
        f"Security: {dims['Security']['status']}",
        f"Risk: {dims['Risk']['status']}",
        f"Tests: {dims['Tests']['status']}",
        f"Side Effects: {dims['Side Effects']['status']}",
        "",
        "Side-effect model:",
    ]
    se = dims["Side Effects"].get("side_effects", {})
    for k, v in se.items():
        lines.append(f"  {k}: {v}")
    lines.append("")
    lines.append("Findings:")
    for d in _DIMENSIONS:
        note = dims[d].get("note", "")
        if dims[d]["status"] != "PASS" or note:
            lines.append(f"- [{d}] {dims[d]['status']}: {note}")
    lines.append("")
    lines.append(f"Decision: {decision}")
    lines.append("")
    lines.append("Required actions:")
    if decision == "APPROVE":
        lines.append("- 无")
    elif decision == "BLOCK":
        for r in reasons:
            lines.append(f"- 阻塞: {r}")
    else:
        for r in reasons:
            lines.append(f"- 处理: {r}")
    if audit_note:
        lines.append("")
        lines.append(f"AUDIT: {audit_note}")
    return "\n".join(lines)


# ---------- Job Ledger 审计 ----------

def write_audit(key: str, fingerprint: str, decision: str, findings_count: int) -> str:
    """写入 Job Ledger；失败返回说明（不阻断审核）。"""
    if not LEDGER.exists():
        return "job-ledger 不可用（ledger.py 缺失），审计未落账"
    job_id = datetime.now().strftime("%Y%m%d-%H%M%S") + f"-SKILL-REVIEW-{key}"
    record = {
        "job_id": job_id,
        "project": "hermes-platform",
        "task": f"SKILL-REVIEW-{key}",
        "objective": f"Skill Review Gate v1 审核 {key}",
        "channel": "local",
        "event": "finished",
        "router": "not_run",
        "guard": "not_run",
        "work_order": "not_run",
        "executed": True,
        "result": "success",
        "read_only": True,
        "skill": key,
        "fingerprint": fingerprint[:16],
        "decision": decision,
        "findings_count": findings_count,
        "reviewer_version": REVIEWER_VERSION,
        "changed_files": [],
        "tests": [],
        "commit_sha": None,
        "pushed": False,
        "released": False,
    }
    try:
        r = subprocess.run([sys.executable, str(LEDGER), "append", "--json",
                            json.dumps(record, ensure_ascii=False)],
                           capture_output=True, text=True, timeout=20)
        if r.returncode == 0:
            return f"已写入 Job Ledger: {job_id}"
        return f"Job Ledger 写入失败(exit {r.returncode}): {r.stderr.strip()[:120]}"
    except Exception as exc:  # noqa: BLE001
        return f"Job Ledger 写入异常: {exc}"


# ---------- 主流程 ----------

def review(key: str) -> int:
    registry, err = load_registry()
    if err:
        print(f"🧩 Skill Review\n\nBLOCK: {err}（先运行 skill_registry scan 刷新）")
        return 1

    recs = {s["key"]: s for s in registry["skills"]}
    if key not in recs:
        print(f"🧩 Skill Review\n\nBLOCK: registry 中无 {key}（先 skill_registry scan）")
        return 1

    rec = recs[key]
    assert rec is not None
    if registry.get("_stale"):
        print(f"🧩 Skill Review\n\nBLOCK: registry 过期（{registry['_stale_age_h']}h > {STALE_AFTER_HOURS}h）"
              f"，先运行 skill_registry scan 刷新")
        return 1

    skill_dir = find_skill_dir(key)
    if skill_dir is None:
        print(f"🧩 Skill Review\n\nBLOCK: 磁盘上找不到 skill 目录 {key}")
        return 1

    dims = {
        "Provenance": review_provenance(rec, skill_dir),
        "Metadata": review_metadata(rec, skill_dir),
        "Trigger": review_trigger(rec),
        "Dependencies": review_dependencies(rec, skill_dir),
        "Security": review_security(rec),
        "Risk": review_risk(rec),
        "Tests": review_tests(rec),
        "Side Effects": review_side_effects(skill_dir),
    }
    decision, reasons = decision_engine(dims)
    findings_count = sum(1 for d in dims.values() if d["status"] in ("WARN", "FAIL", "NOT_AVAILABLE"))
    audit_note = write_audit(key, str(rec.get("fingerprint", "")), decision, findings_count)
    print(render_report(key, rec, dims, decision, reasons, audit_note))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    rp = sub.add_parser("review", help="审核一个 skill")
    rp.add_argument("key")
    rp.add_argument("--refresh-registry", action="store_true",
                    help="允许审核前自动刷新 registry（默认禁止——陈旧数据 BLOCK）")
    args = ap.parse_args()
    if args.cmd == "review":
        if args.refresh_registry:
            print("--refresh-registry 未实现（v1 保守：先手动 skill_registry scan）", file=sys.stderr)
            return 1
        return review(args.key)
    return 0


if __name__ == "__main__":
    sys.exit(main())
