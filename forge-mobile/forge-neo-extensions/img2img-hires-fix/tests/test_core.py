import unittest

from img2img_hires_fix_core import (
    HiresSettingsError,
    SOURCE_DENOISE_METADATA_KEY,
    extract_exact_prompt_negative,
    merge_hires_infotext,
    normalize_hires_settings,
    parse_infotext_parameters,
)


def valid_settings():
    return {
        "denoising_strength": 0.35,
        "hr_scale": 1.5,
        "hr_upscaler": "Latent",
        "hr_second_pass_steps": 25,
        "hr_resize_x": 0,
        "hr_resize_y": 0,
        "hr_sampler_name": "Use same sampler",
        "hr_scheduler": "Use same scheduler",
        "hr_prompt": "detail, sharp focus",
        "hr_negative_prompt": "blur:1.2",
        "hr_cfg": 6.0,
        "hr_distilled_cfg": 3.0,
    }


class SettingsTests(unittest.TestCase):
    def test_normalizes_complete_settings(self):
        result = normalize_hires_settings(
            valid_settings(),
            available_upscalers=["Latent"],
            available_samplers=["Euler a"],
            available_schedulers=["Simple"],
        )
        self.assertEqual(result["hr_second_pass_steps"], 25)
        self.assertEqual(result["hr_prompt"], "detail, sharp focus")

    def test_rejects_unknown_runtime_choice(self):
        settings = valid_settings()
        settings["hr_upscaler"] = "Missing upscaler"
        with self.assertRaisesRegex(HiresSettingsError, "not available"):
            normalize_hires_settings(settings, available_upscalers=["Latent"])

    def test_rejects_non_finite_or_out_of_range_values(self):
        invalid = (
            ("denoising_strength", float("nan")),
            ("hr_scale", 8),
            ("hr_second_pass_steps", 25.5),
            ("hr_resize_x", 8192),
            ("hr_cfg", 0),
        )
        for key, value in invalid:
            with self.subTest(key=key, value=value):
                settings = valid_settings()
                settings[key] = value
                with self.assertRaises(HiresSettingsError):
                    normalize_hires_settings(settings)


class MetadataTests(unittest.TestCase):
    SOURCE = (
        "adult tiger <lora:workshop:0.8>\n"
        "Negative prompt: blurry, extra limbs\n"
        "Steps: 20, Sampler: Euler a, Schedule type: Simple, CFG scale: 6, "
        "Seed: 42, Size: 1024x1536, Denoising strength: 0.55, "
        "Model hash: abc123"
    )

    GENERATED = (
        "adult tiger <lora:workshop:0.8>\n"
        "Negative prompt: blurry, extra limbs\n"
        "Steps: 20, Sampler: Euler a, Schedule type: Simple, CFG scale: 6, "
        "Seed: 42, Size: 1024x1536, Denoising strength: 0.35, "
        "Hires upscale: 1.5, Hires upscaler: Latent, Hires steps: 25, "
        "Hires CFG Scale: 6, Img2img hires enabled: True, "
        "Img2img hires denoising strength: 0.35, "
        "Img2img hires prompt: \"detail, sharp focus\""
    )

    def test_exact_prompt_and_extra_network_tags_survive(self):
        merged = merge_hires_infotext(
            self.SOURCE, self.GENERATED, final_size="1536x2304"
        )
        prompt, negative = extract_exact_prompt_negative(merged)
        self.assertEqual(prompt, "adult tiger <lora:workshop:0.8>")
        self.assertEqual(negative, "blurry, extra limbs")

    def test_size_fields_are_not_corrupted_into_dash_one_dash_two(self):
        merged = merge_hires_infotext(
            self.SOURCE, self.GENERATED, final_size="1536x2304"
        )
        self.assertIn("Size: 1024x1536", merged)
        self.assertIn("Final Size: 1536x2304", merged)
        self.assertNotIn("Size-1", merged)
        self.assertNotIn("Size-2", merged)

    def test_source_and_hires_denoise_both_round_trip(self):
        merged = merge_hires_infotext(
            self.SOURCE, self.GENERATED, final_size="1536x2304"
        )
        params = parse_infotext_parameters(merged)
        self.assertEqual(params["Denoising strength"], "0.35")
        self.assertEqual(params[SOURCE_DENOISE_METADATA_KEY], "0.55")

    def test_comma_and_colon_values_are_quoted(self):
        merged = merge_hires_infotext(
            self.SOURCE, self.GENERATED, final_size="1536x2304"
        )
        self.assertIn('Img2img hires prompt: "detail, sharp focus"', merged)
        parsed = parse_infotext_parameters(merged)
        self.assertEqual(parsed["Img2img hires prompt"], "detail, sharp focus")

    def test_repeated_pass_drops_stale_native_hires_fields(self):
        old_source = self.SOURCE.replace(
            "Model hash: abc123",
            "Model hash: abc123, Hires sampler: DPM++ 2M, Hires schedule type: Karras",
        )
        merged = merge_hires_infotext(
            old_source, self.GENERATED, final_size="1536x2304"
        )
        params = parse_infotext_parameters(merged)
        self.assertNotIn("Hires sampler", params)
        self.assertNotIn("Hires schedule type", params)

    def test_explicit_defaults_replace_stale_destination_values(self):
        generated = self.GENERATED + (
            ", Img2img hires steps: 0, "
            "Img2img hires sampler: Use same sampler, "
            "Img2img hires schedule type: Use same scheduler, "
            "Img2img hires Distilled CFG scale: 3, "
            "Img2img hires negative prompt: "
        )
        # Remove the earlier native nonzero Hires steps so alias synthesis is
        # the behavior under test.
        generated = generated.replace("Hires steps: 25, ", "")
        merged = merge_hires_infotext(
            self.SOURCE, generated, final_size="1536x2304"
        )
        params = parse_infotext_parameters(merged)
        self.assertEqual(params["Hires steps"], "0")
        self.assertEqual(params["Hires sampler"], "Use same sampler")
        self.assertEqual(params["Hires schedule type"], "Use same scheduler")
        self.assertEqual(params["Hires Distilled CFG Scale"], "3")


if __name__ == "__main__":
    unittest.main()
