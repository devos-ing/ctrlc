# Run the local hierarchy benchmark

The runner compares the installed `ctrlc` command with the annotations in
`manifest.json`. It reads only the requested split. The default split is
`tuning`; it does not read held-out screenshots or annotations.

The screenshots and fixed OCR files in `fixtures/` are local inputs and are
excluded from Git. Restore matching inputs at the paths in `manifest.json`
before running the benchmark. The manifest records original local paths or
pinned source URLs, source hashes, and any unknown screenshot asset licenses.
The repository includes the runner, annotations, manifest, and results report.

Install a wheel outside the source checkout. Then run the benchmark from any
working directory:

```bash
python benchmarks/runner.py \
  --manifest benchmarks/manifest.json \
  --out /tmp/ctrlc-benchmark \
  --cli /absolute/path/to/installed/bin/ctrlc \
  --split tuning \
  --max-depth 3 \
  --repetitions 10
```

The runner rejects a CLI path inside the source checkout. It calls that command
from a temporary directory outside the checkout and passes only local image,
OCR, and annotation files. It accepts the generated direct `ctrlc.cli:main`
console entrypoint templates used by setuptools and uv, checks that the
installed distribution registers it at the supplied script path, then queries
that interpreter for the installed package and dependency versions and
package-file hashes. It stops if those bytes do not match the benchmark
checkout snapshot or if the command imports the package from the source tree.
Delegating wrappers remain unknown and cannot produce a benchmark result.

## Manifest and annotations

Each fixture record names a screenshot, fixed OCR file, annotation file, split,
source family, provenance, source hash, upright dimensions, and ROI. Paths are
relative to the manifest. `legacy_scene` records an earlier saved scene when
one exists. The runner still creates the legacy prediction through the
installed command, using the fixture's fixed OCR.

Each annotation records `source_sha256`, `width`, `height`, and `roi`. Its
`nodes` list contains unique IDs, ROI-relative `box` values, levels 1 through 3,
types, parent IDs, atomic-leaf status, and annotation status. Parent boxes must
fully contain children. `ignore_regions`, `ambiguities`, and
`allowed_alternatives` remain explicit. The manifest and annotations are local
evaluation inputs; the runner checks screenshot hashes and dimensions before
scoring them.

The current annotations were authored from the original screenshots and
independently reviewed by a model. They have not been verified by a human.
Reports preserve that status.

## Scoring and outputs

The scorer uses deterministic descending-IoU one-to-one matching with a 0.75
threshold and exact type matching, except that a section may match a container.
Hierarchical predictions match annotations at the same semantic level. The
legacy tree has no semantic levels, so its node score is level-agnostic and the
report labels it that way. The scorer does not invent levels or parents for
legacy nodes.

`result.json` contains per-screen and aggregate metrics. `per-screen.json`
keeps each screen's misses, false positives, required-control losses,
fragmentation, overmerges, matched-box IoU, parent-edge F1, and evidence
integrity result. `comparison.csv` contains the comparison rows.
`overlays/` contains the screenshot ROI with expected boxes in green and
predicted boxes in red. `artifacts/` contains the command outputs used by the
run.

The runner records separately labeled installed-package and benchmark-checkout
hashes, fixture ROI, the installed CLI and benchmark-runner Python/dependency
versions, platform, OCR calls, stage times, total wall time, rendering time,
and process peak memory when the platform reports it. Each sample's fresh or
warm state comes from CLI cache metadata; missing cache status stays unknown.
The report gives actual fresh, warm, and unknown sample counts, since an
existing output cache can make even the first sample warm. Saved-evidence
refinement has a separate cost row and reports its OCR count. All reported
local model-call counts are zero.

Pass `--native-ocr-track` on macOS with `swiftc` to measure native Vision OCR at
depth one. The result separates the first helper compilation time from OCR
time, then records warm cache runs. This track is optional because fixed OCR
data gives comparable inputs across grouping configurations.

The proposed 90% precision and recall targets are not acceptance claims. Use
the per-screen errors and overlays to decide whether a rule change helps. Do
not tune thresholds on the held-out split. Run that split only after the
grouping rules are frozen.
