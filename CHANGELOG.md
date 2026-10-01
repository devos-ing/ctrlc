# Changelog

## 0.1.1 - 2026-10-01

- Added opt-in hierarchy depths 1 through 3 and a saved-evidence `refine` workflow.
  Refinement reuses immutable OCR and pixel measurements, preserves reviewed
  grouping identity, validates source hashes and bounds, and makes no OCR,
  model, or network calls.
- Added saved-depth and raw-measurement inspection for standalone CLI output.
  Unsupported roles, fonts, and behavior remain unknown; measured bounds and
  colors are evidence, while names and groupings remain inferences.
- Added a local 12-screen benchmark runner with per-depth quality, parent-edge,
  fragmentation, overmerge, integrity, and cost reports. The proposed 90%
  quality target was not met; labels were model-authored and model-reviewed,
  not human-verified. Results in [BENCHMARK.md](BENCHMARK.md) were recorded
  against the 0.1.0 candidate on 2026-10-01 and are historical, not a 0.1.1
  benchmark.
- Curated website showcases now expose only the saved top-level elements.
  Original scenes remain unchanged, and standalone inspectors keep their full
  saved hierarchy and measurement controls.
- Added a local-wheel override for installer verification. The default install
  target is the 0.1.1 GitHub release wheel.

## 0.1.0

- Initial local screenshot measurement, saved-scene inspector, installer, and
  curated showcase website.
