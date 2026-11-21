# Forge Mobile Zoom

Mobile viewport scaling for Forge Neo, with the zoom controls embedded directly in the native Quicksettings row.

## Placement

The control is inserted immediately after Forge's `#setting_sd_model_checkpoint` and before `#setting_sd_modules`. Because `#quicksettings` is Forge's own wrapping row, the control naturally occupies the open space to the right of Checkpoint when that space is available and wraps with the other quick settings when it is not.

The control is no longer `position: fixed` and does not float over generation controls.

## Styling

The extension does not hard-code its own palette. Buttons use Gradio's secondary-button variables for background, border, text, hover and focus states, while the label uses Gradio block-label variables. It therefore follows Forge's Default theme, Rin Neon, or another theme automatically.

## Zoom mechanism

The scaling mechanism remains the tested viewport-width implementation:

- numeric mobile viewport width
- no CSS `zoom` on Forge
- no transform on Forge content
- no lightbox hooks
- no IIB special cases
- 50% to 100% in 5% steps
- saved scale and enabled state
- tap the percentage to toggle native 100% / saved zoom
- orientation and resize recalculation

Only the separate floating Forge Mobile UI Generate dock is inverse-scaled toward normal finger size. The inline Zoom control scales with the rest of Quicksettings.
