"""Opt-in ControlNet preprocessor seed controls for Forge Neo.

Monkeypatches the *in-memory* ControlNet class and unit renderer.  Files inside
extensions-builtin/sd_forge_controlnet are never changed.  This is intentionally
specific to Forge Neo's integrated ControlNet implementation (neo branch).
"""
from __future__ import annotations

import logging

import gradio as gr
import numpy as np
import torch

from seed_core import get_map_seeds, parse_seed, temporary_preprocessor_seed

log = logging.getLogger("controlnet-seed-tools")


def _patch_controlnet():
    from modules import scripts as webui_scripts
    from lib_controlnet import external_code
    from lib_controlnet.controlnet_ui.controlnet_ui_group import ControlNetUiGroup
    from lib_controlnet.utils import crop_and_resize_image, judge_image_type
    from modules_forge.utils import numpy_to_pytorch

    matches = [entry.script_class for entry in webui_scripts.scripts_data
               if entry.script_class.__name__ == "ControlNetForForgeOfficial"]
    if not matches:
        log.error("Forge Neo integrated ControlNet was not found; extension inactive")
        return

    controlnet_class = matches[0]
    if getattr(controlnet_class, "_seedtools_patched", False):
        return

    original_render = ControlNetUiGroup.render
    original_ui = controlnet_class.ui
    original_get_enabled_units = controlnet_class.get_enabled_units
    original_process = controlnet_class.process
    original_get_input_data = controlnet_class.get_input_data
    original_after_click = controlnet_class.process_unit_after_click_generate
    original_before_sampling = controlnet_class.process_unit_before_every_sampling

    def render_with_seed_tools(self, tabname, elem_id_tabname):
        state = original_render(self, tabname, elem_id_tabname)
        with gr.Group(elem_classes=["cnseed-settings"]):
            with gr.Row(equal_height=True):
                self.cnseed_vary = gr.Checkbox(
                    label="Vary preprocessor per image",
                    value=False,
                    elem_id=f"{elem_id_tabname}_{tabname}_cnseed_vary",
                    info="Use a fresh, reproducible preprocessor map for each image and each batch.",
                )
                self.cnseed_seed = gr.Number(
                    label="Preprocessor seed (-1 = image seed)",
                    value=-1,
                    precision=0,
                    elem_id=f"{elem_id_tabname}_{tabname}_cnseed_seed",
                    info="An independent seed. With variation enabled, image N uses this seed + N.",
                )
        return state

    def ui_with_seed_tools(self, is_img2img):
        group_start = len(ControlNetUiGroup.all_ui_groups)
        original_controls = original_ui(self, is_img2img)
        groups = ControlNetUiGroup.all_ui_groups[group_start:]
        self._cnseed_unit_count = len(groups)
        extras = []
        for unit_index, group in enumerate(groups):
            extras.extend([group.cnseed_vary, group.cnseed_seed])
            # Preserve the selected options in PNG metadata and allow pasting
            # them back into the same UI slot.
            self.infotext_fields.extend([
                (group.cnseed_vary, f"CN Seed Tools {unit_index} Vary"),
                (group.cnseed_seed, f"CN Seed Tools {unit_index} Base"),
            ])
            self.paste_field_names.extend([
                f"CN Seed Tools {unit_index} Vary", f"CN Seed Tools {unit_index} Base",
            ])
        return tuple(original_controls) + tuple(extras)

    def _unit_arguments(args):
        """Separate integrated ControlNet's Gradio States from seed settings."""
        core = []
        for value in args:
            if isinstance(value, external_code.ControlNetUnit):
                core.append(value)
            elif isinstance(value, dict) and ("enabled" in value or "module" in value):
                core.append(value)
            else:
                break
        return core, args[len(core):]

    def process_with_seed_tools(self, p, *args, **kwargs):
        core, extras = _unit_arguments(args)
        config = []
        for i, _ in enumerate(core):
            flag = extras[2 * i] if len(extras) > 2 * i else False
            seed = extras[2 * i + 1] if len(extras) > 2 * i + 1 else -1
            config.append((bool(flag), parse_seed(seed)))
        self._cnseed_config = config
        # Add keys only for opted-in units; untouched jobs keep original PNGs.
        for i, raw in enumerate(core):
            if not (raw.get("enabled", True) if isinstance(raw, dict) else raw.enabled):
                continue
            vary, seed = config[i]
            if vary or seed != -1:
                p.extra_generation_params[f"CN Seed Tools {i} Vary"] = vary
                p.extra_generation_params[f"CN Seed Tools {i} Base"] = seed
        return original_process(self, p, *args, **kwargs)

    def get_enabled_units_with_seed_tools(self, args):
        core, _extras = _unit_arguments(args)
        # The built-in implementation assumes *every* arg is a ControlNetUnit.
        # Our controls are appended after the original unit states, so filter.
        enabled = original_get_enabled_units(self, core)
        configs = getattr(self, "_cnseed_config", [])
        active_configs = []
        for i, raw in enumerate(core):
            is_enabled = raw.get("enabled", True) if isinstance(raw, dict) else raw.enabled
            if is_enabled:
                active_configs.append(configs[i] if i < len(configs) else (False, -1))
        for unit, (vary, seed) in zip(enabled, active_configs):
            unit._cnseed_vary = vary
            unit._cnseed_base = seed
        return enabled

    def get_input_data_with_seed_tools(self, p, unit, preprocessor, h, w):
        data = original_get_input_data(self, p, unit, preprocessor, h, w)
        if getattr(unit, "_cnseed_vary", False) or getattr(unit, "_cnseed_base", -1) != -1:
            unit._cnseed_input = data
        return data

    def _refresh_conditioning(self, p, params, iteration):
        """Build a tensor of independently preprocessed images for this batch."""
        source = getattr(params, "_cnseed_input", None)
        if source is None:
            return False
        input_list, resize_mode = source
        if len(input_list) != 1:
            log.warning("Multiple ControlNet input images: cannot apply per-image seed logic safely")
            return False

        vary, base = params._cnseed_options
        try:
            selected = get_map_seeds(
                p.all_seeds, int(p.batch_size), int(iteration), vary, base
            )
        except (TypeError, ValueError) as exc:
            log.warning("Cannot derive ControlNet seed: %s", exc)
            return False

        input_image, input_mask = input_list[0]
        preprocessor = params.preprocessor
        processor_res, threshold_a, threshold_b = params._cnseed_preprocessor_options
        h, w, hr_h, hr_w = self.get_target_dimensions(p)
        maps = []
        for seed in selected:
            with temporary_preprocessor_seed(seed):
                map_image = preprocessor(
                    input_image=input_image,
                    input_mask=input_mask,
                    resolution=processor_res,
                    slider_1=threshold_a,
                    slider_2=threshold_b,
                )
            if not judge_image_type(map_image):
                log.warning("%s does not return an image; keeping native ControlNet conditioning",
                            getattr(preprocessor, "name", "preprocessor"))
                return False
            maps.append(map_image)

        def create_batch(height, width):
            tensors = [numpy_to_pytorch(crop_and_resize_image(m, resize_mode, height, width))
                       .movedim(-1, 1) for m in maps]
            stacked = torch.cat(tensors, dim=0)
            if not vary:
                # Same preprocessor map for every image (but independent seed).
                stacked = stacked.repeat(int(p.batch_size), 1, 1, 1)
            return stacked.contiguous()

        params.control_cond = create_batch(h, w)
        if bool(getattr(p, "enable_hr", False)):
            params.control_cond_for_hr_fix = create_batch(hr_h, hr_w)
        else:
            params.control_cond_for_hr_fix = params.control_cond
        params._cnseed_iteration = iteration
        log.info("ControlNet %s: preprocessor seeds for iteration %s: %s",
                 getattr(preprocessor, "name", "?"), iteration, selected)
        return True

    def after_click_with_seed_tools(self, p, unit, params, *args, **kwargs):
        original_after_click(self, p, unit, params, *args, **kwargs)
        vary = bool(getattr(unit, "_cnseed_vary", False))
        base = int(getattr(unit, "_cnseed_base", -1))
        if not (vary or base != -1):
            return
        if params.preprocessor is None or params.model is None:
            return
        params._cnseed_options = (vary, base)
        params._cnseed_input = getattr(unit, "_cnseed_input", None)
        # Original pixel-perfect processing can change the effective resolution.
        params._cnseed_preprocessor_options = (
            unit.processor_res, unit.threshold_a, unit.threshold_b
        )
        self._cnseed_refresh_conditioning(p, params, iteration=0)

    def before_sampling_with_seed_tools(self, p, unit, params, *args, **kwargs):
        if getattr(params, "_cnseed_options", (False, -1))[0]:
            iteration = int(getattr(p, "iteration", 0))
            if iteration != getattr(params, "_cnseed_iteration", None):
                self._cnseed_refresh_conditioning(p, params, iteration)
        return original_before_sampling(self, p, unit, params, *args, **kwargs)

    ControlNetUiGroup.render = render_with_seed_tools
    controlnet_class.ui = ui_with_seed_tools
    controlnet_class.process = process_with_seed_tools
    controlnet_class.get_enabled_units = get_enabled_units_with_seed_tools
    controlnet_class.get_input_data = get_input_data_with_seed_tools
    controlnet_class.process_unit_after_click_generate = after_click_with_seed_tools
    controlnet_class.process_unit_before_every_sampling = before_sampling_with_seed_tools
    controlnet_class._cnseed_refresh_conditioning = _refresh_conditioning
    controlnet_class._seedtools_patched = True
    log.info("ControlNet preprocessor seed tools installed")


try:
    _patch_controlnet()
except Exception:
    log.exception("Could not install ControlNet seed tools; native ControlNet is unchanged")
