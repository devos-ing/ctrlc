# Brokerage screenshot example

The local extractor found 29 raw regions. An assistant review grouped the
visible UI into 11 main components: brokerage menu, theme button, headline
value, account tabs, daily change, return chart, time ranges, chart tools,
margin buying power, options promotion, and bottom navigation.

`scene.json` and `raw-scene.json` preserve the local extraction. The corrected
hierarchy is in `reviewed-scene.json`; its compact counterpart is
`reviewed-packet.json`. Component names and grouped bounds are reviewed
inferences, not automatically recovered layout constraints. The local run's
zero model-call report covers extraction only; the semantic review used the
assistant in this chat.

The chart stays a screenshot graphic, with separately inspectable return and
reference lines. Its numerical time series is not recovered. The options card
and its text retain their gradient background; exact fonts, opacity, shadows,
and original design tokens remain unknown.

Render the saved reviewed scene without rerunning extraction:

```bash
ctrlc render brokerage/reviewed-scene.json brokerage/source.png --out brokerage/inspector.html
```
