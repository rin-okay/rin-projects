# Forge Neo extensions

Forge Neo extensions, maintained in `rin-projects`. Each listed project is independent unless its description names an upstream dependency.

| Extension | Purpose | Get it |
| --- | --- | --- |
| CFG Scheduler v1.4 | Prompt-based CFG changes over sampling steps, with separate base and Hires Fix schedules. | [Guide](CFG-SCHEDULER.md) · [ZIP](forge-cfg-scheduler-v1.4.zip) |
| [Gallery Restore](forge-gallery-restore/) | Recover gallery results and generation settings after mobile browser interruptions; includes img2img source restore support. | [Source](forge-gallery-restore/) · [ZIP](forge-gallery-restore.zip) |
| [Docker Manager](docker-manager/) | Floating, movable Generate, Seed, CFG, Hires Fix, gallery, Save, visibility, and lock docks, plus hot-refreshable dock modules. | [Source folder](docker-manager/) |
| [Mobile Quality of Life](mobile-quality-of-life/) | Mobile zoom, native selection menus, and collapsible Quick Settings. | [Source folder](mobile-quality-of-life/) |
| [Rin Theme](rin-theme/) | Dark purple Rin Neon Gradio styling. | [Source folder](rin-theme/) |
| [Regional Prompter overlay](sd-webui-regional-prompter/README_TAGS.md) v1.0.4 | Adds region prompt-tag support to the upstream Regional Prompter. | [ZIP](regional-prompter-prompt-tag-overlay-v1.0.4.zip) |

The standalone [Regional Prompting Helper](regional-prompting-helper.html) is a browser HTML tool, not a Forge extension.

## Installation

For source folders in this repository, copy the entire corresponding folder into Forge Neo's `extensions/` directory and restart Forge Neo.

For CFG Scheduler, download [`forge-cfg-scheduler-v1.4.zip`](forge-cfg-scheduler-v1.4.zip), extract it, and copy the **inner `forge-cfg-scheduler/` folder** into `sd-webui-forge-neo/extensions/`. Do not place the ZIP itself inside Forge's extension folder. No additional Python packages are required. See [CFG Scheduler usage](CFG-SCHEDULER.md) for examples.

For the Regional Prompter overlay, install the upstream Regional Prompter first and follow the [overlay's instructions](sd-webui-regional-prompter/README_TAGS.md).

Remove or disable older copies providing the same functionality before installing a replacement, to avoid duplicate controls. These projects have different release cycles; their versions are not shared.

For Docker Manager, retain an existing dock layout by copying `state/dock-layout.json` from the old installation to `docker-manager/state/dock-layout.json` locally. Avoid committing local layouts or credentials. Its Full Dock Refresh can load changed dock modules without restarting Forge, though installing a new extension still requires a restart.

Static checks and included unit tests do not replace runtime testing against your Forge Neo installation.
