from __future__ import annotations

import logging
import re
import sys
from typing import Any

import gradio as gr

from modules import (
    extra_networks,
    processing,
    script_callbacks,
    scripts,
    sd_samplers,
    sd_schedulers,
    shared,
)

from hiresfix_tag_core import (
    DEFAULT_SAMPLER,
    DEFAULT_SCHEDULER,
    HiresFixTagConfig,
    HiresFixTagError,
    parse_prompt,
    replace_or_append,
)

LOGGER = logging.getLogger("hiresfix-tag-support")
NETWORK_NAME = "hiresfix"

# UI references only. These dictionaries hold Gradio components, not model or
# processing objects, and are populated only for the small set of IDs below.
_COMPONENTS: dict[str, dict[str, Any]] = {"txt2img": {}, "img2img": {}}
_TOOL_UI: dict[str, dict[str, Any]] = {"txt2img": {}, "img2img": {}}
_WIRED: set[str] = set()
_REGISTERED_IMG2IMG_API = None


class _HiresFixExtraNetwork(extra_networks.ExtraNetwork):
    """Register <hiresfix:...> as a real Forge extra-network namespace.

    Forge itself strips extra-network tags only from its transient conditioning
    copy (p.prompts). The raw p.prompt / p.all_prompts remain untouched and are
    later used for infotext, exactly as with LoRA tags.

    Runtime settings are deliberately NOT applied here because Neo's native
    txt2img p.init() calculates target Hires resolution before extra networks
    are activated. Script.process() below reads the same raw tag non-
    destructively early enough to affect p.init().
    """

    def __init__(self):
        super().__init__(NETWORK_NAME)

    def activate(self, p, params_list):
        # Namespace only. Never rewrite p.prompt, p.prompts, p.all_prompts, or
        # metadata. Forge owns the normal extra-network lifecycle.
        return None

    def deactivate(self, p):
        return None


_HIRESFIX_NETWORK = _HiresFixExtraNetwork()


def _ensure_extra_network_registered() -> None:
    """Robust against Forge clearing/reinitializing its registry at startup."""
    existing = extra_networks.extra_network_registry.get(NETWORK_NAME)
    if existing is _HIRESFIX_NETWORK:
        return
    if existing is not None:
        LOGGER.warning(
            "Leaving existing <%s:> namespace from %s in place. Remove older "
            "hiresfix tag extensions if settings are applied twice.",
            NETWORK_NAME,
            type(existing).__name__,
        )
        return
    extra_networks.register_extra_network(_HIRESFIX_NETWORK)


def _runtime_validate_config(cfg: HiresFixTagConfig) -> HiresFixTagConfig:
    """Reject names unavailable in this Forge instance before generation."""
    cfg.validate()

    latent_modes = getattr(shared, "latent_upscale_modes", {}) or {}
    latent_names = list(latent_modes.keys()) if hasattr(latent_modes, "keys") else list(latent_modes)
    pixel_names = [
        str(item.name)
        for item in (getattr(shared, "sd_upscalers", []) or [])
        if getattr(item, "name", None)
    ]
    available_upscalers = set(latent_names + pixel_names)
    if available_upscalers and cfg.upscaler not in available_upscalers:
        raise HiresFixTagError(
            f"upscaler {cfg.upscaler!r} is not available in this Forge installation"
        )

    if cfg.sampler != DEFAULT_SAMPLER:
        available_samplers = set(sd_samplers.visible_sampler_names())
        if available_samplers and cfg.sampler not in available_samplers:
            raise HiresFixTagError(
                f"sampler {cfg.sampler!r} is not available in this Forge installation"
            )

    if cfg.scheduler != DEFAULT_SCHEDULER:
        available_schedulers = {
            str(item.label) for item in sd_schedulers.schedulers if getattr(item, "label", None)
        }
        if available_schedulers and cfg.scheduler not in available_schedulers:
            raise HiresFixTagError(
                f"scheduler {cfg.scheduler!r} is not available in this Forge installation"
            )

    return cfg


# Register on import, and again in process() for the opposite Forge startup
# ordering. This mirrors the robustness pattern used by the CFG scheduler.
_ensure_extra_network_registered()


def _config_from_processing(p) -> HiresFixTagConfig | None:
    """Read the raw prompt without modifying it or invoking Forge's parser."""
    # A present canonical source is authoritative even when empty/untagged.
    # Native txt2img has one target size per job: last tagged entry in that
    # selected source wins, and last-tag-wins inside each entry is unchanged.
    candidates = []
    for name in ("all_prompts", "prompt", "main_prompt"):
        value = getattr(p, name, None)
        if isinstance(value, str):
            candidates = [value]
            break
        if isinstance(value, (list, tuple)):
            candidates = [text for text in value if isinstance(text, str)]
            if candidates:
                break

    result = None
    for text in candidates:
        try:
            found = parse_prompt(text)
        except HiresFixTagError as exc:
            LOGGER.warning("Ignoring malformed <hiresfix:> tag: %s", exc)
            continue
        if found is not None:
            result = found
    return result


def _apply_txt2img_config(p, cfg: HiresFixTagConfig) -> None:
    """Apply only tag-owned Hires fields; never enable Hires Fix itself."""
    p.hr_upscaler = cfg.upscaler
    p.denoising_strength = cfg.denoise
    p.hr_scale = cfg.scale
    p.hr_cfg = cfg.hires_cfg
    p.hr_second_pass_steps = cfg.steps
    p.hr_resize_x = cfg.resize_x
    p.hr_resize_y = cfg.resize_y
    p.hr_sampler_name = None if cfg.sampler == DEFAULT_SAMPLER else cfg.sampler
    p.hr_scheduler = None if cfg.scheduler == DEFAULT_SCHEDULER else cfg.scheduler
    p.hr_distilled_cfg = cfg.distilled_cfg
    # Hires prompt and Hires negative prompt intentionally remain untouched.


def _positive_from_infotext(infotext: str) -> str:
    """Read only the positive body of standard Forge/A1111 infotext."""
    lines = []
    for line in infotext.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("Negative prompt:"):
            break
        # Forge writes its parameter section starting with Steps. Stop before
        # it so quoted Hires prompt values cannot become active settings.
        if re.match(r"^Steps:\s*\d+(?:\s*,|\s*$)", stripped):
            break
        lines.append(line)
    return "\n".join(lines)


def _img2img_override(context: dict[str, Any], current: dict[str, Any]) -> dict[str, Any] | None:
    """Public hook consumer for the stable img2img Hires Fix extension."""
    cfg = None
    # Explicit per-image positive text, including an empty string, must never
    # fall back to negative text, metadata values, or stale job-level tags.
    text = context.get("prompt")
    if not isinstance(text, str):
        infotext = context.get("source_infotext")
        text = _positive_from_infotext(infotext) if isinstance(infotext, str) else None
    if text is not None:
        try:
            cfg = parse_prompt(text)
        except HiresFixTagError as exc:
            LOGGER.warning("Ignoring malformed <hiresfix:> tag: %s", exc)
    else:
        p = context.get("processing")
        if p is not None:
            cfg = _config_from_processing(p)

    if cfg is None:
        return None

    try:
        cfg = _runtime_validate_config(cfg)
    except HiresFixTagError as exc:
        LOGGER.warning("Ignoring unusable <hiresfix:> tag: %s", exc)
        return None

    return {
        "hr_upscaler": cfg.upscaler,
        "denoising_strength": cfg.denoise,
        "hr_scale": cfg.scale,
        "hr_cfg": cfg.hires_cfg,
        "hr_second_pass_steps": cfg.steps,
        "hr_resize_x": cfg.resize_x,
        "hr_resize_y": cfg.resize_y,
        "hr_sampler_name": cfg.sampler,
        "hr_scheduler": cfg.scheduler,
        "hr_distilled_cfg": cfg.distilled_cfg,
        # hr_prompt / hr_negative_prompt are deliberately omitted so the
        # corresponding accordion values remain authoritative.
    }


_img2img_override._hiresfix_tag_support_override = True


def _try_register_img2img_hook() -> bool:
    global _REGISTERED_IMG2IMG_API

    # Constant-time lookup of the documented public API. No sys.modules scan,
    # imports by filename, or monkey-patching of the stable extension.
    api = sys.modules.get("img2img_hires_fix_api")
    try:
        api_version = int(getattr(api, "API_VERSION", 0)) if api is not None else 0
    except (TypeError, ValueError, OverflowError):
        api_version = 0
    if api is None or api_version < 1:
        _REGISTERED_IMG2IMG_API = None
        return False

    unregister = getattr(api, "unregister_hires_settings_override", None)
    callbacks = getattr(api, "settings_overrides", ())
    if not isinstance(callbacks, (list, tuple)):
        callbacks = ()
    if callable(unregister):
        for callback in tuple(callbacks):
            if getattr(callback, "_hiresfix_tag_support_override", False):
                unregister(callback)

    register = getattr(api, "register_hires_settings_override", None)
    if not callable(register):
        _REGISTERED_IMG2IMG_API = None
        return False

    register(_img2img_override)
    callbacks = getattr(api, "settings_overrides", ())
    registered = _img2img_override in callbacks
    _REGISTERED_IMG2IMG_API = api if registered else None
    return registered


def _unregister_img2img_hook() -> None:
    global _REGISTERED_IMG2IMG_API

    api = _REGISTERED_IMG2IMG_API or sys.modules.get("img2img_hires_fix_api")
    unregister = getattr(api, "unregister_hires_settings_override", None)
    if callable(unregister):
        unregister(_img2img_override)
    _REGISTERED_IMG2IMG_API = None


def _before_ui() -> None:
    # Both extension scripts have been imported by this point. Retrying here
    # makes registration deterministic regardless of extension folder order.
    _ensure_extra_network_registered()
    _try_register_img2img_hook()


def _on_unload() -> None:
    _unregister_img2img_hook()
    if extra_networks.extra_network_registry.get(NETWORK_NAME) is _HIRESFIX_NETWORK:
        extra_networks.extra_network_registry.pop(NETWORK_NAME, None)


def _config_from_ui(
    upscaler,
    denoise,
    scale,
    hires_cfg,
    steps,
    resize_x,
    resize_y,
    sampler,
    scheduler,
    distilled_cfg,
) -> HiresFixTagConfig:
    try:
        return _runtime_validate_config(HiresFixTagConfig(
            upscaler=str(upscaler or ""),
            denoise=float(denoise),
            scale=float(scale),
            hires_cfg=float(hires_cfg),
            steps=steps or 0,
            resize_x=resize_x or 0,
            resize_y=resize_y or 0,
            sampler=str(sampler or DEFAULT_SAMPLER),
            scheduler=str(scheduler or DEFAULT_SCHEDULER),
            distilled_cfg=float(distilled_cfg),
        ).validate())
    except (TypeError, ValueError, HiresFixTagError) as exc:
        raise HiresFixTagError(str(exc)) from exc


def _write_tag(
    prompt,
    upscaler,
    denoise,
    scale,
    hires_cfg,
    steps,
    resize_x,
    resize_y,
    sampler,
    scheduler,
    distilled_cfg,
):
    try:
        cfg = _config_from_ui(
            upscaler, denoise, scale, hires_cfg, steps,
            resize_x, resize_y, sampler, scheduler, distilled_cfg,
        )
        return replace_or_append(prompt, cfg)
    except HiresFixTagError as exc:
        raise gr.Error(f"Unable to write <hiresfix:> tag: {exc}") from exc


def _read_tag(prompt):
    try:
        cfg = parse_prompt(prompt)
    except HiresFixTagError as exc:
        raise gr.Error(f"Invalid <hiresfix:> tag: {exc}") from exc
    if cfg is None:
        raise gr.Error("No <hiresfix:...> tag found in the prompt.")

    try:
        cfg = _runtime_validate_config(cfg)
    except HiresFixTagError as exc:
        raise gr.Error(f"The <hiresfix:> tag cannot be used here: {exc}") from exc

    return (
        cfg.upscaler,
        cfg.denoise,
        cfg.scale,
        cfg.hires_cfg,
        cfg.steps,
        cfg.resize_x,
        cfg.resize_y,
        cfg.sampler,
        cfg.scheduler,
        cfg.distilled_cfg,
    )


_COMPONENT_MAP = {
    # Native txt2img Hires Fix.
    "txt2img_prompt": ("txt2img", "prompt"),
    "txt2img_hr_upscaler": ("txt2img", "upscaler"),
    "txt2img_denoising_strength": ("txt2img", "denoise"),
    "txt2img_hr_scale": ("txt2img", "scale"),
    "txt2img_hr_cfg": ("txt2img", "hires_cfg"),
    "txt2img_hires_steps": ("txt2img", "steps"),
    "txt2img_hr_resize_x": ("txt2img", "resize_x"),
    "txt2img_hr_resize_y": ("txt2img", "resize_y"),
    "hr_sampler": ("txt2img", "sampler"),
    "hr_scheduler": ("txt2img", "scheduler"),
    "txt2img_hr_distilled_cfg": ("txt2img", "distilled_cfg"),

    # Hook-enabled stable img2img Hires Fix extension.
    "img2img_prompt": ("img2img", "prompt"),
    "img2img_hires_fix_upscaler": ("img2img", "upscaler"),
    "img2img_hires_fix_denoise": ("img2img", "denoise"),
    "img2img_hires_fix_scale": ("img2img", "scale"),
    "img2img_hires_fix_hr_cfg": ("img2img", "hires_cfg"),
    "img2img_hires_fix_steps": ("img2img", "steps"),
    "img2img_hires_fix_resize_x": ("img2img", "resize_x"),
    "img2img_hires_fix_resize_y": ("img2img", "resize_y"),
    "img2img_hires_fix_sampler": ("img2img", "sampler"),
    "img2img_hires_fix_scheduler": ("img2img", "scheduler"),
    "img2img_hires_fix_hr_distilled_cfg": ("img2img", "distilled_cfg"),
}

_CONTROL_ORDER = [
    "upscaler", "denoise", "scale", "hires_cfg", "steps",
    "resize_x", "resize_y", "sampler", "scheduler", "distilled_cfg",
]


def _try_wire(tab: str) -> None:
    if tab in _WIRED:
        return

    components = _COMPONENTS[tab]
    tools = _TOOL_UI[tab]
    if not {"write", "read"}.issubset(tools):
        return
    if not {"prompt", *_CONTROL_ORDER}.issubset(components):
        return

    ordered = [components[key] for key in _CONTROL_ORDER]
    tools["write"].click(
        fn=_write_tag,
        inputs=[components["prompt"], *ordered],
        outputs=[components["prompt"]],
        queue=False,
        show_progress=False,
    )
    tools["read"].click(
        fn=_read_tag,
        inputs=[components["prompt"]],
        outputs=ordered,
        queue=False,
        show_progress=False,
    )
    _WIRED.add(tab)


def _capture_component(component, **kwargs):
    elem_id = kwargs.get("elem_id") or getattr(component, "elem_id", None)
    mapped = _COMPONENT_MAP.get(elem_id)
    if mapped is None:
        return

    tab, key = mapped
    _COMPONENTS[tab][key] = component
    if tab == "img2img":
        _try_register_img2img_hook()
    _try_wire(tab)


script_callbacks.on_after_component(
    _capture_component,
    name="hiresfix-tag-support/component-capture",
)
script_callbacks.on_before_ui(_before_ui, name="hiresfix-tag-support/before-ui")
script_callbacks.on_script_unloaded(
    _on_unload,
    name="hiresfix-tag-support/unload",
)


class Script(scripts.Script):
    section = "accordions"
    sorting_priority = 100
    create_group = False

    def title(self):
        return "Hiresfix Tag Support"

    def show(self, is_img2img):
        return scripts.AlwaysVisible

    def ui(self, is_img2img):
        tab = "img2img" if is_img2img else "txt2img"
        with gr.Accordion(
            "Hiresfix Tag",
            open=False,
            elem_id=f"{tab}_hiresfix_tag_tools",
        ):
            with gr.Row():
                write_button = gr.Button(
                    "Write/update <hiresfix:> tag",
                    elem_id=f"{tab}_hiresfix_tag_write",
                )
                read_button = gr.Button(
                    "Read <hiresfix:> tag",
                    elem_id=f"{tab}_hiresfix_tag_read",
                )

        _TOOL_UI[tab] = {"write": write_button, "read": read_button}
        if is_img2img:
            _try_register_img2img_hook()
        _try_wire(tab)
        return []

    def process(self, p, *args):
        # Registration only; never run Forge's parse_prompt() here and never
        # assign to any prompt field. p.all_prompts therefore remains the raw
        # canonical metadata source exactly like the LoRA pathway.
        _ensure_extra_network_registered()

        cfg = _config_from_processing(p)
        if cfg is None:
            p._hiresfix_tag_config = None
            return

        try:
            cfg = _runtime_validate_config(cfg)
        except HiresFixTagError as exc:
            LOGGER.warning("Ignoring unusable <hiresfix:> tag: %s", exc)
            p._hiresfix_tag_config = None
            return

        p._hiresfix_tag_config = cfg

        # Presence of the tag never enables Hires Fix. Native txt2img needs
        # these values before p.init(), which is why this application happens
        # here rather than in ExtraNetwork.activate().
        if isinstance(p, processing.StableDiffusionProcessingTxt2Img) and getattr(p, "enable_hr", False):
            _apply_txt2img_config(p, cfg)
