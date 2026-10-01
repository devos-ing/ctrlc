"""Deterministic screenshot hierarchy scoring; kept outside the production package."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Any, Mapping

from PIL import Image, ImageDraw, ImageOps


REPOSITORY = Path(__file__).resolve().parents[1]
if str(REPOSITORY) not in sys.path:
    sys.path.insert(0, str(REPOSITORY))


IOU_THRESHOLD = 0.75


def _box(value: Any) -> list[float]:
    if isinstance(value, dict):
        value = value.get("box", value.get("bounds"))
    if (not isinstance(value, list) or len(value) != 4
            or any(isinstance(v, bool) or not isinstance(v, (int, float))
                   or not math.isfinite(v) for v in value)):
        raise ValueError("Each annotation node must have a four-number ROI-relative box")
    x, y, width, height = value
    if x < 0 or y < 0 or width <= 0 or height <= 0:
        raise ValueError("Annotation boxes must have nonnegative origins and positive dimensions")
    return [float(v) for v in value]


def validate_annotation(annotation: Mapping[str, Any], fixture: Mapping[str, Any]) -> list[dict[str, Any]]:
    if annotation.get("source_sha256", annotation.get("sourceSha256")) != fixture.get("source_sha256"):
        raise ValueError(f"Annotation source hash mismatch for {fixture.get('id')}")
    for field in ("width", "height", "roi"):
        if annotation.get(field) != fixture.get(field):
            raise ValueError(f"Annotation {field} mismatch for {fixture.get('id')}")
    roi = fixture.get("roi")
    if (type(fixture.get("width")) is not int or type(fixture.get("height")) is not int
            or not isinstance(roi, list) or len(roi) != 4
            or any(type(value) is not int for value in roi)
            or roi[0] < 0 or roi[1] < 0 or roi[2] <= 0 or roi[3] <= 0
            or roi[0] + roi[2] > fixture.get("width", 0)
            or roi[1] + roi[3] > fixture.get("height", 0)):
        raise ValueError(f"Fixture {fixture.get('id')} has an invalid ROI")
    nodes = annotation.get("nodes")
    if not isinstance(nodes, list):
        raise ValueError(f"Annotation for {fixture.get('id')} must contain nodes")
    known = set()
    normalized = []
    for node in nodes:
        if not isinstance(node, dict) or not isinstance(node.get("id"), str) or not node["id"]:
            raise ValueError("Annotation node IDs must be nonempty strings")
        if node["id"] in known:
            raise ValueError(f"Duplicate annotation node ID: {node['id']}")
        known.add(node["id"])
        level = node.get("level")
        if type(level) is not int or not 1 <= level <= 3:
            raise ValueError(f"Annotation node {node['id']} needs a level from 1 to 3")
        kind = node.get("type")
        if kind not in {"container", "button", "input", "image", "text"}:
            raise ValueError(f"Annotation node {node['id']} has unsupported type {kind!r}")
        node_box = _box(node)
        if not _within_roi(node_box, roi):
            raise ValueError(f"Annotation node {node['id']} lies outside the fixture ROI")
        normalized.append({**node, "box": node_box, "parent_id": node.get("parent_id")})
    lookup = {node["id"]: node for node in normalized}
    for node in normalized:
        parent_id = node.get("parent_id")
        if parent_id is None:
            if node["level"] != 1:
                raise ValueError(f"Annotation root {node['id']} must be level 1")
            continue
        parent = lookup.get(parent_id)
        if parent is None or parent["level"] != node["level"] - 1:
            raise ValueError(f"Annotation node {node['id']} has an invalid parent")
        if not _contains(parent["box"], node["box"], 0):
            raise ValueError(f"Annotation parent does not fully contain node {node['id']}")
    ignore_regions = annotation.get("ignore_regions", [])
    if not isinstance(ignore_regions, list):
        raise ValueError("Annotation ignore_regions must be an array")
    for index, region in enumerate(ignore_regions):
        if not _within_roi(_box(region), roi):
            raise ValueError(f"Ignore region {index} lies outside the fixture ROI")
    for parent_id, child_id in _alternatives(annotation):
        child = lookup.get(child_id)
        parent = lookup.get(parent_id) if parent_id is not None else None
        if child is None:
            raise ValueError(f"Allowed alternative references unknown child {child_id!r}")
        if parent_id is None:
            if child["level"] != 1:
                raise ValueError(f"Allowed root alternative for {child_id!r} must be level 1")
        elif parent is None:
            raise ValueError(f"Allowed alternative references unknown parent {parent_id!r}")
        elif parent["level"] != child["level"] - 1 or not _contains(parent["box"], child["box"], 0):
            raise ValueError(f"Allowed alternative edge {parent_id!r} → {child_id!r} is invalid")
    return normalized


def _within_roi(box: list[float], roi: list[int]) -> bool:
    return (box[0] >= 0 and box[1] >= 0
            and box[0] + box[2] <= roi[2]
            and box[1] + box[3] <= roi[3])


def _contains(outer: list[float], inner: list[float], tolerance: float = 0) -> bool:
    return (outer[0] <= inner[0] + tolerance and outer[1] <= inner[1] + tolerance
            and outer[0] + outer[2] >= inner[0] + inner[2] - tolerance
            and outer[1] + outer[3] >= inner[1] + inner[3] - tolerance)


def _iou(first: list[float], second: list[float]) -> float:
    left = max(first[0], second[0])
    top = max(first[1], second[1])
    right = min(first[0] + first[2], second[0] + second[2])
    bottom = min(first[1] + first[3], second[1] + second[3])
    intersection = max(0, right - left) * max(0, bottom - top)
    union = first[2] * first[3] + second[2] * second[3] - intersection
    return intersection / union if union else 0


def _compatible(prediction: Mapping[str, Any], expected: Mapping[str, Any]) -> bool:
    if prediction.get("type") == expected.get("type"):
        return True
    return (prediction.get("role") == "section" and expected.get("type") == "container")


def flatten_scene(scene: Mapping[str, Any], *, legacy: bool = False) -> list[dict[str, Any]]:
    result = []

    def visit(node: Mapping[str, Any], parent: str | None, tree_depth: int) -> None:
        if not isinstance(node, Mapping) or not isinstance(node.get("box"), list):
            raise ValueError("Scene contains an invalid node")
        level = None if legacy else node.get("level", tree_depth)
        result.append({**node, "box": _box(node), "parent_id": parent,
                       "semantic_level": level, "emitted_tree_depth": tree_depth})
        for child in node.get("children", []):
            visit(child, node.get("id"), tree_depth + 1)

    for node in scene.get("nodes", []):
        visit(node, None, 1)
    return result


def _ignore_prediction(node: Mapping[str, Any], regions: list[Any]) -> bool:
    box = node["box"]
    cx, cy = box[0] + box[2] / 2, box[1] + box[3] / 2
    for region in regions:
        area = _box(region)
        if area[0] <= cx <= area[0] + area[2] and area[1] <= cy <= area[1] + area[3]:
            return True
    return False


def _alternatives(annotation: Mapping[str, Any]) -> set[tuple[str | None, str]]:
    edges = set()
    alternatives = annotation.get("allowed_alternatives", [])
    if not isinstance(alternatives, list):
        raise ValueError("Annotation allowed_alternatives must be an array")

    def add_edge(parent_id: Any, child_id: Any) -> None:
        if parent_id is not None and (not isinstance(parent_id, str) or not parent_id):
            raise ValueError("Allowed alternative parent IDs must be nonempty strings or null")
        if not isinstance(child_id, str) or not child_id:
            raise ValueError("Allowed alternative child IDs must be nonempty strings")
        edges.add((parent_id, child_id))

    for alternative in alternatives:
        if isinstance(alternative, dict):
            alternative_edges = alternative.get("edges", [])
            if not isinstance(alternative_edges, list):
                raise ValueError("Allowed alternative edges must be an array")
            for edge in alternative_edges:
                if not isinstance(edge, dict):
                    raise ValueError("Allowed alternative edges must be objects")
                add_edge(edge.get("parent_id"), edge.get("child_id"))
        elif isinstance(alternative, list):
            for edge in alternative:
                if isinstance(edge, list) and len(edge) == 2:
                    add_edge(edge[0], edge[1])
                else:
                    raise ValueError("Allowed alternative edge pairs must contain parent and child IDs")
        else:
            raise ValueError("Allowed alternatives must be edge objects or edge-pair arrays")
    return edges


def _is_ancestor(nodes: Mapping[str, Mapping[str, Any]], ancestor_id: str | None,
                 descendant_id: str | None) -> bool:
    current = nodes.get(descendant_id) if descendant_id else None
    visited = set()
    while current and current.get("parent_id") is not None:
        parent_id = current["parent_id"]
        if parent_id == ancestor_id:
            return True
        if parent_id in visited:
            return False
        visited.add(parent_id)
        current = nodes.get(parent_id)
    return False


def _f1(tp: int, fp: int, fn: int) -> dict[str, float | int]:
    if tp + fp == 0 and tp + fn == 0:
        return {"tp": tp, "fp": fp, "fn": fn, "precision": None, "recall": None, "f1": None}
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "precision": precision,
            "recall": recall, "f1": 2 * precision * recall / (precision + recall)
            if precision + recall else 0.0}


def score_scene(scene: Mapping[str, Any], annotation: Mapping[str, Any], *, depth: int | None,
                legacy: bool = False, iou_threshold: float = IOU_THRESHOLD,
                artifact_path: str | Path | None = None,
                expected_source_hash: str | None = None) -> dict[str, Any]:
    expected_all = annotation["nodes"]
    ignore_regions = annotation.get("ignore_regions", [])
    expected = [node for node in expected_all
                if node.get("status") not in {"ignore", "ambiguous-ignore"}
                and not node.get("ignore") and (depth is None or node["level"] <= depth)]
    predictions = flatten_scene(scene, legacy=legacy)
    if depth is not None and not legacy:
        predictions = [node for node in predictions if node["semantic_level"] is not None
                       and node["semantic_level"] <= depth]
    predictions = [node for node in predictions if not _ignore_prediction(node, ignore_regions)]
    expected_by_level: dict[int, list[dict[str, Any]]] = {}
    pred_by_level: dict[int, list[dict[str, Any]]] = {}
    if legacy:
        expected_by_level[0] = expected
        pred_by_level[0] = predictions
    else:
        for node in expected:
            expected_by_level.setdefault(node["level"], []).append(node)
        for node in predictions:
            pred_by_level.setdefault(node["semantic_level"], []).append(node)
    per_level = {}
    all_matches = []
    all_fp: list[dict[str, Any]] = []
    all_fn: list[dict[str, Any]] = []
    total_tp = total_fp = total_fn = 0
    iou_sum = 0.0
    required_lost = []
    for level in sorted(set(expected_by_level) | set(pred_by_level)):
        expected_level = expected_by_level.get(level, [])
        predictions_level = pred_by_level.get(level, [])
        options = []
        for expected_node in expected_level:
            for prediction in predictions_level:
                if not _compatible(prediction, expected_node):
                    continue
                value = _iou(prediction["box"], expected_node["box"])
                if value >= iou_threshold:
                    options.append((value, expected_node["id"], prediction["id"], expected_node, prediction))
        options.sort(key=lambda item: (-item[0], item[1], item[2]))
        matched_expected: set[str] = set()
        matched_predictions: set[str] = set()
        matches = []
        for value, expected_id, prediction_id, expected_node, prediction in options:
            if expected_id in matched_expected or prediction_id in matched_predictions:
                continue
            matched_expected.add(expected_id)
            matched_predictions.add(prediction_id)
            matches.append({"expectedId": expected_id, "predictionId": prediction_id, "iou": value,
                            "level": expected_node["level"]})
            iou_sum += value
        fp = [node for node in predictions_level if node["id"] not in matched_predictions]
        fn = [node for node in expected_level if node["id"] not in matched_expected]
        required_lost.extend(node["id"] for node in fn
                             if node.get("required") or node.get("important")
                             or node.get("type") in {"button", "input"})
        counts = _f1(len(matches), len(fp), len(fn))
        per_level[str(level)] = {**counts, "expected": len(expected_level),
                                 "predicted": len(predictions_level)}
        total_tp += len(matches)
        total_fp += len(fp)
        total_fn += len(fn)
        all_matches.extend(matches)
        all_fp.extend(fp)
        all_fn.extend(fn)
    node_metrics = _f1(total_tp, total_fp, total_fn)
    if legacy:
        level_metrics = {"status": "legacy-tree-scored-without-semantic-levels",
                         "levelAgnostic": node_metrics}
    else:
        level_metrics = {"status": "scored-at-matching-semantic-levels", "perLevel": per_level,
                         "aggregate": node_metrics}
    pred_to_gt = {item["predictionId"]: item["expectedId"] for item in all_matches}
    expected_lookup = {node["id"]: node for node in expected}
    predicted_lookup = {node["id"]: node for node in predictions}
    expected_edges = {(node.get("parent_id"), node["id"]) for node in expected
                      if node.get("parent_id") in expected_lookup}
    alternatives = _alternatives(annotation)
    accepted_edges = expected_edges | alternatives
    predicted_edges = set()
    predicted_edge_count = 0
    for node in predictions:
        parent_pred = node.get("parent_id")
        if parent_pred not in predicted_lookup:
            continue
        predicted_edge_count += 1
        mapped_parent = pred_to_gt.get(parent_pred, f"unmatched-parent:{parent_pred}")
        mapped_child = pred_to_gt.get(node["id"], f"unmatched-child:{node['id']}")
        predicted_edges.add((mapped_parent, mapped_child))
    expected_children = {child for _parent, child in expected_edges}
    satisfied_children = {child for parent, child in predicted_edges
                          if child in expected_children and (parent, child) in accepted_edges}
    edge_tp = len(satisfied_children)
    edge_fp = predicted_edge_count - edge_tp
    edge_fn = len(expected_children - satisfied_children)
    edge_metrics = _f1(edge_tp, edge_fp, edge_fn)
    matched_iou = iou_sum / len(all_matches) if all_matches else None
    atomic_fragmentation = []
    prediction_lookup = {node["id"]: node for node in predictions}
    for node in expected:
        if not node.get("atomic"):
            continue
        level_preds = [prediction for prediction in predictions
                       if legacy or prediction["semantic_level"] == node["level"]]
        overlaps = [prediction for prediction in level_preds
                    if _iou(prediction["box"], node["box"]) > 0.05]
        pieces = []
        for prediction in overlaps:
            if any(_is_ancestor(prediction_lookup, existing["id"], prediction["id"])
                   and _iou(existing["box"], node["box"]) >= 0.50 for existing in pieces):
                continue
            pieces = [existing for existing in pieces
                      if not (_is_ancestor(prediction_lookup, prediction["id"], existing["id"])
                              and _iou(prediction["box"], node["box"]) >= 0.50)]
            pieces.append(prediction)
        piece_ids = [prediction["id"] for prediction in pieces]
        if len(piece_ids) > 1:
            atomic_fragmentation.append({"expectedId": node["id"], "pieces": piece_ids,
                                         "redundantPieces": len(piece_ids) - 1})
    overmerges = []
    expected_lookup_all = {node["id"]: node for node in expected_all}
    for prediction in predictions:
        same_level = [node for node in expected if legacy or node["level"] == prediction["semantic_level"]]
        overlaps = [node for node in same_level if _iou(prediction["box"], node["box"]) >= 0.15]
        independent = [node for node in overlaps
                       if not any(other["id"] != node["id"]
                                  and _is_ancestor(expected_lookup_all, other["id"], node["id"])
                                  for other in overlaps)]
        if len(independent) > 1:
            overmerges.append({"predictionId": prediction["id"],
                               "expectedIds": [node["id"] for node in independent]})
    return {"depth": depth if not legacy else None,
            "legacy": legacy,
            "nodeMetrics": level_metrics,
            "parentEdgeF1": edge_metrics,
            "matchedBoxMeanIoU": matched_iou,
            "requiredControlLoss": {"count": len(required_lost), "ids": required_lost},
            "fragmentation": {"atomicAssetsFragmented": len(atomic_fragmentation),
                              "redundantPieces": sum(item["redundantPieces"] for item in atomic_fragmentation),
                              "cases": atomic_fragmentation},
            "overmerges": {"count": len(overmerges), "cases": overmerges},
            "evidenceIntegrity": verify_measurement_artifact(scene, artifact_path, expected_source_hash)
            if artifact_path is not None and expected_source_hash is not None
            else {"status": "not-applicable-legacy", "valid": None} if legacy
            else {"status": "missing-artifact", "valid": False},
            "matched": all_matches,
            "falsePositives": [node.get("id") for node in all_fp],
            "misses": [node.get("id") for node in all_fn],
            "predictedNodeCount": len(predictions), "expectedNodeCount": len(expected)}


def verify_measurement_artifact(scene: Mapping[str, Any], artifact_path: str | Path,
                                expected_source_hash: str) -> dict[str, Any]:
    reference = scene.get("measurementArtifact")
    if not isinstance(reference, Mapping) or not Path(artifact_path).is_file():
        return {"status": "missing", "valid": False}
    measurement = json.loads(Path(artifact_path).read_text())
    canonical = json.dumps(measurement, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    candidate_ids = {item.get("evidenceId") for item in measurement.get("candidates", [])}
    candidate_ids |= {item.get("evidenceId") for item in measurement.get("pixelRegions", [])}
    candidate_ids |= {item.get("evidenceId") for item in measurement.get("localRegions", [])}
    errors = []
    if digest != reference.get("sha256"):
        errors.append("artifact hash mismatch")
    if scene.get("sourceSha256") != expected_source_hash or measurement.get("sourceSha256") != expected_source_hash:
        errors.append("source hash mismatch")
    measured_scene = measurement.get("measuredScene", {})
    if scene.get("imageSize") != measurement.get("imageSize") or scene.get("roi") != measurement.get("roi"):
        errors.append("scene dimensions or ROI changed")
    if scene.get("styles") != measured_scene.get("styles"):
        errors.append("measured styles changed")
    if scene.get("unknowns") != measurement.get("unknowns"):
        errors.append("measured unknowns changed")
    for node in _walk(scene.get("nodes", [])):
        refs = node.get("evidenceRefs", [])
        if not all(reference_id in candidate_ids for reference_id in refs):
            errors.append(f"unknown evidence reference in {node.get('id')}")
        if node.get("provenance", {}).get("kind") == "measurement" and refs:
            source_node = next((item["node"] for item in measurement["candidates"]
                                if item["evidenceId"] == refs[0]), None)
            if source_node is None or any(source_node.get(field) != node.get(field)
                                          for field in ("box", "type", "role", "label", "text",
                                                        "styleRef", "styleMeasurements")):
                errors.append(f"measured bounds changed for {node.get('id')}")
        elif node.get("provenance", {}).get("kind") == "inference":
            if node.get("provenance", {}).get("boundsMethod") not in {
                    "child-union", "measured-contour-and-child-union", "contour-union-and-child-union",
                    "measured-local-pixel-region"}:
                errors.append(f"inferred bounds method is missing or unknown for {node.get('id')}")
    try:
        from ctrlc.hierarchy import validate_scene_hierarchy
        validate_scene_hierarchy(scene, tolerance=0)
    except Exception as error:
        errors.append(str(error))
    return {"status": "checked", "valid": not errors, "errors": errors,
            "measurementSha256": digest, "candidateReferenceCount": len(candidate_ids)}


def _walk(nodes: list[dict[str, Any]]):
    for node in nodes:
        yield node
        yield from _walk(node.get("children", []))


def write_overlay(image_path: str | Path, roi: list[int], scene: Mapping[str, Any],
                  annotation: Mapping[str, Any], output_path: str | Path, *, depth: int | None,
                  legacy: bool = False) -> None:
    with Image.open(image_path) as raw:
        image = ImageOps.exif_transpose(raw).convert("RGB")
    x, y, width, height = roi
    image = image.crop((x, y, x + width, y + height)).convert("RGBA")
    overlay = Image.new("RGBA", image.size, (255, 255, 255, 0))
    draw = ImageDraw.Draw(overlay)
    predictions = flatten_scene(scene, legacy=legacy)
    if depth is not None and not legacy:
        predictions = [node for node in predictions if node["semantic_level"] is not None
                       and node["semantic_level"] <= depth]
    for node in annotation.get("nodes", []):
        if depth is not None and node["level"] > depth:
            continue
        box = node["box"]
        draw.rectangle((box[0], box[1], box[0] + box[2], box[1] + box[3]),
                       outline=(20, 150, 70, 220), width=2)
    for node in predictions:
        box = node["box"]
        draw.rectangle((box[0], box[1], box[0] + box[2], box[1] + box[3]),
                       outline=(210, 40, 60, 220), width=2)
    image.alpha_composite(overlay)
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGB").save(target, format="PNG", optimize=True)
