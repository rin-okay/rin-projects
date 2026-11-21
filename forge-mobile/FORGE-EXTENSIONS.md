# Forge Neo extensions with GitHub updates

`start-forge.bat` pulls `rin-okay/rin-projects`, updates the selected Forge extensions, and runs the existing `webui-user.bat` in your Forge Neo folder. It uses the launch options already in that file. Use this wrapper as your Forge shortcut or controller command.

## Windows setup

1. Use a Git checkout of `rin-okay/rin-projects`. The existing Forge Mobile sparse checkout works.
2. Run `start-mobile.bat` once to pull the new files, or run `git pull --ff-only` from the checkout.
3. Stop Forge Neo before installing or updating extensions. From the `forge-mobile` folder, run the commands below with the path to your Forge installation.

```bat
start-forge.bat "C:\path\to\Forge Neo" list
start-forge.bat "C:\path\to\Forge Neo" enable forge-cfg-scheduler forge-controlnet-seed-tools
start-forge.bat "C:\path\to\Forge Neo"
```

Use any IDs from `list` with `enable`. It copies missing extensions and adopts existing files that match GitHub. If a local installation differs, it reports the first conflicting file. Back up that extension before choosing which copy to keep. For a standalone extension, moving the old extension fully outside Forge’s `extensions` folder allows a fresh install. For the Regional Prompter overlay, keep the upstream installation and back up or replace only the two overlay files.

For Img2img Hires Fix and mobile archive metadata, the available IDs are `img2img-hires-fix` and `forge-mobile-input-metadata`. For optional generation tools, the catalog includes CFG Scheduler, ControlNet Seed Tools, Lum Experiment, and Hires Fix Tag Support. The native Dock Manager, Rin Theme, Gallery Restore, and Mobile Quality of Life are also selectable. Native mobile helpers previously shipped as separate extensions are available under `extensions/legacy`. Use either Mobile Quality of Life or the overlapping individual helpers. Regional Prompter Tags installs into the upstream Regional Prompter extension and leaves its upstream files alone.

`list` shows which packages are enrolled for this Forge installation. To stop updates for a package, run `start-forge.bat "C:\path\to\Forge Neo" disable <package-id>`. The installed extension stays available to Forge. The selection is specific to each Forge root.

On startup, an offline fetch or conflicting local file leaves Forge available. Locally edited managed files cause that package to be skipped. Local dock state, debug settings, and files outside the managed set stay in place. Changes to the Forge extension set may affect Forge Mobile’s saved component mapping, so export your workspace first if you are changing the installed set.
