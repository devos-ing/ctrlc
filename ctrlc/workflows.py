"""Opt-in hierarchy workflows layered over the legacy measurement pipeline."""
from __future__ import annotations

import hashlib
import copy
import json
from pathlib import Path
import platform
import sys
import time
from typing import Any, Mapping

from PIL import Image, ImageOps

from .hierarchy import (HIERARCHY_VERSION, MEASUREMENT_VERSION, InvalidHierarchyError,
                        build_hierarchy, compact, fully_contains, make_measurements, sha256,
                        validate_scene_hierarchy, walk)


def _load_upright_image(image_path: Path) -> Image.Image:
    with Image.open(image_path) as raw:
        if raw.format not in ("PNG", "JPEG", "WEBP"):
            raise ValueError("Use a still PNG, JPEG or WebP screenshot")
        return ImageOps.exif_transpose(raw).convert("RGB")


def _measurement_hash(measurement: Mapping[str, Any]) -> str:
    return sha256(compact(measurement).encode())


def _json_write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def _peak_memory_bytes() -> int | None:
    try:
        import resource
        value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return int(value if sys.platform == "darwin" else value * 1024)
    except (ImportError, AttributeError, OSError):
        return None


def _write_artifacts(scene: dict[str, Any], measurement: dict[str, Any], output_dir: Path,
                     image_path: Path, *, inspector: bool, timings: dict[str, float],
                     cache: dict[str, bool], ocr_invocations: int,
                     wall_started: float, mode: str = "extract",
                     pass_counts: Mapping[str, list[int]] | None = None) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    measurement_hash = _measurement_hash(measurement)
    measurement_name = f"measurements-{measurement_hash[:16]}.json"
    measurement_path = output_dir / measurement_name
    if not measurement_path.exists():
        _json_write(measurement_path, measurement)
    scene["measurementArtifact"] = {"path": measurement_name, "sha256": measurement_hash,
                                    "schemaVersion": measurement.get("schemaVersion", 1)}
    scene_path = output_dir / "scene.json"
    packet_path = output_dir / "packet.json"
    run_path = output_dir / "run.json"
    from .extraction import compact as compact_packet, packet
    scene_path.write_text(json.dumps(scene, ensure_ascii=False, indent=2) + "\n")
    encoded = compact_packet(packet(scene))
    packet_path.write_text(encoded + "\n")
    render_seconds = 0.0
    artifacts = {"scene": str(scene_path.resolve()), "packet": str(packet_path.resolve()),
                 "run": str(run_path.resolve()), "measurements": str(measurement_path.resolve())}
    if inspector:
        from .rendering import render
        render_started = time.perf_counter()
        inspector_path = output_dir / "inspector.html"
        inspector_path.write_text(render(scene_path, image_path, measurement_source=measurement_path))
        render_seconds = time.perf_counter() - render_started
        artifacts["inspector"] = str(inspector_path.resolve())
    hierarchy = scene["hierarchy"]
    total = time.perf_counter() - wall_started
    if pass_counts is None:
        evaluated_passes = hierarchy["completedPasses"] if not cache["hierarchy"] else []
        computed_passes = evaluated_passes
        added_passes = evaluated_passes
        evaluated_pass_times = hierarchy.get("passTimingsSeconds", {}) if not cache["hierarchy"] else {}
        added_pass_times = evaluated_pass_times
    else:
        evaluated_passes = list(pass_counts.get("evaluated", []))
        computed_passes = list(pass_counts.get("computed", []))
        added_passes = list(pass_counts.get("added", []))
        evaluated_pass_times = dict(pass_counts.get("timingsEvaluated", {}))
        added_pass_times = dict(pass_counts.get("timingsAdded", {}))
    report = {"cacheHit": cache["measurement"] and cache["hierarchy"],
              "measurementCacheHit": cache["measurement"],
              "hierarchyCacheHit": cache["hierarchy"],
              "llmCalls": 0, "modelTokens": 0,
              "components": hierarchy["rootCount"],
              "rootCount": hierarchy["rootCount"],
              "recursiveNodeCount": hierarchy["recursiveNodeCount"],
              "requestedDepth": hierarchy["requestedDepth"],
              "achievedDepth": hierarchy["achievedDepth"],
              "completedPasses": hierarchy["completedPasses"],
              "passesEvaluatedThisRun": evaluated_passes,
              "passesComputedThisRun": computed_passes,
              "passesAddedThisRun": added_passes,
              "hierarchyPassSecondsThisRun": evaluated_pass_times,
              "hierarchyPassSecondsAddedThisRun": added_pass_times,
              "stopReason": hierarchy["stopReason"],
              "measurementSha256": measurement_hash,
              "ocrInvocations": ocr_invocations,
              "ocrSeconds": round(timings.get("ocr", 0.0), 4),
              "nativeOcrHelperCompilationSeconds": round(
                  timings.get("nativeOcrHelperCompilation", 0.0), 4),
              "measurementSeconds": round(timings.get("measurement", 0.0), 4),
              "hierarchySeconds": round(timings.get("hierarchy", 0.0), 4),
              "renderingSeconds": round(render_seconds, 4),
              "elapsedSeconds": round(total, 4),
              "processPeakMemoryBytes": _peak_memory_bytes(),
              "packetBytes": len(encoded.encode()),
              "output": str(output_dir.resolve()), "mode": mode,
              "artifacts": artifacts}
    _json_write(run_path, report)
    return report


def _resolve_roi(roi: list[int] | tuple[int, ...] | None, image: Image.Image) -> list[int]:
    if roi is None:
        return [0, 0, image.width, image.height]
    if (not isinstance(roi, (list, tuple)) or len(roi) != 4
            or any(type(value) is not int for value in roi)
            or min(roi[:2]) < 0 or min(roi[2:]) <= 0):
        raise ValueError("ROI needs nonnegative x,y and positive width,height integers")
    x, y, width, height = roi
    if x + width > image.width or y + height > image.height:
        raise ValueError("ROI extends outside the orientation-corrected image")
    return list(roi)


def _validate_saved_roi(roi: Any, image_size: list[int] | tuple[int, int]) -> list[int]:
    if (not isinstance(roi, list) or len(roi) != 4 or any(type(value) is not int for value in roi)
            or min(roi[:2]) < 0 or min(roi[2:]) <= 0):
        raise InvalidHierarchyError("Saved ROI needs nonnegative x,y and positive width,height integers")
    x, y, width, height = roi
    if x + width > image_size[0] or y + height > image_size[1]:
        raise InvalidHierarchyError("Saved ROI extends outside the orientation-corrected source image")
    return roi


def run_hierarchical_extraction(image_path: str | Path, output_dir: str | Path, *,
                                depth: int, roi: list[int] | None = None,
                                languages: str = "en-US", ocr_json_path: str | Path | None = None,
                                ocr_data: Mapping[str, Any] | None = None, refresh: bool = False,
                                inspector: bool = False) -> dict[str, Any]:
    """Measure once, persist evidence, and apply a caller-selected hierarchy depth."""
    if type(depth) is not int or not 1 <= depth <= 3:
        raise InvalidHierarchyError("Depth must be an integer from 1 to 3")
    if ocr_json_path is not None and ocr_data is not None:
        raise ValueError("Pass either ocr_json_path or ocr_data, not both")
    from .extraction import (ASSETS, InvalidOCRDataError, compact as extraction_compact,
                             extract, native_ocr, validate_ocr)

    wall_started = time.perf_counter()
    image_path, output_dir = Path(image_path), Path(output_dir)
    source = image_path.read_bytes()
    source_hash = sha256(source)
    upright = _load_upright_image(image_path)
    resolved_roi = _resolve_roi(roi, upright)
    x, y, width, height = resolved_roi
    cropped = upright.crop((x, y, x + width, y + height))
    ocr_path = Path(ocr_json_path) if ocr_json_path is not None else None
    if ocr_path is not None:
        ocr_hash = sha256(ocr_path.read_bytes())
        provider = {"kind": "supplied-json", "sha256": ocr_hash}
    elif ocr_data is not None:
        ocr_hash = sha256(extraction_compact(ocr_data).encode())
        provider = {"kind": "supplied-data", "sha256": ocr_hash}
    else:
        vision_source = ASSETS / "vision_ocr.swift"
        vision_hash = sha256(vision_source.read_bytes())
        provider = {"kind": "native-vision", "languages": languages,
                    "helperSha256": vision_hash, "platform": platform.mac_ver()[0]}
        ocr_hash = vision_hash
    config = {"sourceSha256": source_hash, "roi": resolved_roi,
              "ocrProvider": provider, "measurementVersion": MEASUREMENT_VERSION}
    measurement_key = sha256(extraction_compact(config).encode())
    cache_root = output_dir / ".cache"
    measurement_cache = cache_root / "measurements" / f"{measurement_key}.json"
    measurement_cache.parent.mkdir(parents=True, exist_ok=True)
    measurement_hit = measurement_cache.exists() and not refresh
    ocr_invocations = 0
    timings = {"ocr": 0.0, "nativeOcrHelperCompilation": 0.0,
               "measurement": 0.0, "hierarchy": 0.0}

    if measurement_hit:
        measurement = json.loads(measurement_cache.read_text())
        if (measurement.get("sourceSha256") != source_hash or measurement.get("roi") != resolved_roi
                or measurement.get("measurementVersion") != MEASUREMENT_VERSION
                or measurement.get("ocrProvider") != provider):
            raise InvalidHierarchyError("Measurement cache key does not match its saved evidence")
    else:
        cache_dir = cache_root / "native"
        cache_dir.mkdir(parents=True, exist_ok=True)
        crop_path = cache_dir / f"{measurement_key}.png"
        cropped.save(crop_path)
        ocr_started = time.perf_counter()
        native_timing: dict[str, float] = {}
        try:
            if ocr_path is not None:
                ocr = json.loads(ocr_path.read_text())
            elif ocr_data is not None:
                ocr = dict(ocr_data)
            else:
                ocr = native_ocr(crop_path, cache_dir, languages, timing=native_timing)
                ocr_invocations = 1
        finally:
            timings["ocr"] = native_timing.get("ocrSeconds", time.perf_counter() - ocr_started)
            timings["nativeOcrHelperCompilation"] = native_timing.get(
                "nativeOcrHelperCompilationSeconds", 0.0)
            crop_path.unlink(missing_ok=True)
        validate_ocr(ocr, cropped.size)
        measure_started = time.perf_counter()
        measured_scene = {"schemaVersion": 1, "sourceSha256": source_hash,
                          "imageSize": list(upright.size), "roi": resolved_roi,
                          "coordinates": "Top-left origin, ROI-relative pixels after EXIF orientation",
                          "llmCalls": 0, **extract(cropped, ocr)}
        measurement = make_measurements(source_hash=source_hash, image_size=list(upright.size),
                                        roi=resolved_roi, ocr=ocr, provider=provider,
                                        measured_scene=measured_scene, image=cropped)
        timings["measurement"] = time.perf_counter() - measure_started
        if measurement.get("sourceSha256") != source_hash:
            raise InvalidOCRDataError("Measurement source hash does not match screenshot")
        _json_write(measurement_cache, measurement)

    measurement_digest = _measurement_hash(measurement)
    hierarchy_cache = cache_root / "hierarchy" / f"{measurement_digest}-{HIERARCHY_VERSION}-d{depth}.json"
    hierarchy_cache.parent.mkdir(parents=True, exist_ok=True)
    hierarchy_hit = hierarchy_cache.exists() and not refresh
    if hierarchy_hit:
        scene = json.loads(hierarchy_cache.read_text())
        try:
            validate_scene_hierarchy(scene, tolerance=0)
        except InvalidHierarchyError as error:
            raise InvalidHierarchyError(f"Hierarchy cache is invalid: {error}") from error
        hierarchy = scene.get("hierarchy", {})
        if (scene.get("sourceSha256") != source_hash
                or scene.get("roi") != resolved_roi
                or hierarchy.get("requestedDepth") != depth
                or hierarchy.get("measurementSha256") != measurement_digest):
            raise InvalidHierarchyError("Hierarchy cache metadata does not match the request")
    else:
        hierarchy_started = time.perf_counter()
        scene, _ = build_hierarchy(measurement, depth)
        scene["hierarchy"]["measurementSha256"] = measurement_digest
        timings["hierarchy"] = time.perf_counter() - hierarchy_started
        _json_write(hierarchy_cache, scene)
    return _write_artifacts(scene, measurement, output_dir, image_path, inspector=inspector,
                            timings=timings, cache={"measurement": measurement_hit,
                                                    "hierarchy": hierarchy_hit},
                            ocr_invocations=ocr_invocations, wall_started=wall_started)


def _load_measurement_for_scene(scene_path: Path, scene: Mapping[str, Any]) -> tuple[dict[str, Any], Path, str]:
    reference = scene.get("measurementArtifact")
    if not isinstance(reference, Mapping) or not isinstance(reference.get("path"), str):
        raise InvalidHierarchyError("Scene has no saved measurement artifact; it cannot be refined")
    artifact_path = Path(reference["path"])
    if not artifact_path.is_absolute():
        artifact_path = scene_path.parent / artifact_path
    if not artifact_path.is_file():
        raise FileNotFoundError(f"Saved measurement artifact not found: {artifact_path}")
    measurement = json.loads(artifact_path.read_text())
    actual_hash = _measurement_hash(measurement)
    if reference.get("sha256") != actual_hash:
        raise InvalidHierarchyError("Saved measurement artifact hash does not match its scene reference")
    if measurement.get("sourceSha256") != scene.get("sourceSha256"):
        raise InvalidHierarchyError("Saved measurement artifact source hash does not match its scene")
    return measurement, artifact_path, actual_hash


def _preserve_accepted_groups(previous: Mapping[str, Any], rebuilt: dict[str, Any]) -> None:
    """Retain accepted group identity and review labels when evidence membership is unchanged."""
    accepted: dict[tuple[int, tuple[str, ...]], Mapping[str, Any]] = {}
    for node in walk(previous.get("nodes", [])):
        provenance = node.get("provenance", {})
        refs = node.get("evidenceRefs")
        if provenance.get("kind") == "inference" and isinstance(refs, list) and refs:
            accepted[(node.get("level", 1), tuple(sorted(refs)))] = node
    roi = rebuilt["roi"]
    for node in walk(rebuilt.get("nodes", [])):
        refs = node.get("evidenceRefs")
        prior = accepted.get((node.get("level", 1), tuple(sorted(refs or []))))
        if prior is None:
            continue
        prior_box = prior.get("box")
        if (isinstance(prior_box, list) and len(prior_box) == 4
                and prior_box[0] >= 0 and prior_box[1] >= 0
                and prior_box[0] + prior_box[2] <= roi[2]
                and prior_box[1] + prior_box[3] <= roi[3]
                and all(fully_contains(prior_box, child["box"])
                        for child in node.get("children", []))):
            node["box"] = list(prior_box)
            if isinstance(prior.get("provenance"), dict):
                node["provenance"] = dict(prior["provenance"])
        if isinstance(prior.get("id"), str) and prior["id"]:
            node["id"] = prior["id"]
        structural = {"id", "box", "level", "evidenceRefs", "provenance", "children"}
        for field, value in prior.items():
            if field not in structural:
                node[field] = copy.deepcopy(value)


def _preserve_reviewed_roots(previous: Mapping[str, Any], rebuilt: dict[str, Any],
                             measurement: Mapping[str, Any], depth: int) -> None:
    """Refine inside accepted root groups, even if their membership differs from fresh grouping."""
    candidates = {item["evidenceId"]: item for item in measurement.get("candidates", [])}
    pixel_regions = {item["evidenceId"]: item for item in measurement.get("pixelRegions", [])}
    local_regions = {item["evidenceId"]: item for item in measurement.get("localRegions", [])}
    evidence_ids = set(candidates) | set(pixel_regions) | set(local_regions)

    def candidate_node(evidence_id: str, level: int, max_depth: int) -> dict[str, Any]:
        record = candidates[evidence_id]
        node = copy.deepcopy(record["node"])
        node["id"] = evidence_id
        node["level"] = level
        node["evidenceRefs"] = [evidence_id]
        node["provenance"] = {"kind": "measurement", "boundsMethod": "measured-pixel-or-ocr",
                               "evidenceRefs": [evidence_id]}
        node.setdefault("displayName", node.get("label") or node.get("text")
                        or str(node.get("role") or node.get("type", "Component")).title())
        if level < max_depth:
            node["children"] = [candidate_node(child_id, level + 1, max_depth)
                                for child_id in record.get("childEvidenceIds", [])]
        else:
            node.pop("children", None)
        return node

    def local_region_node(evidence_id: str, level: int, candidate_refs: set[str]) -> dict[str, Any]:
        record = local_regions[evidence_id]
        local_candidates = [
            candidates[candidate_id] for candidate_id in sorted(candidate_refs)
            if fully_contains(record["box"], candidates[candidate_id]["node"]["box"])
        ]
        child_refs = [record["evidenceId"], *record.get("parentEvidenceIds", []),
                      *(item["evidenceId"] for item in local_candidates)]
        node = {"id": evidence_id, "type": "container", "role": "component",
                "displayName": "Component",
                "label": " ".join(filter(None, (item["node"].get("text") or item["node"].get("label")
                                                      for item in local_candidates))),
                "box": list(record["box"]), "level": level, "evidenceRefs": child_refs,
                "provenance": {"kind": "inference", "boundsMethod": "measured-local-pixel-region",
                               "evidenceRefs": child_refs}, "children": []}
        if level < depth:
            node["children"] = [candidate_node(item["evidenceId"], level + 1, depth)
                                for item in local_candidates]
        return node

    def allowed_local_refs(parent_refs: set[str], root_box: list[Any]) -> set[str]:
        if not isinstance(root_box, list) or len(root_box) != 4:
            return set()
        result = set()
        for identity, record in local_regions.items():
            parents = set(record.get("parentEvidenceIds", []))
            if parents & (parent_refs & set(pixel_regions)) and fully_contains(root_box, record.get("box", [])):
                result.add(identity)
        return result

    def preserve_accepted_node(previous_node: Mapping[str, Any]) -> dict[str, Any]:
        """Keep each saved group intact and add only measured children that fit its bounds."""
        node = copy.deepcopy(previous_node)
        level = node.get("level", 1)
        if type(level) is not int or level < 1:
            raise InvalidHierarchyError("Accepted hierarchy node has an invalid level")
        if level >= depth:
            node.pop("children", None)
            return node
        prior_children = previous_node.get("children", [])
        if prior_children:
            children = [preserve_accepted_node(child) for child in prior_children]
        else:
            refs = set(node.get("evidenceRefs", []))
            member_refs = refs & set(candidates)
            if node.get("provenance", {}).get("kind") == "measurement" and node.get("id") in candidates:
                child_ids = list(candidates[node["id"]].get("childEvidenceIds", []))
            else:
                child_ids = sorted(member_refs)
            children = [candidate_node(identity, level + 1, depth)
                        for identity in child_ids if identity in candidates]
        for child in children:
            if not fully_contains(node.get("box", []), child.get("box", [])):
                raise InvalidHierarchyError(
                    f"Accepted parent {node.get('id')} cannot contain its measured children; "
                    "refine is unsupported for this accepted bound")
        if children:
            node["children"] = children
        else:
            node.pop("children", None)
        return node

    old_roots = previous.get("nodes", [])
    if not old_roots or not previous.get("hierarchy"):
        return
    rebuilt_roots = rebuilt.get("nodes", [])
    preserved_roots = []
    changed = False
    for old_root in old_roots:
        provenance = old_root.get("provenance", {})
        if old_root.get("level") != 1:
            preserved_roots.append(old_root)
            continue
        old_refs = set(old_root.get("evidenceRefs", []))
        accepted_refs = old_refs & evidence_ids
        candidate_refs = accepted_refs & set(candidates)
        if provenance.get("kind") == "measurement":
            measured_id = old_root.get("id") if old_root.get("id") in candidates else next(iter(candidate_refs), None)
            accepted = copy.deepcopy(old_root)
            accepted["children"] = ([candidate_node(child_id, 2, depth)
                                     for child_id in candidates[measured_id].get("childEvidenceIds", [])]
                                    if depth >= 2 and measured_id in candidates else [])
            preserved_roots.append(accepted)
            changed = True
            continue
        if provenance.get("kind") != "inference":
            preserved_roots.append(old_root)
            continue
        matches = [node for node in rebuilt_roots
                   if accepted_refs & (set(node.get("evidenceRefs", [])) & evidence_ids)]
        matched_refs = set().union(*(set(node.get("evidenceRefs", [])) & evidence_ids
                                    for node in matches)) if matches else set()
        if not candidate_refs or not candidate_refs <= matched_refs:
            raise InvalidHierarchyError(
                f"Accepted parent {old_root.get('id')} cannot be refined from its saved evidence")
        accepted = copy.deepcopy(old_root)
        local_refs = allowed_local_refs(accepted_refs, accepted.get("box", []))
        child_scope = candidate_refs | local_refs | (accepted_refs & set(pixel_regions))
        children = []
        if depth >= 2:
            prior_children = old_root.get("children", [])
            if prior_children:
                children = [preserve_accepted_node(child) for child in prior_children]
            else:
                for matched in matches:
                    if matched.get("role") == "section" and matched.get("level") == 1:
                        for component in matched.get("children", []):
                            component_refs = set(component.get("evidenceRefs", [])) & evidence_ids
                            selected_refs = component_refs & candidate_refs
                            selected_local_refs = component_refs & local_refs
                            if component_refs and component_refs <= child_scope:
                                children.append(copy.deepcopy(component))
                            else:
                                children.extend(candidate_node(evidence_id, 2, depth)
                                                for evidence_id in sorted(selected_refs))
                                children.extend(local_region_node(evidence_id, 2, candidate_refs)
                                                for evidence_id in sorted(selected_local_refs))
                    else:
                        matched_refs = set(matched.get("evidenceRefs", [])) & child_scope
                        children.extend(candidate_node(evidence_id, 2, depth)
                                        for evidence_id in sorted(matched_refs & candidate_refs))
                        children.extend(local_region_node(evidence_id, 2, candidate_refs)
                                        for evidence_id in sorted(matched_refs & local_refs))
                if not children:
                    children = [candidate_node(evidence_id, 2, depth)
                                for evidence_id in sorted(candidate_refs)]
                    children.extend(local_region_node(evidence_id, 2, candidate_refs)
                                    for evidence_id in sorted(local_refs))
            children_by_id = {child["id"]: child for child in children}
            children = list(children_by_id.values())
            children.sort(key=lambda child: (child["box"][1], child["box"][0]))
        accepted["children"] = children
        if any(not fully_contains(accepted["box"], child["box"]) for child in children):
            raise InvalidHierarchyError(
                f"Accepted parent {old_root.get('id')} does not contain its refined components")
        preserved_roots.append(accepted)
        changed = True
    if changed:
        rebuilt["nodes"] = preserved_roots
        hierarchy = rebuilt["hierarchy"]
        hierarchy["rootCount"] = len(preserved_roots)
        hierarchy["recursiveNodeCount"] = sum(1 for _ in walk(preserved_roots))
        actual_depth = max((node.get("level", 1) for node in walk(preserved_roots)), default=0)
        hierarchy["achievedDepth"] = actual_depth
        hierarchy["availableDepth"] = actual_depth
        hierarchy["completedPasses"] = list(range(1, min(depth, actual_depth) + 1))
        hierarchy["stopReason"] = "no_meaningful_children" if actual_depth < depth else "requested_depth_reached"


def refine_scene(scene_source: str | Path, image_path: str | Path, output_dir: str | Path, *,
                 depth: int, inspector: bool = False) -> dict[str, Any]:
    """Build a deeper (or shallower) scene using only previously saved evidence."""
    if type(depth) is not int or not 1 <= depth <= 3:
        raise InvalidHierarchyError("Depth must be an integer from 1 to 3")
    wall_started = time.perf_counter()
    scene_path, image_path, output_dir = Path(scene_source), Path(image_path), Path(output_dir)
    scene = json.loads(scene_path.read_text())
    if not isinstance(scene, dict) or not isinstance(scene.get("sourceSha256"), str):
        raise InvalidHierarchyError("Scene JSON must include a source hash")
    measurement, measurement_path, _ = _load_measurement_for_scene(scene_path, scene)
    source = image_path.read_bytes()
    if sha256(source) != scene["sourceSha256"]:
        raise ValueError("Screenshot content does not match the scene's source hash")
    upright = _load_upright_image(image_path)
    if list(upright.size) != scene.get("imageSize"):
        raise ValueError("Screenshot dimensions do not match the extracted scene")
    _validate_saved_roi(measurement.get("roi"), list(upright.size))
    if measurement.get("imageSize") != scene.get("imageSize") or measurement.get("roi") != scene.get("roi"):
        raise InvalidHierarchyError("Saved measurement dimensions or ROI do not match the scene")
    if scene.get("hierarchy"):
        validate_scene_hierarchy(scene, tolerance=0)
    hierarchy_started = time.perf_counter()
    previous_depth = scene.get("hierarchy", {}).get("achievedDepth", 0)
    if not previous_depth:
        previous_depth = max((node.get("level", 1) for node in walk(scene.get("nodes", []))), default=0)
    result_scene, _ = build_hierarchy(measurement, depth)
    result_scene["hierarchy"]["measurementSha256"] = _measurement_hash(measurement)
    _preserve_reviewed_roots(scene, result_scene, measurement, depth)
    _preserve_accepted_groups(scene, result_scene)
    validate_scene_hierarchy(result_scene, tolerance=0)
    achieved = result_scene["hierarchy"]["achievedDepth"]
    added_passes = list(range(previous_depth + 1, achieved + 1)) if achieved > previous_depth else []
    if achieved < depth:
        stop_reason = "no_meaningful_children"
    elif depth < previous_depth:
        stop_reason = "requested_depth_reached"
    elif achieved <= previous_depth:
        stop_reason = "structure_unchanged"
    else:
        stop_reason = "requested_depth_reached"
    result_scene["hierarchy"]["stopReason"] = stop_reason
    evaluated_pass_times = result_scene["hierarchy"].get("passTimingsSeconds", {})
    added_pass_times = {str(level): evaluated_pass_times[str(level)]
                        for level in added_passes if str(level) in evaluated_pass_times}
    timings = {"ocr": 0.0, "nativeOcrHelperCompilation": 0.0, "measurement": 0.0,
               "hierarchy": time.perf_counter() - hierarchy_started}
    copied_measurement = json.loads(measurement_path.read_text())
    return _write_artifacts(result_scene, copied_measurement, output_dir, image_path,
                            inspector=inspector, timings=timings,
                            cache={"measurement": True, "hierarchy": False},
                            ocr_invocations=0, wall_started=wall_started, mode="refine",
                            pass_counts={"evaluated": result_scene["hierarchy"]["completedPasses"],
                                         "computed": added_passes, "added": added_passes,
                                         "timingsEvaluated": evaluated_pass_times,
                                         "timingsAdded": added_pass_times})
