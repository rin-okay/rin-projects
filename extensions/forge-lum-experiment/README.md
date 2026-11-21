# Forge Lum Experiment 1.6.0 — experimental

Lumex modifies the **starting noise of base txt2img generation**. It does not apply a final image filter, change Forge's denoising strength, or run on img2img/Hires Fix. The accordion edits `<lumex:...>` prompt tags; changing its sliders alone does not enable normal generation.

The original Splotcher generated a grayscale pattern, encoded it with the VAE, and normalized its residual to a fixed RMS. Its preview ignored influence and luminance strength. That meant a pale reference could produce a substantial effect, while making a reference more contrasty often changed its shape more than its strength.

## Tonal mode: the new preview relationship

New editor tags contain `mode=tonal`. The **effective influence preview** is also the map used to construct injection:

- Middle gray: no dark/light offset.
- Dark gray: a partial push toward the VAE's dark anchor.
- Black: the strongest calibrated dark anchor.
- Light gray and white: corresponding pushes toward the light anchor.

Five flat gray values are encoded through the loaded VAE. Their mean latent vectors, relative to neutral gray, form a lookup table. The shared map is area-downsampled to latent resolution and interpolated through that table. It is **not RMS-normalized**. This ties the displayed tonal intensity directly to the selected latent offset, without claiming the final image will contain those exact gray values.

Black/white are intended as strong dark/light pushes, but **burnt-black or burnt-white final pixels are not guaranteed**. Prompt, model, VAE, sampler and noise trajectory can resist or rearrange the effect. Use the actual generation comparison to tune it for your model. Live GPU comparisons passed on flatDoll_v1 using an RTX 5070 Ti. At full range, black/white map regions produced substantial burn-in; weaker settings preserved a recognizable scene. This is validated for that setup, not a universal pixel-brightness predictor.

## Suggested workflow

1. Open Lum Experiment and choose **tonal**. Enable splotches.
2. Choose a fixed preview seed. Copy txt2img dimensions with the size button.
3. Preview the raw pattern and effective influence. Lower **Tonal attenuation** toward zero for stronger splotches; raise Reference range for greater tonal excursions. The prompt syntax still calls attenuation `denoise` for compatibility.
4. Use **Compare actual generations** to render a baseline and effect with the same seed, prompt, dimensions, steps and CFG. The third image shows absolute difference amplified four times. This runs two actual renders and may take time.
5. Copy the preview seed to txt2img and click **Add / update prompt tag**. Match comparison dimensions/settings if you want to reproduce its result.

Comparison uses the current positive/negative prompt and loaded checkpoint, Euler/Automatic, and its own displayed steps/CFG. It excludes Hires Fix, prompt styles and other always-on scripts. It retains other native prompt tags such as LoRAs. Images are temporary Gradio outputs; download images you want to keep. Normal Forge generation remains the final integration check with your complete setup.

## Controls and formulas

Tonal map, before clipping to `[0,1]`:

```text
0.5 + lum * strength / 2 + pattern * reference_range * (1 - denoise)
```

Lum sets global dark/light bias; Lum strength scales only that bias. Splotch scale sets the short-axis grid count (larger means smaller patches). Pattern hardness changes the pattern distribution. Nearest is blocky, bilinear softer, bicubic smooth with possible overshoot before shaping. Reference range is 0–5; it controls amplitude before final clipping. Attenuation is 0–1; 1 disables the splotches, not the independent Lum bias.

```text
<lumex:mode=tonal:splotch=8,0.25,2,bilinear:denoise=0.5>
<lumex:mode=tonal:lum=-0.2:splotch=4,1,2,bilinear:denoise=0>
```

Preview `-1` resolves to a random seed and writes that value back into the preview seed field, so it can be reused. A different generation seed or aspect ratio produces a different pattern. Preview limits are 4096 pixels per axis and aspect ratio at most 16:1; comparisons are limited to 64–2048 in multiples of eight.

## Legacy compatibility

Tags without `mode=tonal` use the original mapping:

```text
<lumex:-0.35>
<lumex:splotch=8,0.25,2,bilinear:denoise=0.85>
<lumex:splotch=8,0.25,2,bilinear:splotch_strength=0.75>
```

Legacy splotch RMS influence is `(1-denoise)*0.30`; if both influence keys appear, `denoise` wins. In the editor, legacy mode uses the separate **Legacy normalized influence** slider, preserving old values up to 1. Its effective preview is only a normalized pattern proxy, not the actual VAE residual. Old control meanings remain, but the deterministic encoding, zero-range and precision fixes change exact outputs compared with v1.5.

## Install and test

Copy the `forge-lum-experiment` directory into Forge's `extensions/` directory and restart Forge. Install only one copy. No dependencies are installed automatically.

From the extension folder:

```bash
/home/sbertram3/sd-webui-forge-neo/venv/bin/python tests/run_tests.py
/home/sbertram3/sd-webui-forge-neo/venv/bin/python tests/run_tests.py --watch
```

These use Forge's Torch, Pillow, NumPy and Gradio; pytest is not required. `--build /path/to/build` tests another candidate with this suite; `--report /path/report.json` selects the output. Tests exercise the mathematical mapping, RNG preservation, error handling, and editor construction with a synthetic VAE. They do not prove perceptual calibration of real generated images.

See [AUDIT_REPORT.md](AUDIT_REPORT.md) and [CHANGELOG.md](CHANGELOG.md). The original archive remains the rollback source.

## Automated real-generation sweep

After installing and restarting Forge, run:

```bash
/home/sbertram3/sd-webui-forge-neo/venv/bin/python tests/run_live.py --reports lumex-live-results
```

This explicitly runs **eight actual renders**: baseline/effect pairs at attenuations 1, 0.85, 0.5 and 0. It downloads the returned images to the report directory and checks that the zero-effect pair is pixel-identical. Requires the Gradio client already included in Forge. Use `--seed`, `--prompt`, `--width`, `--height`, `--steps`, `--range` and `--attenuations` to choose another bounded sweep. Metrics measure pixel change, not aesthetic quality.
