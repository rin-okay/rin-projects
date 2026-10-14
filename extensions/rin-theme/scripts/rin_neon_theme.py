from modules import script_callbacks, shared_gradio_themes


THEME_NAME = "Rin Neon — Default"


def apply_theme():
    # Use Forge Neo's own Default-theme loader rather than calling Gradio's
    # Base.set() ourselves. This keeps the exact Forge Default structure and
    # avoids depending on theme-token kwargs that vary between Gradio versions.
    shared_gradio_themes.reload_gradio_theme("Default")
    print(f"[{THEME_NAME}] Forge Default base applied; palette supplied by extension CSS")


script_callbacks.on_before_ui(apply_theme, name="rin_neon_theme")
