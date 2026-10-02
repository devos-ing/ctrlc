# ctrlc showcase website

Status: implemented. Public showcase views expose only saved top-level nodes.

[Figma layout draft](../design/website-figma.md): desktop, mobile, and representative hover states.

## Decisions

- The first version shows curated screenshots and a first-level projection of saved scenes.
- Hover highlights the top-level saved node beneath the cursor.
- The page has three sections: header, install hero, and showcases.
- Use a small monorepo. Keep the Python package at its current location and add the website under `apps/web`.
- Use TanStack Start, React, TypeScript, and Bun. Prerender the homepage and each curated showcase route.

The CLI and website share saved scene JSON and source screenshots. Keeping them together makes changes to that contract reviewable in one commit. Python dependencies and releases remain managed by uv. Bun workspaces manage JavaScript dependencies and scripts. Each product has its own release workflow.

## Planned repository layout

```text
ctrlc/                  Existing Python workflows and renderer assets
apps/web/               React website and its Bun package
showcases/catalog.json  Titles, slugs, and paths to existing screenshots/scenes
brokerage/              Existing reviewed example
sample/                 Existing extracted example
pyproject.toml          Python packaging
uv.lock                 Python dependency lock
package.json            Private Bun workspace root
bun.lock                JavaScript dependency lock
```

Start with one JavaScript app. Keep its inspector adapter inside `apps/web`; extract a shared JavaScript package when another consumer needs it.

## Page layout

Use a spacious gallery layout with restrained typography, neutral backgrounds, and white Figma-style inspector panels. Screenshot previews carry the visual content. Reserve image dimensions so loading and hover do not move surrounding cards.

| Section | Behavior |
| --- | --- |
| Header | `ctrlc` wordmark at the left; GitHub button links to `https://github.com/devos-ing/ctrlc` at the right. |
| Hero | Short introduction and one install command with a Copy button. Show Copied only after clipboard success; otherwise keep the command selectable. |
| Showcases | Responsive screenshot grid, initially Brokerage and the existing sign-in example. Show the title and a short inspection hint. Use two desktop columns for the current examples, grow to three when the catalog expands, and use one on mobile. |

The hero copies this exact published command:

```bash
curl -fsSL https://raw.githubusercontent.com/devos-ing/ctrlc/main/install.sh | sh
```

Keep the command on one line with horizontal scrolling when needed. Store it as one configured install-command value.

## Screenshot interaction

1. At rest, show the screenshot without labels covering its content.
2. Hover highlights only the matching top-level saved node and shows its name or type in a small label. Nested saved children are outside the public showcase projection.
3. Moving off the screenshot clears the highlight.
4. Clicking or tapping opens the selected top-level element in the detailed inspector. Keyboard users can open the inspector and choose only top-level elements from its list. Escape clears selection or closes the detail view.
5. The detail route uses the existing renderer with a root-only scene projection in an iframe. It preserves the white panels, root measurements, styles, source hash, ROI, and unknown fields. It does not include child nodes, measurement artifacts, raw candidates, or depth controls. Its link remains shareable at `/showcases/$slug`.

The gallery highlight is a thin adapter over saved bounds. It does not duplicate extraction, matte generation, style inference, or the existing inspector renderer.

Node boxes are ROI-relative, including boxes in nested nodes. For upright, uncropped source previews, add the ROI origin before scaling coordinates into the displayed image content rectangle. Account for letterboxing when the preview uses `object-fit: contain`. Recalculate placement when the image display size changes. Never stretch the image or guess bounds from a thumbnail.

Opening a selected node requires a small, documented selection interface in the existing renderer. Pass only the showcase slug and node ID; validate the ID against the saved scene. Keep standalone CLI rendering compatible.

## Data and build flow

```text
catalog + existing source screenshots + saved scenes
  -> validate matching source hashes, scene versions, and all original nodes
  -> copy a root-only public scene projection without changing saved inputs
  -> existing ctrlc render generates each public inspector from that projection
  -> prepare gallery images and node bounds
  -> Bun builds and TanStack Start prerenders pages
  -> static website assets
```

The catalog accepts any compatible scene and screenshot pair. Brokerage is one entry. Prefer `brokerage/reviewed-scene.json` for its showcase, and label the existing sample scene as extracted rather than semantically reviewed. Generated `scene.json` contains only the original top-level nodes with their `children` stripped; the source scene files remain unchanged.

Use the existing renderer to validate source hash and dimensions while generating each inspector. Check the scene version at the web adapter. Generate public assets from the catalog so fixture paths have one source of truth. Preserve original scene JSON and screenshots.

Load screenshot previews lazily below the hero. Load full inspector documents only when opened. Curated slugs must be enumerated for prerendering. Serve the result as static assets; extraction and semantic review happen outside the visitor flow.

## Implementation sequence

1. Add the Bun workspace and web app. Build the header, install hero, and one Brokerage card with working copy and hover behavior.
2. Connect the existing renderer to the detail route and selected-node interface. Add the sign-in entry through the same catalog. Check nested bounds, nonzero ROI origins, resizing, and loading failures.
3. Complete keyboard and touch inspection, prerendered routes, metadata, and the static build. Prepare a local preview before choosing a hosting target.

Implementation notes: the catalog is `showcases/catalog.json`; build preparation
is `apps/web/scripts/prepare_showcases.py`. It accepts exact integer
`schemaVersion` values 1 and 2 and validates every recursive node
and screenshot/scene pair, then generates `apps/web/public/showcases/` and the
typed browser data consumed by the app. The Vite build prerenders `/` and each
catalog slug with link crawling disabled. Static files are written to
`apps/web/dist/client`; `bun run web:preview` serves that directory without a
TanStack Start runtime.

The detail selection bridge is `?node=<id>` on the showcase route and
`#node=<encoded-id>` in the generated inspector. It accepts only IDs from the
root-only public scene; deep child IDs are invalid and cannot select an iframe
element. Public inspectors have no measurement artifact, raw candidate view,
depth selector, or child-family controls. The website replaces the
iframe hash in the current history entry, keeping browser Back aligned with the
detail route while preserving iframe focus. In embedded use, inspector messages
require both the current origin and iframe window source; Escape closes the
detail route. Standalone inspector Escape behavior remains unchanged.

Use GPT-6 Luna with xhigh effort for implementation and GPT-6.1 Sol with high or xhigh effort for review, following the established project workflow.

## Verification

Keep verification at the browser E2E level:

- Desktop flow: copy the real command, hover and open a top-level node, verify bounds at two preview sizes, then confirm nested IDs and inspector controls are inaccessible.
- Mobile and keyboard flow: tap or choose a top-level node, reject a child deep link, and verify Escape and browser Back return correctly.

Run `bun run web:test:e2e` for the production static build and two real-browser
flows. The local preview is `bun run web:preview`. Run existing CLI checks when
the renderer template changes. Do not add unit tests that restate coordinate
formulas or component markup.

## References

- [Mobbin layout reference](https://mobbin.com/discover/apps/ios/latest). This session redirected to the public landing page, so the signed-in discovery gallery was not visually verified.
- [Bun workspaces](https://bun.com/docs/pm/workspaces).
- [TanStack Start with Bun](https://bun.com/guides/ecosystem/tanstack-start).
- [TanStack Start static prerendering](https://tanstack.com/start/latest/docs/framework/react/guide/static-prerendering).
