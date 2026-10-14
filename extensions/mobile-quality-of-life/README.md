# Mobile Quality of Life

Standalone Forge Neo extension with three front-end mobile tools. Copy **this `mobile-quality-of-life/` folder** into Forge's `extensions/` directory. Does not require Docker Manager or Rin Theme.

- **Mobile Zoom:** viewport-based scaling with compact zoom controls inline in Quicksettings. Existing saved zoom percentages are preserved via the original browser storage keys.
- **Mobile Native Selects:** native iPhone-compatible selectors for txt2img/img2img Sampler and Scheduler, Hires Sampler/Scheduler/Upscaler, where available; 16px prompt typography on phones reduces iOS focus zoom.
- **Mobile Quick Settings:** collapsible Quicksettings bar on phones, plus an optional Hide Styles bar checkbox, enabled by default and persisted in browser storage.

All three scripts are auto-loaded from `javascript/`. Their shared styles live in `style.css` and adapt to Forge's active theme. Python code is not required.

Disable older copies of these tools (e.g. `forge-mobile-zoom-experiment`, `forge-mobile-quicksettings`, `forge-mobile-native-selects`, or a prior Rin Tools bundle) so controls do not appear twice. A browser hard refresh may be needed after updating JS/CSS.
