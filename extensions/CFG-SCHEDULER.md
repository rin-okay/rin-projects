# Forge Neo CFG Scheduler v1.4

[Download the installable ZIP](forge-cfg-scheduler-v1.4.zip)

Change classifier-free guidance (CFG) during a sampling pass with tags written directly in the generation prompt. A `cfg` schedule controls the base pass in txt2img or img2img. An independent `hrcfg` schedule controls Hires Fix, when present. Both are integrated with Forge Neo's native extra-network tag handling so the tags remain in image generation metadata.

## Example

```text
portrait, dramatic lighting,
<cfg:3,5:10,10:4>
<hrcfg:2,3:8,8:3>
```

For a 20-step base pass, `<cfg:3,5:10,10:4>` uses CFG 3 for steps 1–5, CFG 10 for steps 6–10, and CFG 4 for the remaining steps. The Hires Fix schedule applies only to the Hires pass.

## Format

```text
<cfg:value,end:value,end:value>
<hrcfg:value,end:value,end:value>
```

- `:` separates stages, and `,` separates a stage's CFG value from its endpoint.
- Integer endpoints specify inclusive step numbers, such as `5` for step 5.
- Fractional endpoints specify proportions, such as `0.2` for 20% and `1.0` for 100%.
- Percentage endpoints such as `20%` and `100%` are equivalent to their fractional forms.
- The last stage may omit its endpoint, meaning the end of the pass. An explicit final endpoint must be `1.0` or `100%`.
- Multiple tags of the same kind are allowed: the last tag wins. If the last one is invalid, Forge uses normal CFG for that pass.
- `<cfg:...>` never carries into Hires Fix. An explicit Hires prompt's `hrcfg` overrides a main-prompt `hrcfg`.
- The old pipe-separated format (`<cfg:1,5|15,10|2>`) is obsolete in v1.4.

Both tags use native extra-network handling, like LoRA tags, so the literal schedule is retained in PNG info/infotext. No separate CFG schedule metadata field is added.

## Install

1. [Download the v1.4 ZIP](forge-cfg-scheduler-v1.4.zip).
2. Extract the included `forge-cfg-scheduler/` folder into `sd-webui-forge-neo/extensions/`.
3. Restart Forge Neo or reload scripts.

The ZIP includes the full Python source, package README, metadata, and parsing tests. No additional Python packages are required.

[Back to extensions](README.md)
