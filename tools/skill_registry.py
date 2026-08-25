#!/usr/bin/env python3
"""skill-registry — Hermes Skill 资产台账与健康检查（只读）。

扫描 ~/.hermes/skills/ 下全部 SKILL.md，生成 registry.json 并支持查询。
纯 Python 标准库；绝不修改被扫描的 skill（只读打开）。

用法：
  skill-registry scan                 # 生成 ~/.hermes/skill-registry/registry.json
  skill-registry list                 # 全部技能（key/source/health/risk）
  skill-registry health               # 仅异常（WARN/FAIL）
  skill-registry risky                # 高风险技能
  skill-registry untested             # 无测试的技能
  skill-registry show <key>           # 单个技能详情
  skill-registry attention            # Top 10 需关注
  skill-registry summary              # 平台主管视图汇总
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HOME = Path.home()
SKILLS_ROOT = HOME / ".hermes" / "skills"
AGENT_SKILLS = HOME / ".hermes" / "hermes-agent" / "skills"
AGENT_OPTIONAL = HOME / ".hermes" / "hermes-agent" / "optional-skills"
REGISTRY_DIR = HOME / ".hermes" / "skill-registry"
REGISTRY_PATH = REGISTRY_DIR / "registry.json"

# ---------- 来源判定（基于路径/元数据，不猜名称） ----------

def classify_source(skill_dir: Path, frontmatter: dict) -> str:
    """official/bundled/custom/third_party/unknown。

    判定链（按事实依据）：
      1. hermes-agent/skills 下存在同名 → bundled（官方内置）
      2. hermes-agent/optional-skills 下存在 → bundled（官方可选）
      3. frontmatter author 含第三方来源特征 → third_party
      4. 其余 home 内 skill → custom
    """
    rel = skill_dir.relative_to(SKILLS_ROOT) if SKILLS_ROOT in skill_dir.parents else None
    if rel is not None:
        # 去掉分类层，找 skill 名
        name = rel.parts[-1]
        cat = rel.parts[0] if len(rel.parts) > 1 else ""
        if (AGENT_SKILLS / name).is_dir() or (AGENT_SKILLS / cat / name).is_dir():
            return "bundled"
        if (AGENT_OPTIONAL / name).is_dir() or (AGENT_OPTIONAL / cat / name).is_dir():
            return "bundled"
    author = str(frontmatter.get("author", "") or "")
    # 第三方特征：author 含非用户/非 Nous 的多方署名或明确上游仓库
    third_party_hints = ("openclaw", "xdevplatform", "github.com/", "upstream",
                         "third-party", "community")
    if any(h in author.lower() for h in third_party_hints):
        return "third_party"
    # 其余（含 home 内无作者署名）→ 本地自建
    return "custom"


# ---------- 危险/风险模式 ----------

_DANGEROUS_PATTERNS = [
    r"killall\s+chrome",
    r"pkill\s+-f",
    r"rm\s+-rf\s+/\s*[^a-zA-Z]?",
    r"curl[^\n]*\|[^\n]*bash",
    r"\bsudo\s+",
    r"git\s+push\s+--force",
    r">\s*/etc/",
    r"chmod\s+777",
]

_SENSITIVE_DIRS = [
    r"~?/\.ssh",
    r"~?/\.aws",
    r"/etc/shadow",
    r"/etc/passwd",
    r"\.env\b",
    r"keychain",
    r"\.hermes/\.env",
]

_SECRET_PATTERNS = [
    r"\b(token|api[_-]?key|secret|password|passwd|client[_-]?secret)\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{8,}",
    r"\bsk-[A-Za-z0-9_-]{16,}",
    r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----",
    r"ghp_[A-Za-z0-9]{20,}",
]

_HIGH_RISK_PATTERNS = [
    r"git\s+push",
    r"os\.remove|unlink\(|rm\s+-rf",
    r"launchctl\s+(bootstrap|kickstart)",
    r"open\s+-a|osascript",
    r"--remote-debugging-port|cdp",
    r"subprocess.*shell=True",
    r"requests\.(post|put|delete)|urlopen.*POST",
    r"send_message|\.send\(",
]

_MEDIUM_RISK_PATTERNS = [
    r"subprocess|Popen|os\.system|run\(.*shell",
    r"urlopen|requests\.|http://|https://",
    r"open\(.*['\"]w['\"]|write_text|write_bytes",
    r"\bsed\s+-i|find\s+.*-delete",
]


def _scan_text(text: str, patterns: list[str]) -> list[str]:
    return [p for p in patterns if re.search(p, text, re.IGNORECASE | re.MULTILINE)]


# ---------- 健康检查 ----------

def parse_frontmatter(text: str) -> tuple[dict | None, str | None]:
    """解析 SKILL.md frontmatter；失败返回 (None, 原因)。

    优先用 PyYAML（Hermes venv 自带），不可用时回退到最小行解析器
    （覆盖简单 key: value 与多行块标量）。
    """
    if not text.startswith("---"):
        return None, "缺少 frontmatter 起始 ---"
    end = text.find("\n---", 3)
    if end == -1:
        return None, "frontmatter 未闭合（缺第二个 ---）"
    fm_text = text[3:end]
    try:
        import yaml  # type: ignore
        data = yaml.safe_load(fm_text)
        if isinstance(data, dict):
            return data, None
        return None, "frontmatter 顶层不是映射"
    except Exception:
        pass  # 回退到最小解析器
    try:
        data: dict = {}
        lines = fm_text.splitlines()
        i = 0
        while i < len(lines):
            line = lines[i]
            if not line.strip() or line.strip().startswith("#"):
                i += 1
                continue
            m = re.match(r"^([A-Za-z0-9_.-]+):\s*(.*)$", line)
            if not m:
                return None, f"frontmatter 行无法解析: {line[:40]}"
            key, val = m.group(1), m.group(2).strip()
            if val in ("|", ">"):
                # 多行块标量：收集后续缩进行
                block = []
                i += 1
                while i < len(lines) and (lines[i].startswith(" ") or lines[i].startswith("\t")):
                    block.append(lines[i].strip())
                    i += 1
                data[key] = "\n".join(block)
                continue
            if val.startswith('"') and val.endswith('"'):
                val = val[1:-1]
            elif val.startswith("'") and val.endswith("'"):
                val = val[1:-1]
            data[key] = val
            i += 1
        return data, None
    except Exception as exc:  # noqa: BLE001
        return None, f"frontmatter 解析失败: {exc}"


def check_skill(skill_dir: Path) -> dict:
    """对单个 skill 执行 15 项健康检查 + 风险 + trigger 质量。"""
    key = skill_dir.name
    md = skill_dir / "SKILL.md"
    base = {"key": key, "path": str(skill_dir), "health": "PASS", "warnings": [], "fails": []}

    if not md.exists():
        base["health"] = "FAIL"
        base["fails"].append("SKILL.md 不存在")
        return base

    text = md.read_text(encoding="utf-8", errors="replace")
    fm, fm_err = parse_frontmatter(text)
    if fm is None:
        base["health"] = "FAIL"
        base["fails"].append(fm_err or "frontmatter 解析失败")
    else:
        base["frontmatter"] = {k: fm[k] for k in fm if k.lower() not in ("token", "secret")}
        # 2. frontmatter 完整
        desc = str(fm.get("description", "") or "")
        ver = str(fm.get("version", "") or "")
        author = str(fm.get("author", "") or "")
        lic = str(fm.get("license", "") or "")
        plat = str(fm.get("platforms", "") or "")
        # 3. trigger/description
        if not desc:
            base["health"] = "FAIL"; base["fails"].append("description 缺失（无 trigger）")
        elif "use when" not in desc.lower():
            base["warnings"].append("description 缺少 'Use when' trigger 表述")
        # 5. version
        if not ver:
            base["warnings"].append("version 缺失")
        # 6. author/license
        if not author:
            base["warnings"].append("author 缺失")
        if not lic:
            base["warnings"].append("license 缺失")
        # 7. platforms
        if not plat:
            base["warnings"].append("platforms 未声明")
        base["version"] = ver or ""
        base["author"] = author or ""
        base["license"] = lic or ""
        base["platforms"] = plat or ""
        base["trigger_quality"] = _trigger_quality(desc, key)

    # 8. scripts 引用存在
    scripts_refs = re.findall(r"(?:scripts/|`scripts/)?([\w./-]+\.(?:py|sh))", text)
    for ref in dict.fromkeys(scripts_refs):
        candidate = skill_dir / ref
        if not candidate.exists() and not (skill_dir / ref.split("/")[-1]).exists():
            base["warnings"].append(f"脚本引用不存在: {ref}")

    # 10/11. 测试存在 + 语法可编译
    test_files = sorted((skill_dir / "tests").glob("test_*.py")) if (skill_dir / "tests").is_dir() else []
    test_files += sorted(skill_dir.glob("test_*.py"))
    base["has_tests"] = bool(test_files)
    if test_files:
        bad = []
        for tf in test_files:
            r = subprocess.run([sys.executable, "-m", "py_compile", str(tf)],
                               capture_output=True, text=True)
            if r.returncode != 0:
                bad.append(tf.name)
        if bad:
            base["warnings"].append(f"测试语法不可编译: {', '.join(bad)}")
    else:
        base["warnings"].append("无测试")

    # 12. 引用不存在路径（正文中明显的本地路径引用）
    for m in re.finditer(r"(?:`)?(?:~|\.\.?)/([\w./\-]+)", text):
        p = m.group(0).strip("`")
        if p.startswith("~"):
            candidate = HOME / p[2:]
        else:
            candidate = skill_dir / p
        if not candidate.exists():
            base["warnings"].append(f"引用路径不存在: {p}")
            break  # 每条 warning 只记一次

    # 13. 危险 shell 模式
    dangerous = _scan_text(text, _DANGEROUS_PATTERNS)
    if dangerous:
        base["warnings"].append(f"危险 shell 模式: {', '.join(dangerous)}")

    # 14. 敏感目录读取
    sensitive = _scan_text(text, _SENSITIVE_DIRS)
    if sensitive:
        base["warnings"].append(f"涉及敏感路径: {', '.join(sensitive)}")

    # 15. 明文凭据迹象
    secret_hits = _scan_text(text, _SECRET_PATTERNS)
    base["has_secret_like"] = bool(secret_hits)  # 只记布尔，不存值
    if secret_hits:
        base["warnings"].append(f"明文凭据迹象（{len(secret_hits)} 处，不保留内容）")

    # 风险分级
    base["risk_level"] = classify_risk(text, base["warnings"])

    # 汇总 health
    if base["fails"]:
        base["health"] = "FAIL"
    elif len(base["warnings"]) > 2:
        base["health"] = "WARN"
    return base


def classify_risk(text: str, warnings: list[str]) -> str:
    high = _scan_text(text, _HIGH_RISK_PATTERNS)
    med = _scan_text(text, _MEDIUM_RISK_PATTERNS)
    if high:
        return "high"
    if med or any("敏感路径" in w or "凭据迹象" in w for w in warnings):
        return "medium"
    return "low"


def _trigger_quality(desc: str, key: str) -> str:
    if not desc:
        return "ambiguous"
    # Hermes 触发规范：Use when / Use before / Use for / Use to 均为合法变体
    if not re.search(r"use\s+(when|before|for|to)\b", desc.lower()):
        return "ambiguous"
    trigger_part = re.split(r"use\s+(when|before|for|to)\b", desc, flags=re.IGNORECASE)[-1]
    if len(trigger_part.strip()) < 12:
        return "broad"
    broad_terms = ("any", "everything", "all tasks", "general", "whenever", "anything")
    if any(t in trigger_part.lower() for t in broad_terms):
        return "broad"
    if key.lower() in ("helper", "utils", "common", "misc"):
        return "overlapping"
    return "good"


# ---------- 主流程 ----------

def scan_all() -> list[dict]:
    skills = []
    if not SKILLS_ROOT.is_dir():
        print(f"ERROR: {SKILLS_ROOT} 不存在", file=sys.stderr)
        sys.exit(2)
    for skill_dir in sorted(SKILLS_ROOT.rglob("SKILL.md")):
        d = skill_dir.parent
        # 跳过 __pycache__ / node_modules
        if any(part in ("__pycache__", "node_modules") for part in d.parts):
            continue
        md = skill_dir
        text = md.read_text(encoding="utf-8", errors="replace") if md.exists() else ""
        fm, _ = parse_frontmatter(text)
        fm = fm or {}
        rec = check_skill(d)
        rec["source"] = classify_source(d, fm)
        rec["name"] = str(fm.get("name", d.name))
        rec["enabled"] = True  # Hermes 无 per-skill 禁用机制
        rec["last_modified"] = datetime.fromtimestamp(
            md.stat().st_mtime, tz=timezone.utc).isoformat()
        rec["usage"] = {"available": False, "reason": "无可靠调用记录数据源"}
        rec.pop("warnings", None)
        rec.pop("fails", None)
        rec["warnings"] = None  # 保持结构；详情里才有
        skills.append(rec)
    return skills


def summary(skills: list[dict]) -> dict:
    src = {}
    health = {}
    risk = {}
    for s in skills:
        src[s["source"]] = src.get(s["source"], 0) + 1
        health[s["health"]] = health.get(s["health"], 0) + 1
        risk[s["risk_level"]] = risk.get(s["risk_level"], 0) + 1
    return {
        "total": len(skills),
        "by_source": src,
        "by_health": health,
        "by_risk": risk,
        "no_tests": sum(1 for s in skills if not s.get("has_tests")),
        "no_version": sum(1 for s in skills if not s.get("version")),
        "high_risk": sum(1 for s in skills if s["risk_level"] == "high"),
        "trigger_ambiguous": sum(1 for s in skills if s.get("trigger_quality") in ("ambiguous", "broad")),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("cmd", nargs="?", default="scan",
                    choices=["scan", "list", "health", "risky", "untested",
                             "show", "attention", "summary"])
    ap.add_argument("key", nargs="?", default=None)
    args = ap.parse_args()

    if args.cmd == "scan":
        skills = scan_all()
        REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "skills": skills,
            "summary": summary(skills),
        }
        REGISTRY_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"已生成 {REGISTRY_PATH}（{len(skills)} 个 skill）")
        return 0

    if not REGISTRY_PATH.exists():
        print("registry 不存在，先运行: skill-registry scan", file=sys.stderr)
        return 1
    data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    skills = data["skills"]

    if args.cmd == "list":
        for s in skills:
            print(f"{s['key']:<42} {s['source']:<12} {s['health']:<5} risk={s['risk_level']}")
        return 0
    if args.cmd == "health":
        for s in skills:
            if s["health"] != "PASS":
                print(f"{s['health']:<5} {s['key']:<42} {s['source']}")
        return 0
    if args.cmd == "risky":
        for s in skills:
            if s["risk_level"] == "high":
                print(f"{s['key']:<42} {s['source']:<12} {s['health']}")
        return 0
    if args.cmd == "untested":
        for s in skills:
            if not s.get("has_tests"):
                print(f"{s['key']:<42} {s['source']:<12} {s['health']}")
        return 0
    if args.cmd == "show":
        if not args.key:
            print("用法: skill-registry show <skill-key>", file=sys.stderr)
            return 2
        for s in skills:
            if s["key"] == args.key or args.key in s["key"]:
                print(json.dumps(s, ensure_ascii=False, indent=2))
                return 0
        print(f"未找到: {args.key}", file=sys.stderr)
        return 1
    if args.cmd == "attention":
        ranked = sorted(skills, key=lambda s: (
            0 if s["health"] == "FAIL" else 1 if s["health"] == "WARN" else 2,
            0 if s["risk_level"] == "high" else 1 if s["risk_level"] == "medium" else 2))
        for s in ranked[:10]:
            print(f"{s['health']:<5} risk={s['risk_level']:<6} {s['key']:<42} {s['source']}")
        return 0
    if args.cmd == "summary":
        sm = data.get("summary") or summary(skills)
        print(json.dumps(sm, ensure_ascii=False, indent=2))
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
