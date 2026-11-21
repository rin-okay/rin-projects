from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Iterable, Literal, Optional, Sequence


# These regexes are inspection-only. The extension never writes their stripped
# result back into Forge's master prompt arrays; Forge's own extra-network parser
# performs the actual removal from the disposable conditioning prompt.
CFG_TAG_RE = re.compile(r"<\s*cfg\s*:\s*([^>]*)>", re.IGNORECASE)
HRCFG_TAG_RE = re.compile(r"<\s*hrcfg\s*:\s*([^>]*)>", re.IGNORECASE)
_INTEGER_RE = re.compile(r"^[+-]?\d+$")
_EPSILON = 1e-9


class CFGScheduleError(ValueError):
    pass


def _format_number(value: float) -> str:
    if value == 0:
        value = 0.0
    return format(value, ".12g")


def _parse_float(text: str, what: str) -> float:
    try:
        value = float(text)
    except (TypeError, ValueError) as exc:
        raise CFGScheduleError(f"{what} must be a number: {text!r}") from exc

    if not math.isfinite(value):
        raise CFGScheduleError(f"{what} must be finite: {text!r}")

    return value


@dataclass(frozen=True)
class CFGEndpoint:
    kind: Literal["step", "fraction"]
    value: int | float

    @classmethod
    def step(cls, value: int) -> "CFGEndpoint":
        if value < 1:
            raise CFGScheduleError(f"step endpoint must be >= 1: {value!r}")
        return cls("step", int(value))

    @classmethod
    def fraction(cls, value: float) -> "CFGEndpoint":
        value = float(value)
        if not math.isfinite(value) or not (0.0 < value <= 1.0):
            raise CFGScheduleError(f"fraction endpoint must be > 0 and <= 1: {value!r}")
        return cls("fraction", value)

    def canonical(self) -> str:
        if self.kind == "step":
            return str(int(self.value))
        return _format_number(float(self.value))

    def resolve(self, total_steps: int) -> int:
        if total_steps < 1:
            raise CFGScheduleError(f"sampling pass must contain at least one step; got {total_steps!r}")

        if self.kind == "step":
            return int(self.value)

        # Fraction boundaries are inclusive endpoints. ceil() prevents a
        # fractional boundary from ending before the requested percentage.
        return max(1, int(math.ceil((float(self.value) * total_steps) - _EPSILON)))


def _parse_endpoint(text: str) -> CFGEndpoint:
    """
    Endpoint syntax is intentionally lexical:

      5, 10, 1       -> absolute denoiser step endpoints
      .2, 0.5, 1.0   -> normalized pass fractions
      20%, 50%, 100% -> normalized pass fractions

    Integer `1` is step 1 while decimal `1.0` is 100%.
    """
    text = text.strip()
    if not text:
        raise CFGScheduleError("endpoint is empty")

    if text.endswith("%"):
        value = _parse_float(text[:-1].strip(), "endpoint") / 100.0
        if not (0.0 < value <= 1.0):
            raise CFGScheduleError(f"percentage endpoint must be > 0% and <= 100%: {text!r}")
        return CFGEndpoint.fraction(value)

    if _INTEGER_RE.fullmatch(text):
        value = int(text, 10)
        if value < 1:
            raise CFGScheduleError(f"step endpoint must be >= 1: {text!r}")
        return CFGEndpoint.step(value)

    value = _parse_float(text, "endpoint")
    if not (0.0 < value <= 1.0):
        raise CFGScheduleError(
            f"decimal endpoint must be > 0 and <= 1; use an integer for an absolute step: {text!r}"
        )
    return CFGEndpoint.fraction(value)


@dataclass(frozen=True)
class CFGStage:
    cfg: float
    end: CFGEndpoint


@dataclass(frozen=True)
class ResolvedCFGStage:
    cfg: float
    end_step: int


@dataclass(frozen=True)
class ResolvedCFGSchedule:
    stages: tuple[ResolvedCFGStage, ...]
    total_steps: int

    def cfg_at_step(self, step: int) -> float:
        if not self.stages:
            raise CFGScheduleError("resolved schedule has no stages")

        step = min(max(int(step), 1), self.total_steps)
        for stage in self.stages:
            if step <= stage.end_step:
                return stage.cfg
        return self.stages[-1].cfg


@dataclass(frozen=True)
class CFGSchedule:
    stages: tuple[CFGStage, ...]

    @property
    def requires_unconditional(self) -> bool:
        return any(not math.isclose(stage.cfg, 1.0, rel_tol=0.0, abs_tol=_EPSILON) for stage in self.stages)

    def resolve(self, total_steps: int) -> ResolvedCFGSchedule:
        """Resolve mixed fraction/absolute endpoints into inclusive pass step endpoints."""
        try:
            total_steps = int(total_steps)
        except (TypeError, ValueError) as exc:
            raise CFGScheduleError(f"invalid total step count: {total_steps!r}") from exc

        if total_steps < 1:
            raise CFGScheduleError(f"sampling pass must contain at least one step; got {total_steps!r}")

        resolved: list[ResolvedCFGStage] = []
        previous_end = 0

        for index, stage in enumerate(self.stages):
            is_final = index == len(self.stages) - 1
            end_step = stage.end.resolve(total_steps)

            if is_final:
                if stage.end.kind != "fraction" or not math.isclose(
                    float(stage.end.value), 1.0, rel_tol=0.0, abs_tol=_EPSILON
                ):
                    raise CFGScheduleError("schedule is improperly terminated; final endpoint must be 1.0 / 100%")
                end_step = total_steps
            elif end_step >= total_steps:
                source = stage.end.canonical()
                raise CFGScheduleError(
                    f"endpoint {source} resolves to step {end_step}, leaving the following CFG stage unreachable "
                    f"in a {total_steps}-step pass"
                )

            if end_step <= previous_end:
                raise CFGScheduleError(
                    f"endpoints resolve out of order or to the same step ({previous_end} then {end_step}) "
                    f"for a {total_steps}-step pass"
                )

            resolved.append(ResolvedCFGStage(cfg=stage.cfg, end_step=end_step))
            previous_end = end_step

        if not resolved or resolved[-1].end_step != total_steps:
            raise CFGScheduleError("schedule does not terminate at the end of the sampling pass")

        return ResolvedCFGSchedule(tuple(resolved), total_steps)

    def cfg_at_step(self, step: int, total_steps: int) -> float:
        return self.resolve(total_steps).cfg_at_step(step)

    def canonical(self) -> str:
        """Compact native extra-network form. Final ,1.0 is omitted."""
        parts: list[str] = []
        for index, stage in enumerate(self.stages):
            cfg = _format_number(stage.cfg)
            if index == len(self.stages) - 1:
                parts.append(cfg)
            else:
                parts.append(f"{cfg},{stage.end.canonical()}")
        return ":".join(parts)

    def tag(self, namespace: str = "cfg") -> str:
        return f"<{namespace}:{self.canonical()}>"


def parse_schedule_parts(raw_stages: Sequence[str]) -> CFGSchedule:
    """Parse stages already separated by Forge's native ':' extra-network delimiter."""
    if not raw_stages:
        raise CFGScheduleError("schedule is empty")

    raw_stages = [str(part).strip() for part in raw_stages]
    if any(not part for part in raw_stages):
        raise CFGScheduleError("schedule contains an empty stage")

    if any("|" in part for part in raw_stages):
        raise CFGScheduleError("legacy '|' stage separators are no longer supported; use ':' between CFG stages")

    stages: list[CFGStage] = []
    previous_endpoint: Optional[CFGEndpoint] = None

    for index, raw_stage in enumerate(raw_stages):
        is_final = index == len(raw_stages) - 1
        pieces = [piece.strip() for piece in raw_stage.split(",")]

        if len(pieces) == 1:
            if not is_final:
                raise CFGScheduleError("only the final CFG stage may omit its endpoint")
            cfg = _parse_float(pieces[0], "CFG")
            endpoint = CFGEndpoint.fraction(1.0)
        elif len(pieces) == 2:
            cfg = _parse_float(pieces[0], "CFG")
            endpoint = _parse_endpoint(pieces[1])

            if is_final:
                if endpoint.kind != "fraction" or not math.isclose(
                    float(endpoint.value), 1.0, rel_tol=0.0, abs_tol=_EPSILON
                ):
                    raise CFGScheduleError(
                        "schedule is improperly terminated; an explicit final endpoint must be decimal 1.0 or 100%"
                    )
            elif endpoint.kind == "fraction" and math.isclose(
                float(endpoint.value), 1.0, rel_tol=0.0, abs_tol=_EPSILON
            ):
                raise CFGScheduleError("100% / 1.0 may only be used by the final CFG stage")
        else:
            raise CFGScheduleError(f"invalid stage {raw_stage!r}; expected CFG,end or a final CFG")

        if previous_endpoint is not None and previous_endpoint.kind == endpoint.kind:
            if endpoint.kind == "step":
                if int(endpoint.value) <= int(previous_endpoint.value):
                    raise CFGScheduleError("absolute step endpoints must be strictly increasing")
            elif float(endpoint.value) <= float(previous_endpoint.value) + _EPSILON:
                raise CFGScheduleError("fraction/percentage endpoints must be strictly increasing")

        stages.append(CFGStage(cfg=cfg, end=endpoint))
        previous_endpoint = endpoint

    return CFGSchedule(tuple(stages))


def parse_schedule(payload: str) -> CFGSchedule:
    """Parse the literal payload inside <cfg:...> / <hrcfg:...>."""
    payload = payload.strip()
    if not payload:
        raise CFGScheduleError("schedule is empty")
    if "|" in payload:
        raise CFGScheduleError("legacy '|' stage separators are no longer supported; use ':' between CFG stages")
    return parse_schedule_parts(payload.split(":"))


@dataclass(frozen=True)
class ExtractResult:
    # `text` exists for tests/debugging only. Production code does not assign it
    # back to Forge; Forge's own extra-network parser strips the tag later.
    text: str
    schedule: Optional[CFGSchedule]
    errors: tuple[str, ...]
    tag_count: int


def _extract_schedule(text: str, tag_re: re.Pattern[str]) -> ExtractResult:
    """Inspect matching schedule tags. The last matching tag is authoritative."""
    if not isinstance(text, str) or not text:
        return ExtractResult(text=text, schedule=None, errors=(), tag_count=0)

    active: Optional[CFGSchedule] = None
    errors: list[str] = []
    tag_count = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal active, tag_count
        tag_count += 1
        try:
            active = parse_schedule(match.group(1))
        except CFGScheduleError as exc:
            # Last one wins includes failure: a malformed later tag disables an
            # earlier schedule rather than silently resurrecting it.
            active = None
            errors.append(f"{match.group(0)}: {exc}")
        return ""

    cleaned = tag_re.sub(replace, text)
    return ExtractResult(text=cleaned, schedule=active, errors=tuple(errors), tag_count=tag_count)


def extract_cfg_schedule(text: str) -> ExtractResult:
    return _extract_schedule(text, CFG_TAG_RE)


def extract_hrcfg_schedule(text: str) -> ExtractResult:
    return _extract_schedule(text, HRCFG_TAG_RE)


@dataclass(frozen=True)
class PromptScheduleResult:
    text: str
    cfg_schedule: Optional[CFGSchedule]
    hrcfg_schedule: Optional[CFGSchedule]
    cfg_tag_count: int
    hrcfg_tag_count: int
    errors: tuple[str, ...]


def extract_prompt_schedules(text: str) -> PromptScheduleResult:
    """Inspection helper; production uses its schedules but not its stripped text."""
    cfg = extract_cfg_schedule(text)
    hrcfg = extract_hrcfg_schedule(cfg.text)
    return PromptScheduleResult(
        text=hrcfg.text,
        cfg_schedule=cfg.schedule,
        hrcfg_schedule=hrcfg.schedule,
        cfg_tag_count=cfg.tag_count,
        hrcfg_tag_count=hrcfg.tag_count,
        errors=tuple(cfg.errors) + tuple(hrcfg.errors),
    )


def last_schedule(schedules: Iterable[Optional[CFGSchedule]]) -> Optional[CFGSchedule]:
    result: Optional[CFGSchedule] = None
    for schedule in schedules:
        if schedule is not None:
            result = schedule
    return result
