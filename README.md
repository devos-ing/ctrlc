# Screenshot UI Inspector

`ctrlc` 0.1.0 measures screenshot UI, renders saved scenes, and previews the
resulting inspector locally. Shell-capable agents invoke the CLI without model
integration in `ctrlc`.

![ctrlc demo preview](demo/assets/ctrlc-demo.gif)

## Tested agent runtimes

| Agent runtime | Model | Test status |
| --- | --- | --- |
| Codex | GPT-6.1 Sol (`gpt-6.1-sol`) | Tested |
| Codex | Other models | Not tested |
| Claude Code | Not recorded | Not tested |
| Other shell-capable agents | Not recorded | Not tested |

Only Codex with GPT-6.1 Sol has been tested. Agents using GLM or Grok are also
untested. CLI compatibility alone does not verify an agent's optional semantic
review.

## Installation

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) if needed.
Python 3.10 or newer is required. Install the published command from any
directory with:

```bash
uv tool install https://github.com/devos-ing/ctrlc/releases/download/v0.1.0/ctrlc-0.1.0-py3-none-any.whl
```

If `ctrlc` is already installed, replace that installation with:

```bash
uv tool install --force https://github.com/devos-ing/ctrlc/releases/download/v0.1.0/ctrlc-0.1.0-py3-none-any.whl
```

The PyPI distribution named `ctrlc` is an unrelated project. Use the release
wheel URL above. For development, run `uv tool install .` from the repository
root.

Native Vision OCR requires macOS and `swiftc`. On other platforms, provide
compatible OCR data with `--ocr-json`.

## Usage

Copy this prompt into a shell-capable agent:

```text
If uv is missing, install it from https://docs.astral.sh/uv/getting-started/installation/.
Install ctrlc 0.1.0 with `uv tool install https://github.com/devos-ing/ctrlc/releases/download/v0.1.0/ctrlc-0.1.0-py3-none-any.whl`; add `--force` if already installed. Check `ctrlc --version` and `ctrlc --help`.
If `ctrlc` is not on PATH, invoke it by its full path under the directory printed by `uv tool dir --bin`.
Set SCREENSHOT_PATH and OUTPUT_DIR from user-supplied paths. Ask only for missing paths. Inspect the screenshot, exclude OS chrome when present, and choose the application ROI in upright pixels; ask if bounds are unclear.
Run `ctrlc extract "$SCREENSHOT_PATH" --roi X,Y,W,H --out "$OUTPUT_DIR" --inspector`. If native Vision OCR is unavailable, use `--ocr-json` only with compatible OCR supplied by the user; ask if missing.
Check the success JSON and read its reported packet once. Review uncertain roles and grouping. Preserve measured bounds and colors; leave font, responsive, or behavior details unknown only when evidence is insufficient.
Open the reported inspector HTML. If HTTP is needed, start `ctrlc serve "$OUTPUT_DIR/inspector.html" --port 0` in the background and open its URL. For style requests, render the reviewed scene with the same screenshot; do not extract again.
```

The included brokerage example can be rendered and previewed from the checkout:

```bash
ctrlc render brokerage/reviewed-scene.json brokerage/source.png --out brokerage/inspector.html
ctrlc serve brokerage/inspector.html --port 0
```

`render` uses the saved scene and matching screenshot, preserves the white
canvas and style panels, and does not rerun OCR.

## Commands

| Command | Purpose |
| --- | --- |
| `ctrlc extract IMAGE --out DIR` | Measure a screenshot; add `--roi`, `--languages`, `--ocr-json`, `--refresh`, or `--inspector` as needed. |
| `ctrlc render SCENE IMAGE --out HTML` | Render a saved scene without repeating extraction or OCR. |
| `ctrlc serve HTML [--port PORT]` | Serve one inspector on localhost; use port `0` to choose an available port. |
| `ctrlc --help` / `ctrlc COMMAND --help` | Show readable command help. |
| `ctrlc --version` | Print the installed version. |

Successful commands print JSON to stdout. Failures print JSON to stderr and
exit with status 2 for argument errors or 1 for workflow errors; success exits
0. The root scripts `extract_ui.py`, `render_inspector.py`, and
`preview_server.py` remain compatibility commands.

## Development

Sync the project and test dependencies, then run the installed-package E2E:

```bash
uv sync --extra test
uv run --extra test python -m unittest test_cli_e2e -v
```

The existing regression checks are also available:

```bash
uv run --extra test python -m unittest test_extract_ui test_render_inspector -v
node --test test_alpha_matte.js
```

Reusable Python functions are `run_extraction`, `render_scene`, and
`create_preview_server`. The renderer template and native OCR helper live in
`ctrlc/assets/`.

## Contributions

Read [AGENTS.md](AGENTS.md) and [PATTERN.md](PATTERN.md) before changing a
workflow. Keep changes scoped, preserve measured evidence and the self-contained
white-panel inspector, and add command-level E2E coverage only for a new
workflow or material failure.
