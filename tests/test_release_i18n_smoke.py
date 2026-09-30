"""Real Dashboard four-locale acceptance (synthetic data, isolated home).

Uses the existing Chrome fixture; skipped only where Chrome/Hermes is absent.
Local release acceptance must execute these, not treat skips as a pass.
Optional HUD_ACCEPTANCE_ARTIFACT_DIR records viewport screenshots.
"""
import base64
import json
import os
import re
import time
import urllib.request
from pathlib import Path

import pytest

from test_frontend_smoke import SYNTHETIC_SKILLS, hud_env, seed_synthetic_skills  # noqa: F401


def wait_for(cdp, expression, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = cdp.eval(expression)
        if value:
            return value
        time.sleep(0.25)
    raise AssertionError(f"UI did not become ready: {expression}")


SKILL_HEADERS = {
    "zh": ["技能", "分类", "版本", "大小", "最近修改", "描述"],
    "en": ["Skill", "Category", "Version", "Size", "Last Modified", "Description"],
    "fr": ["Compétence", "Catégorie", "Version", "Taille", "Dernière modification", "Description"],
    "ar": ["المهارة", "الفئة", "الإصدار", "الحجم", "آخر تعديل", "الوصف"],
}
UNCATEGORIZED = {"zh": "未分类", "en": "Uncategorized", "fr": "Non classé", "ar": "غير مصنّف"}


def assert_skill_payload(payload, expected_skills, locale):
    assert payload["error"] is None
    for expected in expected_skills:
        matches = [skill for skill in payload["skills"] if skill["name"] == expected["name"]]
        assert len(matches) == 1, (locale, expected["id"], "synthetic metadata missing/rewritten")
        actual = matches[0]
        for field in ("name", "version", "description"):
            assert actual[field] == expected[field], (locale, expected["id"], field)
        category = expected["category"] if expected["category"] is not None else UNCATEGORIZED[locale]
        assert actual["category"] == category, (locale, expected["id"], "category")


@pytest.mark.parametrize("locale", ["zh", "en", "fr", "ar"])
def test_synthetic_skill_collector_contract(tmp_path, monkeypatch, locale):
    """Run the fixture/parser contract even when a browser is unavailable."""
    from dashboard.hud import collectors
    seed_synthetic_skills(tmp_path)
    monkeypatch.setattr(collectors, "HERMES_HOME", tmp_path)
    payload = collectors.collect_skills(locale)
    assert len(payload["skills"]) == len(SYNTHETIC_SKILLS)
    assert_skill_payload(payload, SYNTHETIC_SKILLS, locale)


def skill_api_contract(hud_env, locale):
    """Independent file -> authenticated API check, not just DOM versus API."""
    base = f"http://127.0.0.1:{hud_env['port']}"
    with urllib.request.urlopen(base + "/", timeout=10) as response:
        html = response.read().decode("utf-8")
    token = re.search(r'window\.__HERMES_SESSION_TOKEN__="([^"]+)"', html)
    assert token, "isolated Dashboard session token missing"
    request = urllib.request.Request(base + f"/api/plugins/hermes-hud/skills?locale={locale}",
                                    headers={"X-Hermes-Session-Token": token.group(1)})
    with urllib.request.urlopen(request, timeout=10) as response:
        payload = json.load(response)
    assert_skill_payload(payload, hud_env["synthetic_skills"], locale)
    return payload


def static_ui_text(cdp, skills=None):
    """Exclude only validated observed fields; leave headers/buttons/chrome.

    No broad skills-page/table exclusion. Every visible row must match the
    authenticated API before its four raw metadata cells can be blanked.
    Category controls are raw only when their ENTIRE text matches the API.
    """
    result = cdp.eval("""(() => {
        const root = document.querySelector('.hud-root').cloneNode(true);
        root.querySelectorAll('.hud-incident,.hud-tl-row,.hud-logline').forEach(e=>e.remove());
        const payload = """ + json.dumps(skills, ensure_ascii=True) + """;
        if (payload) {
            const tables = root.querySelectorAll('.hud-table');
            if (tables.length !== 1) return {error: 'expected one skills table'};
            const rows = [...tables[0].querySelectorAll('tbody tr')];
            if (!rows.length) return {error: 'missing skills rows'};
            for (const row of rows) {
                const cells = [...row.querySelectorAll('td')];
                if (cells.length !== 6) return {error: 'unexpected skills columns'};
                const match = payload.skills.find(s => cells[0].textContent === s.name &&
                    cells[1].textContent === s.category &&
                    cells[2].textContent === (s.version || '-') &&
                    cells[5].textContent === (s.description || '').slice(0, 60));
                if (!match) return {error: 'raw skill metadata changed or unexpected static text'};
                // Size and relative-time are formatted UI, NOT raw metadata.
                for (const index of [0, 1, 2, 5]) cells[index].textContent = '';
            }
            const categories = payload.summary.by_category;
            for (const button of root.querySelectorAll('.hud-grid-2 button')) {
                const raw = button.textContent;
                if (Object.keys(categories).some(c => raw === c || raw === c + ' · ' + categories[c]))
                    button.textContent = '';
            }
        }
        return {text: root.textContent};
    })()""")
    assert result and "error" not in result, result
    return (result["text"] or "").replace("简体中文", "")  # picker endonym


def assert_no_static_cjk(cdp, locale, index, skills=None):
    text = static_ui_text(cdp, skills)
    leak = re.search(r"[\u4e00-\u9fff]", text)
    assert not leak, (locale, index,
                     text[max(0, leak.start()-50):leak.end()+70] if leak else "")


def assert_skill_dom_contract(cdp, hud_env, locale, payload):
    assert cdp.eval("[...document.querySelectorAll('.hud-table thead th')].map(e=>e.textContent)") == SKILL_HEADERS[locale]
    rows = cdp.eval("[...document.querySelectorAll('.hud-table tbody tr')]"
                    ".map(r=>[...r.querySelectorAll('td')].map(c=>c.textContent))")
    for expected in hud_env["synthetic_skills"]:
        matches = [row for row in rows if row[0] == expected["name"]]
        assert len(matches) == 1, (locale, expected["id"], "synthetic DOM row missing")
        row = matches[0]
        category = expected["category"] if expected["category"] is not None else UNCATEGORIZED[locale]
        assert [row[i] for i in (0, 1, 2, 5)] == [expected["name"], category,
                                                  expected["version"], expected["description"][:60]]
    assert cdp.eval("document.querySelectorAll('.hud-table td b').length") == 0
    # This controlled fixture MUST exercise the old false positive.
    assert re.search(r"[\u4e00-\u9fff]", cdp.eval("document.querySelector('.hud-table tbody').textContent"))
    static_ui_text(cdp, payload)  # validate all rows/category controls, even zh


@pytest.mark.parametrize("locale,direction", [("zh", "ltr"), ("en", "ltr"),
                                             ("fr", "ltr"), ("ar", "rtl")])
def test_four_locale_real_dashboard(hud_env, locale, direction):
    cdp = hud_env["cdp"]
    url = f"http://127.0.0.1:{hud_env['port']}/hud"
    cdp.eval(f"localStorage.setItem('hermes-hud-locale', {json.dumps(locale)})")
    cdp.cmd("Page.navigate", {"url": url})
    wait_for(cdp, "document.querySelectorAll('.hud-tab').length === 13")
    wait_for(cdp, "document.querySelector('.hud-health-badge') && "
             "!document.querySelector('.hud-health-badge').textContent.includes('加载中')")
    assert cdp.eval("document.querySelector('.hud-root').dir") == direction
    assert cdp.eval("document.querySelector('.hud-root').lang") == locale
    # Capture uncaught browser errors before traversing every HUD tab.
    cdp.eval("window.__hudErrors=[]; window.addEventListener('error', e=>"
             "window.__hudErrors.push(e.message)); window.addEventListener('unhandledrejection',"
             "e=>window.__hudErrors.push(String(e.reason)))")
    for index in range(13):
        assert cdp.eval(f"(() => {{ document.querySelectorAll('.hud-tab')[{index}].click();"
                        "return true; })()")
        time.sleep(1.5)
        active_color = cdp.eval("getComputedStyle(document.querySelector('.hud-tab.active')).color")
        assert active_color not in ("transparent", "rgba(0, 0, 0, 0)"), active_color
        text = cdp.eval("document.querySelector('.hud-root').innerText") or ""
        assert len(text) > 60
        assert "TypeError" not in text and "Internal Server Error" not in text
        assert "undefined" not in text and "NaN" not in text
        skills = None
        if index == 6:
            wait_for(cdp, "!!document.querySelector('.hud-table tbody tr')")
            skills = skill_api_contract(hud_env, locale)
            assert_skill_dom_contract(cdp, hud_env, locale, skills)
        if locale != "zh":
            # Do not confuse canonical persisted incidents, raw logs and
            # observed timeline summaries with untranslated UI chrome.
            assert_no_static_cjk(cdp, locale, index, skills)
    assert cdp.eval("window.__hudErrors") == []
    # Persisted setting + live language selection (without a page reload).
    next_locale = {"zh": "en", "en": "fr", "fr": "ar", "ar": "zh"}[locale]
    endonym = {"zh": "简体中文", "en": "English", "fr": "Français", "ar": "العربية"}[next_locale]
    assert cdp.eval("(() => { const b=[...document.querySelectorAll('.hud-root button')]"
                    f".find(b=>b.textContent==={json.dumps(endonym)}); if(!b)return false;"
                    "b.click();return true; })()")
    wait_for(cdp, f"localStorage.getItem('hermes-hud-locale') === {json.dumps(next_locale)}")
    expected_dir = "rtl" if next_locale == "ar" else "ltr"
    wait_for(cdp, f"document.querySelector('.hud-root').dir === {json.dumps(expected_dir)}")
    # Restore this test's locale through the same real picker for screenshots.
    endonym = {"zh": "简体中文", "en": "English", "fr": "Français", "ar": "العربية"}[locale]
    assert cdp.eval("(() => { const b=[...document.querySelectorAll('.hud-root button')]"
                    f".find(b=>b.textContent==={json.dumps(endonym)}); b.click();return true; }})()")
    wait_for(cdp, f"document.querySelector('.hud-root').lang === {json.dumps(locale)}")
    cdp.eval("document.querySelector('.hud-tab').click()")
    time.sleep(2)
    artifact_dir = os.environ.get("HUD_ACCEPTANCE_ARTIFACT_DIR")
    for width, height in ((1440, 1000), (1024, 900), (390, 844)):
        cdp.cmd("Emulation.setDeviceMetricsOverride", {"width": width, "height": height,
                 "deviceScaleFactor": 1, "mobile": False})
        time.sleep(0.3)
        assert cdp.eval("document.querySelectorAll('.hud-tab').length") == 13
        if artifact_dir:
            target = Path(artifact_dir)
            target.mkdir(parents=True, exist_ok=True)
            shot = cdp.cmd("Page.captureScreenshot", {"format": "png"})
            (target / f"hud-{locale}-{width}.png").write_bytes(base64.b64decode(shot["result"]["data"]))
    cdp.cmd("Emulation.clearDeviceMetricsOverride")


@pytest.mark.parametrize("locale", ["en", "fr", "ar"])
def test_skill_static_translation_negative_controls(hud_env, locale):
    """Same scanner must reject untranslated headers, buttons and row text."""
    cdp = hud_env["cdp"]
    cdp.eval(f"localStorage.setItem('hermes-hud-locale', {json.dumps(locale)})")
    cdp.cmd("Page.navigate", {"url": f"http://127.0.0.1:{hud_env['port']}/hud"})
    wait_for(cdp, "document.querySelectorAll('.hud-tab').length === 13")
    cdp.eval("document.querySelectorAll('.hud-tab')[6].click()")
    wait_for(cdp, "!!document.querySelector('.hud-table tbody tr')")
    payload = skill_api_contract(hud_env, locale)
    assert_no_static_cjk(cdp, locale, 6, payload)
    for selector in (".hud-table thead th", ".hud-grid-2 button", ".hud-table tbody td"):
        # Restore exactly what was changed, even when a negative check fails.
        cdp.eval(f"(() => {{ window.__hudNegativeNode=document.querySelector({json.dumps(selector)});"
                 "window.__hudNegativeOriginal=window.__hudNegativeNode.textContent;"
                 "window.__hudNegativeNode.textContent += ' 静态漏翻译'; })()")
        try:
            with pytest.raises(AssertionError):
                assert_no_static_cjk(cdp, locale, 6, payload)
        finally:
            cdp.eval("window.__hudNegativeNode.textContent=window.__hudNegativeOriginal;"
                     "delete window.__hudNegativeNode; delete window.__hudNegativeOriginal;")
        assert_no_static_cjk(cdp, locale, 6, payload)
