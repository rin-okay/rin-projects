# Hiresfix Tag Support v2.2.1

Adds a portable `<hiresfix:...>` prompt tag to Forge Neo. The tag stores Hires
settings with the prompt while leaving prompt text, LoRA/LyCORIS tags, PNG Info,
and Send-to metadata under Forge's normal extra-network lifecycle.

This extension works by itself for native txt2img Hires Fix. Install the paired
`img2img-hires-fix` extension to use the same tag with automatic or manual
img2img Hires passes.

## Important behavior

The tag **never enables Hires Fix**.

- In txt2img, turn on Forge's native Hires. fix accordion.
- In img2img, enable the automatic pass or click the `✨` gallery button.
- Once a pass is invoked, values in the tag override the matching Hires fields.
- Hires prompt and Hires negative prompt always remain controlled by the
  accordion and are never stored in the tag.

## Syntax

Required fields:

```text
<hiresfix:upscaler:denoise:upscale_by:hires_cfg:steps>
```

Optional trailing fields:

```text
resize_width:resize_height:sampler:scheduler:distilled_cfg
```

Full example:

```text
<hiresfix:4x-UltraSharp:0.35:1.5:6:25:0:0:DPM++ 2M:Karras:3>
```

Defaults for omitted optional fields:

- Resize width: `0`
- Resize height: `0`
- Sampler: `Use same sampler`
- Scheduler: `Use same scheduler`
- Distilled CFG: `3`

## UI controls

Both txt2img and img2img receive a small **Hiresfix Tag** accordion:

- **Write/update tag** reads the visible Hires controls and writes one tag.
  Older duplicate `<hiresfix:...>` tags are removed.
- **Read tag** validates the tag and populates the visible Hires controls.

If a tag names an upscaler, sampler, or scheduler unavailable in the current
Forge installation, it is ignored during generation and the Read button gives
a direct error instead of passing a broken choice into Forge.

## Safety and validation

Prompt-carried numeric values are finite, whole-number fields cannot be silently
truncated, and all values are limited to Forge Neo's visible Hires UI ranges.
The extension makes no network requests, launches no processes, and reads or
writes no files itself.

## Integration

For img2img, this extension registers one scalar/string-only callback with the
public `img2img_hires_fix_api` module exposed by the paired extension. Startup
and reload order are handled explicitly, and the callback is removed on unload.
No monkey-patching or module scanning is used.

## Validation update 2.2.1

See the package-level CHANGELOG.md and VALIDATION_REPORT.md for fixes and
measured live coverage on CachyOS/Forge Neo. No dependencies or models need
upgrading. Back up the existing extension folders before replacing them.

## Positive-prompt precedence in 2.2.1

Only positive prompt text supplies active tags. An explicit empty/untagged
canonical prompt does not reuse older raw settings. Negative prompts and
trailing metadata fields are excluded. In manual img2img mode, the selected
image supplies the source prompt; changing the main textbox alone does not
change that image's saved tag. Prefer one tag per prompt.

For installation and worked examples, see the full distribution's
[INSTALL.md](../INSTALL.md) and [USER_GUIDE.md](../USER_GUIDE.md).
