"""seed namespace 隔离与 final 封存协议测试(§27 Seed isolation)。"""

from __future__ import annotations

import json

import pytest

from rl_curriculum.curriculum261_api import GeneratorError
from rl_curriculum.ppo262_namespaces import (
    PPO262_MODEL_SEEDS, all_262_namespaces, core_train_namespace,
    derive262_seed, final_eval_exposure_marker, final_eval_unlocked,
    verify_namespace_isolation, write_final_eval_exposure,
    _derive262_seed_raw, _ns261_raw,
)
from rl_curriculum.ppo262_banks import (
    PPO262_CORE_BANK_EPISODES, EpisodeKey, core_bank_keys, manifest_equality,
    mixed_order, replicate_pair_offset, staged_order,
)


def test_namespaces_262_mutually_disjoint_small():
    art = verify_namespace_isolation(
        pair_range_262=range(0, 200), pair_range_261=range(0, 200))
    assert art["pass"], art["problems"]


def test_no_overlap_with_qualification_r2_wide():
    """262 全 namespace vs qualification_r2(宽 pair 范围枚举)。"""
    ns_262 = all_262_namespaces()
    seeds_262 = set()
    for ns in ns_262:
        for fam in ("c1_opportunity", "c2_context", "c3_cost"):
            for rung in ("D0", "D1", "D2", "D3"):
                for pair in range(500):
                    for att in range(5):
                        seeds_262.add(_derive262_seed_raw(
                            ns, fam, rung, pair, att))
    seeds_q = set()
    for fam in ("c1_opportunity", "c2_context", "c3_cost"):
        for rung in ("D0", "D1", "D2", "D3"):
            for pair in range(500):
                for att in range(5):
                    seeds_q.add(_ns261_raw(
                        "qualification_r2", fam, rung, pair, att))
    assert not (seeds_262 & seeds_q)


def test_262_namespace_rejects_261_namespaces():
    with pytest.raises(ValueError):
        derive262_seed("qualification_r2", "c1_opportunity", "D1", 0, 0)
    with pytest.raises(ValueError):
        derive262_seed("training_r2", "c1_opportunity", "D1", 0, 0)
    with pytest.raises(ValueError):
        derive262_seed("made_up_ns", "c1_opportunity", "D1", 0, 0)


def test_final_eval_seed_locked_before_plan(tmp_lock_dir):
    assert final_eval_unlocked() is False
    with pytest.raises(RuntimeError, match="锁定前"):
        derive262_seed("ppo_final_eval_262", "c1_opportunity", "D1", 0, 0)


def test_final_eval_seed_unlocked_after_lock(tmp_lock_dir):
    lock = tmp_lock_dir / "final_evaluation_plan.json"
    lock.write_text("{}", encoding="utf-8")
    assert final_eval_unlocked() is True
    s = derive262_seed("ppo_final_eval_262", "c1_opportunity", "D1", 0, 0)
    assert isinstance(s, int)


def test_exposure_marker_blocks_second_run(tmp_lock_dir):
    lock = tmp_lock_dir / "final_evaluation_plan.json"
    lock.write_text("{}", encoding="utf-8")
    write_final_eval_exposure("fp-test", status="running")
    # running -> completed 单次推进允许
    write_final_eval_exposure("fp-test", status="completed")
    # 之后任何写入都拒绝
    with pytest.raises(RuntimeError, match="已消耗"):
        write_final_eval_exposure("fp-test", status="completed")
    with pytest.raises(RuntimeError, match="已消耗"):
        write_final_eval_exposure("fp-other", status="running")
    assert final_eval_exposure_marker().is_file()


def test_staged_mixed_same_multiset_different_order():
    for rep in (1, 2, 3):
        keys = core_bank_keys(rep)
        mixed = mixed_order(keys, model_seed=PPO262_MODEL_SEEDS[rep - 1])
        eq = manifest_equality(staged_order(keys), mixed)
        assert eq["same_multiset"] is True
        assert eq["different_order"] is True
        assert eq["pass"] is True


def test_staged_order_contract():
    keys = core_bank_keys(1)
    ordered = staged_order(keys)
    fams = []
    for k in ordered:
        if not fams or fams[-1] != k.family:
            fams.append(k.family)
    assert fams == ["c1_opportunity", "c2_context", "c3_cost"]
    rungs = []
    fam = None
    for k in ordered:
        if fam != k.family:
            fam = k.family
            rungs = []
        if not rungs or rungs[-1] != k.rung:
            rungs.append(k.rung)
    # 每个 family 内 D0->D1->D2->D3
    assert rungs == ["D0", "D1", "D2", "D3"]


def test_three_replicate_banks_disjoint():
    banks = [core_bank_keys(r) for r in (1, 2, 3)]
    for bank in banks:
        assert len(bank) == PPO262_CORE_BANK_EPISODES
    sets = [{k.canonical() for k in bank} for bank in banks]
    assert not (sets[0] & sets[1])
    assert not (sets[0] & sets[2])
    assert not (sets[1] & sets[2])
    # seeds 也互不相同(episode identity 层面)
    ns_seeds = []
    for r, bank in zip((1, 2, 3), banks):
        ns_seeds.append({
            derive262_seed(
                core_train_namespace(r), k.family, k.rung,
                k.pair_index, 0) for k in bank})
    assert not (ns_seeds[0] & ns_seeds[1])
    assert not (ns_seeds[0] & ns_seeds[2])
    assert not (ns_seeds[1] & ns_seeds[2])


def test_replicate_pair_offsets_disjoint():
    assert replicate_pair_offset(1) == 0
    assert replicate_pair_offset(2) == PPO262_CORE_BANK_EPISODES
    assert replicate_pair_offset(3) == 2 * PPO262_CORE_BANK_EPISODES


def test_train_dev_final_namespaces_disjoint():
    """train(config/probe/core) vs dev_eval vs final_eval seed 不相交。"""
    train_ns = (["ppo_config_dev_262", "ppo_probe_eval_262"
                 ] + [f"ppo_probe_train_262_{f}" for f in
                      ("c1", "c2", "c3")]
                + [core_train_namespace(r) for r in (1, 2, 3)])
    test_ns = {
        ns: {_derive262_seed_raw(ns, f, r, p, a)
             for f in ("c1_opportunity", "c2_context", "c3_cost")
             for r in ("D0", "D1", "D2", "D3")
             for p in range(200) for a in range(5)}
        for ns in train_ns + ["ppo_dev_eval_262", "ppo_final_eval_262"]}
    assert not (test_ns["ppo_dev_eval_262"]
                & set().union(*[test_ns[ns] for ns in train_ns]))
    assert not (test_ns["ppo_final_eval_262"]
                & set().union(*[test_ns[ns] for ns in train_ns]))
    assert not (test_ns["ppo_final_eval_262"] & test_ns["ppo_dev_eval_262"])
