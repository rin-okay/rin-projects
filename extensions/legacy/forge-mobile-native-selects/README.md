# Forge Mobile Native Selects

A mobile-focused Forge extension that replaces a small set of common Gradio dropdowns with browser-native `<select>` controls.

Included replacements:
- txt2img sampler
- img2img sampler
- txt2img scheduler
- img2img scheduler
- hires sampler
- hires scheduler
- hires upscaler
- optional compatibility probes for img2img hires extensions that expose analogous control IDs

Also included:
- an anti-focus-zoom fix for the main prompt and negative prompt textareas on mobile by forcing them to 16px font size

Notes:
- This is mobile-focused and only activates on small/mobile viewports.
- It leaves Forge's original controls as the source of truth and simply proxies them.
- It does not replace multiselect or tokenized controls.
