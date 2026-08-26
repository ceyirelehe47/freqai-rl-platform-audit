"""工作包 H:隐藏输出最小化(脱敏 v2 的最小字段与匿名化)。"""

from __future__ import annotations

import json

from rl_curriculum.exam_pack import minimal_hidden_output, redact_report


def _verdict():
    return {
        "status": "FAIL", "grade": "G2",
        "hard_gates": {
            "split_positive::dev_seed_holdout": True,
            "split_positive::param_extrapolation": False,
            "split_positive::family_holdout": True,
            "vs_always_flat_bootstrap_ci_low_positive": True,
            "counterfactual::null_control": True,
        },
        "score_band": "band_small_positive",
        "recommendation": "do_not_proceed",
    }


def test_minimal_output_whitelist():
    out = minimal_hidden_output(
        attempt_id="a-x", checkpoint_hash="sha", pack_hash="p-1",
        verdict=_verdict(), integrity_ok=True)
    allowed = {
        "attempt_id", "checkpoint_hash", "pack_hash", "status", "grade",
        "hard_gates", "score_band", "integrity_ok", "recommendation",
        "redaction_note",
    }
    assert set(out) == allowed
    text = json.dumps(out)
    for forbidden in ("dev_seed_holdout", "param_extrapolation",
                      "family_holdout", "probe_", "q10", "worst", "best",
                      "\"seed\"", "\"params\"", "by_family"):
        assert forbidden not in text, forbidden


def test_split_names_anonymized():
    out = minimal_hidden_output(
        attempt_id="a", checkpoint_hash="h", pack_hash="p",
        verdict=_verdict(), integrity_ok=True)
    keys = list(out["hard_gates"])
    assert any(k.startswith("split_positive::split_") for k in keys)
    assert all("dev_seed" not in k and "family_holdout" not in k
               for k in keys)


def test_mock_hidden_redact_report_strips_aggregates():
    report = {
        "policy": "sb3:x", "policy_kind": "obs_only",
        "eval_config": {"fee": 0.001},
        "eval_config_hash": "ec-1", "observation_schema_hash": "o-1",
        "evaluator_code_hash": "e-1",
        "overall": {"median": 0.1, "q10": -0.1, "worst": -0.3},
        "by_family": {"probe_segmented_drift": {"median": 0.1}},
        "by_split": {"train": {"median": 0.1}},
        "by_param_bucket": {"probe_segmented_drift:weak": {"median": 0.1}},
        "episodes": [{"seed": 1, "params": {}}],
    }
    red = redact_report(report, "mock_hidden")
    assert "episodes" not in red
    assert "by_family" not in red and "by_split" not in red
    assert "by_param_bucket" not in red and "overall" not in red
    assert red["aggregates_redacted"] is True


def test_public_redact_keeps_aggregates():
    report = {"policy": "rule", "by_family": {"f": {"median": 0.1}},
              "episodes": [{"seed": 1}]}
    red = redact_report(report, "public")
    assert "by_family" in red
    assert "episodes" not in red
