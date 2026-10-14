# Docker Manager

Standalone Forge Neo extension containing the Dock Manager v1.8 core and its independently editable dock modules.

Install this **whole `docker-manager/` directory** in Forge's `extensions/` folder. This extension does not depend on the mobile QoL or Rin Theme extensions.

The Docker Manager accordion provides an Open Dock selector, widths, labels, global **Lock Docks**, **Close All Docks**, and **Full Dock Refresh**. Locking collapses drag handles and disables their gestures. Full Dock Refresh picks up new/changed dock module files without restarting Forge and preserves the position of replaced dock instances.

Available modules: `cfg`, `full-gallery-preview`, `gallery`, `generate`, `hide-all-docks`, `hires-lite`, `lock-docks-toggle`, `save-favorite`, `seed`, `standalone-hiresfix`.

To add a module, create `docks/<id>/dock.json`, `dock.js` and optional `style.css`. Use the manager's Full Dock Refresh to activate it. Editing the manager's own Python/JS or `style.css` requires a Forge restart or browser refresh as appropriate.

Saved dock layouts are local runtime data under `state/dock-layout.json` (excluded from GitHub). Preserve it from an older installation if desired. Core API routes remain `/forge-dock-manager/state` and `/forge-dock-manager/registry` for backward compatibility.
