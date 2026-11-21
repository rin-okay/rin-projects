import math

import torch

from lumex_core import (
    DENOISE_MAX_INFLUENCE,
    LumexConfig,
    LumexConfigError,
    SplotchConfig,
    build_reference_gray,
    denoise_to_influence,
    influence_to_denoise,
    last_lumex_from_prompt,
    parse_lumex_payload,
    remove_lumex_tags,
    update_prompt_tag,
)


def test_legacy_lum_parse_and_tag_stays_compact():
    cfg = parse_lumex_payload("-0.35")
    assert cfg.lum == -0.35
    assert cfg.splotch is None
    assert cfg.strength == 1.0
    assert cfg.tag() == "<lumex:-0.35>"


def test_denoise_mapping():
    assert math.isclose(denoise_to_influence(0.0), 0.30)
    assert math.isclose(denoise_to_influence(0.5), 0.15)
    assert math.isclose(denoise_to_influence(0.85), 0.045)
    assert math.isclose(denoise_to_influence(1.0), 0.0)
    assert math.isclose(influence_to_denoise(0.15), 0.5)


def test_new_keyed_parse_uses_denoise():
    cfg = parse_lumex_payload("lum=0.2:splotch=8,0.25,2,bilinear:strength=0.5:denoise=0.8")
    assert cfg.lum == 0.2
    assert cfg.splotch == SplotchConfig(8, 0.25, 2.0, "bilinear")
    assert cfg.strength == 0.5
    assert math.isclose(cfg.splotch_influence, 0.06)
    assert cfg.tag() == "<lumex:lum=0.2:splotch=8,0.25,2,bilinear:strength=0.5:denoise=0.8>"


def test_denoise_wins_over_legacy_strength():
    cfg = parse_lumex_payload("splotch=8,0.25,2,bilinear:splotch_strength=0.75:denoise=0.5")
    assert math.isclose(cfg.splotch_influence, 0.15)
    assert cfg.tag() == "<lumex:splotch=8,0.25,2,bilinear:denoise=0.5>"


def test_legacy_strength_still_works_and_preserves_extreme_value():
    cfg = parse_lumex_payload("splotch=8,0.25,2,bilinear:splotch_strength=0.75")
    assert cfg.splotch_influence == 0.75
    assert cfg.tag() == "<lumex:splotch=8,0.25,2,bilinear:splotch_strength=0.75>"


def test_splotch_without_control_canonicalizes_to_equivalent_denoise():
    cfg = parse_lumex_payload("splotch=4,0.1,1,nearest")
    assert cfg.splotch is not None
    expected = influence_to_denoise(cfg.splotch_influence)
    assert f"denoise={format(expected, '.12g')}" in cfg.tag()


def test_invalid_denoise_rejected():
    try:
        parse_lumex_payload("splotch=8,0.2,2,bilinear:denoise=1.2")
    except LumexConfigError:
        pass
    else:
        raise AssertionError("expected LumexConfigError")


def test_last_tag_wins():
    found, cfg, err = last_lumex_from_prompt("a <lumex:-0.25> b <lumex:lum=0.4:splotch=8,0.2,2,bilinear:denoise=0.9>")
    assert found and err is None and cfg is not None
    assert cfg.lum == 0.4 and cfg.splotch is not None


def test_update_replaces_all_lumex_tags():
    prompt, tag = update_prompt_tag("cat <lumex:-0.2>\n<lumex:0.3>", LumexConfig(0.5))
    assert prompt == "cat\n<lumex:0.5>"
    assert tag == "<lumex:0.5>"


def test_flat_reference():
    cfg = LumexConfig(lum=-0.4)
    ref = build_reference_gray(cfg, 123, 64, 48)
    assert ref.shape == (1, 1, 48, 64)
    assert torch.allclose(ref, torch.full_like(ref, 0.3))


def test_splotch_reference_is_deterministic_and_spatial():
    cfg = LumexConfig(lum=0.0, splotch=SplotchConfig(8, 0.25, 2.0, "bilinear"))
    a = build_reference_gray(cfg, 12345, 96, 64)
    b = build_reference_gray(cfg, 12345, 96, 64)
    c = build_reference_gray(cfg, 12346, 96, 64)
    assert torch.allclose(a, b, atol=1e-4, rtol=1e-5)
    assert not torch.equal(a, c)
    assert float(a.std()) > 0.01


def test_splotch_amount_above_one_is_allowed_and_preview_clamps():
    cfg = LumexConfig(lum=0.0, splotch=SplotchConfig(8, 2.0, 2.0, "bilinear"))
    ref = build_reference_gray(cfg, 12345, 96, 64)
    assert 0.0 <= float(ref.min()) <= float(ref.max()) <= 1.0
    assert float(ref.min()) == 0.0 or float(ref.max()) == 1.0


def test_remove_tag():
    assert remove_lumex_tags("cat <lumex:lum=0.2:splotch=8,0.2,2,bilinear:denoise=0.9>") == "cat"
