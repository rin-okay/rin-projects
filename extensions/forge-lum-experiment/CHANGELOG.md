# Changelog

## 1.6.0 — experimental, 2026-09-13

- Added explicit `mode=tonal`: the effective grayscale preview and injection share one map. Gray is neutral; black/white reach the loaded VAE's calibrated dark/light anchors. Reference range and attenuation retain their amplitude instead of being normalized away.
- Kept tags without `mode` on the legacy normalized mapping. This preserves their control semantics, not bit-identical v1.5 output: RNG isolation and correctness fixes intentionally affect results.
- Added raw-reference and effective-influence previews, resolved random preview seeds, a seed-copy button, and an explicit same-seed baseline/effect comparison tool.
- Isolated stochastic VAE encoding from sampler RNG; paired encodes use the same calibration seed. Process legacy reference batches individually for consistent per-image results.
- Made zero reference range a true no-op, normalized legacy residuals in float32, validated dimensions/seeds/channels/non-finite latents, and corrected the Forge VAE fallback's layout/range/scaling.
- Preserve an earlier extension's modified noise when applying Lumex. Record successful injection RMS/version/mode or errors in generation metadata.
- Preserve legacy influence values above 0.30 when loading/editing tags. Expanded editor ranges to match parser ranges.
- Added dependency-light regression testing, watch mode, and a live generation sweep runner. 44 regression tests and watch mode passed. Real checkpoint VAE tests preserved RNG and repeatability. Live RTX 5070 Ti comparisons passed at four strengths and a second seed; zero-effect output matched its baseline exactly. Normal 1024×1024 txt2img and the preview/tag/seed UI also passed.

## 1.5 — supplied archive

Original prompt-driven luminance offset and independently RMS-normalized splotches. The editor preview displayed only the raw reference. See the original archive for its historical documentation.
