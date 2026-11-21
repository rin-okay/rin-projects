# Changelog

Documentation refresh: installation/use guidance clarified; no runtime changes.

## 2.2.1 — CachyOS / live Forge validation (2026-09-14)

- Fixed negative-prompt and trailing metadata tags supplying active Hires settings.
- Expanded positive prompts now take precedence over older raw prompt fields;
  explicit empty/untagged prompts do not fall back to stale tagged values.
- Fixed PNG Info → img2img restoring Hires denoise into base denoise. The native
  img2img paste field is replaced after component construction; txt2img retains
  native Hires denoise behavior.
- Interrupted/skipped native passes cannot insert or save their source/partial
  image as a completed enhancement. Automatic batches stop scheduling Hires
  work after cancellation.
- A progress-polling exception keeps the manual button busy until backend
  completion, preventing premature duplicate submissions.
- Added regression tests, a reusable offline runner, a CUA live-test helper,
  screenshots and RAM/VRAM evidence. See VALIDATION_REPORT.md for passed,
  failed-before-fix and untested coverage. The historical 2.2.0 entries below
  are prior release claims; live testing found the additional defects above.
