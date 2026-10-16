# Forge Gallery Restore

A mobile-focused gallery and generation-session recovery extension for Forge Neo, designed for launches using `--no-gradio-queue`.

## What it does

- Adds a `🔄` restore button immediately before `✨` Enhance/Hiresfix in the gallery controls. In img2img, it also adds the button when no Enhance button is present.
- Recovers the latest recorded txt2img or img2img gallery result and generation metadata after the mobile browser is backgrounded, closed, or reopened, while the Forge server remains running.
- Reloads the mobile UI before recovery when needed to escape a stale Gradio session.
- Restores prompts and generation parameters through Forge's native infotext/paste system, plus submission-time snapshots for settings not represented in the output image.
- Retains disabled/inactive Hires Fix settings and the Hiresfix/Enhance `✨` task's own settings.
- Includes img2img source-image caching and restoration for ordinary img2img mode. This newer functionality has had compatibility issues and should be tested with your Forge Neo build before relying on it.

## Installation

Download the [extension ZIP](../forge-gallery-restore.zip), extract it, and place the inner `forge-gallery-restore/` folder in the Forge Neo `extensions/` directory. Remove any earlier copies of this extension, then restart Forge and refresh the browser page.

Alternatively, copy this source folder directly into `extensions/`.

## Notes and limitations

- The extension targets `--no-gradio-queue` and does not implement queue-enabled compatibility.
- Results and submitted-image snapshots are held in Forge's process memory. Restarting Forge clears them; closing the mobile browser does not.
- Browser task IDs are stored in local storage and may be lost if browser data is cleared or the server URL changes.
- Source-image snapshots require a generation made after this version is installed.
- **ControlNet image restoration is currently nonfunctional and is not supported.** Do not rely on it to recover ControlNet inputs.
- This is the current development build, not the previously frozen stable baseline. Keep a backup if you depend on an earlier working version.
