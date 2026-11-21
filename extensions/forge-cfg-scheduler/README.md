# Forge Neo Prompt CFG Scheduler — v1.4

Prompt-native CFG scheduling for Forge Neo. Base/img2img and Hires Fix schedules are independent.

## v1.4 syntax

v1.4 changes the stage separator from `|` to Forge's native extra-network `:` separator:

```text
<cfg:1,5:15,10:2>
```

On a 20-step pass:

```text
steps 1–5    CFG 1
steps 6–10   CFG 15
steps 11–20  CFG 2
```

The old form is intentionally rejected:

```text
<cfg:1,5|15,10|2>   # rejected; use : between stages
```

Forge naturally parses the new form as extra-network arguments equivalent to:

```text
["1,5", "15,10", "2"]
```

Any number of stages is accepted.

## Endpoint syntax

Integer endpoints are exact inclusive step endpoints:

```text
<cfg:1,5:15,10:2>
```

Decimal endpoints are normalized positions through the current pass:

```text
<cfg:5,0.2:10,0.5:5>
```

Percentage spelling is also accepted:

```text
<cfg:5,20%:10,50%:5>
```

The spelling is intentional:

```text
1      = step 1
5      = step 5
10     = step 10

.2     = 20%
0.2    = 20%
0.5    = 50%
1.0    = 100%

20%    = 20%
50%    = 50%
100%   = 100%
```

`1` and `1.0` therefore mean different things.

Fractional endpoints use `ceil(total_steps * fraction)`. For a 25-step pass, `0.3` ends at step 8 and `0.5` ends at step 13.

Step and fractional endpoints may be mixed:

```text
<cfg:2,5:8,0.5:4>
```

On 30 steps this is CFG 2 through step 5, CFG 8 through step 15, then CFG 4 through completion.

## Termination

The final CFG stage may omit its endpoint; omission means the end of the pass:

```text
<cfg:5,0.2:10,0.5:5>
```

is equivalent to:

```text
<cfg:5,0.2:10,0.5:5,1.0>
```

If the final endpoint is explicit, it must be `1.0` or `100%`:

```text
<cfg:5,5:10,20>      # rejected
<cfg:5,0.2:10,1>     # rejected; 1 means step 1
<cfg:5,0.2:10,1.0>   # valid
<cfg:5,20%:10,100%>  # valid
```

A non-final stage cannot end at `1.0` / `100%`. Resolved endpoints must be strictly increasing. Mixed schedules that become impossible for the actual pass length are rejected for that pass and Forge's normal CFG is used instead.

## Base vs Hires

The namespaces are pass-specific:

```text
<cfg:...>    base/txt2img/img2img only
<hrcfg:...>  Hires Fix only
```

Example:

```text
portrait,
<cfg:3,5:10,10:4>
<hrcfg:2,3:8,8:3>
```

The base pass uses the `cfg` schedule. Hires uses the `hrcfg` schedule. A `cfg` schedule never carries into Hires.

An `hrcfg` tag in the main prompt can provide the Hires schedule. If an explicit Hires prompt contains its own `hrcfg`, the explicit Hires schedule wins. A malformed last explicit `hrcfg` is authoritative and disables scheduling rather than falling back to the main prompt.

A `cfg` tag inside an explicit Hires prompt is ignored for Hires scheduling. Forge still removes it from conditioning through the native extra-network parser.

## Last one wins

Multiple tags are allowed. Within each namespace the last tag is authoritative:

```text
<cfg:4,5:8> ... <cfg:2,3:12>
```

uses the second schedule.

If the last tag is invalid, that namespace is unscheduled rather than falling back to an earlier valid tag.

Capitalization variants such as `<CFG:...>` and `<HRCFG:...>` are registered as aliases; lowercase `<cfg>` / `<hrcfg>` is the canonical spelling.

## Native Forge extra-network pathway

v1.4 no longer removes CFG tags by editing `p.all_prompts` or `p.all_hr_prompts`.

Instead, `cfg` and `hrcfg` are registered as Forge extra-network namespaces. Forge's normal prompt lifecycle does the same thing it does for LoRA tags:

```text
source / metadata prompt
cat, <cfg:1,5:15,10:2>, <lora:foo:0.8>

        ↓ Forge copies the current batch

working conditioning prompt
cat, <cfg:1,5:15,10:2>, <lora:foo:0.8>

        ↓ Forge extra-network parsing

text sent to conditioning
cat,  ,
```

The source prompt is never rewritten by the extension, so PNG/infotext metadata retains the literal CFG tag just as it retains the LoRA tag:

```text
cat, <cfg:1,5:15,10:2>, <lora:foo:0.8>
```

No separate `CFG schedule` or `Hires CFG schedule` metadata field is added.

## CFG = 1

Forge Neo normally omits unconditional/negative conditioning when the scalar CFG is exactly 1. When a schedule contains a later value other than 1, the extension temporarily ensures unconditional conditioning is available while conditions are built, then restores the user's scalar CFG value before sampling/metadata use.

It also disables Neo's per-step CFG=1 optimization for a scheduled pass that needs an unconditional branch, allowing schedules such as:

```text
<cfg:1,5:7>
```

## Sampling behavior

The schedule is piecewise constant. It uses Forge Neo's actual denoiser step counter for the current pass.

The scheduled CFG is installed as a Neo `conditioning_modifier`, replacing `cond_scale` immediately before CFG evaluation. The regular CFG slider remains normal when no `cfg` schedule exists, and Hires CFG remains normal when no `hrcfg` schedule exists.

## Install

Copy the whole folder to:

```text
sd-webui-forge-neo/extensions/forge-cfg-scheduler/
```

Important files:

```text
forge-cfg-scheduler/
├── cfg_scheduler_core.py
├── metadata.ini
├── README.md
└── scripts/
    └── cfg_scheduler.py
```

Restart Forge Neo or reload scripts. No additional Python packages are required.
