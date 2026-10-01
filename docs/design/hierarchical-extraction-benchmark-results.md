# Hierarchical extraction benchmark results

Date: 2026-10-01. Status: experimental opt-in implementation.

GPT-6 Luna at xhigh implemented the feature. GPT-6.1 Sol at xhigh reviewed the code, verified repairs, and independently reviewed screenshot annotations. The final code-review receipt is `.scratch/deliver-code/hierarchical-extraction/final-review-v6.json`.

The completed benchmark uses 12 screenshots, six tuning and six held-out, with ten samples per configuration. Grouping rules and annotations stayed fixed for held-out evaluation. A source-coordinate rounding defect found during execution was repaired on a synthetic 842 by 577 image; no held-out images or labels were supplied to the implementer.

The annotations are model-authored and independently model-reviewed. They are not human-verified. Scores describe this small labeled corpus and the chosen strict type, level, and box matching rules.

## Quality by requested depth

The table reports per-screen macro F1 for all returned nodes up to the requested depth. It does not compare different detail targets as if they were the same task.

| Split | Depth 1 | Depth 2 | Depth 3 |
| --- | ---: | ---: | ---: |
| Tuning | 0.413 | 0.337 | 0.379 |
| Held out | 0.140 | 0.031 | 0.211 |
| All screens | 0.277 | 0.184 | 0.295 |

The supplied shopping screenshot has six predicted main sections. Five match the six expected sections, with precision, recall, and F1 of 0.833 at depth one. Its cumulative depth-two F1 is 0.441 and depth-three F1 is 0.400. The remaining depth-one miss is the floating navigation enclosure.

The proposed 90% precision and recall targets are not met. Depth two and three remain unreliable across unfamiliar layouts. Existing legacy extraction stays the default. Omit `--depth` to use it.

Legacy scores are labeled level-agnostic. Hierarchical scores require matching semantic levels, so the headline legacy and depth-three values are not an equivalent comparison. The reports include node matches, misses, parent edges, fragments, overmerges, and unmatched required controls for inspection. Unmatched controls can reflect an incorrect type, level, or enclosure; they do not establish that raw source evidence was deleted.

## Integrity and costs

All hierarchical evidence-integrity checks pass. Original measurement files remain immutable, and source hashes, dimensions, ROIs, and unknown font fields are retained. All 240 saved-evidence refinement samples report zero OCR invocations. Local workflows report zero LLM calls.

Ten extraction samples consist of one fresh measurement sample and nine warm-cache samples for each screen and configuration. Native OCR and saved-evidence refinement have separate tracks. Reports retain actual cache states, sample counts, wall time, per-pass time, bytes, and available memory measurements. Null memory or stage fields remain unknown.

The benchmark used an outside-checkout installed wheel with Python 3.10.21, Pillow 12.3.0, and NumPy 2.2.6. Package source and assets match the reviewed snapshot. The runner verifies the registered direct CLI entrypoint and package hashes before and after commands. Opaque wrappers and mismatched code stop the run.

## Reproduce and inspect

Build and install the reviewed wheel outside this checkout, then run:

```bash
python3 benchmarks/runner.py --manifest benchmarks/manifest.json --out /tmp/ctrlc-benchmark --cli /absolute/path/to/installed/bin/ctrlc --split all --max-depth 3 --repetitions 10 --native-ocr-track
```

Detailed results are saved locally:

- `.scratch/deliver-code/hierarchical-extraction/verified-all-v6/result.json`
- `.scratch/deliver-code/hierarchical-extraction/verified-all-v6/per-screen.json`
- `.scratch/deliver-code/hierarchical-extraction/verified-all-v6/comparison.csv`
- `.scratch/deliver-code/hierarchical-extraction/verified-all-v6/overlays/`
- `.scratch/deliver-code/hierarchical-extraction/verification-evidence.json`

Additional public screenshot examples come from the [UIED repository](https://github.com/MulongXie/UIED), pinned in `benchmarks/manifest.json`. Original local screenshot fixtures remain local; this task does not publish them.

Use this benchmark to locate failures and evaluate the next independently planned improvement. Do not tune the current rules against the held-out errors while continuing to call that split held out.
