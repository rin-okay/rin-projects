# Regional Prompter prompt-tag overlay (Forge Neo)

This is an ADDITIVE OVERLAY for the official hako-mikan `sd-webui-regional-prompter` extension, not a replacement for the upstream extension. It was designed against upstream code inspected on 2026-10-14, including the 2026-09-04 Forge Neo update. It leaves all upstream `rp.py`, `regions.py`, `attention.py`, `latent.py`, JS and UI files untouched. Installation adds `regional_core.py` and `scripts/regional_tag.py` to the upstream folder.

## v1.0.4: preserve original regional prompts in metadata

Captures the styled positive and negative prompts before Regional Prompter replaces separators and expands the common prompt. After each batch finishes sampling, it restores that batch's original prompt text and Forge's raw-comment cache before Forge builds its standard infotext. `ADDCOMM`, `ADDCOL`, `ADDROW`, `ADDBASE`, custom separators, and extra-network tags are preserved. This prevents expanded common prompts and regional tags from being repeated in saved metadata.

Generation still uses upstream's expanded conditioning text. Only completed batch slots are restored, and lists are detached so aliased Hires Fix conditioning is left untouched. No custom PNG Info parser, save callback, or `Regional Tag` metadata field is added. Jobs without a valid regional tag are unchanged.

Forge's comment settings still apply: enable **Save Raw Comments** as well as **Remove Comments from Prompts** to keep the helper's canvas and region annotations in saved metadata. With raw comments disabled, Forge removes comments but retains the regional separators.

Validation: 19 regression tests passed. A separate check exercised the actual upstream separator/common-prompt functions, Forge Comments script, and native infotext writer across 32 cases, including both comment hook orders, settings, and multiple images/iterations. GPU generation remains untested.

## v1.0.3: NegPiP compatibility guard

Fixes an attention-mode crash when `sd-forge-negpip` is installed but inactive: upstream Regional Prompter reads the legacy `contokens` / `untokens` fields, while that implementation uses `c_tokens` / `uc_tokens`.

The overlay now guards the loaded attention helper at runtime without replacing upstream files. Inactive or empty NegPiP conditioning is skipped. The legacy region-aware NegPiP API keeps its original behavior. Active conditioning from the newer Forge NegPiP API stops with an actionable compatibility error; this release does not claim simultaneous support for its different token layout. To use Regional Prompter with that extension installed, disable `sd-forge-negpip` in Extensions and restart Forge.

The guard also applies to ordinary Regional Prompter runs while this overlay is loaded. No other attention logic is changed. Regression tests use simulated script state; real GPU generation remains unverified.

## Install

1. Install the current Regional Prompter from `https://github.com/hako-mikan/sd-webui-regional-prompter` through Extensions > Install from URL, if not already installed.
2. Unzip the overlay into Forge Neo's `extensions` folder, merging the included `sd-webui-regional-prompter` directory into the existing extension. Do not delete upstream's original files. You should end up with `extensions/sd-webui-regional-prompter/regional_core.py` and `extensions/sd-webui-regional-prompter/scripts/regional_tag.py`.
3. Restart Forge completely. `Regional Prompt Tag` appears as an always-visible accordion in txt2img and img2img. The original `Regional Prompter` accordion remains in place.
4. Add a tag to the **positive** prompt (either manually or with the Add/update button). Keep the `BREAK`, `ADDCOL`, `ADDROW`, `ADDCOMM`, `ADDBASE` markers that assign text to individual regions.

Do not install this overlay as a separate extension. If the original RP installation folder has a different name, install these two files into that folder, preserving the `scripts/` subdirectory.

## Examples

Two side-by-side regions:

```text
woman with red hair BREAK woman with blue hair
<regional:mode=columns:calc=attention:ratios=1,1>
```

Simple shorthand also works:

```text
<regional:columns:1,1:attention>
```

Two regions plus common background/lighting prompt:

```text
cinematic evening park BREAK woman with red hair BREAK woman with blue hair
<regional:mode=columns:ratios=1,1:common=1>
```

Two regions blended with a base scene:

```text
sunlit forest BREAK woman with red hair BREAK woman with blue hair
<regional:mode=columns:ratios=1,1:base=1:blend=0.2>
```

2D matrix (use appropriate `ADDROW`/`ADDCOL` separators):

```text
<regional:mode=rows:ratios=1,2;1,1:calc=latent>
```

Advanced:

```text
<regional:mode=columns:calc=attention:ratios=1,1:base=0:blend=0.2:common=0:ncommon=0:flip=0:threshold=0.4:hires=both:lora_stop=0:lora_hr_stop=0>
```

## Matrix canvas editor

Open the standalone `regional-matrix-mobile.html` file on desktop or mobile. It generates 2D ratios and region prompts for the upstream **Matrix** mode (`mode=columns`). It does **not** use the separate Mask mode. The mobile canvas rasterizes strokes into grid-snapped rectangles and then compresses identical horizontal runs of cells into the row/column ratio format already understood by RP. Empty cells are explicit background regions.

**Separator mapping:** use one separator on its own line between each region prompt. For example:

```text
# Region 1: RED
red-haired person
ccc
# Region 2: BLUE
blue-haired person
<regional:mode=columns:calc=attention:ratios=4,4:sep=ccc>
```

The overlay translates standalone `ccc` lines to `BREAK` before invoking the upstream RP processing method. RP's own existing matrix logic then maps those breaks to `ADDROW` and `ADDCOL` depending on `ratios`. This changes conditioning prompts through RP's normal pipeline; no extra PNG Info callback or separate metadata field is introduced. Choose another separator by setting `sep=myword` in the tag. Normal `BREAK`, `ADDCOL` and `ADDROW` remain usable.

**Matrix limitation:** a detached or overlapping box is represented as one or more rectangular tiles. The generated sample may repeat a palette color in multiple region slots, because RP Matrix mode needs a prompt for each tile. Complex drawings can produce many prompt segments. The editor warns when that happens.

## Parameters

* `mode`: `columns`, `rows`, `random`, `prompt`, `prompt-ex` (default `columns`). The first three select the original RP Matrix mode. The last two select the original RP Prompt mode.
* `calc`: `attention` or `latent` (default `attention`). Existing upstream model compatibility limitations apply.
* `ratios`: comma-separated numbers, with semicolons for 2D matrix divisions (default `1,1`).
* `sep`: custom region divider placed **alone on its own line**, default `ccc`. Internally translated to original RP `BREAK` for the generation run.
* `base`: `0` / `1` (default `0`). The base prompt must be provided before the region prompts, as in the upstream syntax.
* `blend`: ratio of base prompt to the region, one value or multiple comma-separated values (default `0.2`; each between 0 and 1).
* `common`, `ncommon`: enable original RP common positive / negative prompt handling (`0` / `1`, default `0`).
* `flip`: flip commas and semicolons (`0` / `1`, default `0`).
* `threshold`: 0 to 1 (default `0.4`). Used for Prompt and Prompt-Ex mode.
* `hires`: `both`, `only`, `off` (default `both`), maps to RP's built-in Hires Fix options.
* `lora_stop`, `lora_hr_stop`: nonnegative integer, default `0`, maps to RP's LoRA stop-step fields.

Positional form `<regional:mode:ratios:calc>` is supported. For clarity and future extensions, the editor generates explicit named fields. Last tag wins. An invalid last tag disables regional prompting for that run and logs an error, rather than silently taking settings from an open RP UI accordion.

## What is deliberately excluded

* Freehand and uploaded image masks: these are image data, not portable textual parameters. Use the original RP mask UI/presets for these.
* Visualization, templates, preset editing: UI tools, not generation settings. Keep using the original RP accordion.
* Debugging switches, manual LoRA negative TE/U-Net ratio overrides, experimental RP Options (chunk rewrite, custom LoHa handling, prompt flipping, comments): not included in v1. The tag resets upstream Options to their ordinary defaults, plus any requested `hires` mode, so previous UI checkbox choices cannot silently change tagged generations.
* Region prompts themselves still use RP's existing `BREAK` / `ADDROW` / `ADDCOL` / `ADDBASE` / `ADDCOMM` syntax. A `<regional>` tag without region separators does not invent separate regions.

## Implementation details

Based directly on the implementation pattern from Forge Lum Experiment 1.6.0: a native `extra_networks.ExtraNetwork` handler for `<regional:...>`, a small pure-Python parser, a Gradio prompt-tag editor, and a non-destructive Load/Add/Update tag workflow. The tag remains a native Forge extra network and is removed before the text reaches the image text encoder.

The bridge wraps the **existing** upstream `rp.Script.process` method and supplies its original positional argument list with tagged values, instead of rebuilding matrix division, attention masks, latent processing, LoRA manipulation, or DiT support. Normal RP processing without tags is unchanged. Tagged settings take priority over stale RP UI settings. It uses the last tag in the positive prompt for a generation, so avoid mixing different regional settings across a batch of prompts.

The overlay follows Forge Neo's normal extra-network prompt handling, just like `<lora:...>` and Lum Experiment's `<lumex:...>`. Forge parses the tag out of the conditioning prompt. The bridge preserves the original prompts separately while Regional Prompter transforms its working lists, then restores completed batch slots and Forge's raw-comment cache before regular image infotext is written. The `<regional:...>` tag is therefore kept in the main positive prompt text, not in an additional parameter field.

**No custom PNG Info logic:** there is no `Regional Tag` metadata field, `on_infotext_pasted` callback, fallback tag insertion, or custom infotext reconstruction. Forge Neo's native processing handles this. The original RP per-control `RP ...` metadata fields are suppressed only when a tag is used, so restoring images won't load stale RP UI values that compete with the prompt tag.

## Testing / compatibility

Run locally from the extension root:

```bash
python tests/test_regional_tag.py
```

Tests validate parser/tag roundtrip, invalid input, mixed-case tags, legacy prompt preservation, RP argument overrides, native extra-network registration, and tagged/non-tagged forwarding with mocked upstream RP. They do **not** validate real Forge Neo generation, Hires Fix, or actual PNG writes; test those on your installed checkpoint. This is a first implementation, not a GPU-validated release.

This code is an AGPL-3.0-compatible overlay for [hako-mikan/sd-webui-regional-prompter](https://github.com/hako-mikan/sd-webui-regional-prompter), which is AGPL-3.0 licensed. No original upstream files are redistributed in this ZIP.


