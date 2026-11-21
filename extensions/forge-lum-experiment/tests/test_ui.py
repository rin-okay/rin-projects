import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch
import torch
import gradio as gr
import lumex_core as core


class FakeScript:
    def on_after_component(self,*args,**kwargs):pass

class FakeNetwork:
    def __init__(self,name):self.name=name


def load_ui():
    modules=types.ModuleType('modules')
    registry={};extra=types.SimpleNamespace(ExtraNetwork=FakeNetwork,extra_network_registry=registry,
        register_extra_network=lambda x:registry.update({x.name:x}),register_extra_network_alias=lambda *x:None)
    modules.extra_networks=extra;modules.scripts=types.SimpleNamespace(Script=FakeScript,AlwaysVisible=True)
    modules.shared=types.SimpleNamespace(sd_model=None)
    modules.ui=types.SimpleNamespace(detect_image_size_symbol='size',reuse_symbol='reuse')
    def button(*args,**kwargs):kwargs.pop('tooltip',None);return gr.Button(*args,**kwargs)
    stubs={'modules':modules,'modules.processing_scripts':types.ModuleType('modules.processing_scripts'),
           'modules.processing_scripts.seed':types.SimpleNamespace(connect_reuse_seed=lambda *x:None),
           'modules.ui_components':types.SimpleNamespace(ToolButton=button)}
    with patch.dict(sys.modules,stubs):
        spec=importlib.util.spec_from_file_location('lumex_ui_test',Path(core.__file__).parent/'scripts/lum_experiment.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


class UITests(unittest.TestCase):
    def setUp(self):self.ui=load_ui()
    def test_random_preview_returns_resolved_seed(self):
        raw,effect,status,seed=self.ui._preview_reference(-1,64,64,0,True,4,.25,2,'bilinear',1,.5)
        self.assertNotEqual(seed,-1);self.assertEqual(raw.size,(64,64));self.assertEqual(effect.size,(64,64))
        repeated=self.ui._preview_reference(seed,64,64,0,True,4,.25,2,'bilinear',1,.5)
        self.assertEqual(effect.tobytes(),repeated[1].tobytes())
    def test_preview_strength_is_visible(self):
        a=self.ui._preview_reference(1,64,64,.5,False,4,.25,2,'bilinear',0,1)[1]
        b=self.ui._preview_reference(1,64,64,.5,False,4,.25,2,'bilinear',1,1)[1]
        self.assertNotEqual(a.tobytes(),b.tobytes())
    def test_legacy_extreme_load_update_preserved(self):
        tag='<lumex:splotch=4,0.25,2,bilinear:splotch_strength=0.75>'
        vals=self.ui._load_prompt(tag,0,4,.25,2,'bilinear',1,.85)
        self.assertEqual(vals[8],'legacy');self.assertEqual(vals[9],.75)
        updated=self.ui._update_prompt(tag,*vals[:10])[0]
        self.assertEqual(core.last_lumex_from_prompt(updated)[1].splotch_influence,.75)
    def test_real_gradio_ui_construction(self):
        with gr.Blocks(analytics_enabled=False) as blocks:
            script=self.ui.Script();script._prompt_component=gr.Textbox();script._negative_component=gr.Textbox();script._seed_component=gr.Number()
            script._txt2img_width_component=gr.Number(value=512);script._txt2img_height_component=gr.Number(value=512)
            self.assertEqual(script.ui(False),[])
        self.assertGreater(len(blocks.get_config_file()["dependencies"]),4)
    def test_hr_and_img2img_are_skipped(self):
        for attr in ['is_hr_pass','init_images']:
            p=types.SimpleNamespace(**{attr:True},modified_noise=None)
            self.ui.Script().process_before_every_sampling(p,noise=torch.ones(1,4,8,8))
            self.assertIsNone(p.modified_noise)
    def test_hook_composes_existing_noise_and_records_success(self):
        p=types.SimpleNamespace(modified_noise=torch.ones(1,4,8,8)*3,
            _lumex_config=core.LumexConfig(lum=.2),seeds=[1],width=64,height=64,extra_generation_params={})
        with patch.object(self.ui,'apply_lumex',side_effect=lambda noise,*a:noise+1):
            self.ui.Script().process_before_every_sampling(p,noise=torch.zeros(1,4,8,8))
        self.assertTrue(torch.all(p.modified_noise==4));self.assertTrue(p._lumex_applied)
    def test_hook_error_is_visible_in_metadata(self):
        p=types.SimpleNamespace(modified_noise=None,_lumex_config=core.LumexConfig(lum=.2),seeds=[1],width=64,height=64,extra_generation_params={})
        with patch.object(self.ui,'apply_lumex',side_effect=RuntimeError('fixture error')):
            self.ui.Script().process_before_every_sampling(p,noise=torch.zeros(1,4,8,8))
        self.assertEqual(p.extra_generation_params['Lumex error'],'fixture error')
