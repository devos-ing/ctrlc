#!/usr/bin/env python3
"""Local screenshot measurements, heuristic component grouping, and compact packets."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import platform
import re
import shutil
import subprocess
import time
from typing import Any, Mapping

import numpy as np
from PIL import Image, ImageOps

HERE = Path(__file__).resolve().parent
ASSETS = HERE / "assets"
VERSION = 1


class InvalidOCRDataError(ValueError):
    """Caller-supplied OCR data is not in the supported JSON shape."""


def compact(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def parse_roi(value):
    try:
        box = [int(part) for part in value.split(",")]
    except ValueError as error:
        raise argparse.ArgumentTypeError("ROI must be x,y,width,height integers") from error
    if len(box) != 4 or min(box) < 0 or box[2] == 0 or box[3] == 0:
        raise argparse.ArgumentTypeError("ROI needs nonnegative x,y and positive width,height")
    return box


def dominant(pixels):
    pixels = np.asarray(pixels).reshape(-1, 3)
    if not len(pixels):
        raise ValueError("Cannot measure an empty pixel region")
    # Sample exact colors deterministically; anti-aliased edge colors stay distinct.
    samples = pixels[::max(1, len(pixels) // 20000)]
    colors, counts = np.unique(samples, axis=0, return_counts=True)
    return colors[np.argmax(counts)]


def hex_color(color):
    return "#" + "".join(f"{int(channel):02x}" for channel in color)


def components(mask):
    """8-connected boxes with run-length union/find, avoiding per-pixel Python work."""
    parent, boxes, areas = [], [], []
    previous = []

    def find(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    for y, row in enumerate(mask):
        edges = np.diff(np.r_[False, row, False].astype(np.int8))
        runs = list(zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)))
        current = []
        pointer = 0
        for left, right in runs:
            left, right = int(left), int(right)
            while pointer < len(previous) and previous[pointer][1] < left:
                pointer += 1
            neighbors, index = [], pointer
            while index < len(previous) and previous[index][0] <= right:
                neighbors.append(find(previous[index][2]))
                index += 1
            if neighbors:
                root = min(neighbors)
                for other in set(neighbors):
                    if other != root:
                        parent[other] = root
                        b = boxes[other]
                        boxes[root] = [min(boxes[root][0], b[0]), min(boxes[root][1], b[1]),
                                       max(boxes[root][2], b[2]), max(boxes[root][3], b[3])]
                        areas[root] += areas[other]
                b = boxes[root]
                boxes[root] = [min(b[0], left), b[1], max(b[2], right), y + 1]
                areas[root] += right - left
            else:
                root = len(parent)
                parent.append(root)
                boxes.append([left, y, right, y + 1])
                areas.append(right - left)
            current.append((left, right, root))
        previous = current
    return [(b[0], b[1], b[2] - b[0], b[3] - b[1], areas[i])
            for i, b in enumerate(boxes) if find(i) == i]


def contains(outer, inner):
    x, y, w, h = outer
    cx, cy = inner[0] + inner[2] / 2, inner[1] + inner[3] / 2
    return x <= cx <= x + w and y <= cy <= y + h


def union(boxes):
    x = min(box[0] for box in boxes)
    y = min(box[1] for box in boxes)
    right = max(box[0] + box[2] for box in boxes)
    bottom = max(box[1] + box[3] for box in boxes)
    return [x, y, right - x, bottom - y]


def label(region):
    region = dict(region)
    # OCR sometimes reads a provider icon as a character before the button label.
    match = re.search(r"continue\s+with\s+\S", region["text"], re.I)
    if match and match.start() > 0:
        region["rawText"] = region["text"]
        region["text"] = region["text"][match.start():]
        words = region.get("words", [])
        start = next((i for i, word in enumerate(words)
                      if word["text"].lower() == "continue"), None)
        if start is not None:
            region["box"] = union([word["box"] for word in words[start:]])
    return region


def native_ocr(image_path, cache, languages):
    if platform.system() != "Darwin" or not shutil.which("swiftc"):
        raise ValueError("Native OCR needs macOS and swiftc; alternatively pass --ocr-json")
    source = ASSETS / "vision_ocr.swift"
    digest = hashlib.sha256(source.read_bytes() + platform.mac_ver()[0].encode()).hexdigest()[:16]
    binary = cache / ("vision-ocr-" + digest)
    if not binary.exists():
        subprocess.run(["swiftc", "-O", str(source), "-o", str(binary)],
                       check=True, capture_output=True, text=True, timeout=120)
    result = subprocess.run([str(binary), str(image_path), languages], check=True,
                            capture_output=True, text=True, timeout=120)
    return json.loads(result.stdout)


def validate_ocr(ocr, size):
    if not isinstance(ocr, Mapping):
        raise InvalidOCRDataError("OCR JSON must be an object")
    if [ocr.get("width"), ocr.get("height")] != list(size):
        raise InvalidOCRDataError("OCR dimensions must match the cropped, orientation-corrected image")
    if not isinstance(ocr.get("texts"), list):
        raise InvalidOCRDataError("OCR JSON must contain a texts array")
    for region in ocr["texts"]:
        if not isinstance(region, Mapping):
            raise InvalidOCRDataError("Each OCR text must be an object")
        box = region.get("box")
        if (not isinstance(region.get("text"), str) or not isinstance(box, list)
                or len(box) != 4 or any(not isinstance(n, (int, float)) for n in box)
                or min(box) < 0 or box[0] + box[2] > size[0]
                or box[1] + box[3] > size[1]):
            raise InvalidOCRDataError("Each OCR text needs a string and an in-bounds top-left pixel box")


def extract(image, ocr):
    full = np.asarray(image.convert("RGB"))
    width, height = image.size
    scale = min(1.0, 640 / width)
    small = image.resize((round(width * scale), round(height * scale)), Image.Resampling.BILINEAR)
    pixels = np.asarray(small.convert("RGB")).astype(np.int16)
    background = dominant(full)
    mask = np.max(np.abs(pixels - background.astype(np.int16)), axis=2) >= 12
    shapes = components(mask)
    boxes = []
    for x, y, w, h, area in shapes:
        if w >= small.width * .45 and small.width * .05 <= h <= small.width * .24:
            candidate = [round(x / scale), round(y / scale),
                          min(width - round(x / scale), round(w / scale)),
                          min(height - round(y / scale), round(h / scale))]
            # Refine raster bounds at full resolution along the control's central axes.
            cx, cy, cw, ch = candidate
            left, right = max(0, cx - 8), min(width, cx + cw + 8)
            top, bottom = max(0, cy - 8), min(height, cy + ch + 8)
            horizontal = np.flatnonzero(np.max(np.abs(full[cy + ch // 2, left:right].astype(np.int16)
                                         - background.astype(np.int16)), axis=1) >= 12)
            vertical = np.flatnonzero(np.max(np.abs(full[top:bottom, cx + cw // 2].astype(np.int16)
                                       - background.astype(np.int16)), axis=1) >= 12)
            if len(horizontal) and len(vertical):
                candidate = [left + int(horizontal[0]), top + int(vertical[0]),
                             int(horizontal[-1] - horizontal[0] + 1),
                             int(vertical[-1] - vertical[0] + 1)]
            boxes.append(candidate)
    regions = [label(item) for item in ocr["texts"]]
    nodes, styles, assigned = [], {}, set()

    def register_style(style):
        for name, existing in styles.items():
            a, b = dict(style), dict(existing)
            ra, rb = a.pop("cornerRadiusPxEstimate", None), b.pop("cornerRadiusPxEstimate", None)
            ba, bb = a.pop("border", None), b.pop("border", None)
            radii_match = ra == rb or (ra is not None and rb is not None and abs(ra - rb) <= 4)
            borders_match = ba == bb
            if ba and bb and ba["widthPx"] == bb["widthPx"]:
                borders_match = max(abs(int(ba["color"][i:i + 2], 16)
                                        - int(bb["color"][i:i + 2], 16)) for i in (1, 3, 5)) <= 6
            if a == b and radii_match and borders_match:
                return name
        name = "s-" + hashlib.sha256(compact(style).encode()).hexdigest()[:8]
        styles[name] = style
        return name

    def text_node(region):
        x, y, w, h = map(int, region["box"])
        patch = full[y:y + h, x:x + w]
        fill = dominant(patch) if patch.size else background
        ink = patch[np.max(np.abs(patch.astype(np.int16) - fill.astype(np.int16)), axis=2) > 40]
        color = hex_color(dominant(ink)) if len(ink) else None
        return {"type": "text", "text": region["text"], "box": region["box"],
                "styleRef": register_style({"textColor": color, "fontFamily": None,
                                             "fontSizePx": None, "fontWeight": None}),
                "inkHeightPx": h, "ocrConfidence": region.get("confidence"),
                "evidence": "ocr", **({"rawText": region["rawText"],
                                         "labelNormalization": "heuristic"}
                                        if "rawText" in region else {})}

    for box in sorted(boxes, key=lambda b: (b[1], b[0])):
        items = [(i, region) for i, region in enumerate(regions) if contains(box, region["box"])]
        if not items:
            continue
        assigned.update(i for i, _ in items)
        x, y, w, h = box
        patch = full[y:y + h, x:x + w]
        fill = dominant(patch)
        outlined = int(np.max(np.abs(fill.astype(np.int16) - background.astype(np.int16)))) < 8
        inner_mask = np.max(np.abs(patch.astype(np.int16) - fill.astype(np.int16)), axis=2) > 20
        inset = max(5, round(w * .01))
        inner_mask[:inset] = inner_mask[-inset:] = False
        inner_mask[:, :inset] = inner_mask[:, -inset:] = False
        for _, region in items:
            tx, ty, tw, th = map(int, region["box"])
            inner_mask[max(0, ty - y - 3):min(h, ty - y + th + 3),
                       max(0, tx - x - 3):min(w, tx - x + tw + 3)] = False
        icons = [{"type": "image", "box": [x + ix, y + iy, iw, ih],
                  "role": "icon", "evidence": "pixel-region"}
                 for ix, iy, iw, ih, area in components(inner_mask)
                 if iw >= width * .008 and ih >= width * .008 and area >= 40
                 and iw <= w * .2 and ih <= h * .9]
        # Merge a detached icon leaf or tiny adjacent graphic piece into its asset bounds.
        icons.sort(key=lambda node: node["box"][0])
        merged = []
        for icon in icons:
            if merged and icon["box"][0] <= merged[-1]["box"][0] + merged[-1]["box"][2] + 5:
                merged[-1]["box"] = union([merged[-1]["box"], icon["box"]])
            else:
                merged.append(icon)
        text = " ".join(region["text"] for _, region in items)
        kind = "input" if re.search(r"\S+@\S+\.\S+", text) else "button" if re.search(
            r"\b(continue|sign in|log in|sign up|submit|next|start)\b", text, re.I) else "container"
        children = [text_node(region) for _, region in items] + merged
        border = None
        if outlined:
            edge_pixels = np.concatenate([patch[:inset].reshape(-1, 3),
                                          patch[-inset:].reshape(-1, 3),
                                          patch[:, :inset].reshape(-1, 3),
                                          patch[:, -inset:].reshape(-1, 3)])
            edge_pixels = edge_pixels[np.max(np.abs(edge_pixels.astype(np.int16)
                                        - fill.astype(np.int16)), axis=1) > 12]
            if len(edge_pixels):
                border = {"color": hex_color(dominant(edge_pixels)), "widthPx": None}
        row = np.max(np.abs(patch[min(3, h - 1)].astype(np.int16)
                           - background.astype(np.int16)), axis=1) >= 12
        hits = np.flatnonzero(row)
        offset = int(hits[0]) if len(hits) else 0
        radius = round((offset + 3 + math.sqrt(6 * offset)) / 4) * 4 if 0 < offset < h / 2 else None
        measured_style = {"fill": hex_color(fill), "border": border,
                          "cornerRadiusPxEstimate": radius}
        nodes.append({"type": kind, "box": box, "label": text,
                      "styleRef": register_style(measured_style), "styleMeasurements": measured_style,
                      "children": sorted(children, key=lambda n: (n["box"][0], n["box"][1])),
                      "evidence": "ocr+pixel-region", "roleInference": "heuristic"})

    for i, region in enumerate(regions):
        if i not in assigned:
            node = text_node(region)
            node["role"] = "separator" if region["text"].strip().lower() == "or" else "text"
            nodes.append(node)
    asset_mask = mask.copy()
    for box in boxes + [region["box"] for region in regions]:
        x, y, w, h = box
        left, top = max(0, int(x * scale) - 3), max(0, int(y * scale) - 3)
        right, bottom = min(small.width, round((x + w) * scale) + 3), min(small.height, round((y + h) * scale) + 3)
        asset_mask[top:bottom, left:right] = False
    for x, y, w, h, area in components(asset_mask):
        if w >= small.width * .025 and h >= small.width * .025 and area >= 40:
            nodes.append({"type": "image", "role": "unknown-asset",
                          "box": [round(x / scale), round(y / scale), round(w / scale), round(h / scale)],
                          "evidence": "pixel-region"})
    nodes.sort(key=lambda n: (n["box"][1], n["box"][0]))

    def identify(node, identity):
        node["id"] = identity
        for index, child in enumerate(node.get("children", []), 1):
            identify(child, f"{identity}.{index}")
    for index, node in enumerate(nodes, 1):
        identify(node, f"n{index}")
    return {"nodes": nodes, "styles": styles, "background": hex_color(background),
            "methods": {"styles": "Cluster border colors within 6/channel and radius estimates within 4px; retain node measurements.",
                        "radius": "Approximate circular-corner fit to edge pixels; not an original CSS radius."},
            "unknowns": ["Exact fonts, layout rules and behavior need inference.",
                         "Image regions identify pixels; original vectors and transparency are unknown.",
                         "Role inference targets simple stacked forms; inspect other layouts."]}


def packet(scene):
    def slim(node):
        result = {key: node[key] for key in ("id", "type", "displayName", "box", "text", "label", "role", "styleRef")
                  if key in node}
        if node.get("children"):
            result["children"] = [slim(child) for child in node["children"]]
        return result
    references = set()
    def collect(node):
        if node.get('styleRef'):
            references.add(node['styleRef'])
        for child in node.get('children', []):
            collect(child)
    for node in scene['nodes']:
        collect(node)
    return {"units": "ROI-relative screenshot pixels; font sizes unknown",
            "roi": scene["roi"], "nodes": [slim(node) for node in scene["nodes"]],
            "styles": {key: value for key, value in scene["styles"].items() if key in references}}


def run_extraction(image_path: str | Path, output_dir: str | Path, *,
                   roi: list[int] | None = None, languages: str = "en-US",
                   ocr_json_path: str | Path | None = None,
                   ocr_data: Mapping[str, Any] | None = None,
                   refresh: bool = False, inspector: bool = False) -> dict[str, Any]:
    """Extract a screenshot into saved scene, packet, run, and optional HTML files.

    Callers may provide OCR as JSON on disk or as an already loaded mapping.
    The returned summary includes absolute artifact paths; no model or network
    calls are made by this local workflow.
    """
    if ocr_json_path is not None and ocr_data is not None:
        raise ValueError("Pass either ocr_json_path or ocr_data, not both")
    if roi is not None:
        if (not isinstance(roi, (list, tuple)) or len(roi) != 4
                or any(type(value) is not int for value in roi)
                or min(roi[:2]) < 0 or min(roi[2:]) <= 0):
            raise ValueError("ROI needs nonnegative x,y and positive width,height integers")

    image_path = Path(image_path)
    output_dir = Path(output_dir)
    ocr_path = Path(ocr_json_path) if ocr_json_path is not None else None
    started = time.monotonic()
    output_dir.mkdir(parents=True, exist_ok=True)
    cache = output_dir / ".cache"
    cache.mkdir(exist_ok=True)
    source = image_path.read_bytes()
    ocr_source_hash = None
    if ocr_path is not None:
        ocr_source_hash = hashlib.sha256(ocr_path.read_bytes()).hexdigest()
    elif ocr_data is not None:
        ocr_source_hash = hashlib.sha256(compact(ocr_data).encode()).hexdigest()
    config = {"version": VERSION, "roi": roi, "languages": languages,
              "code": hashlib.sha256(Path(__file__).read_bytes()
                                     + (ASSETS / "vision_ocr.swift").read_bytes()).hexdigest(),
              "ocrSource": ocr_source_hash,
              "platform": platform.mac_ver()[0]}
    key = hashlib.sha256(source + compact(config).encode()).hexdigest()
    cached = cache / (key + ".json")
    hit = cached.exists() and not refresh
    if hit:
        scene = json.loads(cached.read_text())
    else:
        with Image.open(image_path) as raw:
            if raw.format not in ("PNG", "JPEG", "WEBP"):
                raise ValueError("Use a still PNG, JPEG or WebP screenshot")
            upright = ImageOps.exif_transpose(raw).convert("RGB")
        x, y, w, h = roi or [0, 0, *upright.size]
        if x + w > upright.width or y + h > upright.height:
            raise ValueError("ROI extends outside the orientation-corrected image")
        image = upright.crop((x, y, x + w, y + h))
        crop_path = cache / (key + ".png")
        image.save(crop_path)
        try:
            if ocr_path is not None:
                ocr = json.loads(ocr_path.read_text())
            elif ocr_data is not None:
                ocr = dict(ocr_data)
            else:
                ocr = native_ocr(crop_path, cache, languages)
            validate_ocr(ocr, image.size)
            scene = {"schemaVersion": VERSION, "sourceSha256": hashlib.sha256(source).hexdigest(),
                     "imageSize": list(upright.size), "roi": [x, y, w, h],
                     "coordinates": "Top-left origin, ROI-relative pixels after EXIF orientation",
                     "llmCalls": 0, **extract(image, ocr)}
            cached.write_text(compact(scene))
        finally:
            crop_path.unlink(missing_ok=True)
    scene_path = output_dir / "scene.json"
    packet_path = output_dir / "packet.json"
    run_path = output_dir / "run.json"
    scene_path.write_text(json.dumps(scene, ensure_ascii=False, indent=2) + "\n")
    encoded = compact(packet(scene))
    packet_path.write_text(encoded + "\n")
    artifacts = {"scene": str(scene_path.resolve()), "packet": str(packet_path.resolve()),
                 "run": str(run_path.resolve())}
    if inspector:
        from .rendering import render
        inspector_path = output_dir / "inspector.html"
        inspector_path.write_text(render(scene_path, image_path))
        artifacts["inspector"] = str(inspector_path.resolve())
    report = {"cacheHit": hit, "llmCalls": 0, "modelTokens": 0,
              "components": len(scene["nodes"]), "packetBytes": len(encoded.encode()),
              "elapsedSeconds": round(time.monotonic() - started, 3),
              "output": str(output_dir.resolve())}
    run_path.write_text(json.dumps(report, indent=2) + "\n")
    return {**report, "artifacts": artifacts}
