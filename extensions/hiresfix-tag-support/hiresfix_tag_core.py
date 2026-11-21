from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Iterable

TAG_NAME = "hiresfix"
TAG_RE = re.compile(r"<hiresfix:([^<>]*)>")

DEFAULT_RESIZE_X = 0
DEFAULT_RESIZE_Y = 0
DEFAULT_SAMPLER = "Use same sampler"
DEFAULT_SCHEDULER = "Use same scheduler"
DEFAULT_DISTILLED_CFG = 3.0

# Keep prompt-carried values inside the ranges exposed by Forge Neo's Hires UI.
# This prevents a malformed or untrusted infotext tag from silently requesting
# extreme work that could otherwise result in an avoidable OOM.
MIN_SCALE = 1.0
MAX_SCALE = 4.0
MIN_CFG = 1.0
MAX_CFG = 24.0
MAX_STEPS = 150
MAX_RESIZE = 4096
MAX_CHOICE_LENGTH = 256


class HiresFixTagError(ValueError):
    pass


@dataclass(frozen=True)
class HiresFixTagConfig:
    upscaler: str
    denoise: float
    scale: float
    hires_cfg: float
    steps: int
    resize_x: int = DEFAULT_RESIZE_X
    resize_y: int = DEFAULT_RESIZE_Y
    sampler: str = DEFAULT_SAMPLER
    scheduler: str = DEFAULT_SCHEDULER
    distilled_cfg: float = DEFAULT_DISTILLED_CFG

    def validate(self) -> "HiresFixTagConfig":
        for label, value in (
            ("upscaler", self.upscaler),
            ("sampler", self.sampler),
            ("scheduler", self.scheduler),
        ):
            text = str(value).strip()
            if not text:
                raise HiresFixTagError(f"{label} cannot be empty")
            if len(text) > MAX_CHOICE_LENGTH:
                raise HiresFixTagError(f"{label} is too long")
            if any(character in text for character in ":<>\r\n"):
                raise HiresFixTagError(
                    f"{label} cannot contain ':', angle brackets, or line breaks"
                )

        denoise = _finite_float(self.denoise, "denoise")
        scale = _finite_float(self.scale, "upscale_by")
        hires_cfg = _finite_float(self.hires_cfg, "hires_cfg")
        steps = _whole_number(self.steps, "steps")
        resize_x = _whole_number(self.resize_x, "resize_x")
        resize_y = _whole_number(self.resize_y, "resize_y")
        distilled_cfg = _finite_float(self.distilled_cfg, "distilled_cfg")

        if not 0.0 <= denoise <= 1.0:
            raise HiresFixTagError("denoise must be between 0 and 1")
        if not MIN_SCALE <= scale <= MAX_SCALE:
            raise HiresFixTagError(
                f"upscale_by must be between {MIN_SCALE:g} and {MAX_SCALE:g}"
            )
        if not MIN_CFG <= hires_cfg <= MAX_CFG:
            raise HiresFixTagError(
                f"hires_cfg must be between {MIN_CFG:g} and {MAX_CFG:g}"
            )
        if not 0 <= steps <= MAX_STEPS:
            raise HiresFixTagError(f"steps must be between 0 and {MAX_STEPS}")
        if not 0 <= resize_x <= MAX_RESIZE or not 0 <= resize_y <= MAX_RESIZE:
            raise HiresFixTagError(
                f"resize dimensions must be between 0 and {MAX_RESIZE}"
            )
        if not MIN_CFG <= distilled_cfg <= MAX_CFG:
            raise HiresFixTagError(
                f"distilled_cfg must be between {MIN_CFG:g} and {MAX_CFG:g}"
            )
        return self


def _finite_float(value, label: str) -> float:
    try:
        result = float(value)
    except Exception as exc:
        raise HiresFixTagError(f"invalid {label}: {value!r}") from exc
    if not math.isfinite(result):
        raise HiresFixTagError(f"{label} must be a finite number")
    return result


def _whole_number(value, label: str) -> int:
    number = _finite_float(value, label)
    if not number.is_integer():
        raise HiresFixTagError(f"{label} must be a whole number")
    return int(number)


def parse_items(items: Iterable[str]) -> HiresFixTagConfig:
    values = [str(value).strip() for value in items]
    if len(values) < 5:
        raise HiresFixTagError(
            "hiresfix requires upscaler:denoise:upscale_by:hires_cfg:steps"
        )
    if len(values) > 10:
        raise HiresFixTagError("hiresfix accepts at most 10 fields")

    config = HiresFixTagConfig(
        upscaler=values[0].strip(),
        denoise=_finite_float(values[1], "denoise"),
        scale=_finite_float(values[2], "upscale_by"),
        hires_cfg=_finite_float(values[3], "hires_cfg"),
        steps=_whole_number(values[4], "steps"),
        resize_x=_whole_number(values[5], "resize_x") if len(values) > 5 and values[5] != "" else DEFAULT_RESIZE_X,
        resize_y=_whole_number(values[6], "resize_y") if len(values) > 6 and values[6] != "" else DEFAULT_RESIZE_Y,
        sampler=values[7].strip() if len(values) > 7 and values[7] != "" else DEFAULT_SAMPLER,
        scheduler=values[8].strip() if len(values) > 8 and values[8] != "" else DEFAULT_SCHEDULER,
        distilled_cfg=_finite_float(values[9], "distilled_cfg") if len(values) > 9 and values[9] != "" else DEFAULT_DISTILLED_CFG,
    )
    return config.validate()


def parse_prompt(prompt: str | None) -> HiresFixTagConfig | None:
    matches = list(TAG_RE.finditer(prompt or ""))
    if not matches:
        return None
    return parse_items(matches[-1].group(1).split(":"))


def _fmt_number(value: float) -> str:
    return f"{float(value):g}"


def serialize(config: HiresFixTagConfig) -> str:
    c = config.validate()
    required = [
        c.upscaler,
        _fmt_number(c.denoise),
        _fmt_number(c.scale),
        _fmt_number(c.hires_cfg),
        str(int(c.steps)),
    ]
    optional = [
        str(int(c.resize_x)),
        str(int(c.resize_y)),
        c.sampler,
        c.scheduler,
        _fmt_number(c.distilled_cfg),
    ]
    defaults = [
        str(DEFAULT_RESIZE_X),
        str(DEFAULT_RESIZE_Y),
        DEFAULT_SAMPLER,
        DEFAULT_SCHEDULER,
        _fmt_number(DEFAULT_DISTILLED_CFG),
    ]

    last = len(optional)
    while last > 0 and optional[last - 1] == defaults[last - 1]:
        last -= 1

    return f"<hiresfix:{':'.join(required + optional[:last])}>"


def replace_or_append(prompt: str | None, config: HiresFixTagConfig) -> str:
    source = prompt or ""
    tag = serialize(config)
    matches = list(TAG_RE.finditer(source))
    if matches:
        # Runtime parsing intentionally uses the last tag. When the UI writes a
        # tag, remove every older duplicate and replace only that final tag so
        # the prompt has one unambiguous, portable settings record.
        pieces: list[str] = []
        cursor = 0
        final_index = len(matches) - 1
        for index, match in enumerate(matches):
            pieces.append(source[cursor : match.start()])
            if index == final_index:
                pieces.append(tag)
            cursor = match.end()
        pieces.append(source[cursor:])
        return "".join(pieces)
    if not source:
        return tag
    spacer = "" if source[-1].isspace() else " "
    return source + spacer + tag
