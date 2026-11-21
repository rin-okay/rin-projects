from __future__ import annotations

import itertools
import logging
from typing import Optional

from modules import extra_networks, scripts

from cfg_scheduler_core import CFGSchedule, CFGScheduleError, extract_prompt_schedules


LOGGER = logging.getLogger("forge-cfg-scheduler")
_FORCE_CFG_FOR_CONDITIONING = 1.000001
_MODIFIER_MARKER = "_forge_cfg_scheduler_modifier"
_CFG1_STATE_MARKER = "_forge_cfg_scheduler_previous_cfg1_optimization"


def _case_variants(word: str):
    for choices in itertools.product(*[(c.lower(), c.upper()) for c in word]):
        yield "".join(choices)


class _ScheduleExtraNetwork(extra_networks.ExtraNetwork):
    """
    Registration makes cfg/hrcfg first-class Forge extra-network namespaces.

    Forge itself strips the tag from p.prompts/hr_prompts while leaving
    p.all_prompts/all_hr_prompts untouched, exactly like the LoRA pathway.
    Scheduling is read from the untouched source prompt by the always-on script
    before Forge parses the working copy.
    """

    def activate(self, p, params_list):
        # Hires conditioning can be deferred until the actual Hires pass. Neo
        # activates hr_extra_network_data immediately before calculating those
        # conditions, so re-arm the CFG=1 workaround here when necessary.
        if self.name == "hrcfg" and getattr(p, "is_hr_pass", False):
            schedule = getattr(p, "_cfg_scheduler_hr_batch_schedule", None)
            original = getattr(p, "_cfg_scheduler_original_hr_cfg", None)
            if schedule is not None and schedule.requires_unconditional and original == 1:
                p.hr_cfg = _FORCE_CFG_FOR_CONDITIONING
                p._cfg_scheduler_forced_hr_cfg = True
        return None

    def deactivate(self, p):
        return None


_CFG_EXTRA_NETWORK = _ScheduleExtraNetwork("cfg")
_HRCFG_EXTRA_NETWORK = _ScheduleExtraNetwork("hrcfg")


def _ensure_extra_networks_registered() -> None:
    # process() calls this every generation as well, making registration robust
    # even if Forge cleared/reinitialized the registry after extension import.
    for network in (_CFG_EXTRA_NETWORK, _HRCFG_EXTRA_NETWORK):
        existing = extra_networks.extra_network_registry.get(network.name)
        if existing is not network:
            if existing is not None:
                LOGGER.warning(
                    "Prompt CFG Scheduler: replacing existing extra-network namespace %r (%s).",
                    network.name,
                    type(existing).__name__,
                )
            extra_networks.register_extra_network(network)

    # Preserve the older case-insensitive behavior while keeping lower-case as
    # the canonical/native spelling. All aliases point at the same network.
    for variant in _case_variants("cfg"):
        if variant != "cfg":
            extra_networks.register_extra_network_alias(_CFG_EXTRA_NETWORK, variant)
    for variant in _case_variants("hrcfg"):
        if variant != "hrcfg":
            extra_networks.register_extra_network_alias(_HRCFG_EXTRA_NETWORK, variant)


# Safe when scripts are imported after Forge's registry initialization; process()
# repeats the call before every generation for the opposite startup ordering.
_ensure_extra_networks_registered()


def _remove_our_modifiers(unet) -> None:
    model_options = getattr(unet, "model_options", None)
    if not isinstance(model_options, dict):
        return

    new_options = model_options.copy()
    changed = False

    modifiers = model_options.get("conditioning_modifiers") or []
    kept = [fn for fn in modifiers if not getattr(fn, _MODIFIER_MARKER, False)]
    if len(kept) != len(modifiers):
        changed = True
        if kept:
            new_options["conditioning_modifiers"] = kept
        else:
            new_options.pop("conditioning_modifiers", None)

    cfg1_state = getattr(unet, _CFG1_STATE_MARKER, None)
    if cfg1_state is not None:
        changed = True
        had_key, previous_value = cfg1_state
        if had_key:
            new_options["disable_cfg1_optimization"] = previous_value
        else:
            new_options.pop("disable_cfg1_optimization", None)
        delattr(unet, _CFG1_STATE_MARKER)

    if changed:
        unet.model_options = new_options


def _last_tagged_schedule(
    schedules: list[Optional[CFGSchedule]], tag_counts: list[int]
) -> tuple[bool, Optional[CFGSchedule]]:
    found = False
    result: Optional[CFGSchedule] = None
    for schedule, tag_count in zip(schedules, tag_counts):
        if tag_count > 0:
            found = True
            result = schedule
    return found, result


def _warn_mixed(p, namespace: str, batch_number: int, schedules: list[Optional[CFGSchedule]], label: str) -> None:
    distinct = {s.canonical() for s in schedules if s is not None}
    key = (namespace, batch_number)
    if len(distinct) > 1 and key not in p._cfg_scheduler_warned_mixed:
        LOGGER.warning(
            "Prompt CFG Scheduler: batch %d contains different %s schedules; the last tagged prompt wins.",
            batch_number + 1,
            label,
        )
        p._cfg_scheduler_warned_mixed.add(key)


def _restore_forced_scalars(p) -> None:
    if getattr(p, "_cfg_scheduler_forced_base_cfg", False):
        p.cfg_scale = p._cfg_scheduler_original_cfg_scale
        p._cfg_scheduler_forced_base_cfg = False

    if getattr(p, "_cfg_scheduler_forced_hr_cfg", False):
        p.hr_cfg = p._cfg_scheduler_original_hr_cfg
        p._cfg_scheduler_forced_hr_cfg = False


def _prepare_cfg1_conditioning(p, base_schedule: Optional[CFGSchedule], hr_schedule: Optional[CFGSchedule]) -> None:
    # Start from the user's actual scalar values. This also cleans up a previous
    # batch before deciding whether the next batch needs the workaround.
    _restore_forced_scalars(p)

    if (
        base_schedule is not None
        and base_schedule.requires_unconditional
        and p._cfg_scheduler_original_cfg_scale == 1
    ):
        p.cfg_scale = _FORCE_CFG_FOR_CONDITIONING
        p._cfg_scheduler_forced_base_cfg = True

    if (
        getattr(p, "enable_hr", False)
        and hr_schedule is not None
        and hr_schedule.requires_unconditional
        and p._cfg_scheduler_original_hr_cfg == 1
    ):
        p.hr_cfg = _FORCE_CFG_FOR_CONDITIONING
        p._cfg_scheduler_forced_hr_cfg = True


class Script(scripts.Script):
    create_group = False

    def title(self):
        return "Prompt CFG Scheduler"

    def show(self, is_img2img):
        return scripts.AlwaysVisible

    def ui(self, is_img2img):
        return []

    def process(self, p, *args):
        _ensure_extra_networks_registered()

        p._cfg_scheduler_batch_schedule = None
        p._cfg_scheduler_hr_batch_schedule = None
        p._cfg_scheduler_warned_mixed = set()

        p._cfg_scheduler_original_cfg_scale = getattr(p, "cfg_scale", None)
        p._cfg_scheduler_original_hr_cfg = getattr(p, "hr_cfg", None)
        p._cfg_scheduler_forced_base_cfg = False
        p._cfg_scheduler_forced_hr_cfg = False

        # Old builds wrote these fields. v1.4 relies only on the literal tags in
        # the source prompt, matching Forge's LoRA-style infotext behavior.
        p.extra_generation_params.pop("CFG schedule", None)
        p.extra_generation_params.pop("Hires CFG schedule", None)

        # Deliberately do not modify p.all_prompts, p.main_prompt,
        # p.all_hr_prompts, or p.hr_prompt here.

    def before_process_batch(self, p, *args, **kwargs):
        _ensure_extra_networks_registered()

        prompts = list(kwargs.get("prompts") or [])
        batch_number = int(kwargs.get("batch_number", getattr(p, "iteration", 0)))
        batch_size = len(prompts)
        start = batch_number * getattr(p, "batch_size", batch_size)

        # Remove any previous pass modifier before a new batch is prepared.
        unet = getattr(getattr(p.sd_model, "forge_objects", None), "unet", None)
        if unet is not None:
            _remove_our_modifiers(unet)

        base_schedules: list[Optional[CFGSchedule]] = []
        base_tag_counts: list[int] = []
        main_hr_schedules: list[Optional[CFGSchedule]] = []
        main_hr_tag_counts: list[int] = []
        errors: set[str] = set()

        # Read the current working batch before Forge's extra-network parser runs.
        # We use only the parsed schedule; the stripped result is intentionally
        # ignored so Forge remains the sole owner of prompt stripping.
        for prompt in prompts:
            result = extract_prompt_schedules(prompt)
            base_schedules.append(result.cfg_schedule)
            base_tag_counts.append(result.cfg_tag_count)
            main_hr_schedules.append(result.hrcfg_schedule)
            main_hr_tag_counts.append(result.hrcfg_tag_count)
            errors.update(result.errors)

        _, base_schedule = _last_tagged_schedule(base_schedules, base_tag_counts)
        _warn_mixed(p, "base", batch_number, base_schedules, "CFG")

        main_hr_found, main_hr_schedule = _last_tagged_schedule(main_hr_schedules, main_hr_tag_counts)
        _warn_mixed(p, "main_hr", batch_number, main_hr_schedules, "HRCFG")
        hr_schedule = main_hr_schedule if main_hr_found else None

        # Explicit Hires prompt HRCFG overrides main-prompt HRCFG. A malformed
        # last explicit HRCFG is authoritative and disables the fallback.
        all_hr_prompts = getattr(p, "all_hr_prompts", None)
        explicit_hr_schedules: list[Optional[CFGSchedule]] = []
        explicit_hr_tag_counts: list[int] = []
        if all_hr_prompts:
            for prompt in list(all_hr_prompts[start : start + batch_size]):
                result = extract_prompt_schedules(prompt)
                explicit_hr_schedules.append(result.hrcfg_schedule)
                explicit_hr_tag_counts.append(result.hrcfg_tag_count)
                errors.update(result.errors)

            explicit_found, explicit_schedule = _last_tagged_schedule(
                explicit_hr_schedules, explicit_hr_tag_counts
            )
            if explicit_found:
                hr_schedule = explicit_schedule
            _warn_mixed(p, "explicit_hr", batch_number, explicit_hr_schedules, "explicit HRCFG")

        p._cfg_scheduler_batch_schedule = base_schedule
        p._cfg_scheduler_hr_batch_schedule = hr_schedule

        _prepare_cfg1_conditioning(p, base_schedule, hr_schedule)

        for error in sorted(errors):
            LOGGER.warning("Invalid CFG scheduler tag rejected: %s", error)

    def before_hr(self, p, *args):
        # No prompt mutation is needed here. Forge has already parsed hr_prompts
        # through its native extra-network pathway, exactly as it does for LoRA.
        return None

    def process_before_every_sampling(self, p, *args, **kwargs):
        is_hr = bool(getattr(p, "is_hr_pass", False))
        schedule = p._cfg_scheduler_hr_batch_schedule if is_hr else p._cfg_scheduler_batch_schedule

        # Conditioning has been built by this point. Restore the user's scalar
        # values before sampler/infotext code observes them.
        _restore_forced_scalars(p)

        unet = getattr(getattr(p.sd_model, "forge_objects", None), "unet", None)

        # Always remove this extension's previous modifier at pass start. This
        # guarantees <cfg> cannot bleed into an unscheduled Hires pass.
        if unet is not None:
            _remove_our_modifiers(unet)

        if schedule is None:
            return

        sampler = getattr(p, "sampler", None)
        denoiser = getattr(sampler, "model_wrap_cfg", None)
        if denoiser is None or unet is None:
            LOGGER.warning("Prompt CFG Scheduler: could not find Neo CFG denoiser/UNet; using normal CFG for this pass.")
            return

        resolved_schedule = None
        resolved_total_steps = None
        resolution_failed = False
        tag_name = "hrcfg" if is_hr else "cfg"
        schedule_tag = f"<{tag_name}:{schedule.canonical()}>"

        initial_total_steps = getattr(denoiser, "total_steps", None)
        if initial_total_steps:
            try:
                resolved_schedule = schedule.resolve(initial_total_steps)
                resolved_total_steps = int(initial_total_steps)
            except CFGScheduleError as exc:
                LOGGER.warning(
                    "Prompt CFG Scheduler: schedule %s rejected for this %d-step pass: %s. Using normal CFG.",
                    schedule_tag,
                    int(initial_total_steps),
                    exc,
                )
                return

        def cfg_schedule_modifier(model, x, timestep, uncond, cond, cond_scale, model_options, seed):
            nonlocal resolved_schedule, resolved_total_steps, resolution_failed

            total_steps = int(getattr(denoiser, "total_steps", None) or 1)
            if resolution_failed:
                return model, x, timestep, uncond, cond, cond_scale, model_options, seed

            if resolved_schedule is None or resolved_total_steps != total_steps:
                try:
                    resolved_schedule = schedule.resolve(total_steps)
                    resolved_total_steps = total_steps
                except CFGScheduleError as exc:
                    LOGGER.warning(
                        "Prompt CFG Scheduler: schedule %s rejected for this %d-step pass: %s. Using normal CFG.",
                        schedule_tag,
                        total_steps,
                        exc,
                    )
                    resolution_failed = True
                    return model, x, timestep, uncond, cond, cond_scale, model_options, seed

            current_step = int(getattr(denoiser, "step", 0)) + 1
            scheduled_cfg = resolved_schedule.cfg_at_step(current_step)
            return model, x, timestep, uncond, cond, scheduled_cfg, model_options, seed

        setattr(cfg_schedule_modifier, _MODIFIER_MARKER, True)

        model_options = getattr(unet, "model_options", {}) or {}
        new_options = model_options.copy()
        existing = [
            fn
            for fn in new_options.get("conditioning_modifiers", [])
            if not getattr(fn, _MODIFIER_MARKER, False)
        ]
        new_options["conditioning_modifiers"] = existing + [cfg_schedule_modifier]

        if schedule.requires_unconditional:
            if not hasattr(unet, _CFG1_STATE_MARKER):
                setattr(
                    unet,
                    _CFG1_STATE_MARKER,
                    (
                        "disable_cfg1_optimization" in model_options,
                        model_options.get("disable_cfg1_optimization"),
                    ),
                )
            new_options["disable_cfg1_optimization"] = True

        unet.model_options = new_options

    def postprocess(self, p, processed, *args):
        _restore_forced_scalars(p)

        unet = getattr(getattr(p.sd_model, "forge_objects", None), "unet", None)
        if unet is not None:
            _remove_our_modifiers(unet)
