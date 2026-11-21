# Img2img Hires Fix v2.2.1 for Forge Classic Neo

Adds a native-feeling **Hires. fix** accordion to img2img and a `✨` button to
the img2img gallery controls.

## Features

- Run a second Hires pass automatically after normal img2img generation.
- Enhance only the selected gallery result with the `✨` button.
- Append the enhanced result or replace the selected result.
- Choose from Forge's available latent or pixel-space upscalers; not every
  model combination has been tested.
- Configure denoise, scale, exact resize, Hires steps, sampler, scheduler, CFG,
  Distilled CFG, Hires prompt, and Hires negative prompt.
- Use Forge Neo's task ID, queue, progress polling, live preview, interrupt, and
  screen-wake lifecycle for manual enhancement.
- Preserve raw prompts and prompt-side extra-network tags such as LoRA and
  LyCORIS tags.
- Restore both the original img2img denoise and the Hires denoise when metadata
  is sent back to img2img.
- Restore native Hires fields when metadata is sent to txt2img.

## Installation

1. Stop Forge Neo.
2. Back up and move the old `extensions/img2img-hires-fix` folder outside
   Forge's extensions directory.
3. Copy this `img2img-hires-fix` folder into the Forge Neo `extensions` folder.
4. Install the paired `hiresfix-tag-support` folder if portable prompt tags are
   wanted.
5. Start Forge Neo again. Do not use Reload UI for this upgrade.

No third-party Python packages are required.

## Use

Automatic mode:

1. Open img2img's **Hires. fix** accordion.
2. Enable **Run hires pass automatically after img2img**.
3. Choose the Hires settings and generate normally.

Manual mode:

1. Select a generated image in the img2img gallery.
2. Choose the Hires settings.
3. Set **Star button replaces selected image** before submitting if replacement
   is preferred; otherwise the enhanced image is inserted after the source.
4. Click `✨` beside the gallery controls.

The manual action requires a generated image with an infotext entry. Grids and
ControlNet/control images are intentionally rejected.

## Metadata behavior

The enhanced image is saved only after a lossless metadata merge. The same
merged text is placed in the saved file, returned image, gallery state, PNG
Info, and Send-to state.

- Original prompt, negative prompt, LoRA/LyCORIS tags, seed, sampler, CFG,
  model fields, size, and extension metadata are retained.
- Current Hires settings replace stale Hires fields from an older enhancement.
- Values containing commas, colons, or line breaks are JSON-quoted using
  Forge-compatible infotext rules.
- Combined fields such as `Size: 1024x1536` stay combined and are not rewritten
  as internal UI helper keys.
- The native `Denoising strength` records the latest Hires pass for txt2img.
  `Img2img source denoising strength` separately retains the original img2img
  value and restores it when sent back to img2img.

## Hires step behavior

The configured Hires step count is passed directly to Forge Neo's native
`sample_img2img` Hires path. It is not divided by denoise strength. A value of
`0` uses the original generation's step count, matching native Hires Fix.

## Processing and memory safety

The Hires stage uses a fresh, empty Forge `ScriptRunner`. This disables
arbitrary selectable/always-on img2img scripts for the second pass while still
allowing Forge's native raw-prompt restoration that preserves extra-network
tags in infotext.

The session cache contains only small strings, numbers, booleans, and lists. It
is namespaced by user and job timestamp, guarded for concurrent access, and
capped at 64 entries. It never retains processing objects, model patchers,
tensors, PIL images, script instances, or LoRA objects.

The full VAE encoder is used for the selected image re-encode to reduce colour,
black-level, and contrast drift. Forge's normal cleanup and `torch_gc()` path
runs even when the Hires pass fails.

## Public settings override API

The extension publishes `img2img_hires_fix_api` with `API_VERSION = 2`.
Companion extensions can register:

```python
register_hires_settings_override(callback)
```

The callback receives `(context, current_settings)` and may return a partial
dictionary using the documented Hires fields. Unknown keys and invalid values
are ignored with a console warning. Valid values are normalized against the
current Forge upscaler, sampler, scheduler, and UI ranges before processing.

Accepted override fields are `denoising_strength`, `hr_scale`, `hr_upscaler`,
`hr_second_pass_steps`, `hr_resize_x`, `hr_resize_y`, `hr_sampler_name`,
`hr_scheduler`, `hr_prompt`, `hr_negative_prompt`, `hr_cfg`, and
`hr_distilled_cfg`.

The context contains source prompt/infotext and, only in automatic mode, the
original processing object. Consumers must not retain processing or model
objects. The paired Hiresfix Tag Support extension returns only scalar/string
setting overrides.

## Deliberate limitations

The second pass does not rerun arbitrary img2img scripts, masks, ControlNet
units, or img2img-only postprocessing state. Safely replaying those features
would require each extension's original UI arguments and lifecycle ownership.
Prompt-based extra networks remain supported through Forge's own parser.

## Validation update 2.2.1

See the package-level CHANGELOG.md and VALIDATION_REPORT.md for fixes and
measured live coverage on CachyOS/Forge Neo. No dependencies or models need
upgrading. Back up the existing extension folders before replacing them.

The full distribution includes [installation instructions](../INSTALL.md),
[a user guide](../USER_GUIDE.md) and [patch notes](../PATCH_NOTES.md).
