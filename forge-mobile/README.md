# Forge Mobile Client v0.3.30

A standalone companion on port 7862 with the mobile workspace from the HTML preview. Start Forge normally on 7860, then run this companion from its own directory.

The IIB tab opens a separate instance of the installed Infinite Image Browsing frontend and fills the workspace below the mobile tabs.

IIB must be enabled as an extension in the running Forge instance, so its frontend and native Send to controls are available through 7862. The companion uses Forge's IIB asset/API routes through its existing proxy. A separate standalone IIB service on 7861 alone does not provide Forge's native paste controls.

## Trace delays on 7862

In the mobile workspace, open Panels → Settings and turn on Performance logger. Look in the PC command window running the mobile companion for `[Forge Mobile trace]`. The same entries are also available in the browser console. Recording also covers the native view served on 7862. You can also start it with `?forgeTrace=1` in the mobile URL or `ForgeMobileTrace.start()` in the console.

Reproduce a slow prompt edit, tab switch, or seed reuse. Compare `interaction` and `frame-delay` with `request` and `queue` records on the same timeline. Event Timing and Long Task entries appear when supported by the browser. The two-frame estimate measures a rendering opportunity, and time between received queue messages includes delivery time.

Turn off Performance logger when done, or run `ForgeMobileTrace.stop()`. The toggle resets when the page reloads unless `?forgeTrace=1` is in the URL. `JSON.stringify(ForgeMobileTrace.report())` returns the last 160 records for sharing. The logger is off by default and records timing, control names, and known request routes without recording field contents or request data.

## Set up Img2img Hires Fix and input archiving

Forge Mobile includes Img2img Hires Fix v2.2.1 and the input metadata helper. Both run inside Forge Neo.

1. Stop Forge Neo and Forge Mobile. If changing the enabled Forge extension set, export your mobile workspace first to preserve your current draft.
2. Run `setup-forge.bat` in the Forge Mobile folder and enter the path to your Forge Neo installation. You can also pass the folder directly with `setup-forge.bat "C:\path\to\Forge Neo"`. Add `--check` to check an installation without copying files.
3. Start Forge Neo, then start Forge Mobile with `start-mobile.bat`.

Setup installs missing bundled extensions and reuses matching existing copies. If it finds duplicates or a different installed build, it reports the path. Keep a backup outside Forge's extensions folder before choosing to swap builds. Enable the installed extensions in Forge if they were disabled. For IIB, enable Infinite Image Browsing in Forge separately.

## Start on Windows

1. Clone the repository and open its `forge-mobile` folder. A ZIP installation also works for offline use.
2. Start Forge Neo and wait for its normal interface to load.
3. Stop any older companion process using 7862.
4. Double-click start-mobile.bat.
5. Open http://YOUR-PC-IP:7862 on the iPhone, then choose Open mobile workspace.

The launcher creates its own .venv and installs its own Python dependencies. Python 3.10 or newer is required. The client targets Forge's Gradio 4.40.0 SSE interface.

For a different Forge address or mobile port:

    start-mobile.bat --forge http://127.0.0.1:7860 --port 7862

The default listener is available on the local network without a password. Anyone who can reach it can use the Forge session. Use your trusted network.

## Install Git updates

Install Git for Windows, then run these commands once from a folder where you keep apps.

```bat
git clone --sparse https://github.com/rin-okay/rin-projects.git
cd rin-projects
git sparse-checkout set forge-mobile
forge-mobile\start-mobile.bat
```

If migrating from a ZIP, stop the old companion and copy `workspace.json`, `mobile-settings.json`, the `input-archive/` data directory if present, and your custom docks into the new `forge-mobile/` folder. Keep the old install as a backup.

Each launch fetches `main` from the configured origin and applies a fast-forward update before starting the app. A download failure, wrong checkout, or local Git changes skips the update and continues with the installed copy. A non-Git installation launches normally. Run `set FORGE_SKIP_UPDATES=1` in Command Prompt before running the batch file to bypass updates in that shell.

The launch log reports `Version installed (v…)` after an update or `No new version (v…)` when the checkout is current. The companion also prints its installed version at startup.

## ControlNet / img2img Parameters Saver

Forge Mobile includes the Parameters Saver starting with v0.3.22. Restart the companion to load the bundled copy. The bundled code lives in `extensions/parameters-saver/` so Git can update it alongside an existing manual installation at `extensions/input-archive/`.

For archive capture to work, Forge Neo must load the [bundled metadata helper](forge-neo-extensions/forge-mobile-input-metadata/). The setup above installs it and recognizes the previous manual installation when the files match.

Generate from Forge Mobile with a single img2img source or supported ControlNet inputs. A successful capture writes data to `input-archive/images/` and `input-archive/recipes/` beside `workspace.json`; an output with a saved recipe contains `Forge Mobile input archive: <hash>` in its metadata. IIB can use that reference to restore img2img sources and masks, plus ControlNet settings. ControlNet images are archived for reference and are excluded from automatic restore. Keep the `input-archive/` data folder when moving or upgrading an installation.

## Forge Neo extension updates

[Start Forge with GitHub extension updates](FORGE-EXTENSIONS.md) to select which Forge-side extensions receive updates. Forge Mobile’s own launcher continues to start the mobile companion.

## Recent fixes

- On touch devices, focusing a prompt gives the editor the visible workspace. Tap Done to restore the split. The Seed dock puts the variation checkbox beside the main seed, and the compact Save button centers its icon.

- v0.3.11 bounds automatic thumbnail selection and keeps dock rendering out of the native component refresh loop. Tabs use standard button activation.
- The tap report at `/_forge_mobile/taps` now includes the last 96 touch, pointer, and activation events for the workspace, plus the recorder startup marker. Open it on the same 7862 address in the same browser. No prompt text or image data is recorded.

- A generation progress bar appears above the divider while Forge is generating. It uses the active task's progress and disappears when the task ends.

- Mobile extension styles, scripts and templates use versioned URLs so browsers fetch matching files after an update. The workspace checks that its layout stylesheet applied before opening.
- Tap diagnostics start a fresh report and only compare taps against the visible upper workspace.

- UI scaling uses one transformed upper layout instead of CSS zoom. Tabs, prompts and parameter controls share the same coordinate space at the saved scale, including the default 85%. IIB keeps its native iframe viewport size.
- The tap report includes the build version, UI scale, viewport and element bounds. Taps on the open native Gallery viewer are excluded from missed-tap reports.

- The mobile workspace keeps Gradio's column status indicator in its native column. Positioned controls stay within the upper scroll area so a loading or extension layer cannot cover the tab row from inside a panel.
- If taps still fail on the phone, tap a different visible tab, then open `/_forge_mobile/taps` on the same 7862 address in that browser. The report keeps the last 12 detected misses locally, including which element actually received the tap. It records no field values.

- The companion Seed dock isolates its layout from Forge’s native Docker Manager. Random and Reuse sit beside the seed field, and the variation checkbox sits immediately left of its dice button.

- The mobile workspace hides Gradio queue warnings and places other notices along the bottom edge. The notice backdrop and text let taps through. Tabs also handle a completed touch when the browser does not send a click.

- Editable fields keep a readable font size at every workspace scale to prevent iPhone focus zoom. The native Gallery lightbox opens above the mobile workspace.

- The mobile Panels picker lists only the companion Docker Manager.

- The Seed dock keeps Random and Reuse to the right of the main value in half and full widths.

- LoRAs shows a single native toolbar, including after refresh.

- LoRA browsing retains Forge's real search, folder tree, sorting, sort direction, and refresh toolbar, together with the original ancestor required by its filter handlers.
- The active prompt field fills the upper workspace, including at 85% scale and when the keyboard opens. Long prompts grow and scroll the upper workspace.
- Keep Hires Fix in Params shows expanded settings after the ordinary parameter rows in both modes, when available.
- JavaScript alert warnings become nonblocking status notices on 7862. Mobile compatibility confirms and the browser leave-page warning no longer interrupt navigation. Delete/overwrite decisions and the inline Close All Docks confirmation remain deliberate. Errors remain visible.

## Infinite Image Browsing

Click IIB in the mobile tab row. It occupies everything beneath that row, with the split divider, dock canvas and prompt action buttons hidden while browsing.

The mobile iframe loads the installed IIB frontend's existing document. It shares the 7862 parent window and uses IIB's existing BroadcastChannel bridge, hidden image loader, and Forge ParamBinding paste buttons.

Choose Send to txt2img or Send to img2img in IIB. This returns to Forge's native destination tab while its existing handlers apply the image and generation parameters. Click Open mobile workspace to continue using the same updated controls. The mobile IIB iframe stays mounted between visits to preserve its browsing state.

If the native IIB extension is unavailable, the tab displays an explanation and a Retry button. After enabling IIB in Forge, restart Forge and reload the companion page.

## Live controls

The mobile workspace relocates the actual Forge components and restores them on Back. Their Gradio event handlers remain responsible for generation, sampler/model selection, prompt styles, img2img uploads, inpainting, ControlNet, seed actions, and gallery operations.

Generate and Hires Fix docks click the existing Forge buttons. Gallery docks select the native gallery image. Hires Fix requires the existing Forge feature or installed enhancer to provide its native button. The companion uses the bundled Img2img Hires Fix extension installed by the setup above. Its manual gallery action uses the current Hires Fix fields, falling back to the current regular positive and negative prompts per field. Clone regular prompt copies the corresponding regular prompt into the open Hires Fix editor.

The LoRAs tab uses Forge's actual cards. Clicking a card uses Forge's own insertion handler. The slider stack reads and edits the resulting <lora:name:weight> prompt tags. Installed LoRA cards, previews, search, and refresh remain supplied by Forge.

Selecting an accordion in Panels reveals its contents. InputAccordion's enable state, such as the Hires Fix checkbox, is kept as its native generation control. Merely selecting a panel leaves that setting intact.

## Retained mobile features

The package retains the split workspace, divider lock gesture, bottom-anchored docks, snap on locking, free compact docks, double-tap to raise, triple-tap to close, two-click Close All confirmation, Reload Docks, labels toggle, UI scaling, prompt switches, four txt2img prompt states, LoRA weights, settings import/export, Rin palette, and canvas JPG at 8% opacity anchored to the divider.

Defaults are 85% upper-workspace scale, an unlocked Gallery dock at bottom left, and Generate at bottom right. Saved settings override defaults.

## Persistent state

- workspace.json holds captured Forge controls and generation results.
- mobile-settings.json holds mobile layout, scaling, and dock settings.
- defaults.json supplies initial mobile settings.

Forge Mobile keeps unsubmitted prompt edits in the page and saves prompt values when you submit a generation. Export Settings includes the current prompt text. Live prompt error and token checks are disabled in the mobile workspace. Other native input edits are saved through frontend Gradio events. The companion keeps consuming the generation queue while the phone disconnects. Reloading restores the captured controls and output gallery together with generation metadata.

Cached images and extension-owned Python state still belong to the running Forge process. Restarting Forge can invalidate cached uploads and results. A UI/config fingerprint resets captured component state if Forge's component layout changes.

The companion uses its own upstream Gradio session. Its controls form one shared companion workspace for browsers using 7862.

## Mobile extension organization

    extensions/
      docker-manager/
        extension.json
        style.css
        javascript/dock-manager.js
        docks/
          seed/
            dock.json
            dock.js
            style.css
          ...
      mobile-workspace/
        extension.json
        workspace.html
        workspace.js
        native-adapter.js
        style.css
        canvas.jpg
      iib-bridge/
        extension.json
        bridge.js
        style.css

The loader reads extension.json from each direct child of extensions/. The requires list controls loading order. The styles and scripts lists contain relative paths within that extension.

These are companion frontend extensions. Forge Python generation extensions run in the upstream Forge process.

## Add a custom dock

Create a new directory under extensions/docker-manager/docks/. Copy an existing dock as a starting point. Each dock contains dock.json, a script, and a stylesheet. A minimal manifest is:

    {
      "id": "my-dock",
      "name": "My Dock",
      "version": 1,
      "default_width": "half",
      "allowed_widths": ["half", "full"],
      "tabs": ["txt2img", "img2img"],
      "script": "dock.js",
      "style": "style.css"
    }

The script registers a module using the existing format:

    window.ForgeDockManager.registerDock({
        id: "my-dock",
        name: "My Dock",
        mount(container, ctx) {
            const button = document.createElement("button");
            button.textContent = "Generate";
            button.addEventListener("click", () => {
                ctx.getById(ctx.currentGenerationTab() + "_generate")?.click();
            });
            container.append(button);
        },
        unmount(container) {
            container.replaceChildren();
        }
    });

The companion adapts that registration to its isolated manager while serving the script. Existing dock context methods include getById, currentGenerationTab, isDisplayed, requestPosition, setVisible, onLifecycle, and close. Use ctx.shell for the current dock shell.

Choose Panels → Docker Manager → Reload docks after adding or editing a dock. This rescans manifests and reloads changed scripts/styles while preserving dock positions. The ten shipped docks use this same directory format.

## Source review and verification

IIB integration follows the installed extension's frontend document and transfer protocol, reviewed in these upstream files:

- https://github.com/zanllp/infinite-image-browsing/blob/main/javascript/index.js
- https://github.com/zanllp/infinite-image-browsing/blob/main/scripts/iib_setup.py
- https://github.com/zanllp/infinite-image-browsing/blob/main/vue/src/page/fileTransfer/hooks/useFileItemActions.tsx


Implementation reviewed the Forge Neo neo branch's native UI construction, Toprow, InputAccordion, Seed built-in script, submission/gallery helpers, and extra-network card handlers:

- https://github.com/Haoming02/sd-webui-forge-classic/blob/neo/modules/ui.py
- https://github.com/Haoming02/sd-webui-forge-classic/blob/neo/modules/ui_toprow.py
- https://github.com/Haoming02/sd-webui-forge-classic/blob/neo/modules/ui_components.py
- https://github.com/Haoming02/sd-webui-forge-classic/blob/neo/modules/processing_scripts/seed.py
- https://github.com/Haoming02/sd-webui-forge-classic/blob/neo/javascript/ui.js
- https://github.com/Haoming02/sd-webui-forge-classic/blob/neo/javascript/extraNetworks.js

Verification includes companion HTTP/state integration tests, a real Gradio 4.40 SSE generation, gallery/metadata recovery, Hires callback check using restored image pixels, and native paste callback restoring a prompt plus image, and a DOM fixture checking native component identity, Generate dock clicks, LoRA card/slider integration, Back restoration, plus IIB iframe reuse and Send to handoff to both native destinations.

Run the included transport tests from this directory:

    python -m unittest discover -s tests

GPU generation on your Windows installation, your installed third-party extension combinations, and iPhone Safari rendering still require a live check. Touch-enabled Chromium tests cover the five mobile tabs at 80%, 85%, 100% and 120% scale, prompt focus, restored Params on reload, the IIB iframe's sizing and button interaction, and gallery viewer exclusion from the tap report.
