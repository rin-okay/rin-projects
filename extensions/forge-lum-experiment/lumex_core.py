from __future__ import annotations

import math
import re
import threading
from dataclasses import dataclass
from typing import Optional, Sequence

import torch
import torch.nn.functional as F

LUMEX_TAG_RE = re.compile(r"<\s*lumex\s*:\s*([^>]*)>", re.IGNORECASE)
CALIBRATION_SIZE = 64
MAX_ABS_LUM = 1.0
MAX_STRENGTH = 3.0
MAX_SPLOTCH_INFLUENCE = 1.0
DEFAULT_SPLOTCH_INFLUENCE = 0.05
DENOISE_MAX_INFLUENCE = 0.30
DEFAULT_DENOISE = 0.85
MAX_SPLOTCH_AMOUNT = 5.0
VALID_INTERPOLATION = {"nearest", "bilinear", "bicubic"}
SPLOTCH_SEED_XOR = 0x4C554D4558504C54  # "LUMEXPLT"
MAX_TORCH_SEED = (1 << 63) - 1
ENCODE_LOCK = threading.RLock()
VAE_CALIBRATION_SEED = 1729
VERSION = "1.6.0"


class LumexConfigError(ValueError):
    pass


def _fmt(value: float) -> str:
    value = 0.0 if abs(float(value)) < 1e-12 else float(value)
    return format(value, ".12g")


def denoise_to_influence(denoise: float) -> float:
    value = float(denoise)
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise LumexConfigError("denoise must be between 0 and 1")
    return (1.0 - value) * DENOISE_MAX_INFLUENCE


def influence_to_denoise(influence: float) -> float:
    value = float(influence)
    if not math.isfinite(value):
        raise LumexConfigError("splotch influence must be finite")
    # Legacy splotch_strength tags could exceed the new UI's maximum reference
    # influence. Clamp only for display/editing; generation still keeps the
    # original legacy influence value.
    return max(0.0, min(1.0, 1.0 - (value / DENOISE_MAX_INFLUENCE)))


@dataclass(frozen=True)
class SplotchConfig:
    grid: int = 8
    amount: float = 0.25
    contrast: float = 2.0
    interpolation: str = "bilinear"

    def __post_init__(self):
        grid = int(self.grid)
        amount = float(self.amount)
        contrast = float(self.contrast)
        interpolation = str(self.interpolation).strip().lower()
        if not 2 <= grid <= 128:
            raise LumexConfigError("splotch grid must be between 2 and 128")
        if not math.isfinite(amount) or not 0.0 <= amount <= MAX_SPLOTCH_AMOUNT:
            raise LumexConfigError(f"splotch amount must be between 0 and {MAX_SPLOTCH_AMOUNT:g}")
        if not math.isfinite(contrast) or not 0.05 <= contrast <= 20.0:
            raise LumexConfigError("splotch contrast must be between 0.05 and 20")
        if interpolation not in VALID_INTERPOLATION:
            raise LumexConfigError(f"splotch interpolation must be one of {sorted(VALID_INTERPOLATION)}")
        object.__setattr__(self, "grid", grid)
        object.__setattr__(self, "amount", amount)
        object.__setattr__(self, "contrast", contrast)
        object.__setattr__(self, "interpolation", interpolation)

    def payload(self) -> str:
        return f"{self.grid},{_fmt(self.amount)},{_fmt(self.contrast)},{self.interpolation}"


@dataclass(frozen=True)
class LumexConfig:
    lum: float = 0.0
    splotch: Optional[SplotchConfig] = None
    strength: float = 1.0
    splotch_influence: float = DEFAULT_SPLOTCH_INFLUENCE
    mode: str = "legacy"

    def __post_init__(self):
        if self.mode not in {"legacy", "tonal"}:
            raise LumexConfigError("mode must be legacy or tonal")
        lum = float(self.lum)
        strength = float(self.strength)
        splotch_influence = float(self.splotch_influence)
        if not math.isfinite(lum) or not -MAX_ABS_LUM <= lum <= MAX_ABS_LUM:
            raise LumexConfigError(f"lum must be between {-MAX_ABS_LUM:g} and {MAX_ABS_LUM:g}")
        if not math.isfinite(strength) or not 0.0 <= strength <= MAX_STRENGTH:
            raise LumexConfigError(f"strength must be between 0 and {MAX_STRENGTH:g}")
        if not math.isfinite(splotch_influence) or not 0.0 <= splotch_influence <= MAX_SPLOTCH_INFLUENCE:
            raise LumexConfigError(
                f"splotch_strength must be between 0 and {MAX_SPLOTCH_INFLUENCE:g}"
            )
        object.__setattr__(self, "lum", lum)
        object.__setattr__(self, "strength", strength)
        object.__setattr__(self, "splotch_influence", splotch_influence)

    @property
    def is_noop(self) -> bool:
        lum_off = abs(self.lum) < 1e-12 or self.strength == 0.0
        splotch_off = self.splotch is None or self.splotch.amount == 0.0 or self.splotch_influence == 0.0
        return lum_off and splotch_off

    def tag(self) -> str:
        if self.mode == "legacy" and self.splotch is None and math.isclose(
            self.strength, 1.0, rel_tol=0.0, abs_tol=1e-12
        ):
            # Denoise/reference influence is irrelevant when no splotch exists,
            # so preserve the original compact lum-only syntax regardless of
            # the UI's current denoise slider position.
            return f"<lumex:{_fmt(self.lum)}>"

        parts = ["mode=tonal"] if self.mode == "tonal" else []
        if abs(self.lum) >= 1e-12:
            parts.append(f"lum={_fmt(self.lum)}")
        if self.splotch is not None:
            parts.append(f"splotch={self.splotch.payload()}")
        if not math.isclose(self.strength, 1.0, rel_tol=0.0, abs_tol=1e-12):
            parts.append(f"strength={_fmt(self.strength)}")
        if self.splotch is not None:
            if self.splotch_influence <= DENOISE_MAX_INFLUENCE + 1e-12:
                parts.append(f"denoise={_fmt(influence_to_denoise(self.splotch_influence))}")
            else:
                # Preserve exact behavior for old hand-written tags that used
                # an influence beyond the new denoise slider's range.
                parts.append(f"splotch_strength={_fmt(self.splotch_influence)}")
        if not parts:
            parts.append("lum=0")
        return "<lumex:" + ":".join(parts) + ">"


def parse_splotch_value(value: str) -> SplotchConfig:
    parts = [x.strip() for x in str(value).split(",")]
    if len(parts) != 4:
        raise LumexConfigError("splotch expects grid,amount,contrast,interpolation")
    try:
        grid = int(parts[0], 10)
        amount = float(parts[1])
        contrast = float(parts[2])
    except Exception as exc:
        raise LumexConfigError(f"invalid splotch values: {value!r}") from exc
    return SplotchConfig(grid, amount, contrast, parts[3])


def parse_lumex_items(items: Sequence[str]) -> LumexConfig:
    items = [str(x).strip() for x in items if str(x).strip()]
    if not items:
        raise LumexConfigError("lumex requires at least one argument")

    if len(items) == 1 and "=" not in items[0]:
        try:
            return LumexConfig(lum=float(items[0]))
        except Exception as exc:
            if isinstance(exc, LumexConfigError):
                raise
            raise LumexConfigError(f"lumex value must be numeric: {items[0]!r}") from exc

    named = {}
    positional = []
    for item in items:
        if "=" in item:
            key, value = item.split("=", 1)
            key = key.strip().lower()
            if key in named:
                raise LumexConfigError(f"duplicate lumex key: {key}")
            named[key] = value.strip()
        else:
            positional.append(item)

    if positional:
        raise LumexConfigError("keyed lumex syntax cannot contain positional arguments")

    unknown = set(named) - {"lum", "splotch", "strength", "splotch_strength", "denoise", "mode"}
    if unknown:
        raise LumexConfigError("unknown lumex key(s): " + ", ".join(sorted(unknown)))

    try:
        lum = float(named.get("lum", 0.0))
        strength = float(named.get("strength", 1.0))
        if "denoise" in named:
            # New syntax wins over the legacy raw influence key when both exist.
            splotch_influence = denoise_to_influence(float(named["denoise"]))
        else:
            splotch_influence = float(named.get("splotch_strength", DEFAULT_SPLOTCH_INFLUENCE))
    except ValueError as exc:
        raise LumexConfigError("lum, strength, denoise, and splotch_strength must be numeric") from exc

    splotch = parse_splotch_value(named["splotch"]) if "splotch" in named else None
    return LumexConfig(lum=lum, splotch=splotch, strength=strength, splotch_influence=splotch_influence, mode=named.get("mode", "legacy").lower())


def parse_lumex_payload(payload: str) -> LumexConfig:
    return parse_lumex_items(str(payload).split(":"))


def last_lumex_from_prompt(prompt: str) -> tuple[bool, Optional[LumexConfig], Optional[str]]:
    matches = list(LUMEX_TAG_RE.finditer(prompt or ""))
    if not matches:
        return False, None, None
    raw = matches[-1].group(1)
    try:
        return True, parse_lumex_payload(raw), None
    except LumexConfigError as exc:
        return True, None, str(exc)


def remove_lumex_tags(prompt: str) -> str:
    return LUMEX_TAG_RE.sub("", prompt or "").rstrip()


def update_prompt_tag(prompt: str, config: Optional[LumexConfig]) -> tuple[str, str]:
    cleaned = remove_lumex_tags(prompt)
    if config is None:
        return cleaned, "Lumex tag removed from prompt."
    tag = config.tag()
    return cleaned + ("\n" if cleaned else "") + tag, tag


def derive_splotch_seed(seed: int) -> int:
    value = int(seed) & ((1 << 64) - 1)
    return int((value ^ SPLOTCH_SEED_XOR) % MAX_TORCH_SEED)


def _cpu_random_field(seed: int, grid_h: int, grid_w: int) -> torch.Tensor:
    generator = torch.Generator(device="cpu")
    generator.manual_seed(int(seed))
    return torch.randn((1, 1, grid_h, grid_w), generator=generator, device="cpu")


def make_splotch_field(height: int, width: int, seed: int, config: SplotchConfig) -> torch.Tensor:
    if height < 1 or width < 1:
        raise LumexConfigError("reference dimensions must be positive")

    if height <= width:
        grid_h = config.grid
        grid_w = max(2, int(round(config.grid * width / height)))
    else:
        grid_w = config.grid
        grid_h = max(2, int(round(config.grid * height / width)))

    small = _cpu_random_field(derive_splotch_seed(seed), grid_h, grid_w)
    if config.interpolation == "nearest":
        field = F.interpolate(small, size=(height, width), mode="nearest")
    else:
        field = F.interpolate(small, size=(height, width), mode=config.interpolation, align_corners=False)

    field = torch.tanh(field * config.contrast)
    field = field - field.mean(dim=(-2, -1), keepdim=True)
    peak = field.abs().amax(dim=(-2, -1), keepdim=True).clamp_min(1e-6)
    return field / peak


def validate_dimensions(width, height):
    if int(width) != width or int(height) != height:
        raise LumexConfigError("dimensions must be whole pixels")
    width, height = int(width), int(height)
    if not (8 <= width <= 4096 and 8 <= height <= 4096):
        raise LumexConfigError("dimensions must be between 8 and 4096 pixels")
    if max(width / height, height / width) > 16:
        raise LumexConfigError("reference aspect ratio must not exceed 16:1")
    return width, height


def build_tonal_map(config, seed, width, height):
    """The shared preview/injection control map: 0 dark, .5 none, 1 light."""
    width, height = validate_dimensions(width, height)
    tone = torch.full((1, 1, height, width), 0.5 + config.lum * config.strength * 0.5)
    if config.splotch is not None and config.splotch.amount > 0:
        field = make_splotch_field(height, width, seed, config.splotch)
        tone += field * config.splotch.amount * (config.splotch_influence / DENOISE_MAX_INFLUENCE)
    return tone.clamp(0, 1)


@torch.inference_mode()
def derive_tonal_offsets(model, config, seeds, width, height, target_hw):
    # Calibrate against this VAE's own black/gray/white encoding. No per-image
    # normalization: halfway to an anchor gives halfway its latent offset.
    levels = [0.0, 0.25, 0.5, 0.75, 1.0]
    vectors = torch.stack([_encode_gray_mean_vector(model, g) for g in levels])
    vectors = vectors - vectors[2:3]
    offsets = []
    for seed in seeds:
        tone = build_tonal_map(config, seed, width, height)
        tone = F.interpolate(tone, size=target_hw, mode="area")[0, 0]
        position = tone * 4
        lo = position.floor().long().clamp(0, 3)
        fraction = (position - lo).unsqueeze(-1)
        offset = vectors[lo] * (1 - fraction) + vectors[lo + 1] * fraction
        offsets.append(offset.permute(2, 0, 1).unsqueeze(0))
    return torch.cat(offsets, dim=0)


def build_influence_preview(config, seed, width, height):
    """Fixed-scale grayscale proxy, NOT a prediction of the denoised image.

    Like generation, normalize spatial contrast before applying influence.
    One unit of normalized influence maps to one unit of display gray.
    Do not auto-stretch each output: that would hide strength changes again.
    """
    if config.mode == "tonal":
        proxy = build_tonal_map(config, seed, width, height)
        return proxy, {"spatial_proxy_rms": float((proxy - 0.5).square().mean().sqrt()),
                       "clipped_fraction": float(((proxy <= 0) | (proxy >= 1)).float().mean())}
    raw = build_reference_gray(config, seed, width, height)
    field = raw - raw.mean(dim=(-2, -1), keepdim=True)
    rms = field.square().mean().sqrt()
    influence = config.splotch_influence if config.splotch is not None else 0.0
    field = torch.where(rms > 1e-6, field / rms.clamp_min(1e-6), torch.zeros_like(field))
    if config.splotch is None or config.splotch.amount == 0:
        field = torch.zeros_like(field)
    proxy = 0.5 + config.lum * config.strength * 0.5 + field * influence
    clipped = float(((proxy < 0) | (proxy > 1)).float().mean())
    return proxy.clamp(0, 1), {"spatial_proxy_rms": float((field * influence).square().mean().sqrt()),
                                "clipped_fraction": clipped}


def build_reference_gray(config: LumexConfig, seed: int, width: int, height: int) -> torch.Tensor:
    width, height = validate_dimensions(width, height)
    base = 0.5 + config.lum * 0.5
    reference = torch.full((1, 1, height, width), float(base), dtype=torch.float32)
    if config.splotch is not None:
        field = make_splotch_field(height, width, seed, config.splotch)
        reference = reference + field * config.splotch.amount
    return reference.clamp(0.0, 1.0)


def _extract_latent_tensor(encoded):
    if isinstance(encoded, torch.Tensor):
        return encoded
    latent_dist = getattr(encoded, "latent_dist", None)
    if latent_dist is not None:
        if hasattr(latent_dist, "mode") and callable(latent_dist.mode):
            return latent_dist.mode()
        if hasattr(latent_dist, "mean"):
            return latent_dist.mean
        if hasattr(latent_dist, "sample") and callable(latent_dist.sample):
            return latent_dist.sample()
    if hasattr(encoded, "mode") and callable(encoded.mode):
        return encoded.mode()
    if hasattr(encoded, "sample") and callable(encoded.sample):
        return encoded.sample()
    if hasattr(encoded, "mean") and isinstance(encoded.mean, torch.Tensor):
        return encoded.mean
    raise RuntimeError(f"Unsupported VAE encode result type: {type(encoded).__name__}")


def _model_device_and_dtype(model):
    candidates = [model, getattr(model, "first_stage_model", None)]
    for candidate in candidates:
        if candidate is None:
            continue
        params = getattr(candidate, "parameters", None)
        if callable(params):
            try:
                first = next(params())
                return first.device, first.dtype
            except Exception:
                pass
    return torch.device("cpu"), torch.float32


def _encode_image_tensor_unseeded(model, image_01: torch.Tensor) -> torch.Tensor:
    device, dtype = _model_device_and_dtype(model)
    image = image_01.to(device=device, dtype=dtype) * 2.0 - 1.0

    if hasattr(model, "encode_first_stage") and callable(model.encode_first_stage):
        encoded = model.encode_first_stage(image)
        if hasattr(model, "get_first_stage_encoding") and callable(model.get_first_stage_encoding):
            return model.get_first_stage_encoding(encoded)
        return _extract_latent_tensor(encoded)

    vae = getattr(getattr(model, "forge_objects", None), "vae", None)
    if vae is None:
        raise RuntimeError("No usable VAE encode path was available on the current model.")
    if hasattr(vae, "encode") and callable(vae.encode):
        # Forge VAE.encode expects BHWC in [0, 1], unlike encode_first_stage.
        latent = _extract_latent_tensor(vae.encode(image_01.movedim(1, -1)))
        process_in = getattr(getattr(vae, "first_stage_model", None), "process_in", None)
        return process_in(latent) if callable(process_in) else latent
    raise RuntimeError("The current VAE object does not expose a recognized encode() method.")


@torch.inference_mode()
def _encode_image_tensor(model, image_01):
    # Forge's SD VAE samples its posterior internally. Paired encodes share a
    # fixed RNG stream; restore every touched state so sampler noise is unaffected.
    # Callers in Forge serialize this with the normal generation queue lock.
    devices = list(range(torch.cuda.device_count())) if torch.cuda.is_available() else []
    with ENCODE_LOCK, torch.random.fork_rng(devices=devices):
        torch.manual_seed(VAE_CALIBRATION_SEED)
        latent = _encode_image_tensor_unseeded(model, image_01).detach().float()
    if not torch.isfinite(latent).all():
        raise RuntimeError("VAE returned non-finite reference latents")
    return latent


def _encode_gray_mean_vector(model, gray: float) -> torch.Tensor:
    image = torch.full((1, 3, CALIBRATION_SIZE, CALIBRATION_SIZE), float(gray), dtype=torch.float32)
    latent = _encode_image_tensor(model, image)
    if latent.ndim != 4:
        raise RuntimeError(f"Expected encoded latent to be 4D, got shape {tuple(latent.shape)}")
    return latent.mean(dim=(0, 2, 3)).detach().float().cpu()


def derive_flat_lum_offset(model, config: LumexConfig, latent_channels: int, *, device, dtype) -> torch.Tensor:
    if abs(config.lum) < 1e-12 or config.strength == 0.0:
        return torch.zeros((1, latent_channels, 1, 1), device=device, dtype=dtype)
    neutral_vec = _encode_gray_mean_vector(model, 0.5)
    target_gray = max(0.0, min(1.0, 0.5 + config.lum * 0.5))
    target_vec = _encode_gray_mean_vector(model, target_gray)
    delta = target_vec - neutral_vec
    if int(delta.numel()) != int(latent_channels):
        raise RuntimeError(
            f"Lumex channel mismatch: encoded delta has {delta.numel()} channels, noise has {latent_channels}."
        )
    return delta.to(device=device, dtype=dtype).view(1, latent_channels, 1, 1) * config.strength


def _sample_base_gray(config: LumexConfig) -> float:
    return float(max(0.0, min(1.0, 0.5 + config.lum * 0.5)))


def derive_spatial_splotch_residual(
    model,
    config: LumexConfig,
    seeds: Sequence[int],
    width: int,
    height: int,
    *,
    device,
    dtype,
    target_hw: tuple[int, int],
) -> torch.Tensor:
    if config.splotch is None:
        raise LumexConfigError("spatial splotch residual requested without splotches")
    if not seeds:
        raise LumexConfigError("no generation seeds available for lumex splotches")

    width, height = validate_dimensions(width, height)
    base_gray = _sample_base_gray(config)
    base_rgb = torch.full((1, 3, height, width), base_gray, dtype=torch.float32)
    z_base = _encode_image_tensor(model, base_rgb)
    if z_base.ndim != 4:
        raise RuntimeError("VAE reference encoding did not return 4D image latents")
    residuals = []
    # One image per encode makes results independent of batch placement and
    # prevents a whole batch of full-resolution references consuming VRAM.
    for seed in seeds:
        reference = build_reference_gray(config, int(seed), width, height).repeat(1, 3, 1, 1)
        z_ref = _encode_image_tensor(model, reference)
        if z_ref.shape != z_base.shape:
            raise RuntimeError("Reference and base VAE latent shapes differ")
        delta = z_ref - z_base
        if delta.shape[-2:] != target_hw:
            delta = F.interpolate(delta, size=target_hw, mode="bilinear", align_corners=False)
        # Keep v1.5's global centering in legacy mode.
        delta = delta - delta.mean(dim=(1, 2, 3), keepdim=True)
        rms = delta.square().mean(dim=(1, 2, 3), keepdim=True).sqrt()
        delta = torch.where(rms > 1e-6, delta / rms.clamp_min(1e-6), torch.zeros_like(delta))
        residuals.append(delta.to(device=device, dtype=dtype) * config.splotch_influence)
    return torch.cat(residuals, dim=0)


@torch.inference_mode()
def apply_lumex(
    noise: torch.Tensor,
    model,
    config: Optional[LumexConfig],
    seeds: Sequence[int],
    width: int,
    height: int,
) -> torch.Tensor:
    if config is None or config.is_noop:
        return noise
    if noise.ndim != 4:
        raise LumexConfigError(f"lumex supports only 4D image latents; got shape {tuple(noise.shape)}")

    batch, channels, latent_h, latent_w = noise.shape
    out = noise
    if config.mode == "tonal":
        if len(seeds) < batch:
            raise LumexConfigError("one resolved generation seed is required per batch image")
        offset = derive_tonal_offsets(model, config, seeds[:batch], width, height, (latent_h, latent_w))
        if offset.shape != noise.shape:
            raise RuntimeError(f"Tonal offset/noise shape mismatch: {tuple(offset.shape)} vs {tuple(noise.shape)}")
        return noise + offset.to(noise)

    lum_offset = derive_flat_lum_offset(model, config, channels, device=noise.device, dtype=noise.dtype)
    if lum_offset.abs().amax().item() > 0:
        out = out + lum_offset.expand(batch, channels, 1, 1)

    if config.splotch is not None and config.splotch.amount > 0.0 and config.splotch_influence > 0.0:
        use_seeds = list(seeds[:batch])
        if len(use_seeds) != batch:
            raise LumexConfigError("one resolved generation seed is required per batch image")
        residual = derive_spatial_splotch_residual(
            model,
            config,
            use_seeds,
            int(width),
            int(height),
            device=noise.device,
            dtype=noise.dtype,
            target_hw=(latent_h, latent_w),
        )
        if residual.shape[1] != channels:
            raise RuntimeError(
                f"Lumex channel mismatch: splotch residual has {residual.shape[1]} channels, noise has {channels}."
            )
        out = out + residual

    return out
