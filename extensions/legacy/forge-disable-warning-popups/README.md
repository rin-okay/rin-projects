# Forge Disable Warning Popups

Hides Gradio warning popups in Forge Neo, including the mobile queue warning about changing tabs or putting your phone to sleep. Error and informational popups stay visible and their close buttons work. The toast container lets taps pass through the space around those popups.

## Install

1. Extract the archive into the `extensions` directory of your regular Forge Neo installation. Check that the stylesheet is at `extensions/forge-disable-warning-popups/style.css`.
2. Restart Forge Neo and reload the page you use, including port 7862 for the Mobile Companion.

The extension contains only CSS and works with the Gradio 4.40 toast markup. It changes how warnings are displayed. Forge's queue and reconnection behavior, browser dialogs, and confirmation prompts are handled separately.

To restore warnings, disable the extension in Forge's Extensions tab and restart Forge.
