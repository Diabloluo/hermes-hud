#!/usr/bin/env python3
"""Validate hdiutil snapshots without inventing device ownership."""
import os
from pathlib import Path
import plistlib
import re
import sys

DEVICE = re.compile(r"/dev/disk[0-9]+")


def read(path):
    data = plistlib.loads(Path(path).read_bytes())
    if not isinstance(data, dict):
        raise ValueError("expected a plist dictionary")
    return data


def entities(image):
    rows = image.get("system-entities")
    if not isinstance(rows, list) or any(not isinstance(e, dict) for e in rows):
        raise ValueError("invalid device entities")
    return rows


def one(values):
    if len(values) != 1:
        raise ValueError("expected one device or mount path")
    value = values[0]
    if not isinstance(value, str) or not value.startswith("/") or "\n" in value:
        raise ValueError("invalid absolute device or mount path")
    return value


def parent(image):
    return one([e["dev-entry"] for e in entities(image)
                if isinstance(e.get("dev-entry"), str) and DEVICE.fullmatch(e["dev-entry"])])


def mount(image):
    return one([e["mount-point"] for e in entities(image) if e.get("mount-point")])


def images(path):
    rows = read(path).get("images")
    if not isinstance(rows, list) or any(not isinstance(i, dict) for i in rows):
        raise ValueError("invalid image snapshot")
    for image in rows:
        entities(image)
    return rows


def same_image(image, target):
    path = image.get("image-path")
    if not isinstance(path, str):
        return False
    try:
        return os.path.samefile(path, target)
    except OSError:
        return Path(path).resolve() == Path(target).resolve()


def main(args):
    mode = args[0]
    if mode in ("device", "mount"):
        image = read(args[1])
        print(parent(image) if mode == "device" else mount(image))
    elif mode == "free":
        if any(same_image(i, args[2]) for i in images(args[1])):
            raise ValueError("target image was already attached; no attach/detach attempted")
    elif mode == "owned":
        before = images(args[1])
        old = {e["dev-entry"] for i in before for e in entities(i)
               if isinstance(e.get("dev-entry"), str) and DEVICE.fullmatch(e["dev-entry"])}
        after = images(args[2])
        new = {parent(i) for i in after if same_image(i, args[3])} - old
        if len(new) > 1:
            raise ValueError("multiple new target devices; ownership is uncertain")
        print(next(iter(new)) if new else "")
    elif mode == "owned-mount":
        selected = [i for i in images(args[1])
                    if same_image(i, args[2]) and parent(i) == args[3]]
        if len(selected) != 1:
            raise ValueError("owned image missing or ambiguous in post-attach snapshot")
        print(mount(selected[0]))
    else:
        raise ValueError("unknown receipt operation")


if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except (KeyError, IndexError, TypeError, ValueError, OSError, plistlib.InvalidFileException) as exc:
        print(f"mount receipt: {exc}", file=sys.stderr)
        sys.exit(1)
