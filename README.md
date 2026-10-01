# Screenshot UI Inspector

`ctrlc` 0.1.0 measures screenshot UI, renders saved scenes, and previews the
resulting inspector locally. Shell-capable agents invoke the CLI without model
integration in `ctrlc`.

![ctrlc demo preview](demo/assets/ctrlc-demo.gif)

[Download the MP4 demo](demo/assets/ctrlc-demo.mp4)

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

### Agent install prompt

```text
If uv is missing, install it from https://docs.astral.sh/uv/getting-started/installation/.
Install ctrlc 0.1.0 with `uv tool install https://github.com/devos-ing/ctrlc/releases/download/v0.1.0/ctrlc-0.1.0-py3-none-any.whl`.
Add `--force` to replace an existing installation. Verify `ctrlc --version`.
If ctrlc is not on PATH, use its full path in the directory reported by `uv tool dir --bin`.
```

## Usage

Replace the paths below, then copy this prompt into a shell-capable agent:

```text
Use ctrlc to analyze <screenshot-path> and save results in <output-directory>.
Extract the application UI with --inspector, read the reported packet once, and open the inspector.
Preserve measured bounds and colors. Mark unsupported details as unknown.
For styling changes, render the saved scene without extracting again.
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
