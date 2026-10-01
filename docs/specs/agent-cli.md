# Agent CLI plan

Status: approved for local implementation. The user confirmed the plan and selected the CLI name `ctrlc`, GPT-6 Luna at xhigh for implementation, and GPT-6.1 Sol at xhigh for review.

## Scope and decisions

Provide an installable Python command named `ctrlc` that Codex, Claude, or any shell-capable agent can invoke from any directory. The user selected existing workflows only and an installable command. Reuse the extraction, rendering, and preview behavior; preserve the white inspector panels and the saved brokerage example.

This version adds no semantic-edit command, model integration, MCP server, plugin registry, UI redesign, or new OCR engine.

## Commands

```sh
ctrlc extract image.png --out result --roi 0,150,1179,2370 --inspector
ctrlc extract image.png --out result --ocr-json ocr.json
ctrlc render result/scene.json image.png --out result/inspector.html
ctrlc serve result/inspector.html --port 8767
```

`extract` preserves the current options for ROI, languages, supplied OCR, refresh, and inspector generation. It produces `scene.json`, `packet.json`, `run.json`, and optionally `inspector.html`. Repeated extraction reuses the existing cache unless refreshed or its inputs change.

`render` consumes an explicit saved scene and its matching screenshot. It preserves the fragment option and performs no extraction or OCR. The current example is `brokerage/reviewed-scene.json` with `brokerage/source.png`.

`serve` binds to localhost and exposes only the selected document. Preserve the existing preview routes and use port 0 when the caller requests an available port. Emit a flushed startup result with the actual URL, then run until interrupted.

`--help` describes the commands and arguments in readable text. `--version` reports the installed version.

## Agent output contract

Successful work emits one JSON object on stdout. Serve emits its object when ready. Include `schemaVersion: 1`, `command`, `ok: true`, and `result`.

- Extraction results include the existing run summary and absolute paths to each generated artifact.
- Rendering results include the absolute HTML path, byte count, and `llmCalls: 0`.
- Preview results include the absolute document path and actual localhost URL. Request logs remain quiet.

Expected failures emit one JSON object on stderr, with `schemaVersion: 1`, `command` when known, `ok: false`, and an `error` containing a stable code and actionable message. Keep stdout empty on failure. Exit 0 for success, 2 for argument errors, and 1 for workflow failures. Handle interruption without a traceback. CLI help and version are documented text exceptions to the JSON contract.

The command invokes local functions without constructing shell commands or interpreting prompts. Agents choose the arguments and perform optional semantic review using the compact packet.

## Code design

Use a small `ctrlc` package with `cli.py` for parsing and dispatch, reusable extraction/rendering/preview modules, and bundled HTML, JavaScript, and Swift assets. Use functions with explicit inputs and returned results; add a class only where the standard-library interface requires it.

Move existing implementations into the package without duplicating algorithms or templates. Keep the existing script entry points as thin compatibility adapters. Update imports and resource lookup as required by packaging. A standard `pyproject.toml` declares Python 3.10+, Pillow, NumPy, the package assets, and the console entry point.

The CLI formats JSON and maps failures to exit codes. Workflow functions own measurements, cache use, generated documents, and preview serving. Keep brokerage paths in documentation and E2E fixtures only.

## Delivery order

One bounded work item, CLI-1, with these sequential steps:

1. Package reusable implementations and assets, retain existing script entry points, and expose the installed command and help.
2. Wire extraction and saved-scene rendering to JSON results and errors.
3. Wire localhost preview with a flushed ready result and clean shutdown.
4. Update README and PATTERN with installation, agent prompt examples, and the saved-data styling workflow. Keep AGENTS.md concise and aligned with the command.
5. Review standards and requested behavior, then run fresh E2E verification.

CLI-1 is approved and ready for implementation. There are no external dependencies or issue-tracker blockers.

## Acceptance and E2E seams

Add only a few subprocess-based E2E scenarios, without tests of private helpers:

1. Build and install a wheel into a temporary environment. Invoke the installed command from a separate working directory. Check help/version, package assets, extraction with supplied OCR, generated artifacts, and a second run's cache hit.
2. Render the saved reviewed brokerage scene through the installed command. Check the generated document includes that scene, embeds the screenshot and scripts, retains white-panel styling, and leaves extraction evidence unchanged.
3. Start the installed preview command on an available port, read its startup JSON, fetch the inspector, check an unrelated route is unavailable, and terminate the subprocess.
4. Check representative argument and workflow failures, including a mismatched screenshot. Assert JSON errors, exit codes, and empty stdout.

Use synthetic screenshot/OCR input for portable extraction verification and the real saved brokerage scene for rendering. Smoke-test native macOS OCR once with the installed assets when the local toolchain is available; do not make portable E2E tests depend on macOS or OCR text accuracy.

Planned verification commands:

```sh
python3 -m unittest test_cli_e2e -v
python3 -m unittest test_extract_ui test_render_inspector -v
node --test test_alpha_matte.js
```

The existing regression commands verify preservation after moving the implementations. Add no new unit tests or coverage target.

## Review and evidence

Review against AGENTS.md, existing documented behavior in README/PATTERN, and this specification. Preserve a pre-implementation file fingerprint because this directory has no Git repository. Run standards and specification review after implementation. Record fresh verification evidence and its workspace fingerprint under `.scratch/deliver-code/agent-cli/`.

## Route and permissions

Mode: direct. Selected stages: focused clarification, this bounded specification, one implementation work item, E2E, review, and fresh verification.

Skip broad scaffolding, glossary/ADR documents, external research, and issue publication to honor the requested narrow change. Re-enter those stages only if new scope needs them, a domain ambiguity emerges, a durable architectural trade-off appears, or the user requests external publication.

Requested implementation envelope: local code and documentation edits only. GitHub issues, commits, deployment, and other external writes are outside scope. The user authorized local implementation, documentation, tests, and review of this plan.

## Risks

Native OCR still requires macOS and swiftc; supplied OCR and saved-scene rendering retain the current portable path. Wheel installation must include all required assets. Packaging may require relocating templates and updating their documented editing paths, while leaving the generated appearance intact.
