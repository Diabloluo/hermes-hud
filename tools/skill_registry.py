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
import hashlib
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

# ---------- 来源判定（基于路径/元数据/hash，不猜名称） ----------

def _bundled_locations(name: str) -> list[Path]:
    """在 hermes-agent 内置/可选目录中查找同名 skill 目录。"""
    found = []
    for base in (AGENT_SKILLS, AGENT_OPTIONAL):
        if not base.is_dir():
            continue
        for md in base.rglob("SKILL.md"):
            if md.parent.name == name:
                found.append(md.parent)
    return found


# ---------- 全目录 deterministic fingerprint ----------

_FP_EXCLUDE_DIRS = {"__pycache__", "node_modules", ".git"}
_FP_INCLUDE_SUFFIXES = (".py", ".sh", ".js", ".json", ".yaml", ".yml")

_GLOBAL_NAME_INDEX: dict[str, Path] | None = None


def _build_global_name_index() -> dict[str, Path]:
    """~/.hermes/{skills,plugins,scripts} 全文件名索引（跨 skill/插件引用解析）。"""
    global _GLOBAL_NAME_INDEX
    if _GLOBAL_NAME_INDEX is not None:
        return _GLOBAL_NAME_INDEX
    idx: dict[str, Path] = {}
    for base in (HOME / ".hermes" / "skills", HOME / ".hermes" / "plugins",
                 HOME / ".hermes" / "scripts"):
        if base.is_dir():
            for p in base.rglob("*"):
                if p.is_file() and p.suffix in (".py", ".sh"):
                    idx.setdefault(p.name, p)
    _GLOBAL_NAME_INDEX = idx
    return idx


def _collect_fingerprint_files(skill_dir: Path) -> list[tuple[str, bytes]]:
    """按规则收集 fingerprint 输入：路径排序后 (relative_path, content)。

    至少包含：SKILL.md、scripts/**、tests/**、*.py/*.sh/*.js/*.json/*.yaml/*.yml。
    排除：__pycache__、node_modules、.git、.DS_Store、*.pyc、点开头临时文件。
    """
    out: list[tuple[str, bytes]] = []
    for p in sorted(skill_dir.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(skill_dir)
        parts = rel.parts
        if any(part in _FP_EXCLUDE_DIRS for part in parts):
            continue
        if p.name == ".DS_Store" or p.suffix == ".pyc":
            continue
        if p.name.startswith(".") and p.suffix not in _FP_INCLUDE_SUFFIXES:
            continue  # 临时/隐藏文件
        include = (
            rel.name == "SKILL.md"
            or (len(parts) > 1 and parts[0] in ("scripts", "tests"))
            or p.suffix in _FP_INCLUDE_SUFFIXES
        )
        if include:
            out.append((str(rel), p.read_bytes()))
    return out


def fingerprint_skill(skill_dir: Path) -> str:
    """whole-skill SHA-256：relative_path + file_content，路径排序后统一哈希。"""
    h = hashlib.sha256()
    for rel, content in _collect_fingerprint_files(skill_dir):
        h.update(rel.encode("utf-8"))
        h.update(b"\x00")
        h.update(content)
        h.update(b"\x00")
    return h.hexdigest()


def classify_source(skill_dir: Path, frontmatter: dict) -> tuple[str, str]:
    """返回 (source, confidence)。

    规则：
      - 实际路径就在 agent 内置/可选目录内       → bundled / confirmed
      - home 副本与 bundled whole-skill fingerprint 完全一致
                                                  → bundled-copy / confirmed
      - 同名但 fingerprint 不同                  → custom-derived / inferred
      - author/source/repository 明确第三方      → third_party / inferred|confirmed
      - 无可靠证据                               → custom / unknown
    """
    name = skill_dir.name
    # 1) 实际路径在 agent 目录内
    in_agent = False
    for base in (AGENT_SKILLS, AGENT_OPTIONAL):
        if base.is_dir() and base in skill_dir.parents:
            in_agent = True
            break
    if in_agent:
        return "bundled", "confirmed"

    # 2/3) home 副本 vs bundled 同名目录 whole-skill fingerprint 比较
    bundled = _bundled_locations(name)
    if bundled:
        home_fp = fingerprint_skill(skill_dir)
        same = any(fingerprint_skill(b) == home_fp for b in bundled)
        if same:
            return "bundled-copy", "confirmed"
        return "custom-derived", "inferred"

    # 4) 明确第三方来源（author/source/repository 字段）
    author = str(frontmatter.get("author", "") or "")
    source_field = str(frontmatter.get("source", "") or "")
    repo = str(frontmatter.get("repository", "") or "")
    third_party_hints = ("openclaw", "xdevplatform", "github.com/", "upstream",
                         "third-party", "community")
    if any(h in (author + source_field + repo).lower() for h in third_party_hints):
        conf = "confirmed" if repo else "inferred"
        return "third_party", conf

    # 5) 无可靠证据
    return "custom", "unknown"


# ---------- 递归脱敏（registry 只存布尔/结构，绝不存 credential 值） ----------

_SENSITIVE_KEY_RE = re.compile(
    r"(token|secret|password|passwd|api[_-]?key|apikey|authorization|cookie|"
    r"credential|private[_-]?key|client[_-]?secret)", re.IGNORECASE)


def sanitize_value(v):
    """递归脱敏：敏感键的值统一替换为 [REDACTED]。"""
    if isinstance(v, dict):
        return {k: ("[REDACTED]" if _SENSITIVE_KEY_RE.search(k) else sanitize_value(val))
                for k, val in v.items()}
    if isinstance(v, list):
        return [sanitize_value(i) for i in v]
    return v


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
    """对单个 skill 执行健康检查（metadata/references/dependency/test syntax）。

    Health 只表达 metadata 完整度、引用完整性、依赖完整性、测试语法；
    Risk（low/medium/high）与 Security findings（dangerous_shell/sensitive_path/
    secret_like）独立成字段，不参与 Health 计算。
    """
    key = skill_dir.name
    md = skill_dir / "SKILL.md"
    base = {"key": key, "path": str(skill_dir), "health": "PASS",
            "warnings": [], "fails": [],
            "security_findings": {"dangerous_shell": [], "sensitive_path": [],
                                  "secret_like": 0},
            "risk_level": "low"}

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
        # frontmatter 先递归脱敏再进入 registry（绝不存 credential 值）
        base["frontmatter"] = sanitize_value(fm)
        desc = str(fm.get("description", "") or "")
        ver = str(fm.get("version", "") or "")
        author = str(fm.get("author", "") or "")
        lic = str(fm.get("license", "") or "")
        plat = str(fm.get("platforms", "") or "")
        if not desc:
            base["health"] = "FAIL"; base["fails"].append("description 缺失（无 trigger）")
        elif not re.search(r"use\s+(when|before|for|to)\b", desc.lower()):
            base["warnings"].append("description 缺少 'Use when' trigger 表述")
        if not ver:
            base["warnings"].append("version 缺失")
        if not author:
            base["warnings"].append("author 缺失")
        if not lic:
            base["warnings"].append("license 缺失")
        if not plat:
            base["warnings"].append("platforms 未声明")
        base["version"] = ver or ""
        base["author"] = author or ""
        base["license"] = lic or ""
        base["platforms"] = plat or ""
        base["trigger_quality"] = _trigger_quality(desc, key)
        base["trigger_quality_heuristic"] = True  # 仅启发式，不作 FAIL 条件

    # 8. scripts 引用存在（跳过全局/绝对路径与省略号写法）
    scripts_refs = re.findall(r"(?:scripts/|`scripts/)?([\w./-]+\.(?:py|sh))", text)
    global_index = _build_global_name_index()
    for ref in dict.fromkeys(scripts_refs):
        if ref.startswith(("/", "~", "...")) or ref.startswith(".."):
            continue  # 全局/绝对路径、省略号、上级目录引用——不属于 skill 本地脚本
        # 检查链：skill 根 → scripts/ → ~/.hermes/scripts/ → 全局索引（跨 skill/插件）
        basename = ref.split("/")[-1]
        candidates = [skill_dir / ref, skill_dir / "scripts" / basename,
                      HOME / ".hermes" / "scripts" / basename]
        if any(c.exists() for c in candidates) or basename in global_index:
            continue
        if "/" in ref:
            continue  # 带路径引用（外部/跨项目）——不判 skill 缺脚本
        base["warnings"].append(f"脚本引用不存在: {ref}")

    # 10/11. 测试语义：has_tests / test_syntax_ok / tests_executed / tests_passed
    test_files = sorted((skill_dir / "tests").glob("test_*.py")) if (skill_dir / "tests").is_dir() else []
    test_files += sorted(skill_dir.glob("test_*.py"))
    base["has_tests"] = bool(test_files)
    base["tests_executed"] = False  # 默认禁止执行第三方测试（副作用防护）
    base["tests_passed"] = "unavailable"
    if test_files:
        bad = []
        for tf in test_files:
            r = subprocess.run([sys.executable, "-m", "py_compile", str(tf)],
                               capture_output=True, text=True)
            if r.returncode != 0:
                bad.append(tf.name)
        base["test_syntax_ok"] = not bad
        if bad:
            base["warnings"].append(f"测试语法不可编译: {', '.join(bad)}")
    else:
        base["test_syntax_ok"] = None
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

    # 13-15. Security findings（独立字段，不参与 Health）
    dangerous = _scan_text(text, _DANGEROUS_PATTERNS)
    sensitive = _scan_text(text, _SENSITIVE_DIRS)
    secret_hits = _scan_text(text, _SECRET_PATTERNS)
    base["security_findings"]["dangerous_shell"] = dangerous
    base["security_findings"]["sensitive_path"] = sensitive
    base["security_findings"]["secret_like"] = len(secret_hits)  # 只记数量，不存值

    # 风险分级（独立）
    base["risk_level"] = classify_risk(text, dangerous, sensitive, secret_hits)

    # Health 汇总（仅 metadata/references/dependency/test syntax）
    if base["fails"]:
        base["health"] = "FAIL"
    elif len(base["warnings"]) > 2:
        base["health"] = "WARN"
    return base


def classify_risk(text: str, dangerous: list, sensitive: list, secret_hits: list) -> str:
    high = _scan_text(text, _HIGH_RISK_PATTERNS)
    med = _scan_text(text, _MEDIUM_RISK_PATTERNS)
    if high or dangerous or secret_hits:
        return "high"
    if med or sensitive:
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
        src, conf = classify_source(d, fm)
        rec["source"] = src
        rec["source_confidence"] = conf
        rec["fingerprint"] = fingerprint_skill(d)
        rec["name"] = str(fm.get("name", d.name))
        rec["enabled"] = True  # Hermes 无 per-skill 禁用机制
        rec["last_modified"] = datetime.fromtimestamp(
            md.stat().st_mtime, tz=timezone.utc).isoformat()
        rec["usage"] = {"available": False, "reason": "无可靠调用记录数据源"}
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
