"""工作包 G:泛化等级 G0-G5 分类与判定状态机。"""

from __future__ import annotations

from rl_curriculum.grades import classify_generalization
from rl_curriculum.transfer import (
    TransferProtocolSpec,
    conclude_transfer,
    run_blank_demo,
)
from rl_curriculum.verdicts import (
    CHEAT_REASONS,
    CourseStatus,
    ModelStatus,
    course_status_of,
    status_of,
)


def _synth(train, dev, ext, fam):
    return {"by_split": {
        "train": {"n": 6, "median": train},
        "dev_seed_holdout": {"n": 4, "median": dev},
        "param_extrapolation": {"n": 4, "median": ext},
        "family_holdout": {"n": 4, "median": fam},
    }}


def test_g0_train_only():
    assert classify_generalization(_synth(.1, -.1, -.1, -.1))["grade"] == "G0"


def test_g0_even_with_bad_train():
    assert classify_generalization(_synth(-.1, .1, .1, .1))["grade"] == "G0"


def test_g1_seed_only():
    g = classify_generalization(_synth(.1, .05, -.1, -.1))
    assert g["grade"] == "G1"
    assert "G1" in g["note"]  # 不得单独称为真正泛化


def test_g2_param_pass_family_fail():
    assert classify_generalization(_synth(.1, .05, .05, -.1))["grade"] == "G2"


def test_g3_family_without_cf():
    g = classify_generalization(_synth(.1, .05, .05, .05))
    assert g["grade"] == "G3"


def test_g4_requires_cf():
    assert classify_generalization(
        _synth(.1, .05, .05, .05), counterfactual_all_pass=True)["grade"] == "G4"
    assert classify_generalization(
        _synth(.1, .05, .05, .05), counterfactual_all_pass=False)["grade"] == "G3"


def test_cheating_blocks_upgrade():
    g = classify_generalization(
        _synth(.1, .05, .05, .05), counterfactual_all_pass=True,
        cheating_detected=True)
    assert g["grade"] == "G3"  # 作弊另行判 SUSPECTED_CHEATING


def test_real_rule_policy_grade(gen_a):
    from rl_curriculum.evaluator import EvalConfig, evaluate_policy
    from rl_curriculum.policies import RuleTrendPolicy

    params = {"episode_bars": 96, "drift_bps_range": [18.0, 30.0],
              "vol_bps_range": [20.0, 32.0], "regime_len_range": [12, 40]}
    eps = (
        [gen_a.generate(params, seed=s, split="train") for s in (1, 2, 3)]
        + [gen_a.generate(params, seed=s, split="dev_seed_holdout")
           for s in (11, 12)]
        + [gen_a.generate(
            {**params, "drift_bps_range": [30.0, 45.0],
             "vol_bps_range": [32.0, 50.0]}, seed=s,
            split="param_extrapolation") for s in (21, 22)]
        + [gen_a.generate(params, seed=s, split="family_holdout")
           for s in (31, 32)]
    )
    rep = evaluate_policy(RuleTrendPolicy(ma_threshold=0.001), eps,
                          EvalConfig(fee=0.001))
    g = classify_generalization(rep, counterfactual_all_pass=True)
    assert g["grade"] in ("G1", "G2", "G3", "G4")
    assert g["gates"]["train_positive"] is True


def test_model_status_machine_readable():
    assert status_of("PASS") is ModelStatus.PASS
    assert status_of("SUSPECTED_CHEATING") is ModelStatus.SUSPECTED_CHEATING
    assert course_status_of("QUALIFIED") is CourseStatus.QUALIFIED
    try:
        status_of("MAYBE")
        raise AssertionError("未知状态必须报错")
    except ValueError:
        pass


def test_g5_transfer_protocol_blank_demo():
    spec = TransferProtocolSpec(
        target_course_charter_hash="c-x", exam_pack_hash="p-x",
        seeds=[1, 2, 3, 4], training_budget_steps=0,
        model_capacity={"net_arch": "demo"}, ppo_params={"demo": True},
        n_eval_runs=1)
    demo = run_blank_demo(spec, lambda arm, seed: 0.0)
    assert demo["demo_only"] is True
    assert demo["verdict"] == "NEUTRAL_TRANSFER"  # 恒等分数 -> 无差异
    assert demo["protocol"]["protocol_version"] == "transfer-protocol-v1"


def test_transfer_conclusions():
    pos = conclude_transfer([1.0, 2.0, 3.0], [0.0, 0.0, 0.0])
    assert pos["verdict"] == "POSITIVE_TRANSFER"
    neg = conclude_transfer([0.0, 0.0, 0.0], [1.0, 2.0, 3.0])
    assert neg["verdict"] == "NEGATIVE_TRANSFER"
    neu = conclude_transfer([1.0, 0.0, 1.0], [0.0, 1.0, 0.0])
    assert neu["verdict"] == "NEUTRAL_TRANSFER"


def test_cheat_reasons_covered():
    assert set(CHEAT_REASONS) >= {
        "episode_position", "absolute_price", "periodic_pattern", "future_leak"}
