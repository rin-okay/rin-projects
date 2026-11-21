from __future__ import annotations

import json
import logging
import sys
import threading
import types
from contextlib import closing
from typing import Any

import gradio as gr
from PIL import Image

import modules.scripts as scripts
import modules.shared as shared
from modules import (
    devices,
    images,
    infotext_utils,
    processing,
    script_callbacks,
    sd_samplers,
    sd_schedulers,
)
from modules.infotext_utils import parse_generation_parameters
from modules.ui import plaintext_to_html
from modules.ui_components import ToolButton
from modules.call_queue import wrap_gradio_gpu_call
from modules_forge import main_thread

from img2img_hires_fix_core import (
    HIRES_SETTING_FIELDS,
    HiresSettingsError,
    SOURCE_DENOISE_METADATA_KEY,
    extract_exact_prompt_negative,
    merge_hires_infotext,
    normalize_hires_settings,
)


LOGGER = logging.getLogger("img2img-hires-fix")
_COMPONENTS: dict[str, Any] = {}
_MANUAL_WIRED = False
_LOCAL = threading.local()
_STATE_CACHE: dict[tuple[str, str, str], dict[str, Any]] = {}
_STATE_CACHE_ORDER: list[tuple[str, str, str]] = []
_STATE_CACHE_LOCK = threading.RLock()
_STATE_CACHE_LIMIT = 64


_HIRES_OVERRIDE_API_NAME = "img2img_hires_fix_api"
_api_module = sys.modules.get(_HIRES_OVERRIDE_API_NAME)
if _api_module is None:
    _api_module = types.ModuleType(_HIRES_OVERRIDE_API_NAME)
    sys.modules[_HIRES_OVERRIDE_API_NAME] = _api_module
existing_overrides = getattr(_api_module, "settings_overrides", ())
if not isinstance(existing_overrides, list):
    try:
        _api_module.settings_overrides = list(existing_overrides or ())
    except TypeError:
        # A stale or foreign module may have published a non-iterable value.
        # Start clean instead of making the whole extension fail to import.
        _api_module.settings_overrides = []
_API_LOCK = threading.RLock()


def register_hires_settings_override(callback) -> None:
    """Register callback(context, current_settings) -> override dict | None."""
    if not callable(callback):
        raise TypeError("hires settings override must be callable")
    with _API_LOCK:
        if callback not in _api_module.settings_overrides:
            _api_module.settings_overrides.append(callback)


def unregister_hires_settings_override(callback) -> None:
    with _API_LOCK:
        try:
            _api_module.settings_overrides.remove(callback)
        except ValueError:
            pass


def _available_schedulers() -> list[str]:
    return [
        str(item.label)
        for item in sd_schedulers.schedulers
        if getattr(item, "label", None)
    ]


def _normalize_hires_settings(settings: dict[str, Any]) -> dict[str, Any]:
    return normalize_hires_settings(
        settings,
        available_upscalers=_all_upscalers(),
        available_samplers=sd_samplers.visible_sampler_names(),
        available_schedulers=_available_schedulers(),
    )


def resolve_hires_settings(context: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
    """Apply registered overrides to a copy of current hires settings."""
    resolved = _normalize_hires_settings(dict(settings))
    with _API_LOCK:
        callbacks = tuple(_api_module.settings_overrides)

    for callback in callbacks:
        try:
            override = callback(dict(context), dict(resolved))
        except Exception as exc:
            LOGGER.warning("Settings override %r failed: %s", callback, exc)
            continue
        if override is None:
            continue
        if not isinstance(override, dict):
            LOGGER.warning("Settings override %r returned a non-dict; ignored", callback)
            continue

        unknown = set(override).difference(HIRES_SETTING_FIELDS)
        if unknown:
            LOGGER.warning(
                "Settings override %r returned unsupported fields (ignored): %s",
                callback,
                ", ".join(sorted(unknown)),
            )

        candidate = dict(resolved)
        candidate.update(
            {key: value for key, value in override.items() if key in HIRES_SETTING_FIELDS}
        )
        try:
            resolved = _normalize_hires_settings(candidate)
        except HiresSettingsError as exc:
            LOGGER.warning("Invalid settings override from %r ignored: %s", callback, exc)
    return resolved


_api_module.API_VERSION = 2
_api_module.register_hires_settings_override = register_hires_settings_override
_api_module.unregister_hires_settings_override = unregister_hires_settings_override
_api_module.resolve_hires_settings = resolve_hires_settings
_api_module.HIRES_SETTING_FIELDS = HIRES_SETTING_FIELDS


def _unload_override_api() -> None:
    with _API_LOCK:
        _api_module.settings_overrides.clear()
    if sys.modules.get(_HIRES_OVERRIDE_API_NAME) is _api_module:
        sys.modules.pop(_HIRES_OVERRIDE_API_NAME, None)


script_callbacks.on_script_unloaded(
    _unload_override_api,
    name="img2img-hires-fix/override-api-cleanup",
)


def _current_hires_settings(
    denoising_strength, hr_scale, hr_upscaler, hr_second_pass_steps,
    hr_resize_x, hr_resize_y, hr_sampler_name, hr_scheduler,
    hr_prompt, hr_negative_prompt, hr_cfg, hr_distilled_cfg,
) -> dict[str, Any]:
    return {
        "denoising_strength": denoising_strength,
        "hr_scale": hr_scale,
        "hr_upscaler": hr_upscaler,
        "hr_second_pass_steps": hr_second_pass_steps or 0,
        "hr_resize_x": hr_resize_x or 0,
        "hr_resize_y": hr_resize_y or 0,
        "hr_sampler_name": hr_sampler_name,
        "hr_scheduler": hr_scheduler,
        "hr_prompt": hr_prompt or "",
        "hr_negative_prompt": hr_negative_prompt or "",
        "hr_cfg": hr_cfg,
        "hr_distilled_cfg": hr_distilled_cfg,
    }


def _active() -> bool:
    return bool(getattr(_LOCAL, "active", False))


def _latent_upscalers() -> list[str]:
    modes = getattr(shared, "latent_upscale_modes", {})
    return list(modes.keys()) if hasattr(modes, "keys") else list(modes)


def _pixel_upscalers() -> list[str]:
    names: list[str] = []
    for item in getattr(shared, "sd_upscalers", []) or []:
        name = getattr(item, "name", None)
        if name and name not in names:
            names.append(name)
    return names


def _all_upscalers() -> list[str]:
    # Match txt2img Hires. fix: latent interpolation modes first, followed by
    # every loaded pixel-space upscaler supplied by Forge and extensions.
    choices: list[str] = []
    for name in [*_latent_upscalers(), *_pixel_upscalers()]:
        if name and name not in choices:
            choices.append(name)
    return choices


def _default_upscaler() -> str:
    choices = _all_upscalers()
    latent_default = getattr(shared, "latent_upscale_default_mode", None)
    if latent_default in choices:
        return latent_default
    return choices[0] if choices else "Latent"


def _clean_choice(value: str | None, same_label: str) -> str | None:
    return None if not value or value == same_label else value


def _as_image(value: Any) -> Image.Image:
    image = infotext_utils.image_from_url_text(value)
    if not isinstance(image, Image.Image):
        raise ValueError("The selected gallery entry is not an image.")
    return image.convert("RGB")


def _source_parameters(
    generation_info: str, index: int
) -> tuple[dict[str, Any], list[str], int, dict[str, Any]]:
    try:
        decoded = json.loads(generation_info or "{}")
    except Exception:
        decoded = {}
    info = decoded if isinstance(decoded, dict) else {}

    infotexts_value = info.get("infotexts") or []
    infotexts = infotexts_value if isinstance(infotexts_value, list) else []
    try:
        first = int(info.get("index_of_first_image", 0) or 0)
    except (TypeError, ValueError):
        first = 0
    if index < first or index >= len(infotexts):
        raise ValueError("Select a generated image rather than a grid or control image.")

    params = parse_generation_parameters(infotexts[index] or "", [])
    return params, infotexts, first, info


def _extract_exact_prompt_negative(infotext: str) -> tuple[str, str]:
    return extract_exact_prompt_negative(infotext)


def _parsed_prompt_pair(infotext: str) -> tuple[str, str]:
    prompt, negative = _extract_exact_prompt_negative(infotext)
    if prompt or negative:
        return prompt, negative

    try:
        parsed = parse_generation_parameters(infotext or "", [])
    except Exception:
        parsed = {}
    return str(parsed.get("Prompt", "") or ""), str(parsed.get("Negative prompt", "") or "")


def _merge_hires_infotext(source_infotext: str, hires_infotext: str, final_image: Image.Image | None = None) -> str:
    final_size = (
        f"{final_image.width}x{final_image.height}" if final_image is not None else None
    )
    return merge_hires_infotext(
        source_infotext or "",
        hires_infotext or "",
        final_size=final_size,
    )


def _state_cache_key(
    infotext: str, *, user: str | None = None, job_timestamp: str | None = None
) -> tuple[str, str, str]:
    return str(user or ""), str(job_timestamp or ""), infotext


def _remember_state(
    infotext: str,
    state: dict[str, Any],
    *,
    user: str | None = None,
    job_timestamp: str | None = None,
) -> None:
    """Cache only immutable/small values. Never retain Forge model objects."""
    if not infotext:
        return

    safe: dict[str, Any] = {}
    for key, value in state.items():
        if isinstance(value, (str, int, float, bool, type(None))):
            safe[key] = value
        elif isinstance(value, (list, tuple)) and all(
            isinstance(item, (str, int, float, bool, type(None))) for item in value
        ):
            safe[key] = list(value)

    key = _state_cache_key(
        infotext, user=user, job_timestamp=job_timestamp
    )
    with _STATE_CACHE_LOCK:
        _STATE_CACHE[key] = safe
        if key in _STATE_CACHE_ORDER:
            _STATE_CACHE_ORDER.remove(key)
        _STATE_CACHE_ORDER.append(key)

        while len(_STATE_CACHE_ORDER) > _STATE_CACHE_LIMIT:
            old = _STATE_CACHE_ORDER.pop(0)
            _STATE_CACHE.pop(old, None)


def _recall_state(
    infotext: str, *, user: str | None = None, job_timestamp: str | None = None
) -> dict[str, Any]:
    key = _state_cache_key(
        infotext, user=user, job_timestamp=job_timestamp
    )
    with _STATE_CACHE_LOCK:
        return dict(_STATE_CACHE.get(key) or {})


def _cache_generation_state(p, processed) -> list[dict[str, Any]]:
    """Capture prompt/seed/sampler data without cloning runtime model state."""
    first = int(getattr(processed, "index_of_first_image", 0) or 0)
    count = min(len(getattr(processed, "images", []) or []), len(getattr(processed, "infotexts", []) or []))
    entries: list[dict[str, Any]] = []

    all_prompts = list(getattr(p, "all_prompts", []) or [])
    all_negative = list(getattr(p, "all_negative_prompts", []) or [])
    all_seeds = list(getattr(p, "all_seeds", []) or [])
    all_subseeds = list(getattr(p, "all_subseeds", []) or [])
    user = getattr(p, "user", None)
    # Processed owns the timestamp exported in generation_info.js(); the
    # processing object itself does not. Keying from p here made every normal
    # cache entry use an empty timestamp, so the later gallery lookup (which
    # uses Processed.job_timestamp) could never hit.
    job_timestamp = getattr(processed, "job_timestamp", None)

    for index in range(first, count):
        item = index - first
        infotext = processed.infotexts[index] or ""
        parsed_prompt, parsed_negative = _parsed_prompt_pair(infotext)
        state = {
            # Preserve the exact prompt text written into the source image's
            # infotext so LoRA tags and other prompt-side networks survive in
            # both metadata and any later hires reruns.
            "prompt": parsed_prompt or (all_prompts[item] if item < len(all_prompts) else getattr(p, "prompt", "")),
            "negative_prompt": parsed_negative or (all_negative[item] if item < len(all_negative) else getattr(p, "negative_prompt", "")),
            "seed": all_seeds[item] if item < len(all_seeds) else getattr(p, "seed", -1),
            "subseed": all_subseeds[item] if item < len(all_subseeds) else getattr(p, "subseed", -1),
            "steps": getattr(p, "steps", 20),
            "sampler_name": getattr(p, "sampler_name", None),
            "scheduler": getattr(p, "scheduler", None),
            "cfg_scale": getattr(p, "cfg_scale", 7.0),
            "distilled_cfg_scale": getattr(p, "distilled_cfg_scale", 3.5),
            "subseed_strength": getattr(p, "subseed_strength", 0.0),
            "seed_resize_from_h": getattr(p, "seed_resize_from_h", 0),
            "seed_resize_from_w": getattr(p, "seed_resize_from_w", 0),
            "token_merging_ratio": getattr(p, "token_merging_ratio", 0),
            "token_merging_ratio_hr": getattr(p, "token_merging_ratio_hr", 0),
            "disable_extra_networks": bool(getattr(p, "disable_extra_networks", False)),
            "gallery_index": index,
            "infotext": infotext,
        }
        entries.append(state)
        _remember_state(
            state["infotext"],
            state,
            user=user,
            job_timestamp=job_timestamp,
        )

    return entries


def _make_hires_processing(
    source: Image.Image,
    *,
    prompt: str,
    negative_prompt: str,
    styles: list[str] | None,
    seed: int,
    subseed: int,
    steps: int,
    sampler_name: str | None,
    scheduler: str | None,
    cfg_scale: float,
    distilled_cfg_scale: float,
    denoising_strength: float,
    hr_scale: float,
    hr_upscaler: str,
    hr_second_pass_steps: int,
    hr_resize_x: int,
    hr_resize_y: int,
    hr_sampler_name: str | None,
    hr_scheduler: str | None,
    hr_prompt: str,
    hr_negative_prompt: str,
    hr_cfg: float,
    hr_distilled_cfg: float,
    subseed_strength: float = 0.0,
    seed_resize_from_h: int = 0,
    seed_resize_from_w: int = 0,
    token_merging_ratio: float = 0.0,
    token_merging_ratio_hr: float = 0.0,
    disable_extra_networks: bool = False,
    user: str | None = None,
) -> processing.StableDiffusionProcessingTxt2Img:
    base_steps = max(1, int(steps or 20))
    # Pass the configured Hires steps through unchanged. Forge's native
    # sample_img2img path applies denoising strength internally. Pre-dividing
    # by denoise here caused 22 steps at 0.35 to become 62 before Forge handled
    # the denoising window.
    configured_hr_steps = max(0, int(hr_second_pass_steps or 0))

    p = processing.StableDiffusionProcessingTxt2Img(
        outpath_samples=shared.opts.outdir_samples or shared.opts.outdir_img2img_samples,
        outpath_grids=shared.opts.outdir_grids or shared.opts.outdir_img2img_grids,
        prompt=prompt or "",
        negative_prompt=negative_prompt or "",
        styles=styles or [],
        seed=seed,
        subseed=subseed,
        batch_size=1,
        n_iter=1,
        steps=base_steps,
        sampler_name=sampler_name,
        scheduler=scheduler,
        cfg_scale=float(cfg_scale or 7.0),
        distilled_cfg_scale=float(distilled_cfg_scale or 3.5),
        width=source.width,
        height=source.height,
        enable_hr=True,
        denoising_strength=float(denoising_strength),
        hr_scale=float(hr_scale),
        hr_upscaler=hr_upscaler,
        hr_second_pass_steps=configured_hr_steps,
        hr_resize_x=int(hr_resize_x or 0),
        hr_resize_y=int(hr_resize_y or 0),
        hr_sampler_name=hr_sampler_name,
        hr_scheduler=hr_scheduler,
        hr_prompt=hr_prompt or "",
        hr_negative_prompt=hr_negative_prompt or "",
        hr_cfg=float(hr_cfg),
        hr_distilled_cfg=float(hr_distilled_cfg),
        override_settings={},
    )
    p.firstpass_image = source
    p.txt2img_upscale = True
    # The generated file is saved once, after source and Hires metadata have
    # been merged. Letting process_images() save here would write an earlier,
    # incomplete metadata record and then require an unsafe overwrite.
    p.do_not_save_samples = True
    p.do_not_save_grid = True
    p.user = user
    p.subseed_strength = float(subseed_strength or 0.0)
    p.seed_resize_from_h = int(seed_resize_from_h or 0)
    p.seed_resize_from_w = int(seed_resize_from_w or 0)
    p.token_merging_ratio = float(token_merging_ratio or 0.0)
    p.token_merging_ratio_hr = float(token_merging_ratio_hr or 0.0)
    p.disable_extra_networks = bool(disable_extra_networks)

    # Forge Neo expects this hires-only field to always be iterable. The native
    # txt2img UI uses the sentinel below when no separate second-pass module
    # selection was made.
    p.hr_additional_modules = ["Use same choices"]
    # This is a standalone hires pass. Use a fresh empty ScriptRunner rather
    # than the populated global txt2img runner. This keeps selectable and
    # always-on scripts disabled, while still letting Forge follow its native
    # post-batch lifecycle. In particular, Forge restores p.prompts from
    # p.all_prompts before writing infotext only when p.scripts is not None.
    # That restoration is what preserves <lora:...> and other extra-network
    # tags in PNG Info / Send-to metadata.
    p.scripts = scripts.ScriptRunner()
    p.script_args = ()
    # Re-encoding an already-finished image with TAESD or another approximate
    # VAE encoder can lift blacks, flatten contrast, and shift colour. Native
    # hires fix inherits the global encoder preference, but a gallery enhance
    # operation should preserve the selected image as closely as possible.
    p.override_settings["sd_vae_encode_method"] = "Full"
    p.override_settings["save_images_before_highres_fix"] = False
    p.extra_generation_params["Hires source"] = "img2img output"
    p.extra_generation_params["Original Size"] = f"{source.width}x{source.height}"
    p.extra_generation_params["Img2img hires enabled"] = True
    p.extra_generation_params["Img2img hires denoising strength"] = float(denoising_strength)
    p.extra_generation_params["Img2img hires upscale by"] = float(hr_scale)
    p.extra_generation_params["Img2img hires upscaler"] = hr_upscaler
    p.extra_generation_params["Img2img hires steps"] = int(configured_hr_steps)
    p.extra_generation_params["Img2img hires resize width"] = int(hr_resize_x or 0)
    p.extra_generation_params["Img2img hires resize height"] = int(hr_resize_y or 0)
    p.extra_generation_params["Img2img hires sampler"] = hr_sampler_name or "Use same sampler"
    p.extra_generation_params["Img2img hires schedule type"] = hr_scheduler or "Use same scheduler"
    p.extra_generation_params["Img2img hires CFG scale"] = float(hr_cfg)
    p.extra_generation_params["Img2img hires Distilled CFG scale"] = float(hr_distilled_cfg)
    p.extra_generation_params["Img2img hires prompt"] = hr_prompt or ""
    p.extra_generation_params["Img2img hires negative prompt"] = hr_negative_prompt or ""
    return p


def _should_save_hires_output() -> bool:
    return bool(
        shared.opts.samples_save
        and (
            shared.opts.save_incomplete_images
            or not shared.state.interrupted
            and not shared.state.skipped
        )
    )


def _finalize_hires_result(
    p: processing.StableDiffusionProcessingTxt2Img,
    result,
    source_infotext: str,
):
    """Merge metadata before the only disk save and update gallery PNG info."""
    first = int(getattr(result, "index_of_first_image", 0) or 0)
    merged_infotexts = list(getattr(result, "infotexts", []) or [])
    result_images = list(getattr(result, "images", []) or [])
    all_seeds = list(getattr(p, "all_seeds", []) or [])
    all_prompts = list(getattr(p, "all_prompts", []) or [])
    should_save = _should_save_hires_output()

    for gallery_index in range(first, len(result_images)):
        image = result_images[gallery_index]
        if not isinstance(image, Image.Image):
            continue

        generated_text = (
            merged_infotexts[gallery_index]
            if gallery_index < len(merged_infotexts)
            else ""
        )
        merged_text = _merge_hires_infotext(source_infotext, generated_text, image)

        if gallery_index < len(merged_infotexts):
            merged_infotexts[gallery_index] = merged_text
        else:
            merged_infotexts.extend(
                [""] * (gallery_index - len(merged_infotexts)) + [merged_text]
            )

        if shared.opts.enable_pnginfo:
            image.info["parameters"] = merged_text

        if should_save:
            item = gallery_index - first
            seed = all_seeds[item] if item < len(all_seeds) else getattr(p, "seed", -1)
            prompt = (
                all_prompts[item]
                if item < len(all_prompts)
                else getattr(p, "prompt", "")
            )
            images.save_image(
                image,
                p.outpath_samples,
                "",
                seed=seed,
                prompt=prompt,
                extension=shared.opts.samples_format,
                info=merged_text,
                p=p,
            )

    result.infotexts = merged_infotexts
    if merged_infotexts:
        result.info = merged_infotexts[first] if first < len(merged_infotexts) else merged_infotexts[0]
    return result


def _run_hires(
    p: processing.StableDiffusionProcessingTxt2Img, source_infotext: str
):
    was_active = _active()
    _LOCAL.active = True
    try:
        with closing(p):
            result = processing.process_images(p)
            if shared.state.interrupted or shared.state.skipped:
                # Native Hires can return the source or a partial image on cancel.
                # Do not save or label that output as a completed enhancement.
                result.images = []
                result.infotexts = []
                return result
            return _finalize_hires_result(p, result, source_infotext)
    finally:
        _LOCAL.active = was_active
        devices.torch_gc()


def _manual_enhance_impl(
    request: gr.Request,
    gallery,
    gallery_index,
    generation_info,
    denoising_strength,
    hr_scale,
    hr_upscaler,
    hr_second_pass_steps,
    hr_resize_x,
    hr_resize_y,
    hr_sampler_name,
    hr_scheduler,
    hr_prompt,
    hr_negative_prompt,
    hr_cfg,
    hr_distilled_cfg,
    replace_selected,
):
    if not gallery:
        raise gr.Error("There is no img2img result to enhance.")

    index = int(gallery_index)
    if index < 0 or index >= len(gallery):
        raise gr.Error(f"Invalid gallery index: {index}")

    params, infotexts, first, info = _source_parameters(generation_info, index)
    source = _as_image(gallery[index])

    selected_infotext = infotexts[index] if index < len(infotexts) else ""
    cache_user = getattr(request, "username", None)
    cache_job = str(info.get("job_timestamp", "") or "")
    state = _recall_state(
        selected_infotext,
        user=cache_user,
        job_timestamp=cache_job,
    )

    prompt = state.get("prompt", params.get("Prompt", ""))
    negative_prompt = state.get("negative_prompt", params.get("Negative prompt", ""))
    seed = int(state.get("seed", params.get("Seed", -1)))
    subseed = int(state.get("subseed", params.get("Variation seed", -1)))
    steps = int(state.get("steps", params.get("Steps", hr_second_pass_steps or 20)))
    sampler = state.get("sampler_name", params.get("Sampler"))
    scheduler = state.get("scheduler", params.get("Schedule type") or params.get("Scheduler"))
    cfg = float(state.get("cfg_scale", params.get("CFG scale", 7.0)))
    distilled_cfg = float(state.get("distilled_cfg_scale", params.get("Distilled CFG Scale", 3.5)))

    source_infotext = selected_infotext or (infotexts[index] if index < len(infotexts) else "")
    hires_settings = resolve_hires_settings(
        {
            "mode": "manual",
            "processing": None,
            "prompt": prompt or "",
            "source_infotext": source_infotext,
        },
        _current_hires_settings(
            denoising_strength, hr_scale, hr_upscaler, hr_second_pass_steps,
            hr_resize_x, hr_resize_y, hr_sampler_name, hr_scheduler,
            hr_prompt, hr_negative_prompt, hr_cfg, hr_distilled_cfg,
        ),
    )

    p = _make_hires_processing(
        source,
        prompt=prompt,
        negative_prompt=negative_prompt,
        styles=[],
        seed=seed,
        subseed=subseed,
        steps=steps,
        sampler_name=sampler,
        scheduler=scheduler,
        cfg_scale=cfg,
        distilled_cfg_scale=distilled_cfg,
        denoising_strength=hires_settings["denoising_strength"],
        hr_scale=hires_settings["hr_scale"],
        hr_upscaler=hires_settings["hr_upscaler"],
        hr_second_pass_steps=hires_settings["hr_second_pass_steps"],
        hr_resize_x=hires_settings["hr_resize_x"],
        hr_resize_y=hires_settings["hr_resize_y"],
        hr_sampler_name=_clean_choice(hires_settings["hr_sampler_name"], "Use same sampler"),
        hr_scheduler=_clean_choice(hires_settings["hr_scheduler"], "Use same scheduler"),
        hr_prompt=hires_settings["hr_prompt"],
        hr_negative_prompt=hires_settings["hr_negative_prompt"],
        hr_cfg=hires_settings["hr_cfg"],
        hr_distilled_cfg=hires_settings["hr_distilled_cfg"],
        subseed_strength=float(state.get("subseed_strength", 0.0)),
        seed_resize_from_h=int(state.get("seed_resize_from_h", 0)),
        seed_resize_from_w=int(state.get("seed_resize_from_w", 0)),
        token_merging_ratio=float(state.get("token_merging_ratio", 0.0)),
        token_merging_ratio_hr=float(state.get("token_merging_ratio_hr", 0.0)),
        disable_extra_networks=bool(state.get("disable_extra_networks", False)),
        user=getattr(request, "username", None),
    )
    try:
        result = _run_hires(p, source_infotext)
    finally:
        # Match Forge's native gallery-Hires cleanup even when model loading,
        # sampling, metadata callbacks, or saving fails.
        shared.total_tqdm.clear()

    generated = list(result.images)
    generated_info = list(result.infotexts)
    if not generated:
        message = "Hires enhancement stopped before an image was produced."
        return (
            gr.update(value=gallery, selected_index=index),
            generation_info,
            plaintext_to_html(selected_infotext or message),
            plaintext_to_html(message, classname="comments"),
        )

    new_gallery = list(gallery)
    new_infotexts = list(infotexts)

    if replace_selected:
        new_gallery[index:index + 1] = generated
        new_infotexts[index:index + 1] = generated_info
        selected = index
    else:
        insert_at = index + 1
        new_gallery[insert_at:insert_at] = generated
        new_infotexts[insert_at:insert_at] = generated_info
        selected = insert_at

    info["infotexts"] = new_infotexts
    info["index_of_first_image"] = first

    # Keep Processed.js parallel arrays aligned with manual insert/replace so
    # follow-on extensions do not read a prompt or seed from the wrong image.
    data_index = index - first
    generated_count = len(generated)
    parallel_values = {
        "all_prompts": [prompt] * generated_count,
        "all_negative_prompts": [negative_prompt] * generated_count,
        "all_seeds": [seed] * generated_count,
        "all_subseeds": [subseed] * generated_count,
    }
    for key, values in parallel_values.items():
        existing = info.get(key)
        if not isinstance(existing, list) or data_index < 0:
            continue
        if replace_selected:
            existing[data_index : data_index + 1] = values
        else:
            existing[data_index + 1 : data_index + 1] = values

    if generated_info:
        source_prompt_exact, source_negative_exact = _parsed_prompt_pair(source_infotext)
        generated_state = {
            "prompt": source_prompt_exact or prompt,
            "negative_prompt": source_negative_exact or negative_prompt,
            "seed": seed,
            "subseed": subseed,
            "steps": steps,
            "sampler_name": sampler,
            "scheduler": scheduler,
            "cfg_scale": cfg,
            "distilled_cfg_scale": distilled_cfg,
            "subseed_strength": float(state.get("subseed_strength", 0.0)),
            "seed_resize_from_h": int(state.get("seed_resize_from_h", 0)),
            "seed_resize_from_w": int(state.get("seed_resize_from_w", 0)),
            "token_merging_ratio": float(state.get("token_merging_ratio", 0.0)),
            "token_merging_ratio_hr": float(state.get("token_merging_ratio_hr", 0.0)),
            "disable_extra_networks": bool(state.get("disable_extra_networks", False)),
        }
        for generated_text in generated_info:
            _remember_state(
                generated_text,
                generated_state,
                user=cache_user,
                job_timestamp=cache_job,
            )

    comments = result.comments
    if isinstance(comments, dict):
        comments = "\n".join(f"{key}: {value}" for key, value in comments.items())
    elif comments is None:
        comments = ""
    elif not isinstance(comments, str):
        comments = str(comments)

    return (
        gr.update(value=new_gallery, selected_index=selected),
        json.dumps(info),
        plaintext_to_html(generated_info[0] if generated_info else "Hires pass complete."),
        plaintext_to_html(comments, classname="comments"),
    )


def _manual_enhance(id_task: str, request: gr.Request, *args):
    # id_task is consumed by wrap_gradio_gpu_call to register progress. The
    # actual Forge processing must still execute on Forge's main thread.
    result = main_thread.run_and_wait_result(_manual_enhance_impl, request, *args)
    if result is not None:
        return result

    # Forge's main-thread worker reports processing exceptions to the console
    # and can return None. Gradio still requires one value for every declared
    # output, so preserve the current gallery/state and show a useful message.
    gallery = args[0] if len(args) > 0 else []
    generation_info = args[2] if len(args) > 2 else "{}"
    reason = getattr(main_thread, "last_exception", None)
    message = (
        f"Hires enhancement failed: {reason}"
        if reason
        else "Hires enhancement failed. Check the Forge console for the original error."
    )
    return (
        gr.update(value=gallery),
        generation_info,
        plaintext_to_html(message),
        plaintext_to_html(message, classname="comments"),
    )


def _try_wire_manual() -> None:
    global _MANUAL_WIRED
    if _MANUAL_WIRED:
        return

    needed = {
        "button", "gallery", "generation_info", "infotext", "html_log",
        "denoise", "scale", "upscaler", "steps", "resize_x", "resize_y",
        "sampler", "scheduler", "hr_prompt", "hr_negative", "hr_cfg",
        "hr_distilled_cfg", "replace", "task_id",
    }
    if not needed.issubset(_COMPONENTS):
        return

    c = _COMPONENTS
    event = c["button"].click(
        fn=wrap_gradio_gpu_call(
            _manual_enhance,
            extra_outputs=[None, "", ""],
        ),
        _js="i2iHiresPrepare",
        inputs=[
            c["task_id"],
            c["gallery"],
            c["button"],  # JavaScript replaces this placeholder with selected index.
            c["generation_info"],
            c["denoise"], c["scale"], c["upscaler"], c["steps"],
            c["resize_x"], c["resize_y"], c["sampler"], c["scheduler"],
            c["hr_prompt"], c["hr_negative"], c["hr_cfg"],
            c["hr_distilled_cfg"], c["replace"],
        ],
        outputs=[c["gallery"], c["generation_info"], c["infotext"], c["html_log"]],
        show_progress=False,
    )
    event.then(fn=None, js="i2iHiresFinish", show_progress=False)
    _MANUAL_WIRED = True


def _capture_component(component, **kwargs):
    elem_id = kwargs.get("elem_id") or getattr(component, "elem_id", None)
    mapping = {
        "img2img_denoising_strength": "source_denoise",
        "img2img_gallery": "gallery",
        "generation_info_img2img": "generation_info",
        "html_info_img2img": "infotext",
        "html_log_img2img": "html_log",
    }
    key = mapping.get(elem_id)
    if key:
        _COMPONENTS[key] = component
        _try_wire_manual()


script_callbacks.on_after_component(_capture_component, name="img2img-hires-fix/component-capture")


def _source_denoise_from_metadata(params):
    return params.get(SOURCE_DENOISE_METADATA_KEY, params.get("Denoising strength"))


def _wire_source_denoise_paste():
    # Run after all native components exist, before Forge connects paste events.
    # Replace the native field; duplicate Gradio outputs are not reliable.
    for tabname in ("img2img", "inpaint"):
        fields = infotext_utils.paste_fields.get(tabname, {}).get("fields", [])
        for index, field in enumerate(fields):
            component, key = field
            if (getattr(component, "elem_id", None) == "img2img_denoising_strength"
                    and key == "Denoising strength"):
                fields[index] = infotext_utils.PasteField(
                    component, _source_denoise_from_metadata,
                    api=getattr(field, "api", None),
                )
    return []


script_callbacks.on_ui_tabs(_wire_source_denoise_paste, name="img2img-hires-fix/source-denoise-paste")


class Img2ImgHiresFix(scripts.Script):
    section = "accordions"
    sorting_priority = 20

    def title(self):
        return "Img2img Hires Fix"

    def show(self, is_img2img):
        return scripts.AlwaysVisible if is_img2img else False

    def ui(self, is_img2img):
        with gr.Accordion("Hires. fix", open=False, elem_id="img2img_hires_fix_extension"):
            enable = gr.Checkbox(
                label="Run hires pass automatically after img2img",
                value=False,
                elem_id="img2img_hires_fix_enable",
            )
            with gr.Row():
                upscaler = gr.Dropdown(
                    label="Upscaler",
                    choices=_all_upscalers(),
                    value=_default_upscaler(),
                    elem_id="img2img_hires_fix_upscaler",
                )
                steps = gr.Slider(0, 150, value=25, step=1, label="Hires steps", elem_id="img2img_hires_fix_steps")
                denoise = gr.Slider(0.0, 1.0, value=0.35, step=0.01, label="Denoising strength", elem_id="img2img_hires_fix_denoise")
            with gr.Row():
                scale = gr.Slider(1.0, 4.0, value=1.5, step=0.05, label="Upscale by", elem_id="img2img_hires_fix_scale")
                resize_x = gr.Slider(0, 4096, value=0, step=8, label="Resize width to", elem_id="img2img_hires_fix_resize_x")
                resize_y = gr.Slider(0, 4096, value=0, step=8, label="Resize height to", elem_id="img2img_hires_fix_resize_y")
            with gr.Row():
                sampler = gr.Dropdown(
                    label="Hires sampling method",
                    elem_id="img2img_hires_fix_sampler",
                    choices=["Use same sampler"] + sd_samplers.visible_sampler_names(),
                    value="Use same sampler",
                )
                scheduler = gr.Dropdown(
                    label="Hires schedule type",
                    elem_id="img2img_hires_fix_scheduler",
                    choices=["Use same scheduler"] + [x.label for x in sd_schedulers.schedulers],
                    value="Use same scheduler",
                )
            with gr.Row():
                hr_cfg = gr.Slider(1.0, 24.0, value=6.0, step=0.5, label="Hires CFG Scale", elem_id="img2img_hires_fix_hr_cfg")
                hr_distilled_cfg = gr.Slider(1.0, 24.0, value=3.0, step=0.5, label="Hires Distilled CFG Scale", elem_id="img2img_hires_fix_hr_distilled_cfg")
            hr_prompt = gr.Textbox(label="Hires prompt", lines=2, placeholder="Empty uses the original prompt")
            hr_negative = gr.Textbox(label="Hires negative prompt", lines=2, placeholder="Empty uses the original negative prompt")
            replace = gr.Checkbox(label="Star button replaces selected image", value=False)

            # Forge's native Generate and txt2img hires buttons use a hidden
            # textbox as the JavaScript-replaced task-ID input. gr.State is
            # server-side session state and Gradio 4.40 does not reliably apply
            # a _js return value to it, leaving the backend with an empty task ID
            # while requestProgress() polls the generated ID forever.
            task_id = gr.Textbox(
                value="",
                visible=False,
                elem_id="img2img_hires_fix_task_id",
            )

            manual_button = ToolButton(
                "✨",
                elem_id="img2img_hires_fix_manual_button",
                tooltip="Enhance the selected img2img result using these hires settings.",
            )

        _COMPONENTS.update({
            "button": manual_button,
            "task_id": task_id,
            "denoise": denoise,
            "scale": scale,
            "upscaler": upscaler,
            "steps": steps,
            "resize_x": resize_x,
            "resize_y": resize_y,
            "sampler": sampler,
            "scheduler": scheduler,
            "hr_prompt": hr_prompt,
            "hr_negative": hr_negative,
            "hr_cfg": hr_cfg,
            "hr_distilled_cfg": hr_distilled_cfg,
            "replace": replace,
        })
        _try_wire_manual()

        self.infotext_fields = [
            (enable, "Img2img hires enabled"),
            (denoise, "Img2img hires denoising strength"),
            (scale, "Img2img hires upscale by"),
            (upscaler, "Img2img hires upscaler"),
            (steps, "Img2img hires steps"),
            (resize_x, "Img2img hires resize width"),
            (resize_y, "Img2img hires resize height"),
            (sampler, "Img2img hires sampler"),
            (scheduler, "Img2img hires schedule type"),
            (hr_prompt, "Img2img hires prompt"),
            (hr_negative, "Img2img hires negative prompt"),
            (hr_cfg, "Img2img hires CFG scale"),
            (hr_distilled_cfg, "Img2img hires Distilled CFG scale"),
        ]

        return [
            enable, denoise, scale, upscaler, steps, resize_x, resize_y,
            sampler, scheduler, hr_prompt, hr_negative, hr_cfg,
            hr_distilled_cfg, replace,
        ]

    def postprocess(
        self,
        p,
        processed,
        enable,
        denoise,
        scale,
        upscaler,
        steps,
        resize_x,
        resize_y,
        sampler,
        scheduler,
        hr_prompt,
        hr_negative,
        hr_cfg,
        hr_distilled_cfg,
        replace,
    ):
        if _active() or not processed.images:
            return

        entries = _cache_generation_state(p, processed)
        if not enable or not entries:
            return

        first = int(getattr(processed, "index_of_first_image", 0) or 0)
        first_replacement_text = ""
        cache_user = getattr(p, "user", None)
        cache_job = getattr(processed, "job_timestamp", None)

        # Each standalone native Hires run advances Forge's state twice. Add
        # those jobs up front so automatic multi-image batches do not run past
        # 100% progress after the original img2img pass completes.
        shared.state.job_count = max(
            int(getattr(shared.state, "job_count", 0) or 0),
            int(getattr(shared.state, "job_no", 0) or 0) + 2 * len(entries),
        )
        shared.state.processing_has_refined_job_count = True

        for state in entries:
            if shared.state.interrupted or shared.state.skipped:
                break
            index = int(state.get("gallery_index", -1))
            if index < first or index >= len(processed.images):
                break

            source = processed.images[index]
            if not isinstance(source, Image.Image):
                continue

            source_infotext = str(state.get("infotext", "") or "")
            hires_settings = resolve_hires_settings(
                {
                    "mode": "automatic",
                    "processing": p,
                    "prompt": str(state.get("prompt", "") or ""),
                    "source_infotext": source_infotext,
                },
                _current_hires_settings(
                    denoise, scale, upscaler, steps, resize_x, resize_y, sampler, scheduler,
                    hr_prompt, hr_negative, hr_cfg, hr_distilled_cfg,
                ),
            )

            q = _make_hires_processing(
                source.convert("RGB"),
                prompt=state.get("prompt", ""),
                negative_prompt=state.get("negative_prompt", ""),
                styles=[],
                seed=int(state.get("seed", -1)),
                subseed=int(state.get("subseed", -1)),
                steps=int(state.get("steps", 20)),
                sampler_name=state.get("sampler_name"),
                scheduler=state.get("scheduler"),
                cfg_scale=float(state.get("cfg_scale", 7.0)),
                distilled_cfg_scale=float(state.get("distilled_cfg_scale", 3.5)),
                denoising_strength=hires_settings["denoising_strength"],
                hr_scale=hires_settings["hr_scale"],
                hr_upscaler=hires_settings["hr_upscaler"],
                hr_second_pass_steps=hires_settings["hr_second_pass_steps"],
                hr_resize_x=hires_settings["hr_resize_x"],
                hr_resize_y=hires_settings["hr_resize_y"],
                hr_sampler_name=_clean_choice(hires_settings["hr_sampler_name"], "Use same sampler"),
                hr_scheduler=_clean_choice(hires_settings["hr_scheduler"], "Use same scheduler"),
                hr_prompt=hires_settings["hr_prompt"],
                hr_negative_prompt=hires_settings["hr_negative_prompt"],
                hr_cfg=hires_settings["hr_cfg"],
                hr_distilled_cfg=hires_settings["hr_distilled_cfg"],
                subseed_strength=float(state.get("subseed_strength", 0.0)),
                seed_resize_from_h=int(state.get("seed_resize_from_h", 0)),
                seed_resize_from_w=int(state.get("seed_resize_from_w", 0)),
                token_merging_ratio=float(state.get("token_merging_ratio", 0.0)),
                token_merging_ratio_hr=float(state.get("token_merging_ratio_hr", 0.0)),
                disable_extra_networks=bool(state.get("disable_extra_networks", False)),
                user=getattr(p, "user", None),
            )
            # Automatic mode follows the source job's output destination,
            # including a custom img2img batch output directory.
            q.outpath_samples = getattr(p, "outpath_samples", None) or q.outpath_samples
            q.outpath_grids = getattr(p, "outpath_grids", None) or q.outpath_grids
            result = _run_hires(q, source_infotext)
            if result.images:
                generated_image = result.images[0]
                merged_text = result.infotexts[0] if result.infotexts else ""
                processed.images[index] = generated_image
                if index < len(processed.infotexts):
                    processed.infotexts[index] = merged_text
                if not first_replacement_text:
                    first_replacement_text = merged_text

                updated_state = dict(state)
                exact_prompt, exact_negative = _parsed_prompt_pair(source_infotext)
                updated_state["prompt"] = exact_prompt or str(state.get("prompt", "") or "")
                updated_state["negative_prompt"] = exact_negative or str(state.get("negative_prompt", "") or "")
                _remember_state(
                    merged_text,
                    updated_state,
                    user=cache_user,
                    job_timestamp=cache_job,
                )

        if first_replacement_text:
            processed.info = first_replacement_text
