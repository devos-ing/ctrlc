# ctrlc website layout draft

[Open the editable Figma draft](https://www.figma.com/design/UBSavd065wtHbObzyFCtuV?node-id=5-43).

The draft follows the confirmed curated-showcase plan. It contains a header with the ctrlc wordmark and GitHub link, a hero with the published install command, and a screenshot gallery.

## Views

| View | Figma node | Size | Preview |
| --- | --- | --- | --- |
| Desktop | `5:43` | 1440 × 1202 | [Desktop PNG](website-desktop.png) |
| Mobile | `5:44` | 393 × 1918 | [Mobile PNG](website-mobile.png) |
| Element hover | `5:45` | 1000 × 986 | [Hover PNG](website-hover.png) |

## Style

- White canvas, pale neutral screenshot stages, fine borders, and restrained rounding.
- Geist for website typography and Geist Mono for the wordmark and install command.
- Purple `#9147de` highlights match the existing inspector accent.
- The two current examples use two desktop columns and one mobile column. Additional catalog entries can fill a third desktop column.
- The full install command stays on one line. Its mobile viewport scrolls horizontally; Copy remains visible.

The hero command is `curl -fsSL https://raw.githubusercontent.com/devos-ing/ctrlc/main/install.sh | sh`, stored as one configured install-command value.

The header, command, captions, bounds, and labels are editable Figma layers. Screenshot previews are image assets from the existing source files. No extraction was rerun.

## Interaction details

The Figma prototype includes representative hover hotspots for the Brokerage headline and the sign-in heading. Their outlines use saved ROI-relative bounds plus the ROI origin. The full website will hit-test all compatible nodes.

Copy and Copied use the same 96 × 44 px button. The prototype shows a 120 ms dissolve and resets after 1.5 seconds. It illustrates feedback; it does not write the clipboard. Element highlighting has no animation. Keyboard-driven selection will respond immediately in the website.

The hover detail panel reports measured bounds and color. Unsupported font properties stay unknown.

## Validation

Desktop, mobile, and hover frames were exported and visually checked. Hero text overlap and button width drift were corrected. All UI text uses Geist or Geist Mono. Thirty scoped variables, nine semantic color aliases, reusable controls, and prototype reactions were verified.

The final Figma screenshots are saved alongside this document. CLI code and the existing renderer remain unchanged.
