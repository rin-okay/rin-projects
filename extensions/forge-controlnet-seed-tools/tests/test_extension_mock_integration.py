"""Small simulation of Forge Neo's ControlNet process/sampling hooks.

A real Forge installation still needs an end-to-end smoke test.
"""
import importlib.util
import pathlib
import sys
import types
import unittest
from unittest.mock import patch

import numpy as np
import torch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class FakeUnit:
    def __init__(self, enabled=True, **kwargs):
        self.enabled = enabled
        self.module = kwargs.get('module', 'shuffle')
        self.processor_res = 16
        self.threshold_a = 1
        self.threshold_b = 1
        self.pixel_perfect = False


class FakeGroup:
    all_ui_groups = []

    def __init__(self):
        self.cnseed_vary = None
        self.cnseed_seed = None
        self.all_ui_groups.append(self)

    def render(self, name, tab):
        return FakeUnit()


class FakePreprocessor:
    name = 'shuffle'

    def __call__(self, **kwargs):
        # Distinct random sample in each image, exactly deterministic by seed.
        return np.random.randint(0, 255, size=(16, 16, 3), dtype=np.uint8)


class FakeParams:
    pass


class FakeControlNet:
    def __init__(self):
        self.infotext_fields = []
        self.paste_field_names = []
        self.current_params = {}

    def ui(self, img2img):
        items = []
        for i in range(2):
            g = FakeGroup()
            items.append(g.render(str(i), 'txt2img'))
        return items

    def get_enabled_units(self, units):
        return [v for v in units if v.enabled]

    def get_input_data(self, p, unit, preprocessor, h, w):
        return [ (np.zeros((16, 16, 3), dtype=np.uint8), None) ], None

    def get_target_dimensions(self, p):
        return 16, 16, 16, 16

    def process_unit_after_click_generate(self, p, unit, params):
        prep = FakePreprocessor()
        image_list, resize_mode = self.get_input_data(p, unit, prep, 16, 16)
        native_seed = int(p.all_seeds[0])
        with torch.random.fork_rng(devices=[]):
            np.random.seed(native_seed)
            m = prep(input_image=image_list[0][0])
        params.preprocessor = prep
        params.model = object()
        params.control_cond = torch.from_numpy(m[None].copy()).movedim(-1, 1).repeat(p.batch_size, 1, 1, 1)
        params.control_cond_for_hr_fix = params.control_cond

    def process(self, p, *args):
        self.current_params = {}
        for i, unit in enumerate(self.get_enabled_units(args)):
            params = FakeParams()
            self.process_unit_after_click_generate(p, unit, params)
            self.current_params[i] = params

    def process_unit_before_every_sampling(self, p, unit, params):
        return params.control_cond.clone()

    def process_before_every_sampling(self, p, *args):
        return [self.process_unit_before_every_sampling(p, unit, self.current_params[i])
                for i, unit in enumerate(self.get_enabled_units(args))]


FakeControlNet.__name__ = "ControlNetForForgeOfficial"


class P:
    batch_size = 3
    seed = 100
    all_seeds = list(range(100, 109))
    iteration = 0
    enable_hr = False

    def __init__(self):
        self.extra_generation_params = {}


class ExtensionMockTest(unittest.TestCase):
    def test_ui_process_and_batch_count(self):
        class Entry:
            script_class = FakeControlNet

        script_module = types.ModuleType('modules.scripts')
        script_module.scripts_data = [Entry()]
        modules = types.ModuleType('modules')
        modules.scripts = script_module
        cnet = types.ModuleType('lib_controlnet')
        cnet.external_code = types.ModuleType('lib_controlnet.external_code')
        cnet.external_code.ControlNetUnit = FakeUnit
        pkg = types.ModuleType('lib_controlnet.controlnet_ui')
        groupmod = types.ModuleType('lib_controlnet.controlnet_ui.controlnet_ui_group')
        groupmod.ControlNetUiGroup = FakeGroup
        utils = types.ModuleType('lib_controlnet.utils')
        utils.crop_and_resize_image = lambda m, resize_mode, h, w: m
        utils.judge_image_type = lambda m: isinstance(m, np.ndarray) and m.ndim == 3
        forge = types.ModuleType('modules_forge')
        forge_utils = types.ModuleType('modules_forge.utils')
        forge_utils.numpy_to_pytorch = lambda a: torch.from_numpy(a[None].copy())
        fake_modules = {
            'modules': modules,
            'modules.scripts': script_module,
            'lib_controlnet': cnet,
            'lib_controlnet.external_code': cnet.external_code,
            'lib_controlnet.controlnet_ui': pkg,
            'lib_controlnet.controlnet_ui.controlnet_ui_group': groupmod,
            'lib_controlnet.utils': utils,
            'modules_forge': forge,
            'modules_forge.utils': forge_utils,
        }
        with patch.dict(sys.modules, fake_modules):
            spec = importlib.util.spec_from_file_location(
                'controlnet_seed_extension_test', ROOT / 'scripts/controlnet_seed_tools.py'
            )
            extension = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(extension)
            import gradio as gr
            with gr.Blocks():
                runner = FakeControlNet()
                controls = runner.ui(False)
            self.assertEqual(len(controls), 2 + 2 * 2)
            self.assertEqual(controls[2].label, 'Vary preprocessor per image')
            self.assertEqual(controls[3].value, -1)
            unit0, unit1 = controls[:2]
            p = P()
            runner.process(p, unit0, unit1, True, -1, False, -1)
            first = runner.current_params[0].control_cond.clone()
            self.assertEqual(first.shape, (3, 3, 16, 16))
            self.assertFalse(torch.equal(first[0], first[1]))
            p.iteration = 1
            runner.process_before_every_sampling(p, unit0, unit1, True, -1, False, -1)
            second = runner.current_params[0].control_cond.clone()
            self.assertFalse(torch.equal(first[0], second[0]))
            # Re-generate a midbatch image alone using its own diffusion seed.
            p2 = P()
            p2.batch_size = 1
            p2.all_seeds = [104]
            p2.iteration = 0
            runner.process(p2, unit0, unit1, True, -1, False, -1)
            single = runner.current_params[0].control_cond
            self.assertTrue(torch.equal(second[1:2], single))
            # Independent static seed is stable across different image seeds.
            runner.process(p2, unit0, unit1, False, 777, False, -1)
            fixed = runner.current_params[0].control_cond.clone()
            p2.all_seeds = [456]
            runner.process(p2, unit0, unit1, False, 777, False, -1)
            self.assertTrue(torch.equal(fixed, runner.current_params[0].control_cond))


if __name__ == '__main__':
    unittest.main()
