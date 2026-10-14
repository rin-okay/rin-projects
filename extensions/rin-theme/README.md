# Rin Theme

Standalone Rin Neon theme for Forge Neo. Copy **this `rin-theme/` directory** into Forge's `extensions/` folder. Does not require Docker Manager or Mobile Quality of Life.

The Python `scripts/rin_neon_theme.py` before-UI hook selects Forge's built-in Default theme. `style.css` applies the dark plum/purple palette, square borders, selected-dropdown styling, and a native image-lightbox compatibility exception.

It is meant to run without another theme override competing for Forge's appearance. To try a different theme, disable `rin-theme` rather than editing Docker Manager or Mobile Quality of Life.
