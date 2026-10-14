"""Prompt-tag configuration for hako-mikan Regional Prompter.

Intentionally independent of Forge so the parser can be tested without Torch.
The tag's defaults are fully specified, not inherited from Gradio state.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Optional, Sequence

TAG_RE = re.compile(r"<regional:([^<>]*)>", re.IGNORECASE)

class RegionalTagError(ValueError):
    pass


def _float(v, label, minimum=None, maximum=None):
    try:
        f = float(v)
    except (ValueError, TypeError) as e:
        raise RegionalTagError(f"{label} must be numeric") from e
    if not math.isfinite(f) or (minimum is not None and f < minimum) or (maximum is not None and f > maximum):
        raise RegionalTagError(f"{label} outside allowed range")
    return f


def _bool(v, label):
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    if s in ('1','on','yes','true','enabled'): return True
    if s in ('0','off','no','false','disabled'): return False
    raise RegionalTagError(f"{label} should be 1 or 0")


def _numbers(s, label, lo=0.0, hi=None, separators=',;'):
    if not s:
        raise RegionalTagError(f"{label} cannot be empty")
    if re.search(r'[^0-9.,;eE+\-\s]', s):
        raise RegionalTagError(f"{label} contains invalid characters")
    for v in re.split(r'[,;]', s):
        if not v.strip():
            raise RegionalTagError(f"{label} contains an empty value")
        _float(v.strip(), label, lo, hi)
    return s.replace(' ', '')


@dataclass(frozen=True)
class RegionalConfig:
    mode: str = 'columns'
    calc: str = 'attention'
    ratios: str = '1,1'
    base: bool = False
    blend: str = '0.2'
    common: bool = False
    ncommon: bool = False
    flip: bool = False
    threshold: float = 0.4
    hires: str = 'both'
    lora_stop: int = 0
    lora_hr_stop: int = 0
    sep: str = "ccc"

    def __post_init__(self):
        mode = str(self.mode).strip().lower().replace('_','-')
        calc = str(self.calc).strip().lower()
        hires = str(self.hires).strip().lower()
        if mode not in {'columns','rows','random','prompt','prompt-ex'}:
            raise RegionalTagError('mode must be columns, rows, random, prompt, or prompt-ex')
        if calc not in {'attention','latent'}:
            raise RegionalTagError('calc must be attention or latent')
        if hires not in {'both','only','off'}:
            raise RegionalTagError('hires must be both, only, or off')
        sep = str(self.sep).strip()
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,19}', sep):
            raise RegionalTagError('sep must be a short standalone word, e.g. ccc')
        if sep.upper() in {'BREAK','ADDCOL','ADDROW','ADDBASE','ADDCOMM','AND','ADDP'}:
            raise RegionalTagError('sep cannot be an existing Regional Prompter keyword')
        ratios = _numbers(str(self.ratios), 'ratios', lo=0.0)
        blend = _numbers(str(self.blend), 'blend', lo=0.0, hi=1.0)
        if all(float(v) == 0.0 for v in re.split(r'[,;]', ratios)):
            raise RegionalTagError('ratios must have a positive value')
        thr = _float(self.threshold, 'threshold', 0.0, 1.0)
        stops = []
        for value, label in [(self.lora_stop,'lora_stop'),(self.lora_hr_stop,'lora_hr_stop')]:
            if isinstance(value, bool):
                raise RegionalTagError(f'{label} must be a nonnegative integer')
            try:
                num = float(value)
            except (TypeError, ValueError) as exc:
                raise RegionalTagError(f'{label} must be a nonnegative integer') from exc
            if not math.isfinite(num) or num < 0 or not num.is_integer():
                raise RegionalTagError(f'{label} must be a nonnegative integer')
            iv = int(num)
            if iv > 100000: raise RegionalTagError(f'{label} is too large')
            stops.append(iv)
        for name in ('base','common','ncommon','flip'):
            object.__setattr__(self, name, _bool(getattr(self,name), name))
        for name, value in [('mode',mode),('calc',calc),('hires',hires),('ratios',ratios),('blend',blend),('threshold',thr),('lora_stop',stops[0]),('lora_hr_stop',stops[1]),('sep',sep)]:
            object.__setattr__(self,name,value)

    def tag(self):
        # Explicit values make the prompt self-contained and immune to future UI defaults.
        parts = [
            f'mode={self.mode}', f'calc={self.calc}', f'ratios={self.ratios}',
            f'base={int(self.base)}', f'blend={self.blend}',
            f'common={int(self.common)}',f'ncommon={int(self.ncommon)}',
            f'flip={int(self.flip)}',f'threshold={self.threshold:g}',
            f'sep={self.sep}',
            f'hires={self.hires}',
            f'lora_stop={self.lora_stop}', f'lora_hr_stop={self.lora_hr_stop}',
        ]
        return '<regional:' + ':'.join(parts) + '>'


KEYS = set(RegionalConfig.__dataclass_fields__)
ALIASES = {'direction':'mode', 'method':'calc','ratio':'ratios','baseratio':'blend','negative_common':'ncommon','lstop':'lora_stop','lstop_hr':'lora_hr_stop'}


def parse_regional_items(items: Sequence[str]) -> RegionalConfig:
    items = [str(x).strip() for x in items if str(x).strip()]
    if not items:
        raise RegionalTagError('regional tag requires parameters')
    data = {}
    positional = []
    for item in items:
        if '=' not in item:
            positional.append(item)
            continue
        key, val = item.split('=',1)
        key = ALIASES.get(key.strip().lower(), key.strip().lower())
        if key not in KEYS: raise RegionalTagError(f'unknown parameter {key!r}')
        if key in data: raise RegionalTagError(f'duplicate parameter {key!r}')
        data[key] = val.strip()
    if positional:
        if len(positional) > 3:
            raise RegionalTagError('shorthand is mode:ratios:calc (maximum 3 items)')
        for key, val in zip(('mode','ratios','calc'), positional):
            if key in data: raise RegionalTagError(f'duplicate parameter {key!r}')
            data[key] = val
    if not data: raise RegionalTagError('regional tag is empty')
    return RegionalConfig(**data)


def parse_regional_payload(payload: str) -> RegionalConfig:
    return parse_regional_items(str(payload).split(':'))


def last_regional_from_prompt(prompt: str):
    matches = list(TAG_RE.finditer(prompt or ''))
    if not matches: return False, None, None
    try:
        return True, parse_regional_payload(matches[-1].group(1)), None
    except RegionalTagError as exc:
        return True, None, str(exc)


def remove_regional_tags(prompt: str) -> str:
    return TAG_RE.sub('', prompt or '').rstrip()


def update_prompt_tag(prompt: str, config: Optional[RegionalConfig]):
    cleaned = remove_regional_tags(prompt)
    if config is None: return cleaned, 'Regional tag removed.'
    tag = config.tag()
    return cleaned + ('\n' if cleaned else '') + tag, tag
