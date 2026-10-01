"""Deterministic, local hierarchy passes over saved screenshot evidence."""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Mapping

import numpy as np
from PIL import Image


HIERARCHY_VERSION = 21
MEASUREMENT_VERSION = 14
MAX_DEPTH = 3


class InvalidHierarchyError(ValueError):
    """Saved measurement or hierarchy data is malformed or inconsistent."""


def compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _box_valid(box: Any) -> bool:
    return (isinstance(box, list) and len(box) == 4
            and all(type(number) in (int, float) for number in box)
            and box[0] >= 0 and box[1] >= 0 and box[2] > 0 and box[3] > 0)


def box_union(boxes: list[list[float]]) -> list[float]:
    if not boxes:
        raise InvalidHierarchyError("Cannot build a group without evidence bounds")
    left = min(box[0] for box in boxes)
    top = min(box[1] for box in boxes)
    right = max(box[0] + box[2] for box in boxes)
    bottom = max(box[1] + box[3] for box in boxes)
    return [left, top, right - left, bottom - top]


def fully_contains(outer: list[float], inner: list[float], tolerance: float = 0) -> bool:
    return (outer[0] <= inner[0] + tolerance and outer[1] <= inner[1] + tolerance
            and outer[0] + outer[2] >= inner[0] + inner[2] - tolerance
            and outer[1] + outer[3] >= inner[1] + inner[3] - tolerance)


def _evidence_id(source_hash: str, legacy_id: str, node: Mapping[str, Any]) -> str:
    signature = {key: node.get(key) for key in ("type", "role", "box", "text", "label", "evidence")}
    digest = sha256((source_hash + "\n" + legacy_id + "\n" + compact(signature)).encode())[:14]
    return "ev-" + digest


def _flatten_nodes(nodes: list[dict[str, Any]], source_hash: str) -> list[dict[str, Any]]:
    flattened: list[dict[str, Any]] = []

    def visit(node: dict[str, Any], parent_id: str | None, path: str) -> str:
        if not isinstance(node, dict) or not _box_valid(node.get("box")):
            raise InvalidHierarchyError("Every measured candidate must have a positive pixel box")
        legacy_id = str(node.get("id", path))
        evidence_id = _evidence_id(source_hash, legacy_id, node)
        child_ids = []
        for index, child in enumerate(node.get("children", [])):
            child_ids.append(visit(child, evidence_id, f"{path}.{index + 1}"))
        candidate = {key: value for key, value in node.items() if key not in ("children", "id")}
        flattened.append({"evidenceId": evidence_id, "legacyId": legacy_id,
                          "parentEvidenceId": parent_id, "childEvidenceIds": child_ids,
                          "node": candidate})
        return evidence_id

    for index, node in enumerate(nodes):
        visit(node, None, f"nodes.{index + 1}")
    # `visit` adds parents after children. Store records in a stable visual order.
    flattened.sort(key=lambda item: (item["node"]["box"][1], item["node"]["box"][0],
                                     item["evidenceId"]))
    return flattened


def _surface_regions(image: Image.Image, background: str, source_hash: str) -> list[dict[str, Any]]:
    """Save broad fill and connected-edge candidates as reusable pixel evidence."""
    pixels = np.asarray(image.convert("RGB"))
    height, width = pixels.shape[:2]
    if width > 800:
        scale = 800 / width
        image = image.resize((800, max(1, round(height * scale))), Image.Resampling.BILINEAR)
        pixels = np.asarray(image.convert("RGB"))
    small_height, small_width = pixels.shape[:2]
    try:
        color = np.array([int(background[index:index + 2], 16) for index in (1, 3, 5)])
    except (TypeError, ValueError):
        color = np.array([255, 255, 255])
    found: list[dict[str, Any]] = []
    from .extraction import components
    distance = np.max(np.abs(pixels.astype(np.int16) - color.astype(np.int16)), axis=2)
    scale_x, scale_y = width / small_width, height / small_height
    contrast_mask = distance >= 5
    for left, top, region_width, region_height, area in components(contrast_mask):
        if (region_width < small_width * 0.42 or region_height < small_width * 0.045
                or region_height > small_height * 0.45 or area < small_width * small_height * 0.001):
            continue
        box = [max(0, round(left * scale_x)), max(0, round(top * scale_y)),
               min(width, round((left + region_width) * scale_x)) - max(0, round(left * scale_x)),
               min(height, round((top + region_height) * scale_y)) - max(0, round(top * scale_y))]
        patch = pixels[top:top + region_height, left:left + region_width]
        fill_value = np.median(patch.reshape(-1, 3), axis=0)
        fill = "#" + "".join(f"{int(value):02x}" for value in fill_value)
        coherence = float(np.mean(np.max(np.abs(patch.astype(np.int16) - fill_value.astype(np.int16)), axis=2) <= 6))
        signature = compact({"box": box, "fill": fill, "method": "low-contrast-connected-region"})
        found.append({"evidenceId": "px-" + sha256((source_hash + signature).encode())[:14],
                      "box": box, "fill": fill, "coherence": round(coherence, 4),
                      "method": "low-contrast-connected-region"})

    rgb = pixels.astype(np.int16)
    threshold = 3
    edge_y = np.max(np.abs(rgb[1:, :, :] - rgb[:-1, :, :]), axis=2) >= threshold
    edge_x = np.max(np.abs(rgb[:, 1:, :] - rgb[:, :-1, :]), axis=2) >= threshold
    edge_mask = np.zeros((small_height, small_width), dtype=bool)
    edge_mask[1:, :] |= edge_y
    edge_mask[:, 1:] |= edge_x
    for left, top, region_width, region_height, area in components(edge_mask):
        if (region_width < small_width * 0.42 or region_height < small_width * 0.045
                or region_height > small_height * 0.50
                or area < (region_width + region_height) * 1.2):
            continue
        box = [max(0, round(left * scale_x)), max(0, round(top * scale_y)),
               min(width, round((left + region_width) * scale_x)) - max(0, round(left * scale_x)),
               min(height, round((top + region_height) * scale_y)) - max(0, round(top * scale_y))]
        if any(existing["box"] == box and existing.get("method") == "connected-edge-contour" for existing in found):
            continue
        interior = pixels[top:min(small_height, top + region_height),
                          left:min(small_width, left + region_width)].astype(np.int16)
        fill_value = np.median(interior.reshape(-1, 3), axis=0) if interior.size else np.array([255, 255, 255])
        fill = "#" + "".join(f"{int(value):02x}" for value in fill_value)
        coherence = float(np.mean(np.max(np.abs(interior - fill_value.astype(np.int16)), axis=2) <= 6)) if interior.size else 0.0
        signature = compact({"box": box, "fill": fill, "method": "connected-edge-contour"})
        found.append({"evidenceId": "px-" + sha256((source_hash + signature).encode())[:14],
                      "box": box, "fill": fill, "coherence": round(coherence, 4),
                      "edgePixels": area, "method": "connected-edge-contour"})
    found.sort(key=lambda item: (item["box"][1], item["box"][0]))
    return found


def _local_pixel_regions(image: Image.Image, background: str,
                         surfaces: list[dict[str, Any]], source_hash: str) -> list[dict[str, Any]]:
    """Measure large child regions by contrast against a verified parent's local fill."""
    from .extraction import components

    pixels = np.asarray(image.convert("RGB"))
    image_height, image_width = pixels.shape[:2]
    try:
        page_fill = np.array([int(background[index:index + 2], 16) for index in (1, 3, 5)])
    except (TypeError, ValueError):
        page_fill = np.array([255, 255, 255])
    regions = []
    for surface in surfaces:
        if (surface.get("method") != "connected-edge-contour"
                or surface.get("coherence", 0) < 0.50
                or surface["box"][2] < image_width * 0.70):
            continue
        try:
            fill = np.array([int(surface["fill"][index:index + 2], 16) for index in (1, 3, 5)])
        except (TypeError, ValueError, KeyError):
            continue
        if int(np.max(np.abs(fill - page_fill))) < 40:
            continue
        sx, sy, sw, sh = map(int, surface["box"])
        crop = pixels[sy:sy + sh, sx:sx + sw]
        if crop.size == 0:
            continue
        mask = np.max(np.abs(crop.astype(np.int16) - fill.astype(np.int16)), axis=2) >= 24
        parent_area = sw * sh
        for left, top, width, height, area in components(mask):
            if (width < max(32, sw * 0.055) or height < max(24, sw * 0.035)
                    or area < max(300, parent_area * 0.002)
                    or area >= parent_area * 0.70
                    or (width >= sw * 0.82 and height >= sh * 0.82)):
                continue
            box = [sx + left, sy + top, width, height]
            interior = crop[top:top + height, left:left + width]
            child_fill = np.median(interior.reshape(-1, 3), axis=0)
            child_fill_hex = "#" + "".join(f"{int(value):02x}" for value in child_fill)
            clipped = []
            if left <= 1:
                clipped.append("left")
            if top <= 1:
                clipped.append("top")
            if left + width >= sw - 1:
                clipped.append("right")
            if top + height >= sh - 1:
                clipped.append("bottom")
            signature = {"parentEvidenceId": surface["evidenceId"], "box": box,
                         "fill": child_fill_hex, "method": "local-background-component"}
            regions.append({"evidenceId": "lc-" + sha256((source_hash + compact(signature)).encode())[:14],
                            "parentEvidenceIds": [surface["evidenceId"]],
                            "box": box, "fill": child_fill_hex,
                            "method": "local-background-component",
                            "contrastThreshold": 24, "areaPixels": int(area),
                            "clippedAtParent": clipped})
    regions.sort(key=lambda item: (item["box"][1], item["box"][0], item["evidenceId"]))
    return regions


def _group_surface_contours(regions: list[dict[str, Any]], image_size: list[int]) -> list[dict[str, Any]]:
    """Join overlapping contours as evidence groups without changing raw records."""
    width, height = image_size
    groups: list[dict[str, Any]] = []
    for region in regions:
        box = region["box"]
        if (region.get("method") != "connected-edge-contour"
                or box[2] < width * 0.70 or region.get("coherence", 0) < 0.50):
            continue
        if (_area(box) >= width * height * 0.62
                or (box[2] >= width * 0.92 and box[3] >= height * 0.48)):
            continue
        selected = None
        for group in groups:
            outer = group["box"]
            horizontal_overlap = max(0, min(outer[0] + outer[2], box[0] + box[2]) - max(outer[0], box[0]))
            min_width = max(1, min(outer[2], box[2]))
            same_fill = bool(group.get("fill") and region.get("fill") and
                             max(abs(int(group["fill"][index:index + 2], 16)
                                     - int(region["fill"][index:index + 2], 16))
                                 for index in (1, 3, 5)) <= 20)
            vertical_overlap = max(0, min(outer[1] + outer[3], box[1] + box[3]) - max(outer[1], box[1]))
            dimensions_match = (abs(outer[0] - box[0]) <= width * 0.035
                                and abs(outer[2] - box[2]) <= width * 0.07)
            duplicate = (_box_iou(outer, box) >= 0.80 and dimensions_match and same_fill
                         and horizontal_overlap / min_width >= 0.80
                         and vertical_overlap >= min(outer[3], box[3]) * 0.80)
            if duplicate:
                selected = group
                break
        if selected is None:
            groups.append({"box": list(box), "fill": region.get("fill"),
                           "evidenceIds": [region["evidenceId"]], "contours": [region]})
        else:
            selected["box"] = box_union([selected["box"], box])
            selected["evidenceIds"].append(region["evidenceId"])
            selected["contours"].append(region)
    for group in groups:
        group["boundsMethod"] = "measured-contour" if len(group["evidenceIds"]) == 1 else "union-of-measured-contours"
    return groups


def make_measurements(*, source_hash: str, image_size: list[int], roi: list[int],
                      ocr: Mapping[str, Any], provider: Mapping[str, Any],
                      measured_scene: Mapping[str, Any], image: Image.Image) -> dict[str, Any]:
    """Freeze the measured pixel/OCR evidence used by later grouping passes."""
    nodes = measured_scene.get("nodes")
    if not isinstance(nodes, list):
        raise InvalidHierarchyError("Measured scene must contain a nodes array")
    candidates = _flatten_nodes(nodes, source_hash)
    pixel_regions = _surface_regions(image, measured_scene.get("background", "#ffffff"), source_hash)
    local_regions = _local_pixel_regions(image, measured_scene.get("background", "#ffffff"),
                                         pixel_regions, source_hash)
    measurement = {
        "schemaVersion": 1,
        "measurementVersion": MEASUREMENT_VERSION,
        "sourceSha256": source_hash,
        "imageSize": list(image_size),
        "roi": list(roi),
        "coordinates": "Top-left origin, ROI-relative pixels after EXIF orientation",
        "ocrProvider": dict(provider),
        "ocr": json.loads(compact(ocr)),
        "candidates": candidates,
        "pixelRegions": pixel_regions,
        "localRegions": local_regions,
        "measuredScene": json.loads(compact(measured_scene)),
        "unknowns": list(measured_scene.get("unknowns", [])),
    }
    measurement["evidenceSha256"] = sha256(compact(measurement).encode())
    return measurement


def _group_id(level: int, evidence_refs: list[str]) -> str:
    digest = sha256((str(level) + "\n" + "\n".join(sorted(evidence_refs))).encode())[:14]
    return f"g{level}-" + digest


def _node_text(node: Mapping[str, Any]) -> list[str]:
    text = []
    if isinstance(node.get("text"), str) and node["text"].strip():
        text.append(node["text"].strip())
    if isinstance(node.get("label"), str) and node["label"].strip():
        text.append(node["label"].strip())
    for child in node.get("children", []):
        text.extend(_node_text(child))
    return text


def _root_text(root: Mapping[str, Any]) -> list[str]:
    values = _node_text(root["node"])
    for child in root.get("compoundChildren", []):
        values.extend(_node_text(child))
    return values


def _area(box: list[float]) -> float:
    return box[2] * box[3]


def _box_iou(first: list[float], second: list[float]) -> float:
    left = max(first[0], second[0])
    top = max(first[1], second[1])
    right = min(first[0] + first[2], second[0] + second[2])
    bottom = min(first[1] + first[3], second[1] + second[3])
    intersection = max(0, right - left) * max(0, bottom - top)
    total = _area(first) + _area(second) - intersection
    return intersection / total if total else 0.0


def _is_page_residual(node: Mapping[str, Any], size: list[int], other_count: int) -> bool:
    box = node["box"]
    return (node.get("type") == "image" and node.get("role") == "unknown-asset"
            and _area(box) >= size[0] * size[1] * 0.38
            and (box[3] >= size[1] * 0.42 or box[2] >= size[0] * 0.92)
            and other_count >= 3)


def _root_records(measurement: Mapping[str, Any]) -> tuple[list[dict[str, Any]], dict[str, str]]:
    source_hash = measurement["sourceSha256"]
    all_by_legacy = {item["legacyId"]: item for item in measurement["candidates"]}
    scene = measurement["measuredScene"]
    roots = []
    dispositions: dict[str, str] = {}
    image_size = measurement["roi"][2:]

    def overlay_like(node: Mapping[str, Any]) -> bool:
        box = node["box"]
        return (node.get("type") == "container" and len(node.get("children", [])) >= 4
                and box[1] >= image_size[1] * 0.72
                and box[2] >= image_size[0] * 0.55)

    def add(node: Mapping[str, Any], parent_candidate: Mapping[str, Any] | None = None) -> None:
        legacy_id = str(node.get("id", ""))
        record = all_by_legacy[legacy_id]
        children = list(node.get("children", []))
        valid_children = all(fully_contains(node["box"], child["box"]) for child in children)
        if children and not valid_children:
            dispositions[record["evidenceId"]] = "measured parent was flattened because it does not fully contain every child"
            group_box = box_union([node["box"], *[child["box"] for child in children]])
            is_overlay = overlay_like(node)
            roots.append({"record": record, "node": {**node, "children": []},
                          "splitChildren": children, "compoundChildren": children,
                          "groupBox": group_box, "independentOverlay": is_overlay})
            return
        roots.append({"record": record, "node": node, "splitChildren": [],
                      "independentOverlay": overlay_like(node)})

    for node in scene.get("nodes", []):
        add(node)
    filtered = []
    for root in roots:
        node = root["node"]
        if _is_page_residual(node, image_size, len(roots)):
            dispositions[root["record"]["evidenceId"]] = "omitted: page-spanning residual crosses multiple UI regions"
        else:
            filtered.append(root)
    return filtered, dispositions


def _surface_members(roots: list[dict[str, Any]], regions: list[dict[str, Any]],
                     roi_height: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    assigned: set[str] = set()
    groups: list[dict[str, Any]] = []
    overlays = [root for root in roots if root.get("independentOverlay")]
    for root in overlays:
        box = root.get("groupBox", root["node"]["box"])
        center_y = box[1] + box[3] / 2
        members = [root]
        for candidate in roots:
            if candidate is root:
                continue
            identity = candidate["record"]["evidenceId"]
            candidate_box = candidate.get("groupBox", candidate["node"]["box"])
            center_x = candidate_box[0] + candidate_box[2] / 2
            candidate_y = candidate_box[1] + candidate_box[3] / 2
            if (identity not in assigned and candidate_box[3] <= roi_height * 0.09
                    and abs(candidate_y - center_y) <= roi_height * 0.08
                    and box[0] - box[2] * 0.04 <= center_x <= box[0] + box[2] * 1.04):
                members.append(candidate)
                assigned.add(identity)
        groups.append({"members": members, "region": None, "overlay": True})
        assigned.add(root["record"]["evidenceId"])
    for region in sorted(regions, key=lambda item: _area(item["box"])):
        box = region["box"]
        members = []
        for root in roots:
            identity = root["record"]["evidenceId"]
            root_box = root.get("groupBox", root["node"]["box"])
            center = [root_box[0] + root_box[2] / 2, root_box[1] + root_box[3] / 2]
            horizontal_overlap = max(0, min(box[0] + box[2], root_box[0] + root_box[2])
                                     - max(box[0], root_box[0]))
            overlap_area = horizontal_overlap * max(0, min(box[1] + box[3], root_box[1] + root_box[3])
                                                   - max(box[1], root_box[1]))
            child_area = max(1, root_box[2] * root_box[3])
            full_enclosure = fully_contains(box, root_box, tolerance=2)
            supported_extension = center[0] >= box[0] and center[0] <= box[0] + box[2]
            supported_extension = supported_extension and center[1] >= box[1] and center[1] <= box[1] + box[3]
            supported_extension = supported_extension and overlap_area / child_area >= 0.80
            if identity not in assigned and (full_enclosure or supported_extension):
                members.append(root)
        if len(members) >= 2:
            groups.append({"members": members, "region": region})
            assigned.update(root["record"]["evidenceId"] for root in members)
    return groups, [root for root in roots if root["record"]["evidenceId"] not in assigned]


def _floating_row_groups(roots: list[dict[str, Any]], roi_size: list[int],
                        surfaces: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Keep a compact control row independent when it overlays a larger surface."""
    width, height = roi_size
    small = []
    for root in roots:
        box = root.get("groupBox", root["node"]["box"])
        if box[3] <= height * 0.07 and box[2] <= width * 0.15:
            small.append(root)
    small.sort(key=lambda root: (root.get("groupBox", root["node"]["box"])[1]
                                 + root.get("groupBox", root["node"]["box"])[3] / 2,
                                 root.get("groupBox", root["node"]["box"])[0]))
    bands: list[list[dict[str, Any]]] = []
    for root in small:
        box = root.get("groupBox", root["node"]["box"])
        center_y = box[1] + box[3] / 2
        band = next((item for item in reversed(bands)
                     if center_y - (item[-1].get("groupBox", item[-1]["node"]["box"])[1]
                                    + item[-1].get("groupBox", item[-1]["node"]["box"])[3] / 2) <= height * 0.04), None)
        if band is None:
            bands.append([root])
        else:
            band.append(root)
    grouped: list[dict[str, Any]] = []
    assigned: set[str] = set()
    for band in bands:
        if len(band) < 4:
            continue
        boxes = [root.get("groupBox", root["node"]["box"]) for root in band]
        band_box = box_union(boxes)
        centers = [box[0] + box[2] / 2 for box in boxes]
        center_y = band_box[1] + band_box[3] / 2
        if center_y < height * 0.74:
            continue
        if max(centers) - min(centers) < width * 0.25:
            continue
        covered_by_large_surface = False
        for root in roots:
            if root in band:
                continue
            box = root.get("groupBox", root["node"]["box"])
            if _area(box) < width * height * 0.10 or not (box[1] <= center_y <= box[1] + box[3]):
                continue
            intersection = max(0, min(box[0] + box[2], band_box[0] + band_box[2]) - max(box[0], band_box[0]))
            if intersection >= band_box[2] * 0.25:
                covered_by_large_surface = True
                break
        if not covered_by_large_surface:
            for surface in surfaces:
                box = surface["box"]
                if _area(box) < width * height * 0.10 or not (box[1] <= center_y <= box[1] + box[3]):
                    continue
                intersection = max(0, min(box[0] + box[2], band_box[0] + band_box[2])
                                   - max(box[0], band_box[0]))
                if intersection >= band_box[2] * 0.25:
                    covered_by_large_surface = True
                    break
        if covered_by_large_surface:
            members = list(band)
            for parent in roots:
                if parent in band or not parent.get("independentOverlay"):
                    continue
                parent_box = parent.get("groupBox", parent["node"]["box"])
                parent_center_y = parent_box[1] + parent_box[3] / 2
                row_gap = max(0, max(parent_box[1] - (band_box[1] + band_box[3]),
                                     band_box[1] - (parent_box[1] + parent_box[3])))
                x_overlap = max(0, min(parent_box[0] + parent_box[2], band_box[0] + band_box[2])
                                - max(parent_box[0], band_box[0]))
                if (row_gap <= height * 0.08 and abs(parent_center_y - center_y) <= height * 0.08
                        and x_overlap >= band_box[2] * 0.5):
                    if band_box[2] < parent_box[2] * 0.70:
                        parent["omittedReason"] = "wide backdrop candidate omitted to preserve an independent floating control row"
                        assigned.add(parent["record"]["evidenceId"])
                    else:
                        members.append(parent)
                        assigned.add(parent["record"]["evidenceId"])
            grouped.append({"members": members, "region": None, "overlay": True, "floatingRow": True})
            assigned.update(root["record"]["evidenceId"] for root in band)
    return grouped, [root for root in roots if root["record"]["evidenceId"] not in assigned]


def _band_groups(roots: list[dict[str, Any]], image_width: int) -> list[dict[str, Any]]:
    if not roots:
        return []
    rows = sorted(roots, key=lambda root: (root.get("groupBox", root["node"]["box"])[1],
                                           root.get("groupBox", root["node"]["box"])[0]))
    threshold = max(18, image_width * 0.025)
    clusters: list[list[dict[str, Any]]] = [[rows[0]]]
    first_box = rows[0].get("groupBox", rows[0]["node"]["box"])
    current_bottom = first_box[1] + first_box[3]
    for root in rows[1:]:
        box = root.get("groupBox", root["node"]["box"])
        gap = box[1] - current_bottom
        if gap <= threshold:
            clusters[-1].append(root)
            current_bottom = max(current_bottom, box[1] + box[3])
        else:
            clusters.append([root])
            current_bottom = box[1] + box[3]
    return [{"members": cluster, "region": None} for cluster in clusters]


def _merge_content_bands(groups: list[dict[str, Any]], image_size: list[int]) -> list[dict[str, Any]]:
    """Join adjacent text rows and labels around a large media region into sections."""
    width, height = image_size
    groups = sorted(groups, key=lambda group: min(
        root.get("groupBox", root["node"]["box"])[1] for root in group["members"]))
    merged: list[dict[str, Any]] = []
    for group in groups:
        if not merged:
            merged.append(group)
            continue
        previous = merged[-1]
        previous_members = previous["members"]
        current_members = group["members"]
        previous_boxes = [root.get("groupBox", root["node"]["box"]) for root in previous_members]
        current_boxes = [root.get("groupBox", root["node"]["box"]) for root in current_members]
        first_box, second_box = box_union(previous_boxes), box_union(current_boxes)
        gap = max(0, second_box[1] - (first_box[1] + first_box[3]))
        first_kinds = {root["node"].get("type") for root in previous_members}
        second_kinds = {root["node"].get("type") for root in current_members}
        explicit_container = "container" in first_kinds or "container" in second_kinds
        wide_overlap = (max(0, min(first_box[0] + first_box[2], second_box[0] + second_box[2])
                            - max(first_box[0], second_box[0])) >= width * 0.20)
        text_rows = first_kinds == {"text"} and second_kinds == {"text"}
        combined_members = previous_members + current_members
        contains_media_text = (any(root["node"].get("type") == "image"
                                   and _area(root.get("groupBox", root["node"]["box"])) < width * height * 0.40
                                   and root.get("groupBox", root["node"]["box"])[3] >= height * 0.035
                                   for root in combined_members)
                               and any(root["node"].get("type") == "text" for root in combined_members))
        should_merge = (not explicit_container and wide_overlap and
                        ((text_rows and gap <= height * 0.045)
                         or (contains_media_text and gap <= height * 0.055)))
        if should_merge:
            previous["members"].extend(current_members)
        else:
            merged.append(group)
    return merged


def _form_groups(roots: list[dict[str, Any]], image_width: int, image_height: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Recognize header, credential, and separator-led provider regions in forms."""
    controls = [root for root in roots if root["node"].get("type") in {"input", "button"}]
    inputs = [root for root in controls if root["node"].get("type") == "input"]
    buttons = [root for root in controls if root["node"].get("type") == "button"]
    if len(roots) < 4 or not inputs or len(buttons) < 2:
        return [], roots
    boxes = [root.get("groupBox", root["node"]["box"]) for root in roots]
    centers = [box[0] + box[2] / 2 for box in boxes]
    vertical_span = max(box[1] + box[3] for box in boxes) - min(box[1] for box in boxes)
    if max(centers) - min(centers) > image_width * 0.16 or vertical_span < image_height * 0.28:
        return [], roots
    input_top = min(root["node"]["box"][1] for root in inputs)
    separators = [root for root in roots
                  if root["node"].get("role") == "separator"
                  or (root["node"].get("type") == "text"
                      and " ".join(_node_text(root["node"])).strip().lower() in {"or", "and"})
                  and root["node"]["box"][1] > input_top]
    separators = [root for root in separators if root["node"]["box"][1] > input_top]
    if separators:
        separator_top = min(root["node"]["box"][1] for root in separators)
        header = [root for root in roots if root["node"]["box"][1] < input_top]
        credentials = [root for root in roots if input_top <= root["node"]["box"][1] < separator_top]
        providers = [root for root in roots if root["node"]["box"][1] >= separator_top]
        groups = [{"members": members, "region": None, "form": True}
                  for members in (header, credentials, providers) if members]
        return groups, []
    return [{"members": roots, "region": None, "form": True}], []


def _section_name(members: list[dict[str, Any]], index: int, image_height: int) -> tuple[str, str]:
    boxes = [root.get("groupBox", root["node"]["box"]) for root in members]
    texts = []
    for root in members:
        texts.extend(_root_text(root))
    texts = list(dict.fromkeys(text for text in texts if len(text) <= 64))
    if len(members) >= 4 and max(box[1] + box[3] for box in boxes) - min(box[1] for box in boxes) <= image_height * 0.08:
        return "Shortcut row", "spatial-pattern"
    if texts:
        return texts[0], "ocr-text"
    return f"Section {index}", "fallback"


def _spatially_related(first: list[float], second: list[float], width: int) -> bool:
    ax1, ay1, aw, ah = first
    bx1, by1, bw, bh = second
    ax2, ay2, bx2, by2 = ax1 + aw, ay1 + ah, bx1 + bw, by1 + bh
    x_overlap = max(0, min(ax2, bx2) - max(ax1, bx1)) / max(1, min(aw, bw))
    y_overlap = max(0, min(ay2, by2) - max(ay1, by1)) / max(1, min(ah, bh))
    x_gap = max(0, max(ax1 - bx2, bx1 - ax2))
    y_gap = max(0, max(ay1 - by2, by1 - ay2))
    same_row = y_overlap >= 0.35 or y_gap <= max(12, min(ah, bh) * 0.28)
    close_columns = x_overlap >= 0.35 or x_gap <= max(24, width * 0.045)
    return same_row and close_columns


def _component_clusters(members: list[dict[str, Any]], width: int) -> list[list[dict[str, Any]]]:
    """Pair adjacent measured pieces that plausibly form one component."""
    if any(member.get("independentOverlay") for member in members):
        return [members]
    count = len(members)
    parent = list(range(count))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def join(first: int, second: int) -> None:
        a, b = find(first), find(second)
        if a != b:
            parent[max(a, b)] = min(a, b)

    for first in range(count):
        for second in range(first + 1, count):
            a, b = members[first], members[second]
            # Preserve detector-recognized components with their own children.
            if a["node"].get("children") or b["node"].get("children"):
                continue
            if _spatially_related(a["node"]["box"], b["node"]["box"], width):
                join(first, second)
    clusters: dict[int, list[dict[str, Any]]] = {}
    for index, member in enumerate(members):
        if member.get("compoundChildren"):
            # An OCR/pixel parent that fails full containment stays as evidence, while
            # an inferred wrapper encloses the original parent and its detached children.
            clusters.setdefault(find(index), []).append(member)
        else:
            clusters.setdefault(find(index), []).append(member)
    result = list(clusters.values())
    result.sort(key=lambda cluster: (min(root["node"]["box"][1] for root in cluster),
                                     min(root["node"]["box"][0] for root in cluster)))
    return result


def _active_measurement_node(root: dict[str, Any], level: int, *, include_children: bool) -> dict[str, Any]:
    record, node = root["record"], root["node"]
    result = json.loads(compact(node))
    result.pop("children", None)
    result["id"] = record["evidenceId"]
    result["level"] = level
    result["evidenceRefs"] = [record["evidenceId"]]
    result["provenance"] = {"kind": "measurement", "boundsMethod": "measured-pixel-or-ocr",
                            "evidenceRefs": [record["evidenceId"]]}
    result.setdefault("displayName", node.get("label") or node.get("text") or str(node.get("role") or node.get("type", "Component")).title())
    if include_children:
        children = []
        for child in node.get("children", []):
            child_record = root["childRecords"][str(child.get("id"))]
            child_root = {"record": child_record, "node": child, "splitChildren": [], "childRecords": root["childRecords"]}
            children.append(_active_measurement_node(child_root, level + 1, include_children=False))
        result["children"] = children
    return result


def _measurement_children(root: dict[str, Any], level: int,
                          child_lookup: Mapping[str, dict[str, Any]]) -> list[dict[str, Any]]:
    children = []
    nested = root.get("compoundChildren") or root["node"].get("children", [])
    for child in nested:
        child_record = child_lookup[str(child.get("id"))]
        child_root = {"record": child_record, "node": child,
                      "splitChildren": [], "childRecords": child_lookup}
        children.append(_active_measurement_node(child_root, level, include_children=False))
    return children


def _node_lookup(measurement: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["legacyId"]: item for item in measurement["candidates"]}


def build_hierarchy(measurement: Mapping[str, Any], depth: int) -> tuple[dict[str, Any], dict[str, Any]]:
    """Apply each requested grouping pass over immutable saved evidence."""
    if type(depth) is not int or not 1 <= depth <= MAX_DEPTH:
        raise InvalidHierarchyError("Depth must be an integer from 1 to 3")
    if measurement.get("schemaVersion") != 1 or not isinstance(measurement.get("measuredScene"), dict):
        raise InvalidHierarchyError("Measurement artifact has an unsupported or malformed schema")
    pass_times = {1: 0.0, 2: 0.0, 3: 0.0}
    first_pass_started = time.perf_counter()
    roots, dispositions = _root_records(measurement)
    size = measurement["roi"][2:]
    form_groups, remaining = _form_groups(roots, size[0], size[1])
    surface_groups = _group_surface_contours(measurement.get("pixelRegions", []), size)
    floating_groups, remaining = _floating_row_groups(remaining, size, surface_groups)
    anchored, remaining = _surface_members(remaining, surface_groups, size[1])
    content_groups = _merge_content_bands(_band_groups(remaining, size[0]), size)
    groups = anchored + floating_groups + form_groups + content_groups
    groups.sort(key=lambda group: (min(root["node"]["box"][1] for root in group["members"]),
                                   min(root["node"]["box"][0] for root in group["members"])))
    pass_times[1] += time.perf_counter() - first_pass_started
    child_lookup = _node_lookup(measurement)
    for root in roots:
        root["childRecords"] = child_lookup
    sections = []
    audit: dict[str, Any] = {
        item["evidenceId"]: {"status": "retained", "reason": "measured content remains available as raw evidence"}
        for item in measurement["candidates"]
    }
    for item in measurement.get("localRegions", []):
        audit[item["evidenceId"]] = {"status": "retained", "reason": "measured local-pixel component remains available as raw evidence"}
    for candidate in roots:
        identity = candidate["record"]["evidenceId"]
        if candidate.get("omittedReason"):
            audit[identity] = {"status": "omitted", "reason": candidate["omittedReason"]}
        else:
            audit[identity] = {"status": "included", "reason": "grouped into a useful section"}
    for evidence_id, reason in dispositions.items():
        if reason.startswith("omitted:"):
            audit[evidence_id] = {"status": "omitted", "reason": reason.removeprefix("omitted:").strip()}
        else:
            audit[evidence_id] = {"status": "included", "reason": reason}
    for index, group in enumerate(groups, 1):
        section_started = time.perf_counter()
        members = group["members"]
        if (len(members) == 1 and group.get("region") is None
                and not group.get("form") and not group.get("overlay")
                and not members[0].get("compoundChildren")):
            root_node = _active_measurement_node(members[0], 1, include_children=False)
            pass_times[1] += time.perf_counter() - section_started
            evidence_id = members[0]["record"]["evidenceId"]
            audit[evidence_id] = {"status": "included", "reason": "retained as a measured root because no section group was verified"}
            if depth >= 2:
                component_started = time.perf_counter()
                root_node["children"] = _measurement_children(members[0], 2, child_lookup)
                pass_times[2] += time.perf_counter() - component_started
            sections.append(root_node)
            continue
        refs = [root["record"]["evidenceId"] for root in members]
        refs.extend(child_lookup[str(child.get("id"))]["evidenceId"]
                    for root in members for child in root.get("compoundChildren", []))
        group_id = _group_id(1, refs)
        boxes = [root.get("groupBox", root["node"]["box"]) for root in members]
        region = group.get("region")
        region_refs = region.get("evidenceIds", []) if region else []
        if region:
            boxes.append(region["box"])
        bounds = box_union(boxes)
        name, name_method = _section_name(members, index, size[1])
        if group.get("overlay"):
            name = "Floating navigation" if group.get("floatingRow") or any(root.get("independentOverlay") for root in members) else name
            name_method = "floating-control-row" if group.get("floatingRow") else "bottom-aligned-overlay-pattern"
        node = {"id": group_id, "type": "container", "role": "section", "displayName": name,
                "label": " ".join(_root_text(root)[0] for root in members if _root_text(root)),
                "box": bounds, "level": 1, "evidenceRefs": refs + region_refs,
                "provenance": {"kind": "inference",
                               "boundsMethod": ("contour-union-and-child-union" if region and region.get("boundsMethod") == "union-of-measured-contours"
                                                else "measured-contour-and-child-union" if region
                                                else "child-union"),
                               "evidenceRefs": refs + region_refs,
                               "nameMethod": name_method},
                "children": []}
        pass_times[1] += time.perf_counter() - section_started
        if depth >= 2:
            consumed: set[str] = set()
            if region:
                parent_pixel_refs = set(region.get("evidenceIds", []))
                local_regions = [item for item in measurement.get("localRegions", [])
                                 if parent_pixel_refs & set(item.get("parentEvidenceIds", []))]
                for local_region in local_regions:
                    local_component_started = time.perf_counter()
                    local_box = local_region["box"]
                    local_members = [root for root in members
                                     if root["record"]["evidenceId"] not in consumed
                                     and fully_contains(local_box, root["node"]["box"], tolerance=0)]
                    member_refs = [root["record"]["evidenceId"] for root in local_members]
                    local_refs = [local_region["evidenceId"],
                                  *local_region.get("parentEvidenceIds", []), *member_refs]
                    local_component_id = _group_id(2, local_refs)
                    text_values = list(dict.fromkeys(text for root in local_members
                                                      for text in _root_text(root)))
                    component = {"id": local_component_id, "type": "container", "role": "component",
                                 "displayName": "Component", "label": " ".join(text_values),
                                 "box": local_box, "level": 2, "evidenceRefs": local_refs,
                                 "provenance": {"kind": "inference",
                                                "boundsMethod": "measured-local-pixel-region",
                                                "evidenceRefs": local_refs},
                                 "children": []}
                    if local_region.get("clippedAtParent"):
                        component["clippedAtParent"] = local_region["clippedAtParent"]
                    pass_times[2] += time.perf_counter() - local_component_started
                    if depth >= 3:
                        content_started = time.perf_counter()
                        component["children"] = [_active_measurement_node(root, 3, include_children=False)
                                                  for root in local_members]
                        pass_times[3] += time.perf_counter() - content_started
                    node["children"].append(component)
                    consumed.update(member_refs)
                    audit[local_region["evidenceId"]] = {
                        "status": "grouped", "reason": "measured within a verified parent's local pixel background",
                        "groupId": local_component_id}
                    for member in local_members:
                        audit[member["record"]["evidenceId"]] = {
                            "status": "grouped", "reason": "assigned by full-box containment in a local pixel region",
                            "groupId": local_component_id}
            remaining_members = [root for root in members
                                 if root["record"]["evidenceId"] not in consumed]
            component_pass_started = time.perf_counter()
            component_clusters = _component_clusters(remaining_members, size[0])
            pass_times[2] += time.perf_counter() - component_pass_started
            for component_members in component_clusters:
                component_refs = [root["record"]["evidenceId"] for root in component_members]
                component_refs.extend(child_lookup[str(child.get("id"))]["evidenceId"]
                                      for root in component_members for child in root.get("compoundChildren", []))
                if len(component_members) == 1 and not component_members[0].get("compoundChildren"):
                    component_started = time.perf_counter()
                    component = _active_measurement_node(component_members[0], 2, include_children=False)
                    pass_times[2] += time.perf_counter() - component_started
                    if depth >= 3:
                        content_started = time.perf_counter()
                        component["children"] = _measurement_children(component_members[0], 3, child_lookup)
                        pass_times[3] += time.perf_counter() - content_started
                else:
                    component_started = time.perf_counter()
                    component_id = _group_id(2, component_refs)
                    text_values = list(dict.fromkeys(text for root in component_members for text in _root_text(root)))
                    component = {"id": component_id, "type": "container", "role": "component",
                                 "displayName": text_values[0] if text_values else "Component",
                                 "label": " ".join(text_values), "box": box_union([root.get("groupBox", root["node"]["box"]) for root in component_members]),
                                 "level": 2, "evidenceRefs": component_refs,
                                 "provenance": {"kind": "inference", "boundsMethod": "child-union",
                                                "evidenceRefs": component_refs},
                                 "children": []}
                    pass_times[2] += time.perf_counter() - component_started
                    if depth >= 3:
                        content_started = time.perf_counter()
                        for root in component_members:
                            component["children"].append(_active_measurement_node(root, 3, include_children=False))
                            for child in root.get("compoundChildren", []):
                                child_record = child_lookup[str(child.get("id"))]
                                child_root = {"record": child_record, "node": child,
                                              "splitChildren": [], "childRecords": child_lookup}
                                component["children"].append(_active_measurement_node(child_root, 3, include_children=False))
                        pass_times[3] += time.perf_counter() - content_started
                    for root in component_members:
                        audit[root["record"]["evidenceId"]] = {"status": "grouped", "reason": "spatially adjacent evidence forms one component", "groupId": component_id}
                node["children"].append(component)
        for root in members:
            evidence_id = root["record"]["evidenceId"]
            audit.setdefault(evidence_id, {"status": "included", "reason": "retained as a component"})
            for child in root.get("compoundChildren", []):
                child_id = child_lookup[str(child.get("id"))]["evidenceId"]
                audit[child_id] = {"status": "grouped", "reason": "retained in an inferred component around its measured parent"}
        sections.append(node)
    scene = {"schemaVersion": 2,
             "sourceSha256": measurement["sourceSha256"],
             "imageSize": measurement["imageSize"], "roi": measurement["roi"],
             "coordinates": measurement["coordinates"], "llmCalls": 0,
             "styles": measurement["measuredScene"].get("styles", {}),
             "background": measurement["measuredScene"].get("background"),
             "methods": measurement["measuredScene"].get("methods", {}),
             "unknowns": measurement.get("unknowns", []),
             "nodes": sections,
             "hierarchy": {"algorithmVersion": HIERARCHY_VERSION, "requestedDepth": depth,
                           "supportedDepth": MAX_DEPTH, "rootCount": len(sections),
                           "candidateAudit": audit}}
    actual_depth = max((node.get("level", 1) for node in walk(scene["nodes"])), default=0)
    completed = list(range(1, min(depth, actual_depth) + 1))
    stop_reason = "requested_depth_reached" if actual_depth >= depth else "no_meaningful_children"
    scene["hierarchy"].update({"achievedDepth": actual_depth, "completedPasses": completed,
                                "availableDepth": actual_depth,
                                "passTimingsSeconds": {str(level): round(pass_times[level], 6)
                                                       for level in range(1, depth + 1)},
                                "stopReason": stop_reason,
                                "recursiveNodeCount": sum(1 for _ in walk(scene["nodes"]))})
    validate_scene_hierarchy(scene, tolerance=0)
    return scene, {"candidateAudit": audit, "pixelRegions": measurement.get("pixelRegions", [])}


def walk(nodes: list[dict[str, Any]]):
    for node in nodes:
        yield node
        yield from walk(node.get("children", []))


def validate_scene_hierarchy(scene: Mapping[str, Any], *, tolerance: float = 0) -> None:
    """Check unique IDs, positive ROI-relative boxes, full containment, and acyclicity."""
    roi = scene.get("roi")
    if not isinstance(roi, list) or len(roi) != 4:
        raise InvalidHierarchyError("Hierarchy scene must contain a four-number ROI")
    width, height = roi[2:]
    seen: set[str] = set()
    active: set[int] = set()

    def visit(node: Any, parent: Mapping[str, Any] | None = None) -> None:
        if not isinstance(node, Mapping):
            raise InvalidHierarchyError("Hierarchy nodes must be objects")
        identity = node.get("id")
        if not isinstance(identity, str) or not identity or identity in seen:
            raise InvalidHierarchyError("Hierarchy node IDs must be nonempty and unique")
        seen.add(identity)
        marker = id(node)
        if marker in active:
            raise InvalidHierarchyError("Hierarchy must be acyclic")
        active.add(marker)
        box = node.get("box")
        if not _box_valid(box) or box[0] + box[2] > width + tolerance or box[1] + box[3] > height + tolerance:
            raise InvalidHierarchyError(f"Node {identity} has a box outside its ROI")
        if parent is not None and not fully_contains(parent["box"], box, tolerance):
            raise InvalidHierarchyError(f"Parent does not fully contain child {identity}")
        level = node.get("level")
        if type(level) is not int or not 1 <= level <= MAX_DEPTH:
            raise InvalidHierarchyError(f"Node {identity} has an invalid hierarchy level")
        if parent is not None and level != parent.get("level", 0) + 1:
            raise InvalidHierarchyError(f"Node {identity} is not one level below its parent")
        if parent is None and level != 1:
            raise InvalidHierarchyError(f"Root node {identity} must be at level 1")
        children = node.get("children", [])
        if not isinstance(children, list):
            raise InvalidHierarchyError(f"Node {identity} children must be an array")
        for child in children:
            visit(child, node)
        active.remove(marker)

    nodes = scene.get("nodes")
    if not isinstance(nodes, list):
        raise InvalidHierarchyError("Hierarchy scene must contain a nodes array")
    for node in nodes:
        visit(node)
    hierarchy = scene.get("hierarchy", {})
    if isinstance(hierarchy, Mapping):
        actual_depth = max((node.get("level", 1) for node in walk(nodes)), default=0)
        if hierarchy.get("rootCount", len(nodes)) != len(nodes):
            raise InvalidHierarchyError("Hierarchy root count does not match the saved tree")
        if hierarchy.get("recursiveNodeCount", sum(1 for _ in walk(nodes))) != sum(1 for _ in walk(nodes)):
            raise InvalidHierarchyError("Hierarchy node count does not match the saved tree")
        if hierarchy.get("achievedDepth", actual_depth) != actual_depth:
            raise InvalidHierarchyError("Hierarchy achieved depth does not match the saved tree")
        if hierarchy.get("availableDepth", actual_depth) != actual_depth:
            raise InvalidHierarchyError("Hierarchy available depth does not match the saved tree")
        requested = hierarchy.get("requestedDepth")
        if requested is not None and (type(requested) is not int or not 1 <= requested <= MAX_DEPTH):
            raise InvalidHierarchyError("Hierarchy requested depth must be an integer from 1 to 3")
