"""Build the cursor-motion style preview from the saved brokerage scene."""
from __future__ import annotations

import html
import argparse
import json
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ctrlc.rendering import render  # noqa: E402


def scoped_fragment(source: str, *, root_id: str, board_id: str) -> str:
    image_match = re.search(r"source\.src = '(data:image/png;base64,[^']+)';", source)
    if image_match is None:
        raise ValueError("Renderer fragment did not contain its inline screenshot")
    image_url = image_match.group(1)
    source = source.replace(
        f"source.src = '{image_url}';",
        "source.src = document.getElementById('ctrlc-shared-source').src;",
        1,
    )
    source = source.replace("ui-exploded-inspector", root_id)
    source = source.replace('id="el-board"', f'id="{board_id}"')
    source = source.replace('aria-controls="el-board"', f'aria-controls="{board_id}"')
    return source


def build(output_path: Path) -> Path:
    scene_path = ROOT / "brokerage" / "reviewed-scene.json"
    image_path = ROOT / "brokerage" / "source.png"
    scene = json.loads(scene_path.read_text())
    if len(scene.get("nodes", [])) != 11 or not any(node.get("id") == "b6" for node in scene["nodes"]):
        raise ValueError("Saved brokerage scene no longer matches this demo's selected layer")

    rendered = render(scene_path, image_path, fragment=True)
    image_match = re.search(r"source\.src = '(data:image/png;base64,[^']+)';", rendered)
    if image_match is None:
        raise ValueError("Renderer fragment did not contain its inline screenshot")
    image_url = image_match.group(1)

    desktop = scoped_fragment(rendered, root_id="ctrlc-desktop-inspector", board_id="cd-desktop-board")
    focus = scoped_fragment(rendered, root_id="ctrlc-focus-inspector", board_id="cd-focus-board")
    template = (Path(__file__).with_name("template.html")).read_text()
    shared_image = (
        '<img class="cd-shared-source" id="ctrlc-shared-source" '
        f'src="{html.escape(image_url, quote=True)}" alt="">'
    )
    output = template.replace("__SHARED_IMAGE__", shared_image)
    output = output.replace("__DESKTOP_INSPECTOR__", desktop)
    output = output.replace("__FOCUS_INSPECTOR__", focus)
    if re.search(r"__[A-Z_]+__", output):
        raise ValueError("Preview template contains an unfilled placeholder")
    if "<!doctype" in output.lower() or re.search(r"<\s*(html|head|body)(?:\s|>)", output, re.I):
        raise ValueError("Preview output must remain an HTML fragment")
    if output.count("data:image/png;base64,") != 1:
        raise ValueError("The shared screenshot must appear once in the preview")
    if len(output.encode("utf-8")) >= 1_000_000:
        raise ValueError("Preview exceeds the inline visualization size limit")

    output_path = output_path.expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(output, encoding="utf-8", newline="\n")
    return output_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="output HTML fragment path")
    print(build(parser.parse_args().out))
