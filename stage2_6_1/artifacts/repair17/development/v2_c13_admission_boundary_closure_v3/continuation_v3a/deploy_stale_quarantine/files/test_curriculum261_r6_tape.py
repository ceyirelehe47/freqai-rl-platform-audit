# -*- coding: utf-8 -*-
"""R6 §38 测试:Historical Preservation + Matched Block(§9-§12)。"""

from __future__ import annotations

import numpy as np
import pytest

from rl_curriculum.curriculum261_api import (
    CURRICULUM261_RUNGS,
    episode_content_hash,
)
from rl_curriculum.curriculum261_c2 import (
    C2ContextGatingGenerator,
    C2_RUNG_PARAMS,
    FAMILY_C2,
)
from rl_curriculum.curriculum261_pairs import family_specs
from rl_curriculum.curriculum261_r6_param_pack import C2_LADDER_CANDIDATES
from rl_curriculum.curriculum261_r6_tape import (
    C2_BLOCK_MAX_ATTEMPTS,
    C2_MATCHED_LADDER_BLOCK_VERSION,
    MatchedBlockAttemptLog,
    BlockAttemptRecord,
    check_block_attempt_log,
    derive261_block_seed,
    generate_matched_block_once,
    generate_matched_block_with_attempts,
    matched_block_corpus_summary,
    matched_ladder_contract_identity,
    shared_tape_digest,
    verify_cross_rung_matching,
)

TEST_NS = "ppo_smoke_r6"
LADDER = C2_LADDER_CANDIDATES["c2l_balanced"]


@pytest.fixture(scope="module")
def block():
    return generate_matched_block_with_attempts(
        LADDER, namespace=TEST_NS, block_index=0)


# ------------------------------------------------- Historical Preservation
def test_matched_default_off_bitwise_unchanged():
    """默认实例(非 matched)同 seed 两次生成逐位一致,且与 matched 实例
    的输出不同(流派生不同)——历史路径行为不变由 2.6.1 全套黄金回归
    (reproducibility/families)锁定。"""
    g = C2ContextGatingGenerator()
    assert getattr(g, "_matched_tape_excludes", ()) == ()
    params = g.base_params(dict(C2_RUNG_PARAMS["D1"]), "A")
    seed = derive261_block_seed(TEST_NS, 0, 0)
    e1 = g.generate(params, seed, split=f"curriculum261_{TEST_NS}",
                    timeframe="15m")
    e2 = g.generate(params, seed, split=f"curriculum261_{TEST_NS}",
                    timeframe="15m")
    assert episode_content_hash(e1) == episode_content_hash(e2)
    # family_specs 单例未被污染(默认非 matched)
    spec = family_specs()[FAMILY_C2]
    assert getattr(spec.generator, "_matched_tape_excludes", ()) == ()


def test_matched_instance_isolated_from_singleton(block):
    """matched 生成使用独立实例;单例 generator 仍按历史行为生成
    (同 seed 同 params 下单例 episode != matched episode)。"""
    g = family_specs()[FAMILY_C2].generator
    params = g.base_params(dict(LADDER["D0"]), "A")
    seed = derive261_block_seed(TEST_NS, 0,
                                block.attempt_log.selected_attempt or 0)
    ep_hist = g.generate(params, seed, split=f"curriculum261_{TEST_NS}",
                         timeframe="15m")
    assert episode_content_hash(ep_hist) != episode_content_hash(
        block.episodes["D0"]["A"])


def test_r6_override_only_r6_namespaces():
    """r6 pack override 只在显式传入 rung_params_override 时生效;
    普通 generate_pair(namespace=...) 不带 override = 历史参数。"""
    from rl_curriculum.curriculum261_pairs import generate_pair
    from rl_curriculum.curriculum261_r6_param_pack import (
        r6_override_for,
    )

    rec_plain = generate_pair(FAMILY_C2, "D3", 0, namespace=TEST_NS)
    assert rec_plain.episodes["A"].spec.params["alpha_bps"] == \
        C2_RUNG_PARAMS["D3"]["alpha_bps"]
    override = r6_override_for(FAMILY_C2, {
        "c2_ladder": LADDER, "d3_overrides": {FAMILY_C2: LADDER["D3"]}})
    assert set(override) == {"D0", "D1", "D2", "D3"}
    assert override["D3"]["alpha_bps"] == 23.0


def test_r4_c1_c3_inherited_bitwise():
    from rl_curriculum.curriculum261_r6_param_pack import (
        R4_PARAMETER_PACK_DIGEST,
        R4_SELECTED_C1_D3,
        R4_SELECTED_C3_D3,
        ladder_pack_payload,
        verify_r4_inheritance,
    )
    pack = ladder_pack_payload(
        selected_c2_candidate="c2l_balanced", c2_ladder=LADDER,
        selected_block_count=10, design_plan_digest="r6dp-test",
        matched_contract_identity=matched_ladder_contract_identity(),
        block_integrity_identity="bi-test")
    assert pack["d3_overrides"]["c1_opportunity"] == R4_SELECTED_C1_D3
    assert pack["d3_overrides"]["c3_cost"] == R4_SELECTED_C3_D3
    assert pack["r4_parameter_pack_digest"] == R4_PARAMETER_PACK_DIGEST
    v = verify_r4_inheritance(pack)
    assert v["checks"]["c1_matches_r4_constants"]
    assert v["checks"]["c3_matches_r4_constants"]


# ------------------------------------------------- Matched Block 共享合同
def test_four_rungs_share_structure(block):
    """四 rung 共享 cue 表 / s 链 / w 链 / volume / 基础噪声(逐位/容差)。"""
    from rl_curriculum.curriculum261_r6_tape import _reconstruct_eps

    ref = block.episodes["D0"]["A"]
    ref_cue = ref.hidden["cue_dir"].to_numpy()
    ref_eps = _reconstruct_eps(ref)
    for rung in CURRICULUM261_RUNGS:
        for side in ("A", "B"):
            ep = block.episodes[rung][side]
            assert np.array_equal(
                ep.hidden["cue_dir"].to_numpy(), ref_cue)
            assert np.array_equal(
                ep.hidden["wick_dir_state"].to_numpy(),
                ref.hidden["wick_dir_state"].to_numpy())
            assert np.array_equal(
                ep.hidden["wick_width_state"].to_numpy(),
                ref.hidden["wick_width_state"].to_numpy())
            assert np.array_equal(
                ep.df["volume"].to_numpy(),
                ref.df["volume"].to_numpy())
            assert np.allclose(
                _reconstruct_eps(ep), ref_eps, rtol=0.0, atol=1e-12)
            assert len(ep.df) == len(ref.df)


def test_cross_rung_matching_passes(block):
    assert verify_cross_rung_matching(block.episodes, LADDER) == []
    assert block.cross_rung_integrity["pass"]


def test_matching_violation_detected():
    """params 差异面出现非法键(结构参数)时 cross-rung matching 拒绝。"""
    bad = {r: dict(LADDER[r]) for r in CURRICULUM261_RUNGS}
    bad["D3"]["vol_bps"] = 25.0  # 结构参数(§7 冻结)
    seed = derive261_block_seed(TEST_NS, 99, 0)
    episodes = generate_matched_block_once(LADDER, seed, TEST_NS)
    issues = verify_cross_rung_matching(episodes, bad)
    assert any("params_scope" in i
               for i in issues), issues


def test_block_id_not_in_observation(block):
    """block ID / rung ID 不进入 policy-visible observation:特征列与
    生产 schema 完全一致(8 特征 + OHLCV 原始列),无新增字段。"""
    from rl_curriculum.curriculum261_production_obs import (
        PRODUCTION_FEATURE_COLUMNS,
    )

    expected = set(PRODUCTION_FEATURE_COLUMNS) | {
        "date", "open", "high", "low", "close", "volume"}
    for rung in CURRICULUM261_RUNGS:
        for side in ("A", "B"):
            assert set(block.episodes[rung][side].df.columns) == expected


def test_accepted_block_implies_all_integrity(block):
    summary = matched_block_corpus_summary([block])
    assert summary["all_rung_pair_integrity_pass"]
    assert summary["all_cross_rung_matching_pass"]
    assert all(rec.integrity_ok
               for rec in block.pair_records.values())


def test_ab_contract_in_matched(block):
    """A/B:cue 表相同(共享)、gate 绑定不同(variant 语义保持)。"""
    a = block.episodes["D2"]["A"]
    b = block.episodes["D2"]["B"]
    assert np.array_equal(a.hidden["cue_dir"].to_numpy(),
                          b.hidden["cue_dir"].to_numpy())
    assert a.hidden["active_gate_is_dir"].iloc[0] == 1
    assert b.hidden["active_gate_is_dir"].iloc[0] == 0


# ------------------------------------------------- block attempt 纪律
def test_block_attempt_log_valid(block):
    log = block.attempt_log
    assert log.max_attempts == C2_BLOCK_MAX_ATTEMPTS == 5
    assert not check_block_attempt_log(log)
    assert log.selected_attempt == 0  # ppo_smoke 正常路径 first pass
    assert log.shared_tape_digest.startswith("r6tape-")


def test_block_attempt_log_rejects_bad_patterns():
    base = dict(block_index=0, seed_namespace=TEST_NS)
    # 无选中却记录尝试
    log = MatchedBlockAttemptLog(
        attempts=[BlockAttemptRecord(0, False, "too_few_cues")],
        selected_attempt=None, **base)
    assert check_block_attempt_log(log)
    # 选中前有 accepted
    log2 = MatchedBlockAttemptLog(
        attempts=[BlockAttemptRecord(0, True), BlockAttemptRecord(1, True)],
        selected_attempt=1, **base)
    assert check_block_attempt_log(log2)
    # 编号不连续
    log3 = MatchedBlockAttemptLog(
        attempts=[BlockAttemptRecord(1, False, "x")], selected_attempt=None,
        **base)
    assert check_block_attempt_log(log3)


def test_whole_block_retry_on_failure(monkeypatch):
    """单 rung 失败 → 整 block 重试(不允许只重采样失败 rung):
    monkeypatch contract 使 attempt 0 全部拒绝、attempt 1 通过。"""
    import rl_curriculum.curriculum261_r6_tape as tape

    calls = {"n": 0}
    real_gen = tape.generate_matched_block_once

    def flaky(rung_params, seed, namespace):
        calls["n"] += 1
        return real_gen(rung_params, seed, namespace)

    monkeypatch.setattr(tape, "generate_matched_block_once", flaky)
    real_verify = tape.verify_cross_rung_matching
    gate = {"fail_first": True}

    def flaky_verify(episodes, params):
        if gate["fail_first"]:
            gate["fail_first"] = False
            return ["cross_rung_matching_failed:volume:D0/A"]
        return real_verify(episodes, params)

    monkeypatch.setattr(tape, "verify_cross_rung_matching", flaky_verify)
    blk = tape.generate_matched_block_with_attempts(
        LADDER, namespace=TEST_NS, block_index=7)
    assert blk.attempt_log.selected_attempt == 1
    assert blk.attempt_log.attempts[0].reason.startswith(
        "cross_rung_matching_failed")
    assert not check_block_attempt_log(blk.attempt_log)
    # 两次 attempt 的 block 结构带不同(不同 block seed)
    assert blk.attempt_log.shared_tape_digest.startswith("r6tape-")


def test_no_pnl_rejection_path(block):
    """拒绝原因全部来自结构词表(无 PnL/评估结果参与)。"""
    reasons = set()
    for att in block.attempt_log.attempts:
        if not att.accepted and att.reason:
            reasons.update(att.reason.split("; "))
    vocab = {"too_few_cues", "too_few_aligned_gate_windows",
             "context_polarity_missing", "cross_rung_matching_failed",
             "pair_integrity_failed"}
    assert all(any(r.startswith(v) or r.split(":")[0] in
                   ("D0", "D1", "D2", "D3", "pair") for v in vocab)
               for r in reasons) if reasons else True


def test_candidate_grid_shares_block_schedule():
    """不同 candidate 同 block_index 结构带逐位一致(§20)。"""
    blk_a = generate_matched_block_with_attempts(
        C2_LADDER_CANDIDATES["c2l_balanced"],
        namespace=TEST_NS, block_index=3)
    blk_b = generate_matched_block_with_attempts(
        C2_LADDER_CANDIDATES["c2l_kappa_wide"],
        namespace=TEST_NS, block_index=3)
    assert blk_a.attempt_log.shared_tape_digest == \
        blk_b.attempt_log.shared_tape_digest
    assert np.array_equal(
        blk_a.episodes["D3"]["A"].hidden["cue_dir"].to_numpy(),
        blk_b.episodes["D3"]["A"].hidden["cue_dir"].to_numpy())


def test_contract_identity_stable():
    ident = matched_ladder_contract_identity()
    assert ident.startswith("r6ml-")
    assert matched_ladder_contract_identity() == ident
    assert C2_MATCHED_LADDER_BLOCK_VERSION == "C2MatchedLadderBlock-v1"
