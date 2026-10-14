"""Regional Prompter prompt-tag bridge, based on Lum Experiment's extra-network pattern.

This add-on lives INSIDE the upstream sd-webui-regional-prompter extension.
It wraps, but does not replace, upstream rp.Script.process and its model hooks.
"""
from __future__ import annotations

import itertools
import logging
import re
import sys
from functools import wraps

import gradio as gr
from modules import extra_networks, scripts

from regional_core import (
    RegionalConfig, RegionalTagError,
    last_regional_from_prompt, parse_regional_items,
    update_prompt_tag,
)

LOG = logging.getLogger('regional-prompter-tag')
NAMESPACE = 'regional'


class _RegionalExtraNetwork(extra_networks.ExtraNetwork):
    def activate(self, p, params_list):
        if not params_list:
            p._regional_tag_config = None
            return None
        try:
            p._regional_tag_config = parse_regional_items(list(getattr(params_list[-1], 'items', []) or []))
        except RegionalTagError as exc:
            p._regional_tag_config = None
            LOG.warning('Invalid <regional:...> extra network tag: %s', exc)
        return None

    def deactivate(self, p):
        p._regional_tag_config = None
        return None


_NETWORK = _RegionalExtraNetwork(NAMESPACE)


def _ensure_network():
    reg = extra_networks.extra_network_registry
    if reg.get(NAMESPACE) is not _NETWORK:
        if reg.get(NAMESPACE) is not None:
            LOG.warning('Another extra-network handler owns %r; replacing it.', NAMESPACE)
        extra_networks.register_extra_network(_NETWORK)
    # Same mixed-case aliases as Lum Experiment; avoids prompt case surprises.
    for choices in itertools.product(*[(ch.lower(), ch.upper()) for ch in NAMESPACE]):
        name = ''.join(choices)
        if name != NAMESPACE:
            extra_networks.register_extra_network_alias(_NETWORK, name)


def _string_prompt(p):
    # rp.py itself reads p.prompt before changing all_prompts.
    prompt = getattr(p, 'prompt', '')
    if isinstance(prompt, list):
        return str(prompt[0]) if prompt else ''
    return str(prompt or '')


def _tag_overrides(args, config):
    """Map tag values to the original positional Gradio argument list.

    Keep the upstream signature and its hooks unchanged. Upstream's latent,
    DiT, LoRA, masked-attention and Hires Fix internals remain authoritative.
    """
    values = list(args)
    if len(values) < 20:
        raise RegionalTagError('upstream rp.Script.process has an unexpected argument signature')
    values[0] = True
    if config.mode in ('prompt','prompt-ex'):
        values[2] = 'Prompt'
        values[5] = 'Prompt-Ex' if config.mode == 'prompt-ex' else 'Prompt'
    else:
        values[2] = 'Matrix'
        values[3] = {'columns':'Columns','rows':'Rows','random':'Random'}[config.mode]
    values[6] = config.ratios
    values[7] = config.blend
    values[8] = config.base
    values[9] = config.common
    values[10] = config.ncommon
    values[11] = config.calc.capitalize()
    # The tagged configuration should not inherit old checkbox/preset options.
    options = []
    if config.hires == 'only':
        options.append('Enabled only in Hires Fix')
    elif config.hires == 'off':
        options.append('Disabled in Hires Fix')
    values[12] = options
    values[15] = str(config.threshold)
    # values[16] is the original mask, not supported by v1 tags.
    values[17] = str(config.lora_stop)
    values[18] = str(config.lora_hr_stop)
    values[19] = config.flip
    return values


def _replace_custom_separator(text, separator):
    """Translate a standalone custom separator line to the original RP BREAK.

    Original RP turns BREAK into ADDROW / ADDCOL according to matrix ratios.
    No duplicate matrix encoder, attention hook, or metadata callback.
    """
    pattern = r'(?m)^[ \t]*' + re.escape(separator) + r'[ \t]*(?=\r?$)'
    return re.sub(pattern, ' BREAK ', str(text), flags=re.IGNORECASE)


def _adapt_prompt_separators(p, sep):
    """Apply to both RP's prompt and prompt list before its normal processing."""
    for attr in ('prompt','negative_prompt','all_prompts','all_negative_prompts'):
        src = getattr(p,attr,None)
        if isinstance(src,str):
            setattr(p,attr,_replace_custom_separator(src,sep))
        elif isinstance(src,list):
            setattr(p,attr,[_replace_custom_separator(x,sep) if isinstance(x,str) else x for x in src])


def _wrap_rp_class(cls):
    if getattr(cls, '_regional_tag_bridge_patched', False):
        return False
    original = cls.process

    @wraps(original)
    def tagged_process(self, p, *args, **kwargs):
        _ensure_network()
        present, config, error = last_regional_from_prompt(_string_prompt(p))
        p._regional_tag_requested = bool(present)
        if not present:
            return original(self, p, *args, **kwargs)
        if error or config is None:
            LOG.warning('Ignoring invalid <regional:...> tag: %s', error)
            p.extra_generation_params['Regional Tag Error'] = error or 'invalid tag'
            # Fail closed, do not accidentally use stale enabled UI settings.
            disabled = list(args)
            if disabled:
                disabled[0] = False
            return original(self, p, *disabled, **kwargs)
        try:
            values = _tag_overrides(args, config)
        except RegionalTagError as exc:
            p.extra_generation_params['Regional Tag Error'] = str(exc)
            LOG.error('Cannot apply regional tag: %s', exc)
            disabled = list(args)
            if disabled: disabled[0] = False
            return original(self, p, *disabled, **kwargs)
        p._regional_tag_config = config
        # Native prompt-based handling. RP already maps BREAK -> ADDROW/ADDCOL
        # using its own makeimgtmp/keyconverter; only the alias is translated.
        _adapt_prompt_separators(p, config.sep)
        outcome = original(self, p, *values, **kwargs)
        # Do not write the tag to extra_generation_params or implement a PNG Info
        # reinsertion callback. Forge Neo keeps original extra-network tags in
        # p.all_prompts, then uses those prompts for its normal image infotext.
        # The upstream RP script does transform region separators in its prompt
        # processing, but the <regional:...> tag survives unchanged in the text.
        # RP's old per-control fields are redundant and can override the tag
        # when a PNG is sent back to txt2img/img2img, so suppress just those.
        for key in list(p.extra_generation_params):
            if key.startswith('RP '):
                del p.extra_generation_params[key]
        return outcome

    cls.process = tagged_process
    cls._regional_tag_bridge_patched = True
    return True


def _patch_upstream():
    """Locate the ALREADY-loaded upstream class, avoiding a duplicate import.

    Forge loads extension scripts with a dynamic module name, so importing
    scripts.rp here would risk wrapping a different copy of the class.
    """
    def is_upstream(cls, path):
        if not isinstance(cls, type) or not path.endswith('/scripts/rp.py'):
            return False
        method = getattr(cls, 'process', None)
        namespace = getattr(method, '__globals__', {})
        return ('RPMODES' in namespace and 'ALLALLKEYS' in namespace
                and 'tabs2mode' in namespace)

    count = 0
    for data in getattr(scripts, 'scripts_data', []) or []:
        cls = getattr(data, 'script_class', None)
        path = str(getattr(data, 'path', '') or '').replace('\\', '/').lower()
        if is_upstream(cls, path):
            count += int(_wrap_rp_class(cls))
    for module in tuple(sys.modules.values()):
        if module is None:
            continue
        path = str(getattr(module, '__file__', '') or '').replace('\\', '/').lower()
        cls = getattr(module, 'Script', None)
        if is_upstream(cls, path):
            count += int(_wrap_rp_class(cls))
    return count


# Identical extra-network registration lifecycle to Lum Experiment.
# PNG Info restoration is entirely Forge Neo's responsibility. No hook,
# custom infotext field, or prompt-mutation fallback is installed.
_ensure_network()


def _ui_config(mode, calc, ratios, base, blend, common, ncommon, flip, threshold, hires, lora_stop, lora_hr_stop, sep):
    return RegionalConfig(mode, calc, ratios, base, blend, common, ncommon, flip, threshold, hires, lora_stop, lora_hr_stop, sep)


def _update_prompt(prompt, *values):
    try:
        return update_prompt_tag(prompt or '', _ui_config(*values))
    except (RegionalTagError, ValueError) as exc:
        return prompt, f'Regional tag error: {exc}'


def _load_prompt(prompt, *current):
    found, cfg, error = last_regional_from_prompt(prompt or '')
    if error:
        return (*current, f'Invalid regional tag: {error}')
    if not found or cfg is None:
        return (*current, 'No regional tag found in prompt.')
    return (cfg.mode, cfg.calc, cfg.ratios, cfg.base, cfg.blend,
            cfg.common, cfg.ncommon, cfg.flip, cfg.threshold,
            cfg.hires, cfg.lora_stop, cfg.lora_hr_stop, cfg.sep, 'Loaded: ' + cfg.tag())


class Script(scripts.Script):
    """Tag editor only. The original upstream RP script runs the generation."""
    sorting_priority = 100

    def __init__(self):
        self._prompt_component = None

    def title(self):
        return 'Regional Prompt Tag'

    def show(self, is_img2img):
        _patch_upstream()
        prompt_id = 'img2img_prompt' if is_img2img else 'txt2img_prompt'
        self.on_after_component(lambda x: setattr(self, '_prompt_component', x.component), elem_id=prompt_id)
        return scripts.AlwaysVisible

    def ui(self, is_img2img):
        patched = _patch_upstream()
        if not patched and not any(getattr(getattr(x, 'script_class', None), '_regional_tag_bridge_patched', False) for x in getattr(scripts, 'scripts_data', []) or []):
            LOG.warning('Regional Prompter script not yet found; will retry during generation')
        with gr.Accordion(label=self.title(), open=False):
            gr.Markdown('Configure a `<regional:...>` tag. The tag enables Regional Prompter; the editor controls do **not** affect generation until you click Add/update. Use standalone `ccc` separator lines with `sep=ccc`, or existing `BREAK`/`ADDROW`/`ADDCOL` markers. The original RP accordion remains available for masks and visualization.')
            with gr.Row():
                mode = gr.Dropdown(['columns','rows','random','prompt','prompt-ex'], value='columns', label='Region mode')
                calc = gr.Radio(['attention','latent'], value='attention', label='Calculation')
            ratios = gr.Textbox(label='Division ratios (commas / semicolons for 2D)', value='1,1')
            sep = gr.Textbox(label='Custom region separator (one line per separator)', value='ccc')
            with gr.Row():
                base = gr.Checkbox(label='Use base prompt', value=False)
                blend = gr.Textbox(label='Base blend ratio', value='0.2')
            with gr.Row():
                common = gr.Checkbox(label='Use common positive prompt', value=False)
                ncommon = gr.Checkbox(label='Use common negative prompt', value=False)
                flip = gr.Checkbox(label='Flip comma / semicolon orientation', value=False)
            with gr.Row():
                threshold = gr.Slider(label='Prompt threshold (prompt modes)', minimum=0.0, maximum=1.0, step=0.01, value=0.4)
                hires = gr.Dropdown(['both','only','off'], label='Hires Fix passes', value='both')
            with gr.Row():
                lora_stop = gr.Number(label='LoRA stop step (0 = upstream default)', value=0, precision=0)
                lora_hr_stop = gr.Number(label='LoRA Hires stop step (0 = upstream default)', value=0, precision=0)
            with gr.Row():
                load = gr.Button('Load tag from prompt', variant='secondary')
                update = gr.Button('Add/update prompt tag', variant='primary')
            status = gr.Textbox(label='Tag status', interactive=False)
        prompt = self._prompt_component
        if prompt is not None:
            controls = [mode, calc, ratios, base, blend, common, ncommon, flip, threshold, hires, lora_stop, lora_hr_stop, sep]
            update.click(fn=_update_prompt, inputs=[prompt, *controls], outputs=[prompt, status], queue=False)
            load.click(fn=_load_prompt, inputs=[prompt, *controls], outputs=[*controls, status], queue=False)
        else:
            LOG.warning('Could not capture prompt for regional tag editor; manual tags still work')
        return []

    def process(self, p, *args):
        # Can also catch installations where scripts_data is populated late.
        _patch_upstream()
