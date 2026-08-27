#!/usr/bin/env python3
"""Observer Core — 生成 macOS App icon 全尺寸 + .iconset + menu bar template。

几何（D）：central ring/core · 3 nodes 约 120° · segmented orbital arcs ·
严格几何对称 · 强中心锚点。颜色：Cyan #00E5FF → Mint #6CFFB6 主渐变，
Blue 仅次。32/16px 专门简化（更粗 core / 更少弧线 / 更大 nodes / 清晰轮廓）。
Menu bar template：monochrome（黑色 + alpha），透明背景，无渐变无 glow。
纯 stdlib（zlib/struct 手写 PNG），无 Pillow 依赖。
"""
import math
import os
import struct
import zlib

OUT = os.path.join(os.path.dirname(__file__), "..", "icons")
CYAN = (0, 229, 255)
MINT = (108, 255, 182)
DARK = (14, 17, 23)
GRAF = (0x1A, 0x1F, 0x2A)


def write_png(path, size, px):
    raw = b""
    for y in range(size):
        raw += b"\x00"
        for x in range(size):
            raw += bytes(px[y * size + x])
    def chunk(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw, 9))
           + chunk(b"IEND", b""))
    with open(path, "wb") as f:
        f.write(png)


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def make_icon(size, simplified=False):
    """App icon：深石墨背景 + Observer Core（Cyan→Mint）。"""
    px = [(0, 0, 0, 0)] * (size * size)
    cx = cy = size / 2
    bg_r = size * 0.22  # 圆角半径
    ring_r = size * 0.30          # 中心 ring 半径
    ring_w = size * (0.085 if not simplified else 0.13)   # 简化 → 更粗
    node_r = size * (0.075 if not simplified else 0.11)   # 简化 → 更大 nodes
    arc_span = math.radians(70)   # 弧段角度（缺口 50°）
    core_r = size * 0.045         # 中心 core 点

    for y in range(size):
        for x in range(size):
            d = math.hypot(x + 0.5 - cx, y + 0.5 - cy)
            # 背景：圆角方形（深石墨）——矩形内部全画，仅切圆角外
            bx = min(x, size - 1 - x)
            by = min(y, size - 1 - y)
            if bx < bg_r and by < bg_r:
                corner = math.hypot(bx - bg_r, by - bg_r)
                if corner <= bg_r:
                    px[y * size + x] = (*GRAF, 255)
            else:
                px[y * size + x] = (*GRAF, 255)
            # ring（弧段内 → 渐变）
            if ring_r - ring_w <= d <= ring_r + ring_w:
                ang = (math.atan2(y + 0.5 - cy, x + 0.5 - cx) + math.pi) % (2 * math.pi)
                # 3 个弧段（缺口在 3 个节点位置附近）
                in_arc = False
                for k in range(3):
                    center = (k * 2 * math.pi / 3) % (2 * math.pi)
                    diff = abs(ang - center)
                    diff = min(diff, 2 * math.pi - diff)
                    if diff <= arc_span / 2:
                        in_arc = True
                        break
                if in_arc:
                    t = (ang / (2 * math.pi))
                    col = lerp(CYAN, MINT, t)
                    # 现有背景混合
                    bg = px[y * size + x]
                    if bg[3] == 255:
                        col = tuple(int(bg[i] * 0.5 + col[i] * 0.5) for i in range(3))
                    px[y * size + x] = (*col, 255)
            # 中心 core 点（强锚点）
            if d <= core_r:
                px[y * size + x] = (*MINT, 255)
            # 3 个 node（120°）
            for k in range(3):
                na = k * 2 * math.pi / 3 - math.pi / 2
                nx = cx + ring_r * math.cos(na)
                ny = cy + ring_r * math.sin(na)
                if math.hypot(x + 0.5 - nx, y + 0.5 - ny) <= node_r:
                    px[y * size + x] = (*MINT, 255)
    return px


def make_template(size):
    """Menu bar template：monochrome（黑色+alpha），透明背景，仅 ring+3 nodes+core。"""
    px = [(0, 0, 0, 0)] * (size * size)
    cx = cy = size / 2
    ring_r = size * 0.34
    ring_w = size * 0.16   # template 更粗（小尺寸可辨识）
    node_r = size * 0.12
    core_r = size * 0.06
    for y in range(size):
        for x in range(size):
            d = math.hypot(x + 0.5 - cx, y + 0.5 - cy)
            if ring_r - ring_w <= d <= ring_r + ring_w:
                px[y * size + x] = (0, 0, 0, 255)
            if d <= core_r:
                px[y * size + x] = (0, 0, 0, 255)
            for k in range(3):
                na = k * 2 * math.pi / 3 - math.pi / 2
                nx = cx + ring_r * math.cos(na)
                ny = cy + ring_r * math.sin(na)
                if math.hypot(x + 0.5 - nx, y + 0.5 - ny) <= node_r:
                    px[y * size + x] = (0, 0, 0, 255)
    return px


def main():
    os.makedirs(OUT, exist_ok=True)
    # —— App icon 全尺寸 ——
    for s in (1024, 512, 256, 128, 64, 32, 16):
        simplified = s <= 32
        write_png(os.path.join(OUT, f"icon_{s}.png"), s, make_icon(s, simplified))
        print(f"icon_{s}.png")
    # —— .iconset（iconutil 需要）——
    ic = os.path.join(OUT, "ObserverCore.iconset")
    os.makedirs(ic, exist_ok=True)
    mapping = {
        "icon_16x16.png": 16, "icon_16x16@2x.png": 32,
        "icon_32x32.png": 32, "icon_32x32@2x.png": 64,
        "icon_128x128.png": 128, "icon_128x128@2x.png": 256,
        "icon_256x256.png": 256, "icon_256x256@2x.png": 512,
        "icon_512x512.png": 512, "icon_512x512@2x.png": 1024,
    }
    for name, s in mapping.items():
        write_png(os.path.join(ic, name), s, make_icon(s, simplified=(s <= 32)))
    # —— menu bar template（monochrome）——
    for s in (16, 18, 20):
        write_png(os.path.join(OUT, f"tray_template_{s}.png"), s, make_template(s))
        print(f"tray_template_{s}.png")
    print("done")


if __name__ == "__main__":
    main()
