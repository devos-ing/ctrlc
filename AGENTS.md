# Screenshot UI Inspector

Read `README.md` for commands and `PATTERN.md` for extraction and review boundaries before changing a workflow. Use `ctrlc <command> --help` for CLI arguments. The `ctrlc` package owns reusable workflows; root scripts remain compatibility adapters.

## Project rules

- Reuse the existing extractor, renderer, and preview implementation. Keep argument parsing and output formatting at the CLI boundary; expose workflow functions for other Python callers.
- Accept caller-supplied screenshots, scenes, output paths, and OCR data. Brokerage is an example, not a default or a special case in production code.
- Keep local extraction and rendering free of model calls and network requests. Optional semantic review belongs to the calling agent.
- Preserve measured evidence, source hashes, cache behavior, ROI coordinates, and unsupported fields as unknowns.
- Return documented JSON results and errors from the agent CLI, with meaningful exit codes and explicit artifact paths. Help remains readable text.

## Inspector changes

- Preserve the white Figma-style canvas and panels.
- For styling changes, render saved data rather than rerunning extraction: `ctrlc render brokerage/reviewed-scene.json brokerage/source.png --out brokerage/inspector.html`.
- Keep the renderer template and its required assets together in `ctrlc/assets/` when packaging. Generated inspectors remain self-contained.
- Make only the requested change. When simplifying redundant design, remove one element at a time and keep the removal only when required behavior and quality are preserved.

## Verification

- Add only a small number of E2E tests through the real command and its artifacts or HTTP output. Cover a complete workflow and material failures; avoid mocks of internal functions and coverage-driven test expansion.
- Verify installed-package behavior from outside the source directory, including bundled templates and native OCR assets.
- Keep existing regression checks available. Run the checks appropriate to the affected workflow and record the commands and results.
- Keep the wheel installable with Python 3.10+, Pillow, and NumPy. The `ctrlc` entry point and `python -m ctrlc` must remain available.

## CodeGraph

- When CodeGraph is available and indexed, prefer it for definitions, callers, dependencies, and impact analysis. Use native search for literal text.
- Reuse adequate index results; inspect source when results are absent, inconsistent, or stale after edits. Avoid duplicate exploration.
- When unindexed, use native search and file reads. Initialize an index only when needed and authorized.
