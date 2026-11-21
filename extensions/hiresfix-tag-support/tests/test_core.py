import unittest

from hiresfix_tag_core import (
    HiresFixTagConfig,
    HiresFixTagError,
    parse_prompt,
    replace_or_append,
    serialize,
)


class HiresFixTagCoreTests(unittest.TestCase):
    def test_minimal_defaults(self):
        cfg = parse_prompt("<hiresfix:Latent:0.35:1.5:6:25>")
        self.assertEqual(cfg.resize_x, 0)
        self.assertEqual(cfg.resize_y, 0)
        self.assertEqual(cfg.sampler, "Use same sampler")
        self.assertEqual(cfg.scheduler, "Use same scheduler")
        self.assertEqual(cfg.distilled_cfg, 3.0)

    def test_roundtrip_full(self):
        cfg = HiresFixTagConfig(
            "4x-UltraSharp",
            0.25,
            1.5,
            5.5,
            30,
            1536,
            0,
            "DPM++ 2M",
            "Karras",
            2.5,
        )
        self.assertEqual(parse_prompt(serialize(cfg)), cfg)

    def test_write_preserves_other_extra_networks(self):
        prompt = "girl <lora:stuff:0.8> <cfg:1,5:15,10:2>"
        cfg = HiresFixTagConfig("Latent", 0.35, 1.5, 6, 25)
        result = replace_or_append(prompt, cfg)
        self.assertIn("<lora:stuff:0.8>", result)
        self.assertIn("<cfg:1,5:15,10:2>", result)
        self.assertIn("<hiresfix:Latent:0.35:1.5:6:25>", result)

    def test_update_only_hiresfix(self):
        prompt = "x <lora:a:1> <hiresfix:Latent:0.2:2:5:20> <lum:-0.5>"
        cfg = HiresFixTagConfig("Latent", 0.4, 1.5, 6, 25)
        result = replace_or_append(prompt, cfg)
        self.assertIn("<lora:a:1>", result)
        self.assertIn("<lum:-0.5>", result)
        self.assertEqual(result.count("<hiresfix:"), 1)

    def test_write_removes_all_older_duplicates(self):
        prompt = (
            "x <hiresfix:Latent:0.2:2:5:20> y "
            "<hiresfix:Latent:0.3:1.5:6:25> z"
        )
        result = replace_or_append(
            prompt, HiresFixTagConfig("Latent", 0.4, 1.75, 7, 30)
        )
        self.assertEqual(result.count("<hiresfix:"), 1)
        self.assertIn("<hiresfix:Latent:0.4:1.75:7:30>", result)

    def test_blank_optional_fields_use_defaults(self):
        cfg = parse_prompt(
            "<hiresfix:Latent:0.35:1.5:6:25:  : :Use same sampler>"
        )
        self.assertEqual((cfg.resize_x, cfg.resize_y), (0, 0))

    def test_fractional_integer_field_is_rejected(self):
        with self.assertRaisesRegex(HiresFixTagError, "whole number"):
            parse_prompt("<hiresfix:Latent:0.35:1.5:6:25.5>")

    def test_non_finite_numbers_are_rejected(self):
        for value in ("nan", "inf", "-inf"):
            with self.subTest(value=value):
                with self.assertRaises(HiresFixTagError):
                    parse_prompt(f"<hiresfix:Latent:0.35:{value}:6:25>")

    def test_ui_range_limits_are_enforced(self):
        invalid_tags = (
            "<hiresfix:Latent:0.35:4.01:6:25>",
            "<hiresfix:Latent:0.35:1.5:24.1:25>",
            "<hiresfix:Latent:0.35:1.5:6:151>",
            "<hiresfix:Latent:0.35:1.5:6:25:4104:0>",
        )
        for tag in invalid_tags:
            with self.subTest(tag=tag):
                with self.assertRaises(HiresFixTagError):
                    parse_prompt(tag)

    def test_choice_delimiters_are_rejected(self):
        with self.assertRaises(HiresFixTagError):
            serialize(HiresFixTagConfig("Bad:Upscaler", 0.35, 1.5, 6, 25))


if __name__ == "__main__":
    unittest.main()
