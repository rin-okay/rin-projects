from __future__ import annotations

import itertools
import logging
import random
import torch

import gradio as gr
import numpy as np
from PIL import Image

from modules import extra_networks, scripts, shared, ui
from modules.processing_scripts.seed import connect_reuse_seed
from modules.ui_components import ToolButton

from lumex_core import (
    DEFAULT_DENOISE,
    denoise_to_influence,
    influence_to_denoise,
    LumexConfig,
    LumexConfigError,
    SplotchConfig,
    apply_lumex,
    build_reference_gray,
    build_influence_preview,
    VERSION,
    last_lumex_from_prompt,
    parse_lumex_items,
    update_prompt_tag,
)

LOGGER = logging.getLogger("forge-lum-experiment")
NAMESPACE = "lumex"


class _LumexExtraNetwork(extra_networks.ExtraNetwork):
    def activate(self, p, params_list):
        if not params_list:
            p._lumex_config = None
            return None
        params = params_list[-1]
        try:
            config = parse_lumex_items(list(getattr(params, "items", []) or []))
        except LumexConfigError as exc:
            p._lumex_config = None
            LOGGER.warning("Lum Experiment: invalid <lumex:...> tag rejected: %s", exc)
            return None
        p._lumex_config = config
        return None

    def deactivate(self, p):
        p._lumex_config = None
        return None


_LUMEX_EXTRA_NETWORK = _LumexExtraNetwork(NAMESPACE)


def _case_variants(word: str):
    for choices in itertools.product(*[(c.lower(), c.upper()) for c in word]):
        yield "".join(choices)


def _ensure_extra_network_registered() -> None:
    existing = extra_networks.extra_network_registry.get(_LUMEX_EXTRA_NETWORK.name)
    if existing is not _LUMEX_EXTRA_NETWORK:
        if existing is not None:
            LOGGER.warning(
                "Lum Experiment: replacing existing extra-network namespace %r (%s).",
                _LUMEX_EXTRA_NETWORK.name,
                type(existing).__name__,
            )
        extra_networks.register_extra_network(_LUMEX_EXTRA_NETWORK)
    for variant in _case_variants(NAMESPACE):
        if variant != NAMESPACE:
            extra_networks.register_extra_network_alias(_LUMEX_EXTRA_NETWORK, variant)


_ensure_extra_network_registered()


def _config_from_ui(lum, enable_splotch, grid, amount, contrast, interpolation, strength, denoise, mode="tonal", legacy_influence=0.05):
    splotch = None
    if enable_splotch:
        splotch = SplotchConfig(int(grid), float(amount), float(contrast), str(interpolation))
    return LumexConfig(
        float(lum),
        splotch=splotch,
        strength=float(strength),
        splotch_influence=float(legacy_influence) if mode == "legacy" else denoise_to_influence(float(denoise)),
        mode=mode,
    )


def _update_prompt(prompt, lum, enable_splotch, grid, amount, contrast, interpolation, strength, denoise, mode="tonal", legacy_influence=0.05):
    try:
        config = _config_from_ui(lum, enable_splotch, grid, amount, contrast, interpolation, strength, denoise, mode, legacy_influence)
        return update_prompt_tag(prompt or "", config)
    except Exception as exc:
        return prompt, f"Could not update prompt: {exc}"


def _load_prompt(prompt, current_lum, current_grid, current_amount, current_contrast, current_mode, current_strength, current_denoise, current_mode_type="tonal", current_legacy_influence=0.05):
    found, config, error = last_lumex_from_prompt(prompt or "")
    if error:
        return current_lum, False, current_grid, current_amount, current_contrast, current_mode, current_strength, current_denoise, current_mode_type, current_legacy_influence, f"Lumex tag invalid: {error}"
    if not found or config is None:
        return current_lum, False, current_grid, current_amount, current_contrast, current_mode, current_strength, current_denoise, current_mode_type, current_legacy_influence, "No lumex tag found in prompt."
    s = config.splotch
    return (
        config.lum,
        s is not None,
        s.grid if s else current_grid,
        s.amount if s else current_amount,
        s.contrast if s else current_contrast,
        s.interpolation if s else current_mode,
        config.strength,
        influence_to_denoise(config.splotch_influence) if s else current_denoise,
        config.mode,
        config.splotch_influence,
        f"Loaded: {config.tag()}",
    )


def _preview_reference(seed, width, height, lum, enable_splotch, grid, amount, contrast, interpolation, strength, denoise, mode="tonal", legacy_influence=0.05):
    try:
        requested_seed = int(seed)
        resolved_seed = random.randrange(0, 4294967294) if requested_seed == -1 else requested_seed
        config = _config_from_ui(lum, enable_splotch, grid, amount, contrast, interpolation, strength, denoise, mode, legacy_influence)
        gray = build_reference_gray(config, resolved_seed, int(width), int(height))[0, 0].numpy()
        image = Image.fromarray(np.round(np.clip(gray, 0.0, 1.0) * 255.0).astype(np.uint8), mode="L")
        effective, metrics = build_influence_preview(config, resolved_seed, int(width), int(height))
        effect_image = Image.fromarray(np.round(effective[0, 0].numpy() * 255).astype(np.uint8))
        stats = (
            f"Mode: {config.mode}. Black = dark push; gray = neutral; white = light push. "
            f"{'Shared injection control map' if config.mode == 'tonal' else 'Approximate normalized-influence proxy'}. "
            "Not a prediction of final pixels; compare actual generations below.\n"
            f"Map RMS from neutral: {metrics['spatial_proxy_rms']:.4f}; clipped pixels: {metrics['clipped_fraction']:.1%}.\n"
            f"Reference seed: {resolved_seed} | {image.width}×{image.height} | "
            f"gray mean {float(gray.mean()):.3f} | min {float(gray.min()):.3f} | max {float(gray.max()):.3f}\n\n"
            f"{config.tag()}"
        )
        return image, effect_image, stats, resolved_seed
    except Exception as exc:
        LOGGER.exception("Lum Experiment reference preview failed")
        return None, None, f"Preview failed: {exc}", seed


def _copy_dimensions(width, height):
    return width, height


class Script(scripts.Script):
    section = None
    create_group = True
    sorting_priority = 21

    def __init__(self):
        self._prompt_component = None
        self._negative_component = None
        self._seed_component = None
        self._txt2img_width_component = None
        self._txt2img_height_component = None
        self._preview_width_component = None
        self._preview_height_component = None
        self._copy_dimensions_button = None
        self._copy_dimensions_wired = False

    def title(self):
        return "Lum Experiment"

    def _capture_txt2img_width(self, x):
        self._txt2img_width_component = x.component
        self._wire_dimension_capture_if_ready()

    def _capture_txt2img_height(self, x):
        self._txt2img_height_component = x.component
        self._wire_dimension_capture_if_ready()

    def _wire_dimension_capture_if_ready(self):
        if self._copy_dimensions_wired:
            return
        if any(
            x is None
            for x in (
                self._txt2img_width_component,
                self._txt2img_height_component,
                self._preview_width_component,
                self._preview_height_component,
                self._copy_dimensions_button,
            )
        ):
            return

        self._copy_dimensions_button.click(
            fn=_copy_dimensions,
            inputs=[self._txt2img_width_component, self._txt2img_height_component],
            outputs=[self._preview_width_component, self._preview_height_component],
            show_progress=False,
            queue=False,
        )
        self._copy_dimensions_wired = True

    def show(self, is_img2img):
        if is_img2img:
            return False
        self.on_after_component(lambda x: setattr(self, "_prompt_component", x.component), elem_id="txt2img_prompt")
        self.on_after_component(lambda x: setattr(self, "_negative_component", x.component), elem_id="txt2img_neg_prompt")
        self.on_after_component(lambda x: setattr(self, "_seed_component", x.component), elem_id="txt2img_seed")
        self.on_after_component(self._capture_txt2img_width, elem_id="txt2img_width")
        self.on_after_component(self._capture_txt2img_height, elem_id="txt2img_height")
        return scripts.AlwaysVisible

    def ui(self, is_img2img):
        if is_img2img:
            return []

        with gr.Accordion(open=False, label=self.title(), elem_id="lum_experiment"):
            with gr.Accordion(open=False, label="Parameter guide", elem_id="lum_experiment_parameter_guide"):
                gr.Markdown(
                    """
**Lum** — default `0.0`. Sets the base grayscale reference: `-1` is black, `0` is 50% gray, `+1` is white.

**Add splotches** — default **off**. Adds procedural light/dark structure to the grayscale reference.

**Splotch scale** — default `8`. Lower values make fewer/larger regions; higher values make more/smaller regions.

**Reference range** — default `0.25`. Controls how far the splotch pattern moves away from the base gray before clipping to black/white. Values above `1` deliberately produce increasingly clipped, posterized references.

**Pattern hardness** — default `2.0`. Controls the shape of the grayscale pattern. Lower values give gentler gradients; higher values push regions toward harder light/dark separation.

**Splotch mode** — default `bilinear`. `bilinear` is soft, `bicubic` is smooth/organic, and `nearest` is hard/blocky.

**Lum strength** — default `1.0`. Scales only the global VAE-derived luminance offset.

**Denoise** — default `0.85`. Img2img-style analogy for splotch influence: `0` is strongest reference influence and `1` ignores the splotch reference. In tonal mode this attenuates the map before injection. Legacy mode instead uses the separate normalized-influence slider.

**Preview width / height** — default `512 × 512`. These set preview and comparison dimensions; ordinary generation uses txt2img dimensions. The 📐 button copies the current txt2img Width and Height.

**Preview seed** — default `-1`. `-1` makes a new random preview pattern on each click. The ♻️ button copies the seed from the currently selected image in the last txt2img generation.
                    """.strip()
                )

            gr.Markdown("**1.6.0 experimental tonal mapping.** The influence preview is the control map used for injection: black/darkening, gray/no push, white/brightening. Final saturation still depends on the model, prompt and sampler.")
            mode = gr.Radio(["tonal", "legacy"], value="tonal", label="Injection mode (old tags load as legacy)")
            legacy_influence = gr.Slider(0, 1, value=0.05, step=0.005, label="Legacy normalized influence (used only in legacy mode)")
            lum = gr.Slider(-1.0, 1.0, value=0.0, step=0.01, label="Lum (-1 dark, 0 neutral, +1 light)")

            enable_splotch = gr.Checkbox(value=False, label="Add splotches")
            with gr.Row():
                grid = gr.Slider(2, 128, value=8, step=1, label="Splotch scale")
                amount = gr.Slider(0.0, 5.0, value=0.25, step=0.05, label="Reference range")
            with gr.Row():
                contrast = gr.Slider(0.05, 20.0, value=2.0, step=0.05, label="Pattern hardness")
                interpolation = gr.Dropdown(
                    choices=["nearest", "bilinear", "bicubic"], value="bilinear", label="Splotch mode"
                )

            strength = gr.Slider(0.0, 3.0, value=1.0, step=0.05, label="Lum strength")
            denoise = gr.Slider(
                0.0,
                1.0,
                value=DEFAULT_DENOISE,
                step=0.01,
                label="Tonal attenuation (1 = no splotches, 0 = full range; tag: denoise)",
            )

            with gr.Accordion(open=False, label="Preview reference", elem_id="lum_experiment_preview"):
                with gr.Row():
                    preview_width = gr.Slider(64, 2048, value=512, step=8, label="Preview width")
                    preview_height = gr.Slider(64, 2048, value=512, step=8, label="Preview height")
                    copy_dimensions_button = ToolButton(
                        ui.detect_image_size_symbol,
                        elem_id="lum_experiment_copy_dimensions",
                        tooltip="Copy current txt2img Width and Height",
                    )

                preview_image = gr.Image(
                    label="Grayscale reference preview", type="pil", interactive=False, height=320
                )

                effect_preview = gr.Image(label="Effective influence: black ← dark | neutral gray | light → white", type="pil", interactive=False, height=320)
                with gr.Row():
                    preview_seed = gr.Number(
                        value=-1,
                        precision=0,
                        label="Preview seed (-1 = random)",
                        min_width=120,
                    )
                    reuse_preview_seed = ToolButton(
                        ui.reuse_symbol,
                        elem_id="lum_experiment_reuse_preview_seed",
                        tooltip="Reuse seed from selected image in last generation",
                    )
                    preview_button = gr.Button("Preview reference", variant="secondary")

                use_seed_button = gr.Button("Use preview seed for txt2img")
                preview_status = gr.Textbox(label="Preview status", interactive=False, lines=3)

            with gr.Accordion("Compare actual generations (two renders)", open=False):
                gr.Markdown("Uses the current prompt and negative prompt, preview seed/dimensions and settings below. Renders a baseline and this editor's tag with the loaded checkpoint. Other always-on scripts, Hires Fix and prompt styles are excluded from this comparison. Images are temporary; download any you want to keep.")
                with gr.Row():
                    comparison_steps = gr.Slider(1, 60, value=20, step=1, label="Comparison steps")
                    comparison_cfg = gr.Slider(1, 20, value=6, step=0.5, label="Comparison CFG")
                comparison_button = gr.Button("Generate baseline / effect pair (Euler, Automatic)")
                comparison_images = gr.Gallery(label="Baseline | Effect | Absolute difference ×4", columns=3)
                comparison_status = gr.Textbox(label="Comparison result", lines=5)
            with gr.Row():
                load_button = gr.Button("Load tag from prompt", variant="secondary")
                update_button = gr.Button("Add / update prompt tag", variant="primary")

            tag_status = gr.Textbox(label="Tag status", interactive=False, lines=2)

        prompt = self._prompt_component
        if prompt is None:
            LOGGER.error("Lum Experiment: txt2img prompt component was not captured; tag editor buttons cannot be wired.")
            tag_status.value = "UI wiring failed: txt2img prompt was not available. Restart Forge and check console."
            return []

        # Save preview-side components and wire the dimension-copy button. This
        # also supports user-reordered Forge UI categories where the main
        # Width/Height sliders may be created after this script's UI.
        self._preview_width_component = preview_width
        self._preview_height_component = preview_height
        self._copy_dimensions_button = copy_dimensions_button
        self._wire_dimension_capture_if_ready()

        # Use Forge Neo's own seed-reuse helper. It reads generation_info_txt2img
        # plus selected_gallery_index(), exactly like the built-in seed ♻️ button.
        self.on_after_component(
            lambda x: connect_reuse_seed(preview_seed, reuse_preview_seed, x.component, False),
            elem_id="generation_info_txt2img",
        )

        preview_button.click(
            fn=_preview_reference,
            inputs=[
                preview_seed,
                preview_width,
                preview_height,
                lum,
                enable_splotch,
                grid,
                amount,
                contrast,
                interpolation,
                strength,
                denoise, mode, legacy_influence,
            ],
            outputs=[preview_image, effect_preview, preview_status, preview_seed],
            show_progress=False,
        )
        update_button.click(
            fn=_update_prompt,
            inputs=[prompt, lum, enable_splotch, grid, amount, contrast, interpolation, strength, denoise, mode, legacy_influence],
            outputs=[prompt, tag_status],
            show_progress=False,
        )
        load_button.click(
            fn=_load_prompt,
            inputs=[prompt, lum, grid, amount, contrast, interpolation, strength, denoise, mode, legacy_influence],
            outputs=[lum, enable_splotch, grid, amount, contrast, interpolation, strength, denoise, mode, legacy_influence, tag_status],
            show_progress=False,
        )
        if self._seed_component is not None:
            use_seed_button.click(fn=lambda seed: seed, inputs=[preview_seed], outputs=[self._seed_component], queue=False)
        if self._negative_component is not None:
            from lumex_compare import compare_ui
            comparison_button.click(
                fn=lambda *values: compare_ui(Script, _config_from_ui, *values),
                inputs=[prompt, self._negative_component, preview_seed, preview_width, preview_height,
                        comparison_steps, comparison_cfg, lum, enable_splotch, grid, amount, contrast,
                        interpolation, strength, denoise, mode, legacy_influence],
                outputs=[comparison_images, comparison_status, preview_seed],
            )
        return []

    def process(self, p, *args):
        _ensure_extra_network_registered()
        p._lumex_config = None
        p._lumex_applied = False

    def process_before_every_sampling(self, p, *args, **kwargs):
        if getattr(p, "is_hr_pass", False):
            return
        if getattr(p, "init_images", None):
            return

        noise = kwargs.get("noise")
        if noise is None:
            return
        if getattr(noise, "ndim", None) != 4:
            LOGGER.warning("Lum Experiment: only 4D image latents are supported; got %s.", getattr(noise, "shape", None))
            return

        config = getattr(p, "_lumex_config", None)
        if config is None or config.is_noop:
            return

        seeds = list(getattr(p, "seeds", None) or getattr(p, "all_seeds", None) or [])
        if not seeds:
            LOGGER.warning("Lum Experiment: no generation seeds available; leaving starting noise unchanged.")
            return

        try:
            base_noise = p.modified_noise if getattr(p, "modified_noise", None) is not None else noise
            p.modified_noise = apply_lumex(
                base_noise,
                shared.sd_model,
                config,
                seeds,
                int(getattr(p, "width", noise.shape[-1] * 8)),
                int(getattr(p, "height", noise.shape[-2] * 8)),
            )
            delta = (p.modified_noise - base_noise).float()
            p._lumex_applied = True
            p.extra_generation_params["Lumex version"] = VERSION
            p.extra_generation_params["Lumex mode"] = config.mode
            p.extra_generation_params["Lumex injected RMS"] = round(float(delta.square().mean().sqrt()), 6)
        except Exception as exc:
            p.extra_generation_params["Lumex error"] = str(exc)
            LOGGER.exception("Lum Experiment: reference-latent transform failed; using Forge's original noise: %s", exc)
