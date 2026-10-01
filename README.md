# Screenshot UI Inspector

`ctrlc` turns a screenshot into a scene you can inspect in your browser. It
measures UI bounds and colors, reads text with OCR, and saves the results locally.
You can run it yourself or ask an agent to use it.

Extraction and rendering don't make model calls or network requests. If you
want an agent to review names, roles, or grouping, the agent handles that part.

![ctrlc demo preview](demo/assets/ctrlc-demo.gif)

[Download the MP4 demo](demo/assets/ctrlc-demo.mp4)

## Which agents have been tested?

We've tested:

- Codex with GPT-6.1 Sol, `gpt-6.1-sol`.
- GLM 5.3.

Other models, including Grok, haven't been tested. Getting the CLI to run
doesn't tell you how well an agent will review names, roles, or grouping.

## Installation

Run this in your terminal:

```bash
curl -fsSL https://raw.githubusercontent.com/devos-ing/ctrlc/main/install.sh | sh
```

The script installs `uv` if you need it, installs `ctrlc` 0.1.0, and checks
`ctrlc --version`. Run it again to replace an existing installation. If the
command isn't on your PATH, the script prints the full path you can use.

### If you already use uv

You'll need Python 3.10 or newer. Run this from any directory:

```bash
uv tool install https://github.com/devos-ing/ctrlc/releases/download/v0.1.0/ctrlc-0.1.0-py3-none-any.whl
```

If you already have `ctrlc` installed, use `--force` to replace it:

```bash
uv tool install --force https://github.com/devos-ing/ctrlc/releases/download/v0.1.0/ctrlc-0.1.0-py3-none-any.whl
```

Use the wheel URL above. `uv tool install ctrlc` installs a different project
from PyPI.
If you're working on this repo, run `uv tool install .` from the repository root
instead.

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
| `ctrlc extract IMAGE --out DIR` | Measure a screenshot. Options include `--roi`, `--languages`, `--ocr-json`, `--refresh`, and `--inspector`. |
| `ctrlc render SCENE IMAGE --out HTML` | Render a saved scene without running extraction or OCR again. |
| `ctrlc serve HTML [--port PORT]` | Serve an inspector on localhost. Use port `0` to let it pick an available port. |
| `ctrlc --help` / `ctrlc COMMAND --help` | Show the available commands and options. |
| `ctrlc --version` | Print the installed version. |

Workflow commands return JSON so agents and scripts can read the results.
Successful commands write to stdout and exit with code `0`. Errors write to
stderr and exit with code `2` for argument errors or `1` for workflow errors.
Help and version output are plain text.

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

The installer tests download the release wheel and `uv` into temporary
directories. They leave your installed tools alone.

Run the existing regression checks with:

```bash
uv run --extra test python -m unittest test_extract_ui test_render_inspector -v
node --test test_alpha_matte.js
```

To call the workflows from Python, use `run_extraction`, `render_scene`, and
`create_preview_server`. The renderer template and native OCR helper are in
`ctrlc/assets/`.

## Contributions

Read [AGENTS.md](AGENTS.md) and [PATTERN.md](PATTERN.md) before changing a
workflow. Keep each change focused and preserve the measurements. The inspector
should stay self-contained, with its white canvas and panels.

For a new workflow or an important failure case, add an end-to-end test that runs the
real command and checks its output.
