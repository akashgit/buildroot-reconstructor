"""Tests for agent data models — BuildAttempt, DeadEndEntry, EvalResult."""

from buildroot.agent.models import (
    BuildAttempt,
    DeadEndEntry,
    EvalResult,
)


class TestDeadEndEntry:
    def test_not_exhausted_initially(self):
        de = DeadEndEntry(error_class="test", approach="try1")
        assert not de.is_exhausted

    def test_exhausted_after_threshold(self):
        de = DeadEndEntry(error_class="test", approach="try1", threshold=2)
        de.record_failure("error 1")
        assert not de.is_exhausted
        de.record_failure("error 2")
        assert de.is_exhausted

    def test_examples_capped_at_3(self):
        de = DeadEndEntry(error_class="test", approach="try1")
        for i in range(5):
            de.record_failure(f"error {i}")
        assert len(de.examples) == 3

    def test_to_dict(self):
        de = DeadEndEntry(error_class="jdk", approach="use jdk 11")
        de.record_failure("failed")
        d = de.to_dict()
        assert d["error_class"] == "jdk"
        assert d["failure_count"] == 1
        assert d["is_exhausted"] is False

    def test_custom_threshold(self):
        de = DeadEndEntry(error_class="test", approach="try1", threshold=5)
        for _ in range(4):
            de.record_failure("err")
        assert not de.is_exhausted
        de.record_failure("err")
        assert de.is_exhausted


class TestEvalResult:
    def test_all_levels_pass(self):
        er = EvalResult(l1_parse=True, l2_build=True, l3_command=True, l4_match=True)
        reward = er.compute_reward()
        assert reward == 1.0
        assert er.level_reached == 4

    def test_no_levels_pass(self):
        er = EvalResult()
        reward = er.compute_reward()
        assert reward == 0.0
        assert er.level_reached == 0

    def test_l1_only(self):
        er = EvalResult(l1_parse=True)
        reward = er.compute_reward()
        assert reward == 0.05
        assert er.level_reached == 1

    def test_l1_l2(self):
        er = EvalResult(l1_parse=True, l2_build=True)
        reward = er.compute_reward()
        assert abs(reward - 0.15) < 1e-9
        assert er.level_reached == 2

    def test_l1_l2_l3(self):
        er = EvalResult(l1_parse=True, l2_build=True, l3_command=True)
        reward = er.compute_reward()
        assert reward == 0.50
        assert er.level_reached == 3

    def test_l4prime_high_score_promotes_to_level_4(self):
        er = EvalResult(
            l1_parse=True, l2_build=True, l3_command=True,
            l4_score=1.0, l4_signal_source="fallback_signals",
        )
        er.compute_reward()
        assert er.reward == 1.0
        assert er.level_reached == 4

    def test_l4prime_low_score_stays_level_3(self):
        er = EvalResult(
            l1_parse=True, l2_build=True, l3_command=True,
            l4_score=0.7, l4_signal_source="fallback_signals",
        )
        er.compute_reward()
        assert er.level_reached == 3

    def test_l4prime_at_threshold_promotes(self):
        er = EvalResult(
            l1_parse=True, l2_build=True, l3_command=True,
            l4_score=0.98, l4_signal_source="fallback_signals",
        )
        er.compute_reward()
        assert er.level_reached == 4

    def test_l4prime_just_below_threshold_stays_level_3(self):
        er = EvalResult(
            l1_parse=True, l2_build=True, l3_command=True,
            l4_score=0.979, l4_signal_source="fallback_signals",
        )
        er.compute_reward()
        assert er.level_reached == 3

    def test_to_dict(self):
        er = EvalResult(l1_parse=True, l2_build=True)
        er.compute_reward()
        d = er.to_dict()
        assert abs(d["reward"] - 0.15) < 1e-9
        assert d["level_reached"] == 2


class TestBuildAttempt:
    def test_default_id(self):
        ba = BuildAttempt()
        assert ba.id
        assert len(ba.id) == 36  # uuid4

    def test_to_dict(self):
        ba = BuildAttempt(reward=0.5, level_reached=3, error_class="test")
        d = ba.to_dict()
        assert d["reward"] == 0.5
        assert d["level_reached"] == 3
        assert d["error_class"] == "test"
