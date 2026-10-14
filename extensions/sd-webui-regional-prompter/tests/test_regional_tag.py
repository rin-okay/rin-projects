import os
import sys
import types
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, ROOT)
from regional_core import RegionalConfig, RegionalTagError, parse_regional_payload, last_regional_from_prompt, update_prompt_tag


class TestParser(unittest.TestCase):
    def test_complete_roundtrip(self):
        a = RegionalConfig(mode='rows',calc='latent',ratios='1,2;2,1',base=True,blend='0.2,0.3',common=True,
                           ncommon=True,flip=True,hires='only', lora_stop=10,lora_hr_stop=3)
        b = parse_regional_payload(a.tag()[10:-1])
        self.assertEqual(a,b)

    def test_custom_separator_tag(self):
        c = RegionalConfig(ratios='2,3,4;1,2,7', sep='ccc')
        self.assertIn(':sep=ccc:',c.tag())
        self.assertEqual(parse_regional_payload(c.tag()[10:-1]),c)

    def test_invalid_separators(self):
        for val in ('BREAK','ADDCOL','', 'space here', '0', 'abc!'):
            with self.subTest(sep=val):
                with self.assertRaises(RegionalTagError):
                    RegionalConfig(sep=val)

    def test_shorthand(self):
        x = parse_regional_payload('rows:1,2:latent')
        self.assertEqual((x.mode, x.ratios, x.calc), ('rows','1,2','latent'))

    def test_case_insensitivity(self):
        found,cfg,error = last_regional_from_prompt('sky BREAK forest <REGIONAL:MODE=ROWS:RATIOS=1,1>')
        self.assertTrue(found)
        self.assertIsNone(error)
        self.assertEqual(cfg.mode,'rows')

    def test_last_wins(self):
        found,cfg,error = last_regional_from_prompt('<regional:mode=rows> <regional:mode=columns>')
        self.assertEqual(cfg.mode,'columns')

    def test_replace_preserves_other_extra_networks(self):
        s = '<lumex:0.2> BREAK woman <regional:mode=rows> <lora:a:0.8>'
        result, tag = update_prompt_tag(s, RegionalConfig(mode='columns'))
        self.assertIn('<lumex:0.2>',result)
        self.assertIn('<lora:a:0.8>',result)
        self.assertEqual(result.count('<regional:'), 1)
        self.assertTrue(result.endswith(tag))

    def test_invalid(self):
        for x in ['ratios=1,0,foo','mode=mask','calc=poetry','blend=2','hires=sometimes','base=maybe','ratios=0,0','wrong=1','lora_stop=1.5']:
            with self.subTest(x=x):
                with self.assertRaises(RegionalTagError): parse_regional_payload(x)

    def test_gradio_number_float(self):
        self.assertEqual(RegionalConfig(lora_stop=4.0).lora_stop, 4)


class TestBridge(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # stubs are intentionally separate from upstream: verify bridge semantics
        # without running Stable Diffusion or installing Gradio / Torch in tests.
        g = types.ModuleType('gradio')
        sys.modules['gradio'] = g
        modules = types.ModuleType('modules')
        extra = types.ModuleType('modules.extra_networks')
        class ExtraNetwork:
            def __init__(self,name): self.name=name
        extra.ExtraNetwork=ExtraNetwork
        extra.extra_network_registry={}
        extra.register_extra_network=lambda n:extra.extra_network_registry.update({n.name:n})
        extra.register_extra_network_alias=lambda *args:None
        scripts=types.ModuleType('modules.scripts')
        scripts.Script=type('BaseScript',(object,),{})
        scripts.AlwaysVisible = True
        scripts.scripts_data=[]
        modules.extra_networks=extra; modules.scripts=scripts
        sys.modules['modules']=modules
        sys.modules['modules.extra_networks']=extra
        sys.modules['modules.scripts']=scripts
        import importlib.util
        path=os.path.join(ROOT,'scripts','regional_tag.py')
        spec=importlib.util.spec_from_file_location('regional_bridge_under_test',path)
        bridge=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(bridge)
        cls.bridge=bridge
        cls.extra=extra

    def test_custom_sep_translated_for_matrix(self):
        p=types.SimpleNamespace(
            prompt='LEFT\nccc\nRIGHT\n<regional:mode=columns:ratios=4,4:sep=ccc>',
            all_prompts=['LEFT\nccc\nRIGHT\n<regional:mode=columns:ratios=4,4:sep=ccc>'],
            negative_prompt='noise',all_negative_prompts=['noise'])
        self.bridge._adapt_prompt_separators(p,'ccc')
        self.assertEqual(p.prompt.count('BREAK'),1)
        self.assertIn('<regional:mode=columns:',p.prompt)
        self.assertIn('BREAK',p.all_prompts[0])
        self.assertNotIn('BREAK',p.negative_prompt)
        self.assertEqual(self.bridge._replace_custom_separator('red ccc blue', 'ccc'),'red ccc blue')
        self.assertEqual(self.bridge._replace_custom_separator('ccc color', 'ccc'),'ccc color')

    def test_positional_arguments_match_upstream(self):
        original=[False,False,'Matrix','Columns','Mask','Prompt','1,1','0.2',False,False,False,
                  'Attention',[], '0','0','0.4',None,'0','0',False]
        cfg=RegionalConfig(mode='rows',calc='latent',ratios='2,1',base=True,blend='0.5',common=True,
                           ncommon=True,hires='off',flip=True,threshold=0.7,lora_stop=9)
        new=self.bridge._tag_overrides(original,cfg)
        self.assertTrue(new[0]);self.assertEqual(new[3],'Rows')
        self.assertEqual(new[11],'Latent');self.assertEqual(new[12],['Disabled in Hires Fix'])
        self.assertEqual((new[6],new[7],new[8],new[9],new[10]),('2,1','0.5',True,True,True))
        self.assertEqual(new[17],'9')
        self.assertEqual(original[3],'Columns')

    def test_native_extra_network_registration(self):
        # The tag gets parsed as a native extra network, just like <lora>.
        self.assertIn('regional', self.extra.extra_network_registry)
        params=types.SimpleNamespace(items=['mode=rows','ratios=2,1'])
        p=types.SimpleNamespace(_regional_tag_config=None)
        self.extra.extra_network_registry['regional'].activate(p,[params])
        self.assertEqual(p._regional_tag_config.ratios, '2,1')
        self.assertEqual(p._regional_tag_config.mode, 'rows')

    def test_native_prompt_metadata_path(self):
        # Forge Neo saves prompt text from p.all_prompts after restoring
        # p.prompts from it during postprocess_batch. The extension doesn't
        # need its own PNG Info callback or metadata field.
        tag='<regional:mode=rows:ratios=2,1>'
        p=types.SimpleNamespace(all_prompts=['left BREAK right\n'+tag])
        self.assertIn(tag, p.all_prompts[0])
        import re
        p.prompts=[re.sub(r'<(\w+):([^>]+)>','',p.all_prompts[0])]
        self.assertNotIn(tag,p.prompts[0])
        p.prompts=p.all_prompts[:]
        self.assertIn(tag,p.prompts[0])

    def test_wrapped_matrix_uses_native_break_conversion(self):
        seen=[]
        class RP:
            def process(self,p,*args):
                seen.append((p.prompt,p.all_prompts[:],args[2],args[3],args[6]))
        self.bridge._wrap_rp_class(RP)
        args=[False,False,'Matrix','Columns','Mask','Prompt','1,1','0.2',False,False,False,'Attention',[], '0','0','0.4',None,'0','0',False]
        prompt=('top-left\nccc\ntop-right\nccc\nbottom\n'
                '<regional:mode=columns:calc=attention:ratios=2,2,2;2,4:sep=ccc>')
        p=types.SimpleNamespace(prompt=prompt,all_prompts=[prompt],negative_prompt='',
                                all_negative_prompts=[''],extra_generation_params={})
        RP().process(p,*args)
        actual, batch, tab, submode, ratios=seen[-1]
        self.assertEqual(actual.count('BREAK'),2)
        self.assertEqual(batch[0].count('BREAK'),2)
        self.assertEqual((tab,submode,ratios),('Matrix','Columns','2,2,2;2,4'))
        self.assertIn('<regional:',actual)

    def test_wrapped_upstream_process(self):
        seen=[]
        class RP:
            def process(self,p,*args):
                seen.append(tuple(args))
                p.extra_generation_params['RP Ratios'] = args[6]
        self.bridge._wrap_rp_class(RP)
        args=[False,False,'Matrix','Columns','Mask','Prompt','1,1','0.2',False,False,False,'Attention',[], '0','0','0.4',None,'0','0',False]
        p=types.SimpleNamespace(prompt='cat BREAK dog <regional:mode=rows:ratios=2,1>',extra_generation_params={})
        RP().process(p,*args)
        self.assertEqual(seen[-1][3],'Rows')
        self.assertTrue(seen[-1][0])
        self.assertNotIn('Regional Tag',p.extra_generation_params)
        self.assertNotIn('RP Ratios',p.extra_generation_params)
        no_tag=types.SimpleNamespace(prompt='cat BREAK dog',extra_generation_params={})
        RP().process(no_tag,*args)
        self.assertFalse(seen[-1][0])


if __name__ == '__main__': unittest.main()
