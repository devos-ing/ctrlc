# Screenshot extraction benchmark

Recorded on 2026-10-01 against the 0.1.0 candidate/current code at that time.
This report is a historical baseline, not a 0.1.1 benchmark. Hierarchical
extraction remains experimental and opt-in. Omit `--depth` to use the existing
default extraction workflow.

The benchmark covers 12 screenshots with six used for tuning and six held
out for evaluation. Each configuration has ten runs. Screens from the same
app or template family stay in one split. The
[fixture manifest](benchmarks/manifest.json) records source hashes, regions
of interest, provenance, and annotation paths.

Labels were authored from screenshots and independently reviewed by a model.
They have not been verified by a human. The results describe this small
corpus, rather than general accuracy across applications.

## Quality results

Depth one returns main sections, depth two returns components, and depth three
returns meaningful contents. Each row below reports the mean per-screen F1
for all nodes up to the requested depth. F1 balances precision and recall.

| Split | Depth 1 | Depth 2 | Depth 3 |
| --- | ---: | ---: | ---: |
| Tuning | 0.413 | 0.337 | 0.379 |
| Held out | 0.140 | 0.031 | 0.211 |
| All 12 screens | 0.277 | 0.184 | 0.295 |

The shopping screenshot recovered five of six main sections at depth one,
with precision, recall, and F1 of **0.833**. Its cumulative F1 was **0.441** at
depth two and **0.400** at depth three. The floating navigation enclosure
was the remaining depth-one miss.

The proposed 90% precision and recall targets were not met. Deeper extraction
remains unreliable on unfamiliar layouts, and more passes do not guarantee
better results.

Matching uses a box intersection-over-union threshold of 0.75, compatible
types, and the same semantic level. Reports also include parent edges,
fragmentation, overmerges, and unmatched required controls. An unmatched
control can have the wrong enclosure, type, or level while its raw evidence
remains available.

Legacy extraction has no semantic levels and receives a level-agnostic score.
Its headline F1 is not directly comparable to the hierarchical scores.

## Evidence integrity and execution cost

All hierarchical evidence-integrity checks passed. Source hashes, ROI
coordinates, measured bounds and colors, and unknown font fields are
preserved. All **240 saved-evidence refinement runs made zero OCR calls**.
Local extraction and rendering made zero LLM calls.

For each extraction configuration, the ten samples contain one fresh
measurement run and nine warm-cache runs. Native OCR and saved-evidence
refinement have separate cost tracks. The report records actual cache states,
sample counts, wall time, per-pass time, artifact bytes, and available memory
measurements. Missing measurements remain unknown.

The run used a wheel installed outside the checkout with Python 3.10.21,
Pillow 12.3.0, and NumPy 2.2.6. Package source and bundled assets matched the
reviewed code. The runner verified the registered CLI entrypoint and installed
package hashes before and after each command.

## Reproduce the benchmark

Install the current checkout into a tool environment outside the source
directory:

```bash
uv tool install --force .
```

Screenshots and fixed OCR inputs remain local and are excluded from Git. Restore
matching inputs at the paths in the manifest; see the
[benchmark runner guide](benchmarks/README.md) for fixture provenance.
Then run from the repository root:

```bash
python3 benchmarks/runner.py \
  --manifest benchmarks/manifest.json \
  --out /tmp/ctrlc-benchmark \
  --cli "$(command -v ctrlc)" \
  --split all \
  --max-depth 3 \
  --repetitions 10 \
  --native-ocr-track
```

The native OCR track requires macOS and `swiftc`. Omit `--native-ocr-track`
to run with the saved OCR inputs alone.

The output directory contains `result.json`, `per-screen.json`,
`comparison.csv`, prediction and annotation overlays, and command artifacts.
See the [benchmark runner guide](benchmarks/README.md) for the input format
and scoring details.

Keep held-out rules and labels fixed when comparing results. Further tuning
against this split requires a new independent evaluation set.
