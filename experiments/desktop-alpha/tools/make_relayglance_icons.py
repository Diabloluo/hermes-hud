#!/usr/bin/env python3
"""Compile the approved, unchanged RelayGlance raster into desktop icon formats.

The color artwork is only resampled, never redrawn. The monochrome menu-bar
asset is a code-native radar glyph, since macOS template icons require black
pixels and alpha instead of the app's color artwork. Run from any directory.

Dependency: tools/requirements-icons.txt. No network access or macOS required.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import struct

from PIL import Image

DESKTOP = Path(__file__).resolve().parents[1]
SOURCE = DESKTOP.parents[1] / "dashboard/dist/relayglance-radar.png"
SOURCE_SHA256 = "2b3cb47ffbfcb0570001c394d925ff8ba46452aa5a8905ee28462e6f97366277"
SIZES = (16, 32, 64, 128, 256, 512, 1024)
ICONSET = {
    "icon_16x16.png": 16, "icon_16x16@2x.png": 32,
    "icon_32x32.png": 32, "icon_32x32@2x.png": 64,
    "icon_128x128.png": 128, "icon_128x128@2x.png": 256,
    "icon_256x256.png": 256, "icon_256x256@2x.png": 512,
    "icon_512x512.png": 512, "icon_512x512@2x.png": 1024,
}
# Modern macOS PNG-backed ICNS representations, including Retina variants.
ICNS = {
    b"icp4": 16, b"icp5": 32, b"icp6": 64, b"ic07": 128,
    b"ic08": 256, b"ic09": 512, b"ic10": 1024,
    b"ic11": 32, b"ic12": 64, b"ic13": 256, b"ic14": 512,
}


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_template(size):
    """Antialiased black/alpha radar: two rings, center, sweep and one return."""
    scale = 4
    hi = size * scale
    image = Image.new("RGBA", (hi, hi))
    pixels = image.load()
    # Match the selected radar orientation (sweep to the upper right).
    theta = -math.pi / 6
    end_x, end_y = 0.39 * math.cos(theta), 0.39 * math.sin(theta)
    length_sq = end_x * end_x + end_y * end_y
    for y in range(hi):
        for x in range(hi):
            dx, dy = (x + 0.5) / hi - 0.5, (y + 0.5) / hi - 0.5
            radius = math.hypot(dx, dy)
            t = max(0, min(1, (dx * end_x + dy * end_y) / length_sq))
            sweep_distance = math.hypot(dx - t * end_x, dy - t * end_y)
            return_distance = math.hypot(dx - 0.17, dy + 0.19)
            ring = abs(radius - 0.39) < 0.035 or abs(radius - 0.22) < 0.025
            ticks = ((abs(dx) < 0.027 and 0.35 < abs(dy) < 0.46)
                     or (abs(dy) < 0.027 and 0.35 < abs(dx) < 0.46))
            if ring or ticks or radius < 0.055 or sweep_distance < 0.025 or return_distance < 0.055:
                pixels[x, y] = (0, 0, 0, 255)
    return image.resize((size, size), Image.Resampling.LANCZOS)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DESKTOP,
                        help="Desktop root containing icons/ and assets/")
    args = parser.parse_args()
    if sha256(SOURCE) != SOURCE_SHA256:
        raise SystemExit("Approved radar source changed; review the artwork before rebuilding icons.")
    source = Image.open(SOURCE)
    source.load()
    if source.size != (1254, 1254):
        raise SystemExit("Unexpected radar source dimensions.")
    source = source.convert("RGBA")
    out = args.output_dir
    icons = out / "icons"
    iconset = icons / "RelayGlance.iconset"
    iconset.mkdir(parents=True, exist_ok=True)
    (out / "assets").mkdir(parents=True, exist_ok=True)
    for size in SIZES:
        source.resize((size, size), Image.Resampling.LANCZOS).save(icons / f"icon_{size}.png")
    (icons / "icon.png").write_bytes((icons / "icon_256.png").read_bytes())
    (out / "assets/relayglance-radar.png").write_bytes((icons / "icon_256.png").read_bytes())
    for filename, size in ICONSET.items():
        (iconset / filename).write_bytes((icons / f"icon_{size}.png").read_bytes())
    chunks = []
    for kind, size in ICNS.items():
        data = (icons / f"icon_{size}.png").read_bytes()
        chunks.append(kind + struct.pack(">I", len(data) + 8) + data)
    payload = b"".join(chunks)
    (icons / "icon.icns").write_bytes(b"icns" + struct.pack(">I", len(payload) + 8) + payload)
    # Both 1x and 2x assets are available for platform-specific display QA.
    for size in (16, 18, 20, 32, 36, 40):
        make_template(size).save(icons / f"tray_template_{size}.png")
    files = sorted(icons.rglob("*.png")) + [icons / "icon.icns", out / "assets/relayglance-radar.png"]
    manifest = {
        "source": "dashboard/dist/relayglance-radar.png",
        "source_sha256": SOURCE_SHA256,
        "files": {str(p.relative_to(out)): sha256(p) for p in files},
    }
    (icons / "brand-assets.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Compiled {len(files)} desktop assets from unchanged approved radar source.")


if __name__ == "__main__":
    main()
