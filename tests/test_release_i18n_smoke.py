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
from pathlib import Path

import pytest

from test_frontend_smoke import hud_env  # noqa: F401


def wait_for(cdp, expression, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = cdp.eval(expression)
        if value:
            return value
        time.sleep(0.25)
    raise AssertionError(f"UI did not become ready: {expression}")


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
        if locale != "zh":
            # Do not confuse canonical persisted incidents, raw logs and
            # observed timeline summaries with untranslated UI chrome.
            ui_text = cdp.eval("(() => { const root=document.querySelector('.hud-root').cloneNode(true);"
                "root.querySelectorAll('.hud-incident,.hud-tl-row,.hud-logline').forEach(e=>e.remove());"
                "return root.textContent; })()") or ""
            ui_text = ui_text.replace("简体中文", "")  # picker endonym
            leak = re.search(r"[\u4e00-\u9fff]", ui_text)
            assert not leak, (locale, index,
                ui_text[max(0, leak.start()-50):leak.end()+70] if leak else "")
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
