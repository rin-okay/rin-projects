# Audit and validation status

## Purpose and root cause

The extension steers initial txt2img noise using VAE-derived luminance offsets and procedural spatial structure. The original raw-reference preview ignored `strength` and `denoise`; meanwhile RMS normalization removed reference amplitude. Thus its black/white display was not a reliable measure of injected intensity.

The new opt-in tonal mapping uses the same control map for display and injection. It interpolates fixed VAE-calibrated gray anchors instead of stretching every pattern to a constant RMS. This provides a direct control relationship. It does not establish that black/white map regions become black/white final pixels; actual diffusion comparisons are required.

## Other findings addressed

- The installed Forge SD VAE samples its posterior. Unisolated encodes consumed global RNG and added differing random terms to reference and baseline. Fixed paired streams now restore touched Torch RNG states.
- Zero reference range could still produce a residual through stochastic encoding. It now short-circuits without VAE calls.
- Half-precision subtraction/squaring risked unstable RMS normalization. Encoding results are now checked and converted to float32 before arithmetic.
- Legacy preview/editor round-trips clamped influence above 0.30. A separate legacy influence control preserves those values.
- Random preview seeds were displayed but not written back to the seed field. They are now reusable directly.
- VAE fallback passed BCHW `[-1,1]` to a Forge wrapper expecting BHWC `[0,1]`. It now uses the wrapper's layout and latent scaling.
- Another extension's previously modified noise was overwritten. Lumex now composes with it.
- Failed injection was only logged; generation metadata now records the error, and comparison reports reject a silently unapplied effect.

## Scope and limits

Backend and UI construction tests run with Forge's installed Python 3.13 / Torch 2.13 / Gradio 4.40. They use a controlled synthetic VAE, including a stochastic variant. The agent shell cannot directly access CUDA devices. After installation and restart, live Forge UI and GPU comparisons passed on an RTX 5070 Ti. Ordinary txt2img at 1024×1024 / Euler a / 32 steps recorded successful tonal injection. The comparison tool ran 512×512 / Euler / 20-step pairs at attenuations 1, .85, .5 and 0, plus a strong pair at a second seed. A repeated strong UI run returned the same reported metrics. Zero-effect output matched baseline pixels exactly.

The comparison tool uses Forge's generation queue and main execution thread. No new HTTP routes or downloads are added. Full integration with other extensions is not covered by isolated tests. Ordinary Forge batch prompt handling selects the native extra-network configuration; use a separate generation for different Lumex configurations. Unsupported 5D/video latents are skipped. Very large maps still cost memory, and the full-resolution legacy VAE path costs more than tonal calibration.

Legacy tags preserve mapping semantics, not exact historical images after RNG and numerical repairs. The strongest tonal anchor is not a guarantee of output saturation. This remains experimental; paired renders establish a useful range for each model and sampler.

## Measured tonal behavior on flatDoll_v1

Fixed prompt/seed 12345, grid 4, range 1, hardness 2, bilinear, 512×512, Euler/Automatic, 20 steps, CFG 6:

| Attenuation | Injected RMS | Near-black output | Near-white output | Map/change correlation |
|---|---:|---:|---:|---:|
| 1 (off) | 0 | 0.013% | 0.081% | — |
| .85 | .189 | 0% | 2.16% | .162 |
| .5 | .859 | 37.34% | 25.21% | .865 |
| 0 | 1.237 | 44.09% | 28.15% | .903 |

Near-black/white thresholds are mean RGB below .03 / above .97. Correlation compares the control map with the per-pixel change in mean RGB from baseline. These are descriptive measurements from one prompt/model, not population estimates. The weak setting's low correlation shows that diffusion can move scene content instead of following the map locally. At stronger settings the burn-in aligns closely with the map. A second seed also produced heavy dark/light clipping.

The real checkpoint's VAE weights were independently loaded with strict weight matching through a CPU Diffusers adapter. Repeated offsets were exact, Torch RNG state was unchanged, and the measured low-range injection RMS scaled with influence. This complements, rather than replaces, the live Forge test.

44 automated regressions cover the synthetic VAE and real Gradio UI construction. A watch-mode source edit triggered a second passing run. Hires/img2img exclusion is covered at hook level, not by a full GPU matrix. Only one checkpoint was visually calibrated. No claim is made that all models, samplers, sizes or other extension combinations behave identically.

Original-code reproductions confirmed that zero range still injected RMS 0.05 with a stochastic test VAE, changed global Torch RNG state, and displayed an identical raw preview at zero and maximum influence. The repaired implementation covers these cases in regression tests.
