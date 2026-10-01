# Screenshot to UI layers with bounded model work

Use this flow when the requested result is a component tree and style estimates
from a screenshot. `ctrlc` measures locally; an agent may use model judgment
only for uncertain names, roles, or grouping.

1. Select the application region. Exclude keyboard, OS chrome, and watermarks
   when they are outside the requested UI. Record the ROI in screenshot pixels.
2. Run `ctrlc extract` with the screenshot, ROI, and output directory. Add
   `--inspector` only when a visual preview is requested. Pass `--depth 1`,
   `--depth 2`, or `--depth 3` to opt in to a hierarchy. Omit it to retain the
   legacy scene. Native OCR uses macOS Vision; elsewhere, supply compatible OCR
   with `--ocr-json`.
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

## Saved hierarchy refinement

An opted-in extraction saves immutable OCR and pixel evidence in a
`measurements-*.json` file. The scene references that file by relative path and
content hash. Keep the scene, measurement file, and matching screenshot together.

Run `ctrlc refine` to request another saved depth:

```bash
ctrlc extract screenshot.png --out result --depth 1
ctrlc refine result/scene.json screenshot.png --out refined --depth 3 --inspector
```

Refinement checks the screenshot hash, source dimensions, ROI, and measurement
hash. It does not run OCR. It retains accepted section IDs and names when their
evidence stays the same. The result reports the requested and achieved depths,
completed passes, stop reason, node counts, cache state, and artifact paths.

The inspector's depth selector only displays levels saved in the scene. Use
`Raw candidates` to inspect measured OCR and pixel candidates with their
grouping decisions. Changing the selector does not extract or refine data.

## Reusable agent prompt

For installation and PATH setup, see [README Installation](README.md#installation).
Attach a screenshot or provide a local image path with this prompt.

```text
Use ctrlc to analyze the screenshot I've attached, or the local image path I've provided.
Use the attachment's local file if one is available. Otherwise, save the original attachment locally without resizing it.
If you can't access or save the attachment, ask me for a local file path.
Save the results in a new output folder unless I specify one, and tell me where it is.
Extract the application UI with --inspector, read the reported packet.json once, and open the inspector.
Keep the measured bounds and colors. Mark details you can't verify as unknown.
If you change the inspector's styling, render the saved scene without extracting again.
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
