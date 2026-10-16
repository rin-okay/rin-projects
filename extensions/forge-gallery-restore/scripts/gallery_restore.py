"""Forge Neo gallery restore compatibility patch.

Designed for Forge Neo running with --no-gradio-queue.

This extension adds a visible gallery-side restore button in JavaScript and reuses
Neo's existing hidden Restore Progress button for all server-side restore events. Neo
restores the gallery normally, while an additional handler repopulates the current tab's
input controls using the same infotext parsing and paste-field definitions that Forge
uses for PNG Info / Send To behavior. No additional Gradio layout components are added.

It additionally keeps a lightweight server-side snapshot of selected submitted UI values,
so the restore button can recover inputs that may not have been active in the generated
image itself, such as disabled Hires Fix settings, and can restore the main img2img
source image.
"""

from __future__ import annotations

import inspect
import json
import threading
from functools import partial, wraps
from io import BytesIO

import gradio as gr
import numpy as np
from PIL import Image

from modules import progress
import modules.infotext_utils as infotext_utils
import modules.script_callbacks as script_callbacks
import modules.txt2img as txt2img_module
import modules.img2img as img2img_module
import modules.ui_toprow as ui_toprow
from modules_forge.forge_canvas.canvas import LogicalImage

try:
    from lib_controlnet.external_code import ControlNetUnit
except Exception:
    ControlNetUnit = None


_original_record_results = progress.record_results
_original_restore_progress = progress.restore_progress
_original_add_paste_fields = infotext_utils.add_paste_fields
_original_create_tools_row = ui_toprow.Toprow.create_tools_row
_original_txt2img = txt2img_module.txt2img
_original_txt2img_upscale = txt2img_module.txt2img_upscale
_original_img2img = img2img_module.img2img

_restore_buttons = {}
_bound_restore_tabs = set()
_submission_snapshots = {}
_submission_snapshot_order = []
_MAX_SUBMISSION_SNAPSHOTS = 16
_snapshot_lock = threading.RLock()
_bound_img2img_source_restore = False
_bound_controlnet_restore_tabs = set()
_controlnet_logical_images = {"txt2img": [], "img2img": []}



def _encode_source(value):
    if isinstance(value, Image.Image):
        image = value
    elif isinstance(value, np.ndarray):
        image = Image.fromarray(value)
    else:
        raise TypeError("unsupported image representation")

    image = image.convert("RGBA")
    image.info.clear()
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _decode_source(data, component):
    with Image.open(BytesIO(data)) as decoded:
        image = decoded.convert("RGBA")
        return np.array(image, dtype=np.uint8, copy=True) if getattr(component, "numpy", False) else image


def _capture_controlnet_component(component, **kwargs):
    if not isinstance(component, LogicalImage):
        return

    elem_id = (getattr(component, "elem_id", None) or kwargs.get("elem_id") or "").lower()
    if "controlnet" not in elem_id:
        return

    tabname = None
    if "txt2img" in elem_id:
        tabname = "txt2img"
    elif "img2img" in elem_id:
        tabname = "img2img"

    if tabname is None:
        return

    if component not in _controlnet_logical_images[tabname]:
        _controlnet_logical_images[tabname].append(component)


def _snapshot_controlnet_units(values):
    snapshots = []
    for value in values or ():
        is_dict_unit = isinstance(value, dict) and ("image" in value or "enabled" in value)
        is_unit = is_dict_unit or (ControlNetUnit is not None and isinstance(value, ControlNetUnit)) or value.__class__.__name__ == "ControlNetUnit"
        if not is_unit:
            continue

        unit = {}
        for name in ("image", "image_fg", "mask_image", "mask_image_fg"):
            source = value.get(name) if isinstance(value, dict) else getattr(value, name, None)
            if isinstance(source, dict):
                nested = source.get("image", None)
                if nested is None:
                    nested = source.get("mask", None)
                source = nested
            if source is None:
                unit[name] = None
                continue
            try:
                unit[name] = _encode_source(source)
            except Exception:
                unit[name] = None
        snapshots.append(unit)

    return snapshots


def _flatten_controlnet_sources(snapshot):
    result = []
    for unit in snapshot.get("controlnet_units", []) or []:
        for name in ("image", "image_fg", "mask_image", "mask_image_fg"):
            result.append(unit.get(name))
    return result


def _img2img_source_update(id_task, *, component):
    with _snapshot_lock:
        snapshot = _submission_snapshots.get(id_task) or {}
        source = snapshot.get("source_png")

    if source is None:
        return gr.skip()

    try:
        # Return the raw value, not gr.update(value=...). Neo's LogicalImage must
        # retain its constructor's numpy setting.
        return _decode_source(source, component)
    except Exception:
        return gr.skip()


def _try_bind_img2img_source_restore():
    global _bound_img2img_source_restore
    if _bound_img2img_source_restore:
        return

    button = _restore_buttons.get("img2img")
    source = infotext_utils.paste_fields.get("img2img", {}).get("init_img")
    fields = infotext_utils.paste_fields.get("img2img", {}).get("fields") or []
    if button is None or source is None or not fields:
        return
    if not isinstance(source, LogicalImage):
        return

    button.click(
        fn=partial(_img2img_source_update, component=source),
        js="function(){return [localStorage.getItem('forge_gallery_restore_img2img_task_id')];}",
        inputs=[fields[0][0]],
        outputs=[source],
        queue=False,
        show_progress=False,
    )
    _bound_img2img_source_restore = True


def _controlnet_restore_values(id_task, *, tabname, components):
    with _snapshot_lock:
        snapshot = _submission_snapshots.get(id_task) or {}
        sources = _flatten_controlnet_sources(snapshot)

    results = []
    for index, component in enumerate(components):
        source = sources[index] if index < len(sources) else None
        if source is None:
            results.append(gr.skip())
            continue
        try:
            results.append(_decode_source(source, component))
        except Exception:
            results.append(gr.skip())
    if len(results) == 1:
        return results[0]
    return results


def _try_bind_controlnet_restore(tabname):
    if tabname in _bound_controlnet_restore_tabs:
        return

    button = _restore_buttons.get(tabname)
    components = list(_controlnet_logical_images.get(tabname) or [])
    fields = infotext_utils.paste_fields.get(tabname, {}).get("fields") or []
    if button is None or not components or not fields:
        return

    ext_key = f"forge_gallery_restore_{tabname}_task_id"
    button.click(
        fn=partial(_controlnet_restore_values, tabname=tabname, components=components),
        js=f"function(){{return [localStorage.getItem('{ext_key}')];}}",
        inputs=[fields[0][0]],
        outputs=components,
        queue=False,
        show_progress=False,
    )
    _bound_controlnet_restore_tabs.add(tabname)

def _copy_output(value):
    if isinstance(value, dict):
        copied = value.copy()
        if "value" in copied:
            inner = copied["value"]
            if isinstance(inner, list):
                copied["value"] = list(inner)
            elif isinstance(inner, tuple):
                copied["value"] = tuple(inner)
        return copied

    return value


def _copy_result(result):
    if isinstance(result, tuple):
        return tuple(_copy_output(item) for item in result)
    if isinstance(result, list):
        return [_copy_output(item) for item in result]
    return _copy_output(result)


def _record_results_snapshot(id_task, result):
    return _original_record_results(id_task, _copy_result(result))


def _restore_progress_snapshot(id_task):
    result = _original_restore_progress(id_task)
    result = _copy_result(result)

    if isinstance(result, (tuple, list)) and len(result) == 5:
        return result[0], result[2], result[3], result[4]

    return result


def _remember_submission_snapshot(id_task: str | None, snapshot: dict):
    if not id_task:
        return

    with _snapshot_lock:
        _submission_snapshots[id_task] = snapshot
        if id_task in _submission_snapshot_order:
            _submission_snapshot_order.remove(id_task)
        _submission_snapshot_order.append(id_task)

        while len(_submission_snapshot_order) > _MAX_SUBMISSION_SNAPSHOTS:
            oldest = _submission_snapshot_order.pop(0)
            _submission_snapshots.pop(oldest, None)


def _bound_arguments(func, args, kwargs=None):
    """Bind runtime args to Neo's own named function signature.

    Gradio injects a Request object after the task ID, so no positional offsets
    are used here.
    """
    return inspect.signature(func).bind_partial(*args, **(kwargs or {})).arguments


def _snapshot_txt2img_processing_bound(bound, *, source="txt2img") -> dict:
    return {
        "tabname": "txt2img",
        "source": source,
        "api_values": {
            "prompt": bound.get("prompt"),
            "negative_prompt": bound.get("negative_prompt"),
            "styles": bound.get("prompt_styles"),
            "batch_size": bound.get("batch_size"),
            "cfg_scale": bound.get("cfg_scale"),
            "distilled_cfg_scale": bound.get("distilled_cfg_scale"),
            "height": bound.get("height"),
            "width": bound.get("width"),
            "enable_hr": bound.get("enable_hr"),
            "denoising_strength": bound.get("denoising_strength"),
            "hr_scale": bound.get("hr_scale"),
            "hr_upscaler": bound.get("hr_upscaler"),
            "hr_second_pass_steps": bound.get("hr_second_pass_steps"),
            "hr_resize_x": bound.get("hr_resize_x"),
            "hr_resize_y": bound.get("hr_resize_y"),
            "hr_checkpoint_name": bound.get("hr_checkpoint_name"),
            "hr_additional_modules": bound.get("hr_additional_modules"),
            "hr_sampler_name": bound.get("hr_sampler_name"),
            "hr_scheduler": bound.get("hr_scheduler"),
            "hr_prompt": bound.get("hr_prompt"),
            "hr_negative_prompt": bound.get("hr_negative_prompt"),
            "hr_cfg": bound.get("hr_cfg"),
            "hr_distilled_cfg": bound.get("hr_distilled_cfg"),
        },
    }


def _snapshot_txt2img_args(args, kwargs=None) -> dict:
    bound = _bound_arguments(txt2img_module.txt2img_create_processing, args, kwargs)
    snapshot = _snapshot_txt2img_processing_bound(bound)
    outer = _bound_arguments(_original_txt2img, args, kwargs)
    snapshot["controlnet_units"] = _snapshot_controlnet_units(outer.get("args", ()))
    return snapshot


def _snapshot_txt2img_upscale_args(args) -> dict:
    # txt2img_upscale receives five leading values of its own:
    # id_task, request, gallery, gallery_index, generation_info.
    # Everything after that is the exact normal txt2img processing argument list
    # submitted from the current UI. Bind that tail to txt2img_create_processing
    # so the Hires accordion is snapshotted exactly as it looked at star-click time.
    outer = _bound_arguments(_original_txt2img_upscale, args)
    processing_args = outer.get("args", ())
    processing_bound = _bound_arguments(
        txt2img_module.txt2img_create_processing,
        (outer.get("id_task"), outer.get("request"), *processing_args),
    )
    snapshot = _snapshot_txt2img_processing_bound(processing_bound, source="txt2img_upscale")
    snapshot["gallery_index"] = outer.get("gallery_index")
    inner = _bound_arguments(
        _original_txt2img,
        (outer.get("id_task"), outer.get("request"), *processing_args),
    )
    snapshot["controlnet_units"] = _snapshot_controlnet_units(inner.get("args", ()))
    return snapshot


def _snapshot_img2img_args(args, kwargs=None) -> dict:
    bound = _bound_arguments(img2img_module.img2img_function, args, kwargs)

    snapshot = {
        "tabname": "img2img",
        "api_values": {
            "prompt": bound.get("prompt"),
            "negative_prompt": bound.get("negative_prompt"),
            "styles": bound.get("prompt_styles"),
            "batch_size": bound.get("batch_size"),
            "cfg_scale": bound.get("cfg_scale"),
            "distilled_cfg_scale": bound.get("distilled_cfg_scale"),
            "image_cfg_scale": bound.get("image_cfg_scale"),
            "denoising_strength": bound.get("denoising_strength"),
            "height": bound.get("height"),
            "width": bound.get("width"),
        },
        "controlnet_units": _snapshot_controlnet_units(bound.get("args", ())),
    }

    if bound.get("mode") == 0 and bound.get("init_img") is not None:
        try:
            snapshot["source_png"] = _encode_source(bound.get("init_img"))
        except Exception:
            pass

    return snapshot


@wraps(_original_txt2img)
def _txt2img_with_snapshot(*args, **kwargs):
    id_task = args[0] if args and isinstance(args[0], str) and args[0].startswith("task(") else None
    try:
        _remember_submission_snapshot(id_task, _snapshot_txt2img_args(args, kwargs))
    except Exception:
        pass

    return _original_txt2img(*args, **kwargs)


@wraps(_original_txt2img_upscale)
def _txt2img_upscale_with_snapshot(*args, **kwargs):
    id_task = args[0] if args and isinstance(args[0], str) and args[0].startswith("task(") else None
    try:
        _remember_submission_snapshot(id_task, _snapshot_txt2img_upscale_args(args))
    except Exception:
        pass

    return _original_txt2img_upscale(*args, **kwargs)


@wraps(_original_img2img)
def _img2img_with_snapshot(*args, **kwargs):
    id_task = args[0] if args else kwargs.get("id_task")
    id_task = id_task if isinstance(id_task, str) and id_task.startswith("task(") else None
    try:
        _remember_submission_snapshot(id_task, _snapshot_img2img_args(args, kwargs))
    except Exception:
        pass

    return _original_img2img(*args, **kwargs)


def _extract_infotext_from_generation_info(generation_info):
    if not generation_info:
        return ""

    try:
        parsed = json.loads(generation_info)
        infotexts = parsed.get("infotexts") or []
        if infotexts:
            return infotexts[0] or ""
    except Exception:
        pass

    return ""


def _is_image_bearing_component(component) -> bool:
    """Session restore only replays scalar/config fields.

    Image-bearing extension fields (ControlNet canvases, gr.Image inputs, galleries,
    etc.) are intentionally excluded unless this extension explicitly snapshots them.
    """
    if isinstance(component, (LogicalImage, gr.Image, gr.Gallery)):
        return True

    module_name = component.__class__.__module__.lower()
    class_name = component.__class__.__name__.lower()
    return (
        "forge_canvas" in module_name
        or "image" == class_name
        or "gallery" == class_name
        or "logicalimage" == class_name
    )


def _filter_restore_paste_fields(paste_fields):
    return [
        field
        for field in paste_fields
        if not _is_image_bearing_component(field[0])
    ]


def _build_paste_fields_with_override(tabname: str):
    tab_data = infotext_utils.paste_fields.get(tabname, {})
    paste_fields = list(tab_data.get("fields") or [])
    override_settings_component = tab_data.get("override_settings_component")

    if override_settings_component is not None:
        handled_fields = [key for _, key in paste_fields]

        def paste_settings(params):
            vals = infotext_utils.get_override_settings(params, skip_fields=handled_fields)
            vals_pairs = [f"{infotext_text}: {value}" for infotext_text, _, value in vals]
            return gr.update(value=vals_pairs, choices=vals_pairs, visible=bool(vals_pairs))

        paste_fields = paste_fields + [(override_settings_component, paste_settings)]

    return paste_fields


def _update_for_snapshot_value(value):
    return gr.update(value=value)


def _apply_snapshot_overrides(id_task: str, paste_fields, paste_updates):
    snapshot = _submission_snapshots.get(id_task) or {}
    api_values = snapshot.get("api_values") or {}
    if not api_values:
        return paste_updates

    api_positions = {}
    for index, field in enumerate(paste_fields):
        api_name = getattr(field, "api", None)
        if api_name:
            api_positions[api_name] = index

    for api_name, value in api_values.items():
        index = api_positions.get(api_name)
        if index is None:
            continue
        paste_updates[index] = _update_for_snapshot_value(value)

    return paste_updates


def _restore_params_only(id_task: str, *, tabname: str):
    # Neo's stock Restore Progress event handles gallery/generation-info/infotext/log.
    # This second handler only restores the UI controls and optional img2img source.
    _gallery, generation_info, _infotext, _html_log = progress.restore_progress(id_task)

    raw_infotext = _extract_infotext_from_generation_info(generation_info)
    params = infotext_utils.parse_generation_parameters(raw_infotext)
    script_callbacks.infotext_pasted_callback(raw_infotext, params)

    paste_fields = _filter_restore_paste_fields(_build_paste_fields_with_override(tabname))
    paste_updates = [infotext_utils._parse_info(output, key, params) for output, key in paste_fields]
    paste_updates = _apply_snapshot_overrides(id_task, paste_fields, paste_updates)

    return [*paste_updates]


def _try_bind_restore_action(tabname: str):
    if tabname in _bound_restore_tabs:
        return

    button = _restore_buttons.get(tabname)
    tab_data = infotext_utils.paste_fields.get(tabname)
    if button is None or not tab_data:
        return

    paste_fields = _filter_restore_paste_fields(_build_paste_fields_with_override(tabname))
    if not paste_fields:
        return

    outputs = [component for component, _ in paste_fields]

    # Any existing component can be the placeholder input because this JS replaces
    # its value with Forge's current task ID before the Python callback runs.
    placeholder_input = paste_fields[0][0]
    task_key = f"{tabname}_task_id"

    button.click(
        fn=partial(_restore_params_only, tabname=tabname),
        _js=f"function(){{ return [localGet('{task_key}')]; }}",
        inputs=[placeholder_input],
        outputs=outputs,
        show_progress=False,
    ).then(fn=None, js=f"recalculate_prompts_{tabname}")

    _bound_restore_tabs.add(tabname)


def _create_tools_row_with_restore_capture(self):
    result = _original_create_tools_row(self)

    tabname = getattr(self, "id_part", None)
    if tabname in {"txt2img", "img2img"} and self.restore_progress_button is not None:
        _restore_buttons[tabname] = self.restore_progress_button
        _try_bind_restore_action(tabname)
        if tabname == "img2img":
            _try_bind_img2img_source_restore()
        _try_bind_controlnet_restore(tabname)

    return result


def _add_paste_fields_and_bind(tabname: str, init_img, fields, override_settings_component=None):
    result = _original_add_paste_fields(tabname, init_img, fields, override_settings_component)

    if tabname in {"txt2img", "img2img"}:
        _try_bind_restore_action(tabname)
        if tabname == "img2img":
            _try_bind_img2img_source_restore()
        _try_bind_controlnet_restore(tabname)

    return result


script_callbacks.on_after_component(_capture_controlnet_component)

if not getattr(progress.record_results, "_gallery_restore_snapshot_fix", False):
    _record_results_snapshot._gallery_restore_snapshot_fix = True
    progress.record_results = _record_results_snapshot

if not getattr(progress.restore_progress, "_gallery_restore_snapshot_fix", False):
    _restore_progress_snapshot._gallery_restore_snapshot_fix = True
    progress.restore_progress = _restore_progress_snapshot

if not getattr(infotext_utils.add_paste_fields, "_gallery_restore_snapshot_fix", False):
    _add_paste_fields_and_bind._gallery_restore_snapshot_fix = True
    infotext_utils.add_paste_fields = _add_paste_fields_and_bind

if not getattr(ui_toprow.Toprow.create_tools_row, "_gallery_restore_snapshot_fix", False):
    _create_tools_row_with_restore_capture._gallery_restore_snapshot_fix = True
    ui_toprow.Toprow.create_tools_row = _create_tools_row_with_restore_capture

if not getattr(txt2img_module.txt2img, "_gallery_restore_snapshot_fix", False):
    _txt2img_with_snapshot._gallery_restore_snapshot_fix = True
    txt2img_module.txt2img = _txt2img_with_snapshot

if not getattr(txt2img_module.txt2img_upscale, "_gallery_restore_snapshot_fix", False):
    _txt2img_upscale_with_snapshot._gallery_restore_snapshot_fix = True
    txt2img_module.txt2img_upscale = _txt2img_upscale_with_snapshot

if not getattr(img2img_module.img2img, "_gallery_restore_snapshot_fix", False):
    _img2img_with_snapshot._gallery_restore_snapshot_fix = True
    img2img_module.img2img = _img2img_with_snapshot
