#!/usr/bin/env python3
"""Validate curated saved scenes and prepare static website assets."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import shutil
import sys
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps


REPO_ROOT = Path(__file__).resolve().parents[3]
CATALOG_PATH = REPO_ROOT / "showcases" / "catalog.json"
WEB_ROOT = REPO_ROOT / "apps" / "web"
PUBLIC_ROOT = WEB_ROOT / "public"
GENERATED_ROOT = WEB_ROOT / "src" / "generated"
SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SHA_PATTERN = re.compile(r"^[a-f0-9]{64}$")


class CatalogError(ValueError):
    """Catalog inputs cannot be prepared safely."""


def catalog_path(value: Any, field: str, slug: str) -> Path:
    if not isinstance(value, str) or not value:
        raise CatalogError(f"{slug}: {field} must be a relative file path")
    candidate = (REPO_ROOT / value).resolve()
    if not candidate.is_relative_to(REPO_ROOT):
        raise CatalogError(f"{slug}: {field} must stay inside the repository")
    if not candidate.is_file():
        raise CatalogError(f"{slug}: {field} does not exist: {value}")
    return candidate


def finite_number(value: Any) -> bool:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except (OverflowError, ValueError):
        return False


def validate_scene(scene: Any, slug: str) -> list[dict[str, Any]]:
    if (not isinstance(scene, dict) or type(scene.get("schemaVersion")) is not int
            or scene["schemaVersion"] not in (1, 2)):
        raise CatalogError(f"{slug}: scene schemaVersion must be integer 1 or 2")

    image_size = scene.get("imageSize")
    roi = scene.get("roi")
    source_hash = scene.get("sourceSha256")
    if (not isinstance(image_size, list) or len(image_size) != 2
            or any(not isinstance(value, int) or isinstance(value, bool) or value <= 0 for value in image_size)):
        raise CatalogError(f"{slug}: imageSize must contain two positive integers")
    if (not isinstance(roi, list) or len(roi) != 4 or not all(finite_number(value) for value in roi)
            or roi[0] < 0 or roi[1] < 0 or roi[2] <= 0 or roi[3] <= 0
            or roi[0] + roi[2] > image_size[0] or roi[1] + roi[3] > image_size[1]):
        raise CatalogError(f"{slug}: roi must be a positive rectangle inside imageSize")
    if not isinstance(source_hash, str) or not SHA_PATTERN.fullmatch(source_hash):
        raise CatalogError(f"{slug}: sourceSha256 must be a lowercase SHA-256 digest")
    if not isinstance(scene.get("nodes"), list):
        raise CatalogError(f"{slug}: scene nodes must be an array")

    flattened: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    def visit(nodes: list[Any], depth: int) -> None:
        for node in nodes:
            if not isinstance(node, dict):
                raise CatalogError(f"{slug}: every scene node must be an object")
            node_id = node.get("id")
            node_type = node.get("type")
            box = node.get("box")
            if not isinstance(node_id, str) or not node_id:
                raise CatalogError(f"{slug}: every scene node must have a non-empty id")
            if node_id in seen_ids:
                raise CatalogError(f"{slug}: duplicate node id {node_id!r}")
            seen_ids.add(node_id)
            if not isinstance(node_type, str) or not node_type:
                raise CatalogError(f"{slug}: node {node_id!r} must have a non-empty type")
            if (not isinstance(box, list) or len(box) != 4 or not all(finite_number(value) for value in box)
                    or box[2] <= 0 or box[3] <= 0):
                raise CatalogError(f"{slug}: node {node_id!r} must have finite x/y and positive width/height")
            display_name = node.get("displayName") or node.get("label") or node.get("text") or node_type.title()
            flattened.append({
                "id": node_id,
                "type": node_type,
                "name": str(display_name),
                "box": box,
                "depth": depth,
            })
            children = node.get("children", [])
            if not isinstance(children, list):
                raise CatalogError(f"{slug}: node {node_id!r} children must be an array")
            visit(children, depth + 1)

    visit(scene["nodes"], 0)
    return flattened


def first_level_projection(scene: dict[str, Any]) -> dict[str, Any]:
    """Build the public showcase scene from top-level saved nodes only."""
    projection = copy.deepcopy(scene)
    roots = []
    for node in scene["nodes"]:
        root = copy.deepcopy(node)
        root.pop("children", None)
        if isinstance(root.get("level"), int):
            root["level"] = 1
        roots.append(root)
    projection["nodes"] = roots
    projection.pop("measurementArtifact", None)

    hierarchy = projection.get("hierarchy")
    if isinstance(hierarchy, dict):
        depth = 1 if roots else 0
        hierarchy["rootCount"] = len(roots)
        hierarchy["recursiveNodeCount"] = len(roots)
        hierarchy["requestedDepth"] = 1
        hierarchy["achievedDepth"] = depth
        hierarchy["availableDepth"] = depth
        hierarchy["supportedDepth"] = 1
        hierarchy["completedPasses"] = [1] if roots else []
        hierarchy["stopReason"] = "showcase_first_level_projection"
        hierarchy.pop("candidateAudit", None)
        hierarchy.pop("measurementSha256", None)
        pass_timings = hierarchy.get("passTimingsSeconds")
        if isinstance(pass_timings, dict):
            hierarchy["passTimingsSeconds"] = {key: value for key, value in pass_timings.items()
                                                if key == "1"}
    return projection


def main() -> int:
    sys.path.insert(0, str(REPO_ROOT))
    from ctrlc.rendering import render_scene

    try:
        catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        if not isinstance(catalog, list) or not catalog:
            raise CatalogError("showcases/catalog.json must be a non-empty array")

        seen_slugs: set[str] = set()
        prepared: list[dict[str, Any]] = []
        resolved_entries: list[tuple[dict[str, Any], Path, Path, dict[str, Any], list[dict[str, Any]]]] = []
        for entry in catalog:
            if not isinstance(entry, dict):
                raise CatalogError("Every catalog entry must be an object")
            slug = entry.get("slug")
            title = entry.get("title")
            context = entry.get("context")
            if not isinstance(slug, str) or not SLUG_PATTERN.fullmatch(slug):
                raise CatalogError(f"Invalid showcase slug: {slug!r}")
            if slug in seen_slugs:
                raise CatalogError(f"Duplicate showcase slug: {slug}")
            seen_slugs.add(slug)
            if not isinstance(title, str) or not title.strip():
                raise CatalogError(f"{slug}: title must be a non-empty string")
            if not isinstance(context, str) or not context.strip():
                raise CatalogError(f"{slug}: context must be a non-empty string")
            if not isinstance(entry.get("reviewed"), bool):
                raise CatalogError(f"{slug}: reviewed must be a boolean")

            scene_path = catalog_path(entry.get("scene"), "scene", slug)
            source_path = catalog_path(entry.get("source"), "source", slug)
            try:
                scene = json.loads(scene_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                raise CatalogError(f"{slug}: cannot read scene JSON: {error}") from error
            all_nodes = validate_scene(scene, slug)
            nodes = [node for node in all_nodes if node["depth"] == 0]
            try:
                with Image.open(source_path) as image:
                    oriented_size = ImageOps.exif_transpose(image).size
            except Exception as error:
                raise CatalogError(f"{slug}: cannot read source screenshot: {error}") from error
            if list(oriented_size) != scene["imageSize"]:
                raise CatalogError(f"{slug}: source screenshot dimensions do not match scene imageSize")

            actual_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
            if actual_hash != scene["sourceSha256"]:
                raise CatalogError(f"{slug}: source screenshot hash does not match scene sourceSha256")

            resolved_entries.append((entry, scene_path, source_path, scene, nodes))

        public_showcases = PUBLIC_ROOT / "showcases"
        if public_showcases.exists():
            shutil.rmtree(public_showcases)
        public_showcases.mkdir(parents=True, exist_ok=True)
        GENERATED_ROOT.mkdir(parents=True, exist_ok=True)

        for entry, scene_path, source_path, scene, nodes in resolved_entries:
            slug = entry["slug"]
            target_dir = public_showcases / slug
            target_dir.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_path, target_dir / "source.png")
            public_scene = first_level_projection(scene)
            (target_dir / "scene.json").write_text(
                json.dumps(public_scene, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            render_result = render_scene(
                public_scene,
                source_path,
                target_dir / "inspector.html",
            )
            prepared.append({
                "slug": slug,
                "title": entry["title"],
                "context": entry["context"],
                "reviewed": entry["reviewed"],
                "imageSize": scene["imageSize"],
                "roi": scene["roi"],
                "nodes": nodes,
                "imageUrl": f"/showcases/{slug}/source.png",
                "inspectorUrl": f"/showcases/{slug}/inspector.html",
                "sceneHash": scene["sourceSha256"],
                "inspectorBytes": render_result["bytes"],
            })

        entries_json = json.dumps(prepared, ensure_ascii=False, separators=(",", ":"))
        generated = '''export type ShowcaseNode = {
  id: string;
  type: string;
  name: string;
  box: [number, number, number, number];
  depth: number;
};

export type Showcase = {
  slug: string;
  title: string;
  context: string;
  reviewed: boolean;
  imageSize: [number, number];
  roi: [number, number, number, number];
  nodes: ShowcaseNode[];
  imageUrl: string;
  inspectorUrl: string;
  sceneHash: string;
  inspectorBytes: number;
};

export const showcases: Showcase[] = ''' + entries_json + ''';
'''
        (GENERATED_ROOT / "showcases.ts").write_text(generated, encoding="utf-8")
        print(f"Prepared {len(prepared)} showcases and {sum(len(item['nodes']) for item in prepared)} saved nodes.")
        return 0
    except (CatalogError, OSError, json.JSONDecodeError, ValueError) as error:
        print(f"showcase preparation failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
