from __future__ import annotations

import json
import math
import re
from collections.abc import Iterable, Mapping
from typing import Any


USE_SAME_SAMPLER = "Use same sampler"
USE_SAME_SCHEDULER = "Use same scheduler"

HIRES_SETTING_FIELDS = frozenset(
    {
        "denoising_strength",
        "hr_scale",
        "hr_upscaler",
        "hr_second_pass_steps",
        "hr_resize_x",
        "hr_resize_y",
        "hr_sampler_name",
        "hr_scheduler",
        "hr_prompt",
        "hr_negative_prompt",
        "hr_cfg",
        "hr_distilled_cfg",
    }
)

CUSTOM_HIRES_METADATA_KEYS = (
    "Hires source",
    "Original Size",
    "Final Size",
    "Img2img hires enabled",
    "Img2img hires denoising strength",
    "Img2img hires upscale by",
    "Img2img hires upscaler",
    "Img2img hires steps",
    "Img2img hires resize width",
    "Img2img hires resize height",
    "Img2img hires sampler",
    "Img2img hires schedule type",
    "Img2img hires CFG scale",
    "Img2img hires Distilled CFG scale",
    "Img2img hires prompt",
    "Img2img hires negative prompt",
)

SOURCE_DENOISE_METADATA_KEY = "Img2img source denoising strength"

_PARAM_RE = re.compile(
    r'\s*([\w\s\-\/]+):\s*("(?:\\.|[^\\"])+"|[^,]*)(?:,|$)'
)


class HiresSettingsError(ValueError):
    pass


def _finite_float(value: Any, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise HiresSettingsError(f"{label} must be a number") from exc
    if not math.isfinite(number):
        raise HiresSettingsError(f"{label} must be finite")
    return number


def _whole_number(value: Any, label: str) -> int:
    number = _finite_float(value, label)
    if not number.is_integer():
        raise HiresSettingsError(f"{label} must be a whole number")
    return int(number)


def _bounded(value: float, label: str, minimum: float, maximum: float) -> float:
    if not minimum <= value <= maximum:
        raise HiresSettingsError(
            f"{label} must be between {minimum:g} and {maximum:g}"
        )
    return value


def _choice(value: Any, label: str, default: str | None = None) -> str:
    text = str(value if value not in (None, "") else (default or "")).strip()
    if not text:
        raise HiresSettingsError(f"{label} cannot be empty")
    if len(text) > 256 or any(character in text for character in "<>\r\n"):
        raise HiresSettingsError(f"{label} contains unsupported characters")
    return text


def _check_available(value: str, label: str, available: Iterable[str]) -> None:
    choices = {str(item) for item in available if str(item)}
    if choices and value not in choices:
        raise HiresSettingsError(f"{label} {value!r} is not available")


def normalize_hires_settings(
    settings: Mapping[str, Any],
    *,
    available_upscalers: Iterable[str] = (),
    available_samplers: Iterable[str] = (),
    available_schedulers: Iterable[str] = (),
) -> dict[str, Any]:
    """Validate and normalize the public override API's complete settings map."""
    missing = HIRES_SETTING_FIELDS.difference(settings)
    if missing:
        names = ", ".join(sorted(missing))
        raise HiresSettingsError(f"missing Hires setting fields: {names}")

    denoise = _bounded(
        _finite_float(settings["denoising_strength"], "denoising strength"),
        "denoising strength",
        0.0,
        1.0,
    )
    scale = _bounded(
        _finite_float(settings["hr_scale"], "upscale by"),
        "upscale by",
        1.0,
        4.0,
    )
    upscaler = _choice(settings["hr_upscaler"], "upscaler")
    steps = _whole_number(settings["hr_second_pass_steps"], "Hires steps")
    resize_x = _whole_number(settings["hr_resize_x"], "resize width")
    resize_y = _whole_number(settings["hr_resize_y"], "resize height")
    cfg = _bounded(
        _finite_float(settings["hr_cfg"], "Hires CFG"),
        "Hires CFG",
        1.0,
        24.0,
    )
    distilled_cfg = _bounded(
        _finite_float(settings["hr_distilled_cfg"], "Hires Distilled CFG"),
        "Hires Distilled CFG",
        1.0,
        24.0,
    )

    if not 0 <= steps <= 150:
        raise HiresSettingsError("Hires steps must be between 0 and 150")
    if not 0 <= resize_x <= 4096 or not 0 <= resize_y <= 4096:
        raise HiresSettingsError("resize dimensions must be between 0 and 4096")

    sampler = _choice(
        settings["hr_sampler_name"], "Hires sampler", USE_SAME_SAMPLER
    )
    scheduler = _choice(
        settings["hr_scheduler"], "Hires scheduler", USE_SAME_SCHEDULER
    )

    _check_available(upscaler, "upscaler", available_upscalers)
    if sampler != USE_SAME_SAMPLER:
        _check_available(sampler, "sampler", available_samplers)
    if scheduler != USE_SAME_SCHEDULER:
        _check_available(scheduler, "scheduler", available_schedulers)

    return {
        "denoising_strength": denoise,
        "hr_scale": scale,
        "hr_upscaler": upscaler,
        "hr_second_pass_steps": steps,
        "hr_resize_x": resize_x,
        "hr_resize_y": resize_y,
        "hr_sampler_name": sampler,
        "hr_scheduler": scheduler,
        "hr_prompt": str(settings["hr_prompt"] or ""),
        "hr_negative_prompt": str(settings["hr_negative_prompt"] or ""),
        "hr_cfg": cfg,
        "hr_distilled_cfg": distilled_cfg,
    }


def _has_parameter_line(line: str) -> bool:
    return len(_PARAM_RE.findall(line or "")) >= 3


def extract_exact_prompt_negative(infotext: str | None) -> tuple[str, str]:
    lines = (infotext or "").splitlines()
    if not lines:
        return "", ""

    body_lines = lines[:-1] if _has_parameter_line(lines[-1]) else lines
    prompt_lines: list[str] = []
    negative_lines: list[str] = []
    in_negative = False

    for line in body_lines:
        if line.lstrip().startswith("Negative prompt:"):
            in_negative = True
            prefix_at = line.find("Negative prompt:")
            negative_lines.append(line[prefix_at + len("Negative prompt:") :].lstrip())
        elif in_negative:
            negative_lines.append(line)
        else:
            prompt_lines.append(line)

    return "\n".join(prompt_lines).strip(), "\n".join(negative_lines).strip()


def parse_infotext_parameters(infotext: str | None) -> dict[str, Any]:
    """Parse only the raw parameter line without Forge's default injection.

    Forge's UI parser expands values such as ``Size: 1024x1024`` into
    ``Size-1``/``Size-2`` fields for component pasting. Re-serializing that
    dictionary corrupts PNG metadata. This lossless parser keeps the original
    key/value form specifically for metadata merging.
    """
    lines = (infotext or "").strip().split("\n")
    if not lines or not _has_parameter_line(lines[-1]):
        return {}

    result: dict[str, Any] = {}
    for key, raw_value in _PARAM_RE.findall(lines[-1]):
        value: Any = raw_value
        if value.startswith('"') and value.endswith('"'):
            try:
                value = json.loads(value)
            except (TypeError, ValueError, json.JSONDecodeError):
                pass
        result[key.strip()] = value
    return result


def quote_infotext_value(value: Any) -> str:
    text = str(value)
    if "," not in text and "\n" not in text and ":" not in text:
        return text
    try:
        return json.dumps(text, ensure_ascii=False)
    except (TypeError, ValueError):
        return text


def compose_infotext(
    prompt: str, negative_prompt: str, parameters: Mapping[str, Any]
) -> str:
    lines = [prompt or ""]
    if negative_prompt:
        lines.append(f"Negative prompt: {negative_prompt}")

    fields = [
        f"{key}: {quote_infotext_value(value)}"
        for key, value in parameters.items()
        if key not in {"Prompt", "Negative prompt"} and value is not None
    ]
    if fields:
        lines.append(", ".join(fields))
    return "\n".join(lines).strip()


def _is_native_hires_key(key: str) -> bool:
    return key == "Denoising strength" or key.startswith("Hires ")


def merge_parameter_maps(
    source: Mapping[str, Any],
    generated: Mapping[str, Any],
    *,
    final_size: str | None = None,
) -> dict[str, Any]:
    """Keep source generation settings and replace only the current Hires pass."""
    source_denoise = source.get(
        SOURCE_DENOISE_METADATA_KEY, source.get("Denoising strength")
    )
    custom_keys = set(CUSTOM_HIRES_METADATA_KEYS)

    merged: dict[str, Any] = {}
    for key, value in source.items():
        if key in {"Prompt", "Negative prompt", SOURCE_DENOISE_METADATA_KEY}:
            continue
        if key in custom_keys or _is_native_hires_key(key):
            continue
        merged[key] = value

    if source_denoise is not None:
        merged[SOURCE_DENOISE_METADATA_KEY] = source_denoise

    for key, value in generated.items():
        if key in custom_keys or _is_native_hires_key(key):
            merged[key] = value

    # Forge conditionally omits native Hires fields when their value means
    # "same" or zero. Explicit values are required for clean Send-to round
    # trips because an existing destination UI can otherwise keep stale data.
    native_aliases = {
        "Hires upscaler": "Img2img hires upscaler",
        "Hires steps": "Img2img hires steps",
        "Hires sampler": "Img2img hires sampler",
        "Hires schedule type": "Img2img hires schedule type",
        "Hires prompt": "Img2img hires prompt",
        "Hires negative prompt": "Img2img hires negative prompt",
        "Hires CFG Scale": "Img2img hires CFG scale",
        "Hires Distilled CFG Scale": "Img2img hires Distilled CFG scale",
    }
    for native_key, custom_key in native_aliases.items():
        if native_key not in merged and custom_key in merged:
            merged[native_key] = merged[custom_key]

    if "Hires resize" not in merged and "Hires upscale" not in merged:
        upscale = merged.get("Img2img hires upscale by")
        if upscale is not None:
            merged["Hires upscale"] = upscale

    if final_size:
        merged["Final Size"] = final_size
    return merged


def merge_hires_infotext(
    source_infotext: str,
    generated_infotext: str,
    *,
    final_size: str | None = None,
) -> str:
    prompt, negative_prompt = extract_exact_prompt_negative(source_infotext)
    source_parameters = parse_infotext_parameters(source_infotext)
    generated_parameters = parse_infotext_parameters(generated_infotext)
    merged = merge_parameter_maps(
        source_parameters,
        generated_parameters,
        final_size=final_size,
    )
    return compose_infotext(prompt, negative_prompt, merged)
