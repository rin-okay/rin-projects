import unittest
from types import SimpleNamespace,ModuleType
from unittest.mock import patch
from PIL import Image
import lumex_core as c
import lumex_compare as compare

class CompareTests(unittest.TestCase):
    def test_metrics_report_noop_exactly(self):
        image=Image.new('RGB',(8,8),(128,128,128));metrics,diff=compare.image_metrics(image,image)
        self.assertEqual(metrics['mean_absolute_pixel_change'],0)
        self.assertEqual(diff.getextrema(),((0,0),(0,0),(0,0)))
    def render(self,applied=True):
        created=[]
        class P:
            def __init__(self,**kwargs):self.__dict__.update(kwargs);self.extra_generation_params={};created.append(self)
            def close(self):self.closed=True
        def process(p):
            p._lumex_applied=applied
            return SimpleNamespace(images=[Image.new('RGB',(64,64),'gray')],index_of_first_image=0)
        modules=ModuleType('modules');modules.processing=SimpleNamespace(StableDiffusionProcessingTxt2Img=P,process_images=process)
        modules.scripts=SimpleNamespace(ScriptRunner=lambda:SimpleNamespace())
        modules.shared=SimpleNamespace(state=SimpleNamespace(interrupted=False,stopping_generation=False))
        with patch.dict('sys.modules',{'modules':modules}):
            result=compare.render_pair(lambda:SimpleNamespace(), 'test <lumex:.2>', '', 23,64,64,10,6,c.LumexConfig(lum=.3,mode='tonal'))
        return created,result
    def test_pair_uses_same_seed_and_closes_processing(self):
        created,result=self.render()
        self.assertEqual([p.seed for p in created],[23,23]);self.assertEqual(created[0].prompt,'test')
        self.assertIn('mode=tonal',created[1].prompt)
        self.assertTrue(all(p.closed and p.do_not_save_samples and not p.enable_hr for p in created))
        self.assertEqual(len(result[0]),3)
    def test_unapplied_effect_is_reported_as_failure(self):
        with self.assertRaisesRegex(RuntimeError,'did not apply'):self.render(False)
