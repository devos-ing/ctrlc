# Screenshot UI Inspector

`ctrlc` turns a screenshot into a scene you can inspect in your browser. It
measures UI bounds and colors, reads text with OCR, and saves the results locally.
You can run it yourself or ask an agent to use it.

Extraction and rendering don't make model calls or network requests. If you
want an agent to review names, roles, or grouping, the agent handles that part.

![ctrlc demo preview](demo/assets/ctrlc-demo.gif)

[Download the MP4 demo](demo/assets/ctrlc-demo.mp4)

[Changelog](CHANGELOG.md) · [Download version 0.1.1](https://github.com/devos-ing/ctrlc/releases/tag/v0.1.1).

## Which agents have been tested?

We've tested:

- Codex with GPT-6.1 Sol, `gpt-6.1-sol`.
- GLM 5.3.

Other models, including Grok, haven't been tested. Getting the CLI to run
doesn't tell you how well an agent will review names, roles, or grouping.

## Benchmark

We evaluated 12 screenshots, including six held-out screens, with ten runs per
configuration. Held-out depth-three macro F1 was **0.211**, so hierarchical
extraction remains experimental and opt-in. Labels were model-reviewed, not
human-verified. See [benchmark results and reproduction](BENCHMARK.md).

## Installation

Run this in your terminal:

```bash
curl -fsSL https://raw.githubusercontent.com/devos-ing/ctrlc/main/install.sh | sh
```

The script installs `uv` if you need it, installs `ctrlc` 0.1.1, and checks
`ctrlc --version`. Run it again to replace an existing installation. If the
command isn't on your PATH, the script prints the full path you can use.
The default wheel URL targets the 0.1.1 GitHub release asset.
To install a locally built wheel, set
`CTRLC_WHEEL_PATH` to its path when running `install.sh`.

### If you already use uv

You'll need Python 3.10 or newer. Run this from any directory:

```bash
uv tool install https://github.com/devos-ing/ctrlc/releases/download/v0.1.1/ctrlc-0.1.1-py3-none-any.whl
```

If you already have `ctrlc` installed, use `--force` to replace it:

```bash
uv tool install --force https://github.com/devos-ing/ctrlc/releases/download/v0.1.1/ctrlc-0.1.1-py3-none-any.whl
```

Use the wheel URL above. `uv tool install ctrlc` installs a different project
from PyPI.
If you're working on this repo, run `uv tool install .` from the repository root
instead.

Local installs and installer tests can use a wheel path with
`CTRLC_WHEEL_PATH=/path/to/ctrlc-0.1.1-py3-none-any.whl`.

The built-in OCR uses macOS Vision and needs `swiftc`. On other platforms, pass
your own OCR data with `--ocr-json`. See [the OCR format](PATTERN.md#supplied-ocr-and-compatibility).

### Ask an agent to install it

```text
Install ctrlc with `curl -fsSL https://raw.githubusercontent.com/devos-ing/ctrlc/main/install.sh | sh`.
The script installs uv if needed and checks `ctrlc --version` after installation.
If ctrlc isn't on PATH, use the full path printed by the script.
```

## Try it

Attach a screenshot and give this prompt to an agent that can run shell
commands. You can also provide a local file path:

```text
Use ctrlc to analyze the screenshot I've attached, or the local image path I've provided.
Use the attachment's local file if one is available. Otherwise, save the original attachment locally without resizing it.
If you can't access or save the attachment, ask me for a local file path.
Save the results in a new output folder unless I specify one, and tell me where it is.
Extract the application UI with --inspector, read the reported packet.json once, and open the inspector.
Keep the measured bounds and colors. Mark details you can't verify as unknown.
If you change the inspector's styling, render the saved scene without extracting again.
```

To try the included brokerage example, run these commands from the repository
root:

```bash
ctrlc render brokerage/reviewed-scene.json brokerage/source.png --out brokerage/inspector.html
ctrlc serve brokerage/inspector.html --port 0
```

`render` uses the saved scene and its matching screenshot. It keeps the white
canvas and style panels, so you can check styling changes without running OCR
again.

## Commands

| Command | What it does |
| --- | --- |
| `ctrlc extract IMAGE --out DIR` | Measure a screenshot. Options include `--roi`, `--languages`, `--ocr-json`, `--refresh`, `--inspector`, and the opt-in `--depth`. |
| `ctrlc refine SCENE IMAGE --out DIR --depth N` | Refine a saved hierarchy from its measurement artifact without running OCR. |
| `ctrlc render SCENE IMAGE --out HTML` | Render a saved scene without running extraction or OCR again. |
| `ctrlc serve HTML [--port PORT]` | Serve an inspector on localhost. Use port `0` to let it pick an available port. |
| `ctrlc --help` / `ctrlc COMMAND --help` | Show the available commands and options. |
| `ctrlc --version` | Print the installed version. |

Workflow commands return JSON so agents and scripts can read the results.
Successful commands write to stdout and exit with code `0`. Errors write to
stderr and exit with code `2` for argument errors or `1` for workflow errors.
Help and version output are plain text.

### Choose a hierarchy depth

Omit `--depth` to keep the legacy scene format and grouping. Use `--depth 1`, `--depth 2`, or `--depth 3` to request sections, components, or meaningful contents. A pass stops when the saved evidence cannot support another useful level.

```bash
ctrlc extract screenshot.png --out result --depth 1 --inspector
ctrlc refine result/scene.json screenshot.png --out refined --depth 3 --inspector
```

Hierarchical extraction saves OCR and pixel measurements in a content-addressed `measurements-*.json` artifact. Refinement validates that artifact and the screenshot hash, then reuses the saved measurements. The inspector can show a saved depth or raw candidates with their grouping decisions. Changing the view does not run extraction.

The Python package exports `run_extraction(..., depth=None)` and `refine_scene(scene_source, image_path, output_dir, *, depth)`. Leave `depth` omitted to use the legacy workflow.

The original scripts still work: `extract_ui.py`,
`render_inspector.py`, and `preview_server.py`.

## Development

Install the project and test dependencies, then run the end-to-end test. It
checks the installed package from outside the source directory:

```bash
uv sync --extra test
uv run --extra test python -m unittest test_cli_e2e -v
```

To check the installer too, run:

```bash
uv run --extra test python -m unittest test_install_sh -v
```

The installer tests build a 0.1.1 wheel locally and pass it to the real
installer with `CTRLC_WHEEL_PATH`. The bootstrap case downloads `uv` only when
needed, and the offline failure case uses the default release URL. Tests use
temporary tool directories and leave your installed tools alone.

Run the existing regression checks with:

```bash
uv run --extra test python -m unittest test_extract_ui test_render_inspector -v
node --test test_alpha_matte.js
```

### Showcase website

The curated website lives in `apps/web`; its workspace uses Bun while the
existing Python package and release remain managed by uv. From the repository
root, install the JavaScript workspace and start the site with:

```bash
bun install
bun run web:dev
```

The development server uses `http://127.0.0.1:5173`. To build and inspect the
production static files locally:

```bash
bun run web:build
bun run web:preview
```

The preview serves TanStack Start's prerendered client output as static files.
It does not start the Start server runtime. The E2E command builds the site and
checks the published clipboard command, saved-node highlighting, detail route,
mobile tap, keyboard selection, and Escape return flow:

```bash
bun run web:test:e2e
```

`showcases/catalog.json` is the source for curated entries. Each record points
to an existing scene and matching screenshot and records whether the scene has
received semantic review. Build preparation checks the source hash, oriented
image dimensions, scene version, and unique recursive node IDs before using
`ctrlc.rendering.render_scene` to create each self-contained inspector. It
does not extract screenshots or run OCR.

The showcase adapter keeps saved node boxes ROI-relative. Gallery highlights add
the ROI origin once and scale into the screenshot's displayed image area. A
detail URL may include `?node=<id>`; the web page validates the ID and passes it
to the embedded inspector as `#node=<encoded-id>`. The inspector also supports
hash changes after load. The website replaces the fragment within the iframe's
current history entry, so browser Back follows the detail route and keeps the
inspector document focused. Embedded Escape requests are accepted only from the
same-origin inspector iframe, while standalone inspector behavior stays intact.

To call the workflows from Python, use `run_extraction`, `render_scene`, and
`create_preview_server`. The renderer template and native OCR helper are in
`ctrlc/assets/`.

## Contributions

Read [AGENTS.md](AGENTS.md) and [PATTERN.md](PATTERN.md) before changing a
workflow. Keep each change focused and preserve the measurements. The inspector
should stay self-contained, with its white canvas and panels.

For a new workflow or an important failure case, add an end-to-end test that runs the
real command and checks its output.
