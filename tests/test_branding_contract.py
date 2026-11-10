"""Display-only rebrand: stable identities, local artwork and four languages."""
import hashlib
import json
import shutil
import struct
import subprocess
from pathlib import Path
from urllib.parse import urljoin

import pytest

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dashboard/dist"


def test_manifest_keeps_runtime_identity():
    manifest = json.loads((ROOT / "dashboard/manifest.json").read_text())
    assert manifest["label"] == "RelayGlance"
    assert manifest["name"] == "hermes-hud"
    assert manifest["tab"] == {"path": "/hud", "position": "after:sessions"}
    assert manifest["entry"] == "dist/index.js"
    assert manifest["css"] == "dist/style.css"
    assert manifest["api"] == "plugin_api.py"
    desktop = json.loads((ROOT / "experiments/desktop-alpha/tauri.conf.json").read_text())
    assert desktop["identifier"] == "com.diabloluo.hermes-hud-desktop"
    assert desktop["version"] == "0.1.1"
    assert desktop["productName"] == "驿览 · RelayGlance"


def test_selected_radar_asset_is_unchanged_and_relative():
    artwork = (DIST / "relayglance-radar.png").read_bytes()
    assert artwork[:8] == b"\x89PNG\r\n\x1a\n"
    assert struct.unpack(">II", artwork[16:24]) == (1254, 1254)
    assert hashlib.sha256(artwork).hexdigest() == (
        "2b3cb47ffbfcb0570001c394d925ff8ba46452aa5a8905ee28462e6f97366277")
    css = (DIST / "style.css").read_text()
    # Relative to the stylesheet, not the document: preserves both older
    # unscoped hosts and newer /@profile + reverse-proxy asset prefixes.
    assert 'url("./relayglance-radar.png")' in css


@pytest.mark.parametrize("asset_prefix", [
    "/dashboard-plugins/hermes-hud/dist/",
    "/dashboard-plugins/@work%20bench/hermes-hud/dist/",
    "/reverse-proxy/dashboard-plugins/@work%20bench/hermes-hud/dist/",
])
def test_icon_url_preserves_stylesheet_scope(asset_prefix):
    # URL-resolution contract only; real host serving/browser decoding is
    # covered separately by test_release_i18n_smoke when available.
    origin = "http://127.0.0.1:9119"
    assert urljoin(origin + asset_prefix + "style.css", "./relayglance-radar.png") == (
        origin + asset_prefix + "relayglance-radar.png")


@pytest.mark.parametrize("locale,title,subtitle", [
    ("zh", "驿览 · RelayGlance", "原 Hermes HUD · 非官方 Hermes 社区观察插件"),
    ("en", "RelayGlance", "Formerly Hermes HUD · Unofficial Hermes community dashboard"),
    ("fr", "RelayGlance", "Anciennement Hermes HUD · Tableau de bord communautaire non officiel pour Hermes"),
    ("ar", "RelayGlance", "Hermes HUD سابقًا · لوحة مراقبة مجتمعية غير رسمية لـ Hermes"),
])
def test_brand_header_and_runtime_contract(locale, title, subtitle):
    if not shutil.which("node"):
        pytest.skip("Node.js required for frontend render contract")
    script = r'''
const fs=require('fs'),vm=require('vm');
const locale=process.argv[2],readKeys=[];
const hooks={useState(v){return [typeof v==='function'?v():v,()=>{}];},
 useEffect(){},useMemo(fn){return fn();},useRef(){return {};},useCallback(fn){return fn;}};
const sdk={React:{createElement(type,props,...children){return {type:typeof type==='function'?type.name:type,props,children};}},
 hooks,components:{},utils:{},useI18n(){return {locale};}};
const ctx={window:{__HERMES_PLUGIN_SDK__:sdk,__HERMES_PLUGINS__:{register(id,app){ctx.app=app;ctx.id=id;}}},
 localStorage:{getItem(key){readKeys.push(key);return null;}}};
const source=fs.readFileSync(process.argv[1],'utf8');
vm.runInNewContext(source.replace('window.__HERMES_PLUGINS__.register("hermes-hud", HudApp);',
 'window.__brand=BrandHeader;window.__api=API;window.__HERMES_PLUGINS__.register("hermes-hud", HudApp);'),ctx);
const root=ctx.app();
console.log(JSON.stringify({id:ctx.id,api:ctx.window.__api,root,brand:ctx.window.__brand(),readKeys}));
'''
    result = subprocess.run(["node", "-e", script, str(DIST / "index.js"), locale],
                            capture_output=True, text=True, check=True, timeout=15)
    rendered = json.loads(result.stdout)
    assert rendered["id"] == "hermes-hud"
    assert rendered["api"] == "/api/plugins/hermes-hud"
    assert rendered["readKeys"] == ["hermes-hud-locale"]
    assert rendered["root"]["props"]["lang"] == locale
    assert rendered["root"]["props"]["dir"] == ("rtl" if locale == "ar" else "ltr")
    assert sum(child.get("type") == "BrandHeader" for child in rendered["root"]["children"]) == 1
    brand = rendered["brand"]
    assert brand["type"] == "header"
    assert brand["children"][0]["props"]["aria-hidden"] == "true"
    copy = brand["children"][1]["children"]
    assert copy[0]["type"] == "h1"
    assert copy[0]["children"] == [title]
    assert copy[1]["children"] == [subtitle]
