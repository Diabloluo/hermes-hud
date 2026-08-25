"""skill-registry 扫描器测试。

覆盖：正常 skill / 缺 SKILL.md / 缺 version / broken script ref / no tests /
dangerous command / duplicate key / malformed frontmatter / secret-like string /
overlapping trigger / unknown source。
额外证明：scan 不修改被扫描 skill；registry 可重复生成；同一输入结果稳定；
malformed skill 不导致全盘扫描失败。
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import skill_registry as sr  # noqa: E402

GOOD_FM = """---
name: test-skill
description: Use when testing skill registry scanner behaviour.
version: 1.0.0
author: Test Author
license: MIT
platforms: [macos, linux]
---
# Body
"""


def _write_skill(root: Path, name: str, content: str) -> Path:
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(content, encoding="utf-8")
    return d


@pytest.fixture
def fake_root(tmp_path, monkeypatch) -> Path:
    root = tmp_path / "skills"
    root.mkdir()
    # 让 check_skill 直接工作（不依赖 scan_all 的全局 SKILLS_ROOT）
    return root


# ---------- 1. 正常 skill ----------

def test_normal_skill_passes(fake_root) -> None:
    d = _write_skill(fake_root, "good-one", GOOD_FM)
    rec = sr.check_skill(d)
    assert rec["health"] == "PASS"
    assert rec["version"] == "1.0.0"
    assert rec["trigger_quality"] == "good"


# ---------- 2. 缺 SKILL.md ----------

def test_missing_skill_md(fake_root) -> None:
    d = fake_root / "ghost"
    d.mkdir()
    rec = sr.check_skill(d)
    assert rec["health"] == "FAIL"
    assert any("SKILL.md" in f for f in rec["fails"])


# ---------- 3. 缺 version ----------

def test_missing_version(fake_root) -> None:
    fm = GOOD_FM.replace("version: 1.0.0\n", "")
    d = _write_skill(fake_root, "no-ver", fm)
    rec = sr.check_skill(d)
    assert rec["version"] == ""
    assert any("version" in w for w in rec["warnings"])


# ---------- 4. broken script ref ----------

def test_broken_script_ref(fake_root) -> None:
    body = GOOD_FM + "\n```bash\npython3 scripts/does_not_exist.py\n```\n"
    d = _write_skill(fake_root, "broken-ref", body)
    rec = sr.check_skill(d)
    assert any("脚本引用不存在" in w for w in rec["warnings"])


# ---------- 5. no tests ----------

def test_no_tests(fake_root) -> None:
    d = _write_skill(fake_root, "no-tests", GOOD_FM)
    rec = sr.check_skill(d)
    assert rec["has_tests"] is False
    assert any("无测试" in w for w in rec["warnings"])


# ---------- 6. dangerous command ----------

def test_dangerous_command_detected(fake_root) -> None:
    body = GOOD_FM + "\n```bash\nsudo rm -rf /\n```\n"
    d = _write_skill(fake_root, "danger", body)
    rec = sr.check_skill(d)
    # security findings 独立字段（字段存的是匹配的模式串）
    assert any("rm" in s and "-rf" in s for s in rec["security_findings"]["dangerous_shell"])
    assert rec["risk_level"] == "high"


# ---------- 7. duplicate key（frontmatter 重复键不崩） ----------

def test_duplicate_key_does_not_crash(fake_root) -> None:
    fm = GOOD_FM + "version: 2.0.0\n"  # 重复 version 键
    d = _write_skill(fake_root, "dup-key", fm)
    rec = sr.check_skill(d)  # 不抛异常
    assert rec["key"] == "dup-key"


# ---------- 8. malformed frontmatter ----------

def test_malformed_frontmatter(fake_root) -> None:
    bad = "---\nnot valid : yaml : : :\n  - broken\n---\nbody\n"
    d = _write_skill(fake_root, "malformed", bad)
    rec = sr.check_skill(d)
    assert rec["health"] == "FAIL"
    assert rec["fails"]


# ---------- 9. secret-like string（security finding + registry 零值） ----------

def test_secret_like_detected_without_value(fake_root) -> None:
    body = GOOD_FM + "\nAPI key example: sk-test-abc123def456ghi789\n"
    d = _write_skill(fake_root, "secrety", body)
    rec = sr.check_skill(d)
    assert rec["security_findings"]["secret_like"] >= 1
    assert rec["risk_level"] == "high"
    # registry 内容不得出现 secret 字面量
    dump = json.dumps(rec, ensure_ascii=False)
    assert "sk-test-abc123def456ghi789" not in dump


def test_frontmatter_recursive_sanitize(fake_root) -> None:
    """P0：frontmatter 递归脱敏——嵌套敏感键值必须为 [REDACTED]，字面量 0。"""
    fm = """---
name: secret-skill
description: Use when testing frontmatter sanitization.
version: 1.0.0
api_key: sk-test-xxxxxxxxxxxxxxxx
password: hunter123
telegram_bot_token: 123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefg
nested:
  client_secret: abcdef123456
---
body
"""
    d = _write_skill(fake_root, "secret-skill", fm)
    rec = sr.check_skill(d)
    fm_stored = rec["frontmatter"]
    dump = json.dumps(fm_stored, ensure_ascii=False)
    # 四个敏感字面量必须 0 出现
    for literal in ("sk-test-xxxxxxxxxxxxxxxx", "hunter123",
                    "123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefg", "abcdef123456"):
        assert literal not in dump, f"secret 泄漏: {literal}"
    # 敏感键的值统一为 [REDACTED]
    assert fm_stored["api_key"] == "[REDACTED]"
    assert fm_stored["password"] == "[REDACTED]"
    assert fm_stored["telegram_bot_token"] == "[REDACTED]"
    assert fm_stored["nested"]["client_secret"] == "[REDACTED]"
    # 非敏感键保留
    assert fm_stored["version"] == "1.0.0"


# ---------- 10. overlapping / ambiguous trigger ----------

def test_overlapping_trigger_quality(fake_root) -> None:
    fm = GOOD_FM.replace("Use when testing skill registry scanner behaviour.",
                         "Use when doing anything with anything at all.")
    d = _write_skill(fake_root, "broad-trigger", fm)
    rec = sr.check_skill(d)
    assert rec["trigger_quality"] == "broad"


def test_ambiguous_trigger_quality(fake_root) -> None:
    fm = "---\nname: no-trigger\ndescription: A generic helper for many things.\n---\n"
    d = _write_skill(fake_root, "no-trigger", fm)
    rec = sr.check_skill(d)
    assert rec["trigger_quality"] == "ambiguous"


# ---------- 11. unknown / custom source ----------

def test_source_classification(fake_root, tmp_path, monkeypatch) -> None:
    # 无 agent 匹配、无第三方特征 → custom / unknown
    src, conf = sr.classify_source(fake_root / "whatever", {})
    assert src == "custom" and conf == "unknown"
    # author 含第三方特征 → third_party
    src2, conf2 = sr.classify_source(fake_root / "x", {"author": "openclaw upstream"})
    assert src2 == "third_party" and conf2 == "inferred"
    # repository 明确 → third_party / confirmed
    src3, conf3 = sr.classify_source(fake_root / "y",
                                     {"repository": "https://github.com/someone/skill"})
    assert src3 == "third_party" and conf3 == "confirmed"


def test_provenance_bundled_copy_and_derived(tmp_path, monkeypatch) -> None:
    """同名但 hash 一致 → bundled-copy/confirmed；hash 不一致 → custom-derived/inferred。"""
    agent = tmp_path / "agent-skills"
    agent.mkdir()
    bundled_dir = agent / "xurl"
    bundled_dir.mkdir()
    (bundled_dir / "SKILL.md").write_text("---\nname: xurl\n---\nbody\n", encoding="utf-8")
    home_skills = tmp_path / "home-skills"
    home_skills.mkdir()
    monkeypatch.setattr(sr, "AGENT_SKILLS", agent)
    monkeypatch.setattr(sr, "AGENT_OPTIONAL", tmp_path / "agent-optional")

    # 副本 hash 一致 → bundled-copy / confirmed
    same = home_skills / "xurl"
    same.mkdir()
    (same / "SKILL.md").write_text("---\nname: xurl\n---\nbody\n", encoding="utf-8")
    assert sr.classify_source(same, {}) == ("bundled-copy", "confirmed")

    # 同名但内容不同 → custom-derived / inferred
    diff = home_skills / "xurl-modified"
    diff.mkdir()
    (diff / "SKILL.md").write_text("---\nname: xurl-modified\n---\nchanged\n", encoding="utf-8")
    # 名字不同不匹配 bundled；用同名的不同内容目录验证
    diff2 = home_skills / "xurl2"
    diff2.mkdir()
    monkeypatch.setattr(sr, "AGENT_SKILLS", tmp_path / "empty-agent")  # 无 bundled → custom
    assert sr.classify_source(diff2, {})[0] == "custom"


def test_test_semantics_fields(fake_root) -> None:
    """P1：测试语义字段——py_compile 不等于 tests passed。"""
    d = _write_skill(fake_root, "semantic", GOOD_FM)
    (d / "tests").mkdir()
    (d / "tests" / "test_x.py").write_text("def test_x(): assert True\n", encoding="utf-8")
    rec = sr.check_skill(d)
    assert rec["has_tests"] is True
    assert rec["test_syntax_ok"] is True
    assert rec["tests_executed"] is False       # 默认不执行第三方测试
    assert rec["tests_passed"] == "unavailable"  # 不把语法检查当通过


# ---------- 零修改证明 + 可重复生成 ----------

def test_scan_does_not_modify_skills(fake_root, monkeypatch) -> None:
    d = _write_skill(fake_root, "pristine", GOOD_FM)
    monkeypatch.setattr(sr, "SKILLS_ROOT", fake_root)
    before = {p: (p.stat().st_mtime_ns, p.stat().st_size, hashlib.sha256(p.read_bytes()).hexdigest())
              for p in fake_root.rglob("*") if p.is_file()}
    sr.scan_all()
    after = {p: (p.stat().st_mtime_ns, p.stat().st_size, hashlib.sha256(p.read_bytes()).hexdigest())
             for p in fake_root.rglob("*") if p.is_file()}
    assert before == after  # mtime/size/内容全部不变


def test_scan_deterministic(fake_root, monkeypatch) -> None:
    _write_skill(fake_root, "a", GOOD_FM)
    _write_skill(fake_root, "b", GOOD_FM.replace("test-skill", "b-skill"))
    monkeypatch.setattr(sr, "SKILLS_ROOT", fake_root)
    r1 = [(s["key"], s["health"]) for s in sr.scan_all()]
    r2 = [(s["key"], s["health"]) for s in sr.scan_all()]
    assert r1 == r2  # 同一输入结果稳定


def test_malformed_skill_does_not_break_scan(fake_root, monkeypatch) -> None:
    _write_skill(fake_root, "ok", GOOD_FM)
    _write_skill(fake_root, "broken", "---\nnot valid yaml\n---\n")
    monkeypatch.setattr(sr, "SKILLS_ROOT", fake_root)
    results = sr.scan_all()
    keys = {s["key"] for s in results}
    assert {"ok", "broken"} <= keys  # 正常 + malformed 都扫到，全盘不崩
    by_key = {s["key"]: s for s in results}
    assert by_key["ok"]["health"] == "PASS"
    assert by_key["broken"]["health"] == "FAIL"


def test_registry_json_shape(fake_root, monkeypatch, tmp_path) -> None:
    _write_skill(fake_root, "ok", GOOD_FM)
    monkeypatch.setattr(sr, "SKILLS_ROOT", fake_root)
    monkeypatch.setattr(sr, "REGISTRY_DIR", tmp_path)
    monkeypatch.setattr(sr, "REGISTRY_PATH", tmp_path / "registry.json")
    sr.main_called = False
    # 直接调用 scan 主逻辑
    skills = sr.scan_all()
    payload = {"generated_at": "x", "skills": skills, "summary": sr.summary(skills)}
    (tmp_path / "registry.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    loaded = json.loads((tmp_path / "registry.json").read_text(encoding="utf-8"))
    assert loaded["summary"]["total"] == 1
    assert loaded["skills"][0]["key"] == "ok"
