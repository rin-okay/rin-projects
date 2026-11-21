import unittest

from cfg_scheduler_core import (
    CFGScheduleError,
    extract_cfg_schedule,
    extract_hrcfg_schedule,
    extract_prompt_schedules,
    parse_schedule,
    parse_schedule_parts,
)


class CFGSchedulerCoreTests(unittest.TestCase):
    def test_optional_final_endpoint_is_equivalent(self):
        short = parse_schedule("5,0.2:10,0.5:5")
        explicit = parse_schedule("5,0.2:10,0.5:5,1.0")
        self.assertEqual(short, explicit)
        self.assertEqual(short.canonical(), "5,0.2:10,0.5:5")

    def test_native_extra_network_parts(self):
        schedule = parse_schedule_parts(["1,5", "15,10", "2"])
        self.assertEqual(schedule.canonical(), "1,5:15,10:2")

    def test_absolute_step_schedule(self):
        schedule = parse_schedule("1,5:15,10:2")
        resolved = schedule.resolve(20)
        self.assertEqual([stage.end_step for stage in resolved.stages], [5, 10, 20])
        self.assertEqual(resolved.cfg_at_step(1), 1)
        self.assertEqual(resolved.cfg_at_step(5), 1)
        self.assertEqual(resolved.cfg_at_step(6), 15)
        self.assertEqual(resolved.cfg_at_step(10), 15)
        self.assertEqual(resolved.cfg_at_step(11), 2)
        self.assertEqual(resolved.cfg_at_step(20), 2)

    def test_integer_one_is_step_decimal_one_is_fraction(self):
        step_schedule = parse_schedule("5,1:10")
        self.assertEqual(step_schedule.stages[0].end.kind, "step")
        self.assertEqual(step_schedule.resolve(20).stages[0].end_step, 1)

        fraction_schedule = parse_schedule("5,1.0")
        self.assertEqual(fraction_schedule.stages[0].end.kind, "fraction")
        self.assertEqual(fraction_schedule.resolve(20).stages[0].end_step, 20)

    def test_mixed_step_and_fraction_schedule(self):
        schedule = parse_schedule("2,5:8,0.5:4")
        resolved = schedule.resolve(30)
        self.assertEqual([stage.end_step for stage in resolved.stages], [5, 15, 30])

    def test_percentages_use_ceil_endpoint(self):
        schedule = parse_schedule("3,0.3:9,0.5:4")
        resolved = schedule.resolve(25)
        self.assertEqual([stage.end_step for stage in resolved.stages], [8, 13, 25])

    def test_unlimited_style_stage_count(self):
        schedule = parse_schedule("4,1:6,2:8,3:10,4:12,5:10,6:8,7:6,8:4,9:2")
        self.assertEqual(len(schedule.stages), 10)
        resolved = schedule.resolve(20)
        self.assertEqual(resolved.cfg_at_step(1), 4)
        self.assertEqual(resolved.cfg_at_step(2), 6)
        self.assertEqual(resolved.cfg_at_step(20), 2)

    def test_percent_syntax(self):
        schedule = parse_schedule("5,20%:10,50%:5")
        self.assertEqual(schedule.canonical(), "5,0.2:10,0.5:5")
        self.assertEqual([s.end_step for s in schedule.resolve(20).stages], [4, 10, 20])

    def test_legacy_pipe_syntax_is_rejected(self):
        with self.assertRaisesRegex(CFGScheduleError, "legacy"):
            parse_schedule("1,5|15,10|2")

    def test_last_tag_wins(self):
        result = extract_cfg_schedule("x <CFG:1,.2:2> y <cfg:3,4:4> z")
        self.assertEqual(result.schedule.canonical(), "3,4:4")
        self.assertNotIn("<CFG", result.text.upper())

    def test_last_tag_wins_across_capitalization(self):
        result = extract_cfg_schedule("<cfg:1,3:2> x <CfG:5,4:6> x <CFG:7,5:8>")
        self.assertEqual(result.schedule.canonical(), "7,5:8")
        self.assertEqual(result.tag_count, 3)

    def test_invalid_last_tag_rejects_schedule(self):
        result = extract_cfg_schedule("<cfg:5,.5:7> text <cfg:3:9,.5>")
        self.assertIsNone(result.schedule)
        self.assertEqual(len(result.errors), 1)

    def test_valid_last_tag_can_follow_invalid_earlier_tag(self):
        result = extract_cfg_schedule("<cfg:3:9,.5> text <cfg:5,5:7>")
        self.assertEqual(result.schedule.canonical(), "5,5:7")
        self.assertEqual(len(result.errors), 1)

    def test_hrcfg_uses_same_schedule_grammar(self):
        result = extract_hrcfg_schedule("x <hrcfg:1,5:15,10:2> y")
        self.assertEqual(result.schedule.canonical(), "1,5:15,10:2")
        self.assertNotIn("HRCFG", result.text.upper())

    def test_cfg_and_hrcfg_are_independent_namespaces(self):
        result = extract_prompt_schedules(
            "x <cfg:3,5:7> y <hrcfg:2,4:8> z <cfg:4,6:5> <hrcfg:1,3:6>"
        )
        self.assertEqual(result.cfg_schedule.canonical(), "4,6:5")
        self.assertEqual(result.hrcfg_schedule.canonical(), "1,3:6")
        self.assertEqual(result.cfg_tag_count, 2)
        self.assertEqual(result.hrcfg_tag_count, 2)

    def test_inspection_does_not_require_mutating_source(self):
        source = "cat, <cfg:1,5:15,10:2>, <lora:foo:0.8>"
        result = extract_prompt_schedules(source)
        self.assertEqual(source, "cat, <cfg:1,5:15,10:2>, <lora:foo:0.8>")
        self.assertEqual(result.cfg_schedule.canonical(), "1,5:15,10:2")
        self.assertIn("<lora:foo:0.8>", result.text)

    def test_invalid_last_hrcfg_does_not_disable_cfg(self):
        result = extract_prompt_schedules("<cfg:3,5:7> <hrcfg:2,4:8> <hrcfg:3:9,.5>")
        self.assertEqual(result.cfg_schedule.canonical(), "3,5:7")
        self.assertIsNone(result.hrcfg_schedule)
        self.assertEqual(len(result.errors), 1)

    def test_invalid_last_cfg_does_not_disable_hrcfg(self):
        result = extract_prompt_schedules("<hrcfg:2,4:8> <cfg:3,5:7> <cfg:3:9,.5>")
        self.assertIsNone(result.cfg_schedule)
        self.assertEqual(result.hrcfg_schedule.canonical(), "2,4:8")
        self.assertEqual(len(result.errors), 1)

    def test_intermediate_endpoint_required(self):
        with self.assertRaises(CFGScheduleError):
            parse_schedule("5:10,.5:5")

    def test_same_kind_endpoints_strictly_increase(self):
        with self.assertRaises(CFGScheduleError):
            parse_schedule("5,10:10,5:5")
        with self.assertRaises(CFGScheduleError):
            parse_schedule("5,.5:10,.3:5")

    def test_mixed_backward_schedule_rejected_when_resolved(self):
        schedule = parse_schedule("5,12:10,0.5:5")
        with self.assertRaises(CFGScheduleError):
            schedule.resolve(20)

    def test_collapsed_fraction_boundaries_rejected_when_resolved(self):
        schedule = parse_schedule("5,.2:10,.3:5")
        with self.assertRaises(CFGScheduleError):
            schedule.resolve(3)

    def test_absolute_endpoint_beyond_pass_rejected(self):
        schedule = parse_schedule("5,30:10")
        with self.assertRaises(CFGScheduleError):
            schedule.resolve(20)

    def test_absolute_endpoint_at_pass_end_rejected_if_more_stages_follow(self):
        schedule = parse_schedule("5,20:10")
        with self.assertRaises(CFGScheduleError):
            schedule.resolve(20)

    def test_explicit_final_integer_is_improper_termination(self):
        with self.assertRaises(CFGScheduleError):
            parse_schedule("5,5:10,20")
        with self.assertRaises(CFGScheduleError):
            parse_schedule("5,0.2:10,1")

    def test_explicit_final_decimal_or_percent_must_be_end(self):
        with self.assertRaises(CFGScheduleError):
            parse_schedule("5,.2:10,.5")
        self.assertEqual(parse_schedule("5,.2:10,1.0").canonical(), "5,0.2:10")
        self.assertEqual(parse_schedule("5,20%:10,100%").canonical(), "5,0.2:10")

    def test_nonfinal_100_percent_is_rejected(self):
        with self.assertRaises(CFGScheduleError):
            parse_schedule("5,1.0:10")
        with self.assertRaises(CFGScheduleError):
            parse_schedule("5,100%:10")

    def test_decimal_greater_than_one_is_not_an_absolute_step(self):
        with self.assertRaises(CFGScheduleError):
            parse_schedule("5,5.0:10")

    def test_zero_step_is_rejected(self):
        with self.assertRaises(CFGScheduleError):
            parse_schedule("5,0:10")

    def test_cfg_one_mixed_schedule_needs_unconditional(self):
        self.assertTrue(parse_schedule("1,5:7").requires_unconditional)
        self.assertFalse(parse_schedule("1").requires_unconditional)

    def test_tag_uses_new_native_syntax(self):
        self.assertEqual(parse_schedule("1,5:15,10:2").tag(), "<cfg:1,5:15,10:2>")
        self.assertEqual(parse_schedule("2,4:8").tag("hrcfg"), "<hrcfg:2,4:8>")


if __name__ == "__main__":
    unittest.main()
