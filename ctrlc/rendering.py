#!/usr/bin/env python3
"""Build a local interactive inspector from an extracted scene and its screenshot."""
import base64
import hashlib
import io
import json
from pathlib import Path
from typing import Any, Mapping

from PIL import Image, ImageOps


ASSETS = Path(__file__).resolve().parent / "assets"


class InvalidSceneError(ValueError):
    """Saved scene data is not in the supported object shape."""


def render(scene_source: str | Path | Mapping[str, Any], image_path: str | Path,
           fragment: bool = False) -> str:
    """Render a saved scene and matching screenshot into a standalone inspector."""
    if isinstance(scene_source, Mapping):
        scene = dict(scene_source)
    else:
        scene = json.loads(Path(scene_source).read_text())
    if not isinstance(scene, dict):
        raise InvalidSceneError("Scene JSON must be an object")
    if (not isinstance(scene.get("sourceSha256"), str)
            or not isinstance(scene.get("imageSize"), list)
            or len(scene["imageSize"]) != 2
            or not isinstance(scene.get("nodes"), list)):
        raise InvalidSceneError("Scene JSON must contain sourceSha256, imageSize, and a nodes array")
    source = Path(image_path).read_bytes()
    if hashlib.sha256(source).hexdigest() != scene["sourceSha256"]:
        raise ValueError("Screenshot content does not match the scene's source hash")
    with Image.open(io.BytesIO(source)) as raw:
        image = ImageOps.exif_transpose(raw).convert("RGB")
    if list(image.size) != scene["imageSize"]:
        raise ValueError("Screenshot dimensions do not match the extracted scene")
    for node in scene["nodes"]:
        if (not isinstance(node, Mapping) or not isinstance(node.get("box"), list)
                or len(node["box"]) != 4
                or any(not isinstance(value, (int, float)) for value in node["box"])):
            raise InvalidSceneError("Each scene node must contain a four-number box")
        if node["box"][2] <= 0 or node["box"][3] <= 0:
            raise ValueError("Inspector nodes must have positive dimensions")
    encoded = io.BytesIO()
    image.save(encoded, format="PNG", optimize=True)
    data_url = "data:image/png;base64," + base64.b64encode(encoded.getvalue()).decode()
    template = (ASSETS / "inspector.html").read_text()
    matte = (ASSETS / "alpha_matte.js").read_text()
    # OCR content remains inert JSON, even if it contains HTML/script-looking text.
    data = json.dumps(scene, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    html = (template.replace("__SCENE_JSON__", data).replace("__IMAGE_DATA_URL__", data_url)
            .replace("__MATTE_JS__", matte))
    if len(html.encode()) >= 1_000_000 and fragment:
        raise ValueError("Inline inspector exceeds 1 MB; use standalone output")
    if fragment:
        return html
    header = ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
              '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
              '<meta name="color-scheme" content="light">\n'
              '<title>Screenshot component inspector</title>\n'
              '<style>html{color-scheme:light}body{margin:0;padding:28px;'
              'background:#f3f4f6}main{max-width:920px;margin:0 auto}'
              '@media(max-width:520px){body{padding:14px}}</style>\n</head>\n<body>\n<main>\n')
    return header + html + "\n</main>\n</body>\n</html>\n"


def render_scene(scene: str | Path | Mapping[str, Any], image_path: str | Path,
                 output_path: str | Path, *, fragment: bool = False) -> dict[str, Any]:
    """Render supplied scene data and screenshot to a caller-selected output path."""
    html = render(scene, image_path, fragment=fragment)
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(html)
    return {"html": str(target.resolve()), "bytes": len(html.encode()), "llmCalls": 0}
