# Screenshot to UI layers with bounded model work

Use this flow when the requested result is a component tree and style estimates
from a screenshot. `ctrlc` measures locally; an agent may use model judgment
only for uncertain names, roles, or grouping.

1. Select the application region. Exclude keyboard, OS chrome, and watermarks
   when they are outside the requested UI. Record the ROI in screenshot pixels.
2. Run `ctrlc extract` with the screenshot, ROI, and output directory. Add
   `--inspector` only when a visual preview is requested. Native OCR uses
   macOS Vision; elsewhere, supply compatible OCR with `--ocr-json`.
3. Check the JSON response, then read the reported `packet.json` once. Keep
   `scene.json` on disk for detailed evidence. If the inferred roles and
   grouping already satisfy the request, finish here.
4. If semantic review is needed, review the compact packet once. Read the
   screenshot only when visual information is necessary. Request changes by
   node ID; preserve measured bounds and colors.
5. Validate that every edit references an existing node and every proposed
   parent contains its child. Save the reviewed scene while preserving pixel
   and OCR evidence separately from inferred design choices.
6. If interactive inspection is requested, run `ctrlc render` with the saved
   reviewed scene and its source screenshot. This renders saved data without
   extraction or OCR. Treat a requested prototype, Figma export, or visual QA
   as a separate task.

The command has no model client or network request. It never interprets prompts
or constructs shell commands. Agents choose command arguments, read the
resulting packet, and perform any optional semantic review themselves.

## Reusable agent prompt

```text
If uv is missing, install it from https://docs.astral.sh/uv/getting-started/installation/.
Install ctrlc 0.1.0 with `uv tool install https://github.com/devos-ing/ctrlc/releases/download/v0.1.0/ctrlc-0.1.0-py3-none-any.whl`; add `--force` if already installed. Check `ctrlc --version` and `ctrlc --help`.
If `ctrlc` is not on PATH, invoke it by its full path under the directory printed by `uv tool dir --bin`.
Set SCREENSHOT_PATH and OUTPUT_DIR from user-supplied paths. Ask only for missing paths. Inspect the screenshot, exclude OS chrome when present, and choose the application ROI in upright pixels; ask if bounds are unclear.
Run `ctrlc extract "$SCREENSHOT_PATH" --roi X,Y,W,H --out "$OUTPUT_DIR" --inspector`. If native Vision OCR is unavailable, use `--ocr-json` only with compatible OCR supplied by the user; ask if missing.
Check the success JSON and read its reported packet once. Review uncertain roles and grouping. Preserve measured bounds and colors; leave font, responsive, or behavior details unknown only when evidence is insufficient.
Open the reported inspector HTML. If HTTP is needed, start `ctrlc serve "$OUTPUT_DIR/inspector.html" --port 0` in the background and open its URL. For style requests, render the reviewed scene with the same screenshot; do not extract again.
```

After semantic review, render the saved scene with:

```bash
ctrlc render result/reviewed-scene.json screenshot.png --out result/inspector.html
```

## Supplied OCR and compatibility

An alternate OCR provider can write JSON with the crop dimensions and text
boxes in orientation-corrected pixels:

```json
{"width":300,"height":250,"texts":[{"text":"Continue","confidence":0.99,"box":[100,170,90,20]}]}
```

Each box is `[x,y,width,height]`. An optional `words` array contains objects
with `text` and `box` fields. Pass the file with `ctrlc extract --ocr-json`.
The original script entry points remain available as `python3 extract_ui.py`,
`python3 render_inspector.py`, and `python3 preview_server.py`.

The local detector and renderer make zero model calls; optional semantic
review is a separate action by the calling agent.

## Evidence and estimates

`run.json` reports bytes, wall time, cache status, and zero model calls for the
local stage. Bytes are not an exact token count. Native OCR confidence
describes text recognition; it does not certify component roles. Bounds and
colors come from pixels. Names, grouping, corner-radius estimates, and style
clustering are inferences. Review complex layouts before treating them as a
design system.
