# Hierarchical extraction and benchmarking plan

Status: implementation in progress. The opt-in hierarchy CLI, saved measurements,
inspector controls, and benchmark runner are implemented. Final review and the
full benchmark are pending.
Date: 2026-10-01.

Build a useful component hierarchy from a screenshot. Let callers choose a maximum detail depth, while preserving the original measured evidence. Prove that the hierarchy removes noise without losing important UI.

## Define what a loop does

Each pass adds one level to the hierarchy. Repeating identical extraction does not count as refinement.

| Requested depth | Result | Shopping screenshot example |
| --- | --- | --- |
| 1 | Main UI sections | Shortcuts, order card, email card, Recently viewed, brand card, bottom navigation |
| 2 | Components within each section | Shortcut buttons, carousel product cards, brand header, product row, navigation buttons |
| 3 | Meaningful component contents | Labels, price badges, ratings, product images, action icons |

Treat photographs and complete icons as leaves. Four disconnected squares belonging to one grid icon remain one useful asset. A component can stop before the requested depth when no meaningful children can be verified. Overlapping sections, such as floating navigation, remain independent roots when appropriate.

Support depths 1 through 3 for the first release. Keep the current extraction behavior when the depth option is omitted until benchmark results justify a default change. Do not impose a depth of three on existing saved scenes.

## Preserve measurements separately from grouping

Reuse `run_extraction`, the existing renderer, the existing preview server, and the native OCR helper. Keep model calls and network requests outside local extraction and rendering.

Introduce a saved measurement artifact containing the source hash, upright image dimensions, ROI, OCR results and confidence, pixel candidates, measured styles, and evidence IDs. Keep exact fonts, original assets, layout behavior, and unsupported roles unknown.

The active scene contains the useful hierarchy and references the measurement artifact. Every raw candidate remains available as evidence, even when the useful hierarchy omits it. Unknown assets are not automatically noise. A verified product photograph is useful even when its original asset identity is unknown.

Existing measured bounds and colors remain unchanged. A new grouping node can use a union of child bounds or a separately measured contour, but it records the method and its evidence references. A union is an inferred enclosure, not a recovered original component boundary. Never shrink a measured child to fit a proposed parent.

Keep all scene boxes ROI-relative. Add the ROI origin only when sampling or displaying the original screenshot. Require unique IDs, an acyclic tree, and full parent containment, with an explicit small pixel tolerance. Center-point containment alone is insufficient. Record clipping at the screenshot boundary without guessing offscreen bounds.

Preserve evidence IDs and previously accepted group IDs across refinement. Give new groups deterministic IDs based on their evidence and grouping level. Define a cross-depth contract: a depth-one scene matches the root projection of deeper scenes, and refinement keeps accepted parents stable. An explicit regrouping operation can revise a parent later.

Split cache identity into two parts:

- Measurement cache: source hash, ROI, OCR input or provider, language, and measurement algorithm version.
- Hierarchy cache: measurement hash, grouping algorithm version, and requested depth.

Changing depth or inspector presentation must reuse measurements. Changes to actual measurement rules must invalidate the relevant evidence cache.

## Proposed caller interface

These commands are proposed and do not exist yet:

```bash
ctrlc extract screenshot.png --out result --inspector --depth 1
ctrlc refine result/scene.json screenshot.png --out refined --depth 3 --inspector
```

Extend the Python interface with `run_extraction(..., depth=None)`. Add `refine_scene(scene_source, image_path, output_dir, *, depth)` for saved-evidence refinement. Accept caller-supplied paths and scenes. Validate the screenshot hash and measurement references before refinement.

`depth` is the maximum returned hierarchy level. Refinement can stop earlier. Return requested depth, achieved depth, completed passes, a stop reason, root count, recursive node count, and absolute artifact paths. Retain existing result fields for compatibility. Report local model calls as zero.

Keep argument parsing and result formatting in `ctrlc/cli.py`. Root scripts remain compatibility adapters. Preserve JSON errors, meaningful exit codes, `ctrlc`, and `python -m ctrlc`.

## Deliver in small checkpoints

1. **Freeze the contract and pilot annotations.** Label the three existing screenshot fixtures at all three levels. Specify atomic assets, clipping, overlay placement, and ambiguous regions. Audit the current flat output against those labels before tuning rules. Verify the labels independently of extracted nodes.
2. **Save reusable evidence.** Persist complete OCR and measured candidates, add evidence references, and separate measurement caching from hierarchy caching. Keep legacy output behavior available. Verify a saved scene can be refined outside the source checkout without native OCR.
3. **Make depth one useful.** Detect large sections using local background contrast, contours, whitespace, borders, and OCR placement. Support tall cards and panels. Reject a page-spanning residual region as a useful asset when it crosses distinct sections. Keep rejected candidates in the measurement artifact. Compare each rule change against the pilot before keeping it.
4. **Refine within accepted parents.** Apply region-specific measurement and grouping rules to find components, then meaningful contents. Reuse OCR boxes and original pixels. Group disconnected icon pieces and flag symbol-like OCR as uncertain evidence. Do not silently rewrite raw OCR or discard valid small text. Stop on atomic assets, unchanged structure, or insufficient evidence.
5. **Expose depth in the CLI and inspector.** Add the proposed interfaces and JSON fields. Preserve the white canvas and existing panels. Show the useful tree by default, with a way to inspect raw candidates and reasons for omission. Permit display of any saved depth and expansion of saved children. Rendering or changing visible depth does not run extraction. Refinement beyond saved depth requires the refinement workflow.
6. **Run the benchmark and release checks.** Compare legacy extraction with depths one, two, and three. Freeze rules before evaluating held-out screenshots. Keep only changes that improve grouping while preserving recall and measurements. Document actual results and remaining failure cases.

An optional agent review can correct names, roles, or grouping through a saved reviewed scene. Evaluate this separately from the local algorithm. Count its passes and model usage separately. Do not credit manual or agent fixes to local extraction.

## Build a benchmark with useful labels

Start with the sign-in, brokerage, and shopping fixtures. The current saved scenes are starting predictions, not ground truth. The reviewed brokerage scene still needs an independent annotation check.

Expand to 12 independently sourced screens covering forms, dashboards, shopping, lists, desktop panels, and dark or low-contrast UI. Include nested cards, floating overlays, clipped carousels, and disconnected icons. Use six screens for tuning and six for held-out evaluation. Keep screenshots from the same app or template family in one split. The three initial fixtures belong to tuning.

Each annotation records:

- Source hash, upright dimensions, ROI, and excluded chrome or watermarks.
- Expected nodes, component bounds, semantic level, type, parent, and atomic-leaf status.
- Important labels or controls that must not disappear.
- Explicit ambiguity and ignore regions, plus allowed alternative groupings where justified.
- Annotation version and review status.

Store the private shopping screenshot in a stable local benchmark directory before runs. Reference its hash in the manifest. Fixture availability and labels must be checked before a run. Avoid publishing copied screenshots as part of this plan.

## Score quality without rewarding extra layers

Use deterministic one-to-one box matching with type compatibility and an initial intersection-over-union threshold of 0.75. Freeze matching rules after the annotation pilot. Match predictions and ground truth at the same detail level. Unmatched expected nodes are misses. Unmatched active predictions are false positives, except in explicitly ignored regions. Raw candidates outside the active hierarchy do not count as useful predictions.

Report the legacy tree as emitted, without inventing missing parents or semantic levels for it. Report scores per depth and per screen so a coarse result cannot compete against a detailed target by returning fewer nodes.

| Metric | What it answers |
| --- | --- |
| Useful-node precision | How many returned nodes match valid UI components? |
| Useful-node recall | How many expected components were recovered? |
| F1 at each depth | Does noise reduction preserve coverage? |
| Parent-edge F1 | Are the expected parent-child relationships recovered, including missing edges? |
| Fragmentation | How many redundant pieces are emitted for one annotated atomic asset? |
| Matched-box IoU | How closely do detected bounds match the annotations? |
| Required-control retention | Did any annotated important control or label disappear? |
| Evidence integrity | Are original measured bounds, colors, hashes, and unknown fields preserved? |

Do not use total layer count or unknown-asset count as the quality score. Also record overmerges: one predicted asset that spans multiple annotated independent components. Report per-screen failures alongside aggregate scores.

Use provisional quality targets of at least 90% macro precision and recall at each supported depth, and at least 50% fewer redundant icon fragments on the complex fixtures. Permit no more than a two-percentage-point recall regression on simple forms. Treat these as proposed targets, not measured results. Adjust targets after the pilot, then freeze them before held-out evaluation.

Require zero lost important controls, zero original-evidence mutations, and zero malformed trees. Preserve unknowns rather than inventing details to improve a score. Unknown or ambiguous annotations must remain visible in the report.

## Measure cost separately

Record OCR time, measurement time, hierarchy time per pass, rendering time, total wall time, peak memory, node counts, artifact bytes, and OCR invocation count. Record the platform, Python and dependency versions, code hashes, fixture hashes, ROI, depth, and cache state.

Run ten repetitions per screenshot and configuration. Compare fresh measurement runs, warm-cache runs, and refinement from saved evidence separately. Treat the first native OCR helper compilation as a separate setup cost. Use identical screenshots, ROIs, fixed supplied OCR for grouping comparisons, and matching rendering settings. Run a separate native-OCR track to measure the full user workflow.

Report medians and observed tail timings with sample counts. Saved-evidence refinement must invoke OCR zero times and local workflows must make zero model calls. Establish the runtime budget from the pilot rather than comparing historical timings with unknown conditions.

For each rule change, compare the prior implementation with the changed implementation on the same tuning fixtures. This shows which rule actually helps. Avoid tuning thresholds on the held-out split after seeing its results.

## Benchmark runner and artifacts

Add a small local benchmark runner that calls the installed CLI from outside the checkout. Keep scoring separate from the production package and avoid new production dependencies beyond Pillow and NumPy. Run from a fixture manifest with a versioned annotation file.

The runner writes a result JSON file, per-screen metrics, code and fixture metadata, a comparison table, and visual overlays of predictions and annotations. Report separate rows for legacy, depth one, depth two, depth three, and optional reviewed output. Fail clearly for missing fixtures, invalid labels, invalid output, or source mismatches.

Keep a small benchmark subset for routine checks. Run the full annotated corpus for changes to grouping rules and before release. The corpus is an evaluation dataset, not a reason to create one unit test per heuristic.

## Verification through real workflows

Add only a small number of E2E cases to the existing installed-package checks:

- Extract at depth one, refine to depth three, render, and serve the result from outside the checkout. Verify hierarchy validity, important controls, stable measurements and IDs, explicit artifacts, and no OCR during refinement.
- Reject invalid depth, missing evidence, and mismatched screenshots with documented JSON errors and exit codes.

Retain existing regressions. Run the repository commands after implementation:

```bash
uv run --extra test python -m unittest test_cli_e2e -v
uv run --extra test python -m unittest test_extract_ui test_render_inspector -v
node --test test_alpha_matte.js
```

Verify wheel installation with Python 3.10 or newer and bundled inspector and native OCR assets. Check old saved scenes, bookmarks, and the showcase embedding where affected. Do not rewrite unrelated website or inspector work already in progress.

## Current diagnostic baseline

The accompanying `docs/design/hierarchical-extraction-baseline.json` inventories saved artifacts without extracting again or rereading their packets. All three source hashes match their scenes.

| Fixture | Root candidates | Total recursive nodes | Current tree depth |
| --- | --- | --- | --- |
| Sign-in | 7 | 14 | 2 |
| Brokerage | 29 | 38 | 2 |
| Shopping | 37 | 42 | 2 |

These counts describe detector output only. They are not benchmark scores. Historical elapsed times are retained in the snapshot with unknown execution conditions and must not be used as comparative performance claims. Accuracy remains unmeasured until independent annotations and a scorer exist.

The first reviewable implementation checkpoint is a depth-one scene for the three pilot screens, a preserved measurement artifact, and a report showing precision, recall, and visible errors. Complete that checkpoint before adding deeper passes.
