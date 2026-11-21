import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch
import torch
import torch.nn.functional as F
import lumex_core as c


class TestVAE:
    def __init__(self, stochastic=False, dtype=torch.float32):
        self.stochastic=stochastic; self.dtype=dtype; self.calls=0
    def encode_first_stage(self, image):
        self.calls+=1
        z=F.avg_pool2d(image.float().mean(dim=1,keepdim=True),8).repeat(1,4,1,1)
        z=z*torch.tensor([1,2,3,4]).view(1,4,1,1)
        if self.stochastic:z=z+torch.randn_like(z)*.03
        return z.to(self.dtype)


class CoreRegressions(unittest.TestCase):
    def setUp(self):
        self.noise=torch.zeros((1,4,8,8)); self.model=TestVAE()
        self.cfg=c.LumexConfig(splotch=c.SplotchConfig(4,.25,2,'bilinear'),splotch_influence=.3,mode='tonal')
    def apply(self,cfg,model=None):return c.apply_lumex(self.noise,model or self.model,cfg,[12],64,64)
    def test_old_tags_default_to_legacy(self):self.assertEqual(c.parse_lumex_payload('splotch=4,.25,2,bilinear').mode,'legacy')
    def test_tonal_tag_roundtrip(self):self.assertEqual(c.parse_lumex_payload(self.cfg.tag()[7:-1]),self.cfg)
    def test_bad_mode_rejected(self):
        with self.assertRaises(c.LumexConfigError):c.parse_lumex_payload('mode=other')
    def test_neutral_tonal_is_identity_without_vae(self):
        self.assertIs(self.apply(c.LumexConfig(mode='tonal')),self.noise); self.assertEqual(self.model.calls,0)
    def test_zero_amount_no_vae_or_injected_noise(self):
        for mode in ['tonal','legacy']:
            cfg=replace(self.cfg,mode=mode,splotch=replace(self.cfg.splotch,amount=0))
            self.assertIs(self.apply(cfg,TestVAE(True)),self.noise)
    def test_denoise_one_disables_preview_and_injection(self):
        cfg=replace(self.cfg,splotch_influence=0)
        self.assertTrue(torch.equal(c.build_tonal_map(cfg,12,64,64),torch.full((1,1,64,64),.5)))
        self.assertIs(self.apply(cfg),self.noise)
    def test_tonal_range_retains_strength(self):
        a=self.apply(replace(self.cfg,splotch=replace(self.cfg.splotch,amount=.05)))
        b=self.apply(replace(self.cfg,splotch=replace(self.cfg.splotch,amount=.1)))
        self.assertTrue(torch.allclose(b,2*a,atol=1e-5))
    def test_tonal_attenuation_scales_strength(self):
        a=self.apply(replace(self.cfg,splotch_influence=.15)); b=self.apply(self.cfg)
        self.assertTrue(torch.allclose(b,2*a,atol=1e-5))
    def test_preview_is_exact_tonal_control_map(self):
        preview,_=c.build_influence_preview(self.cfg,12,64,64)
        self.assertTrue(torch.equal(preview,c.build_tonal_map(self.cfg,12,64,64)))
        expected=F.avg_pool2d(preview*2-1,8).repeat(1,4,1,1)*torch.tensor([1,2,3,4]).view(1,4,1,1)
        self.assertTrue(torch.allclose(self.apply(self.cfg),expected,atol=2e-6))
    def test_black_white_are_calibrated_anchors(self):
        for lum in [-1,1]:
            result=self.apply(c.LumexConfig(lum=lum,mode='tonal'))
            expected=(torch.tensor([1.,2.,3.,4.])*lum).view(1,4,1,1).expand_as(result)
            self.assertTrue(torch.allclose(result,expected))
    def test_strength_zero_removes_lum_preview(self):
        cfg=c.LumexConfig(lum=.8,strength=0,mode='tonal')
        self.assertTrue(torch.all(c.build_tonal_map(cfg,1,64,64)==.5))
    def test_stochastic_vae_is_repeatable_and_rng_unchanged(self):
        for mode in ['tonal','legacy']:
            model=TestVAE(True);cfg=replace(self.cfg,mode=mode)
            before=torch.random.get_rng_state().clone();a=self.apply(cfg,model)
            self.assertTrue(torch.equal(before,torch.random.get_rng_state()))
            torch.randn(17);b=self.apply(cfg,model)
            self.assertTrue(torch.equal(a,b))
    def test_batch_matches_individual_images(self):
        for mode in ['tonal','legacy']:
            cfg=replace(self.cfg,mode=mode);model=TestVAE(True)
            both=c.apply_lumex(self.noise.repeat(2,1,1,1),model,cfg,[12,13],64,64)
            one=c.apply_lumex(self.noise,model,cfg,[13],64,64)
            self.assertTrue(torch.equal(both[1:],one))
    def test_missing_seed_rejected(self):
        with self.assertRaises(c.LumexConfigError):c.apply_lumex(self.noise,self.model,self.cfg,[],64,64)
    def test_fp16_output_finite(self):
        result=self.apply(replace(self.cfg,mode='legacy'),TestVAE(True,torch.float16))
        self.assertTrue(torch.isfinite(result).all())
    def test_legacy_rms_mapping_retained(self):
        result=self.apply(replace(self.cfg,mode='legacy',splotch_influence=.075))
        self.assertAlmostEqual(float(result.square().mean().sqrt()),.075,places=6)
    def test_nonfinite_vae_rejected(self):
        with patch.object(self.model,'encode_first_stage',return_value=torch.full((1,4,8,8),float('nan'))):
            with self.assertRaises(RuntimeError):self.apply(self.cfg)
    def test_rng_restored_when_vae_raises(self):
        before=torch.random.get_rng_state().clone()
        def fail(x):torch.randn(9);raise RuntimeError('fixture')
        with patch.object(self.model,'encode_first_stage',side_effect=fail):
            with self.assertRaises(RuntimeError):self.apply(self.cfg)
        self.assertTrue(torch.equal(before,torch.random.get_rng_state()))
    def test_channel_mismatch_rejected(self):
        with self.assertRaises(RuntimeError):c.apply_lumex(torch.zeros(1,3,8,8),self.model,self.cfg,[1],64,64)
    def test_invalid_dimensions_rejected(self):
        for width,height in [(-1,64),(8192,64),(8,4096),(64.1,64)]:
            with self.assertRaises(c.LumexConfigError):c.build_tonal_map(self.cfg,1,width,height)
    def test_forge_vae_fallback_uses_bhwc_and_process_in(self):
        seen=[]
        def encode(image):seen.append(image);return torch.ones(1,4,8,8)
        vae=SimpleNamespace(encode=encode,first_stage_model=SimpleNamespace(process_in=lambda x:x*2))
        model=SimpleNamespace(forge_objects=SimpleNamespace(vae=vae))
        out=c._encode_image_tensor(model,torch.ones(1,3,64,64)*.25)
        self.assertEqual(seen[0].shape,(1,64,64,3));self.assertTrue(torch.all(seen[0]==.25));self.assertTrue(torch.all(out==2))
