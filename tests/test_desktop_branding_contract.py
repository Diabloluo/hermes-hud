"""Lightweight desktop rebrand checks; these are not native release validation."""
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import zlib

ROOT = Path(__file__).resolve().parents[1]
DESKTOP = ROOT / "experiments/desktop-alpha"
NAME = "驿览 · RelayGlance"
VERSION = "0.1.1"
SOURCE_SHA = "2b3cb47ffbfcb0570001c394d925ff8ba46452aa5a8905ee28462e6f97366277"


def png_size(data):
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", data[16:24])


def test_names_versions_and_technical_identity():
    conf = json.loads((DESKTOP / "tauri.conf.json").read_text())
    cargo = (DESKTOP / "Cargo.toml").read_text()
    lock = (DESKTOP / "Cargo.lock").read_text()
    assert conf["productName"] == NAME
    assert conf["version"] == VERSION
    assert conf["identifier"] == "com.diabloluo.hermes-hud-desktop"
    assert 'name = "hermes-hud-desktop"' in cargo
    assert f'version = "{VERSION}"' in cargo
    assert f'name = "hermes-hud-desktop"\nversion = "{VERSION}"' in lock
    assert conf["bundle"]["icon"] == ["icons/icon.icns"]
    assert conf["build"]["devUrl"] == "http://127.0.0.1:9119/hud"


def test_shell_and_setup_branding_keep_local_security_contract():
    rust = (DESKTOP / "src/lib.rs").read_text()
    setup = (DESKTOP / "assets/setup.html").read_text()
    assert f'const DISPLAY_NAME: &str = "{NAME}";' in rust
    assert f'const OPEN_LABEL: &str = "Open {NAME}";' in rust
    assert ".title(DISPLAY_NAME)" in rust
    assert ".tooltip(DISPLAY_NAME)" in rust
    assert '"open", OPEN_LABEL' in rust
    assert 'include_bytes!("../icons/tray_template_20.png")' in rust
    assert ".icon_as_template(true)" in rust
    assert "default_window_icon()" not in rust  # must not overwrite the template
    assert '<title>' + NAME + '</title>' in setup
    assert '<h1>' + NAME + '</h1>' in setup
    assert f'macOS Desktop Alpha {VERSION}' in setup
    assert f'<code>{VERSION}-alpha</code>' in setup
    assert 'src="relayglance-radar.png"' in setup
    assert "Observer Core" not in setup
    assert "<svg" not in setup
    assert "HUD 已可用" not in setup
    assert "无法继续使用 HUD" not in setup
    assert "RelayGlance 已可用" in setup
    assert "无法继续使用 RelayGlance" in setup
    assert "window.__hud_set_state__" in setup
    assert "window.__hud_pending_state__" in setup
    assert 'WebviewUrl::App("setup.html".into())' in rust
    assert 'if url.scheme() != "tauri"' in rust
    assert "/api/plugins/hermes-hud/health" in rust
    capabilities = json.loads((DESKTOP / "capabilities/local-bundled.json").read_text())
    assert capabilities["local"] is True
    assert "remote" not in capabilities


def test_all_compiled_assets_match_the_approved_manifest():
    manifest = json.loads((DESKTOP / "icons/brand-assets.json").read_text())
    assert manifest["source"] == "dashboard/dist/relayglance-radar.png"
    assert manifest["source_sha256"] == SOURCE_SHA
    assert hashlib.sha256((ROOT / manifest["source"]).read_bytes()).hexdigest() == SOURCE_SHA
    assets = {str(p.relative_to(DESKTOP)) for p in (DESKTOP / "icons").rglob("*.png")}
    assets.update(["icons/icon.icns", "assets/relayglance-radar.png"])
    assert assets == set(manifest["files"])
    for filename, sha in manifest["files"].items():
        assert hashlib.sha256((DESKTOP / filename).read_bytes()).hexdigest() == sha, filename
    assert not (DESKTOP / "icons/ObserverCore.iconset").exists()
    for size in (16, 32, 64, 128, 256, 512, 1024):
        assert png_size((DESKTOP / f"icons/icon_{size}.png").read_bytes()) == (size, size)
    assert (DESKTOP / "assets/relayglance-radar.png").read_bytes() == (DESKTOP / "icons/icon_256.png").read_bytes()
    assert (DESKTOP / "icons/icon.png").read_bytes() == (DESKTOP / "icons/icon_256.png").read_bytes()


def test_icns_has_all_sizes_and_exact_png_payloads():
    data = (DESKTOP / "icons/icon.icns").read_bytes()
    assert data[:4] == b"icns"
    assert struct.unpack(">I", data[4:8])[0] == len(data)
    expected = {b"icp4": 16, b"icp5": 32, b"icp6": 64, b"ic07": 128,
                b"ic08": 256, b"ic09": 512, b"ic10": 1024,
                b"ic11": 32, b"ic12": 64, b"ic13": 256, b"ic14": 512}
    found = {}
    offset = 8
    while offset < len(data):
        kind = data[offset:offset + 4]
        length = struct.unpack(">I", data[offset + 4:offset + 8])[0]
        assert length > 8 and offset + length <= len(data)
        assert kind not in found and kind in expected
        size = expected[kind]
        payload = data[offset + 8:offset + length]
        assert png_size(payload) == (size, size)
        assert payload == (DESKTOP / f"icons/icon_{size}.png").read_bytes()
        found[kind] = size
        offset += length
    assert found == expected


def test_iconset_dimensions_cover_retina():
    icons = list((DESKTOP / "icons/RelayGlance.iconset").glob("*.png"))
    assert len(icons) == 10
    for icon in icons:
        match = re.fullmatch(r"icon_(\d+)x\d+(@2x)?\.png", icon.name)
        assert match
        size = int(match[1]) * (2 if match[2] else 1)
        assert png_size(icon.read_bytes()) == (size, size)
        assert icon.read_bytes() == (DESKTOP / f"icons/icon_{size}.png").read_bytes()


def rgba_png_pixels(data):
    """Decode tiny generated RGBA PNGs without a Pillow dependency in CI."""
    width, height = png_size(data)
    assert data[24:29] == bytes([8, 6, 0, 0, 0])
    compressed = b""
    offset = 8
    while offset < len(data):
        length = struct.unpack(">I", data[offset:offset + 4])[0]
        kind = data[offset + 4:offset + 8]
        chunk = data[offset + 8:offset + 8 + length]
        if kind == b"IDAT":
            compressed += chunk
        offset += length + 12
    raw = zlib.decompress(compressed)
    stride = width * 4
    assert len(raw) == height * (stride + 1)
    previous = bytearray(stride)
    decoded = bytearray()
    for y in range(height):
        row_offset = y * (stride + 1)
        kind = raw[row_offset]
        row = bytearray(raw[row_offset + 1:row_offset + 1 + stride])
        for i in range(stride):
            left = row[i - 4] if i >= 4 else 0
            up = previous[i]
            upper_left = previous[i - 4] if i >= 4 else 0
            if kind == 1:
                predictor = left
            elif kind == 2:
                predictor = up
            elif kind == 3:
                predictor = (left + up) // 2
            elif kind == 4:
                p = left + up - upper_left
                distances = [abs(p - v) for v in (left, up, upper_left)]
                predictor = (left, up, upper_left)[distances.index(min(distances))]
            else:
                assert kind == 0
                predictor = 0
            row[i] = (row[i] + predictor) & 255
        decoded.extend(row)
        previous = row
    return [tuple(decoded[i:i + 4]) for i in range(0, len(decoded), 4)]


def test_tray_is_black_with_alpha_not_the_color_app_icon():
    for size in (16, 18, 20, 32, 36, 40):
        data = (DESKTOP / f"icons/tray_template_{size}.png").read_bytes()
        assert png_size(data) == (size, size)
        pixels = rgba_png_pixels(data)
        assert all(pixel[:3] == (0, 0, 0) for pixel in pixels)
        alpha = [pixel[3] for pixel in pixels]
        assert min(alpha) == 0 and max(alpha) >= 230
        assert any(0 < a < 255 for a in alpha)  # antialiasing
        assert alpha[0] == 0


def test_bundle_verifier_brand_contract_and_regressions():
    tools = DESKTOP / "tools"
    result = subprocess.run(["bash", str(tools / "test_verify_release_bundle.sh")],
                            capture_output=True, text=True, timeout=15, check=True)
    assert "22 passed, 0 failed" in result.stdout
    result = subprocess.run(["bash", "-c", 'VERIFY_SOURCE=1 source "$1"; printf "%s\\n%s\\n%s\\n" "$EXPECTED_VERSION" "$EXPECTED_PRODUCT_NAME" "$EXPECTED_DMG_NAME"',
                             "test", str(tools / "verify_release_bundle.sh")],
                            capture_output=True, text=True, timeout=15, check=True)
    assert result.stdout.splitlines() == [VERSION, NAME, f"RelayGlance-Desktop-{VERSION}-macOS-arm64.dmg"]
