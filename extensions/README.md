# Rin's Mobile Extensions for Forge Neo

Three independent Forge Neo extensions, maintained together in `rin-projects`.
Existing projects in `extensions/` are independent and unaffected.

| Extension | Purpose |
| --- | --- |
| [`docker-manager/`](docker-manager/) | Floating, movable docks for Generate, Seed, CFG, Hires Fix, galleries, Save, visibility, and lock controls. Includes the v1.8 manager, Full Dock Refresh and 10 docks. |
| [`mobile-quality-of-life/`](mobile-quality-of-life/) | Mobile viewport zoom controls, native selection menus, and collapsible Quick Settings. |
| [`rin-theme/`](rin-theme/) | Dark purple Rin Neon Gradio theme and related CSS fixes. |

## Installation

Copy any of these three folders into Forge Neo's `extensions/` folder, then restart Forge. They are separate extensions; install one, two, or all three as desired. Remove or disable older installations of the same functionality to avoid duplicate controls. These are source folders, not ZIP archives to place inside Forge.

For Dock Manager, existing layouts can be retained by copying `state/dock-layout.json` from the previous installation to `docker-manager/state/dock-layout.json` in Forge. Avoid committing your local saved layout or credentials to GitHub. Dock Manager's **Full Dock Refresh** allows new or updated docks in `docks/` to load without restarting Forge; initial extension installation still requires a restart.

Each extension has its own README. Static checks performed during packaging do not replace runtime testing against Forge Neo.
