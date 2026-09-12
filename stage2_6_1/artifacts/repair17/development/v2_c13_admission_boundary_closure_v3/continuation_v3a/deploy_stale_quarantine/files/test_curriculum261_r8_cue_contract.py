# -*- coding: utf-8 -*-
"""R8 §36 测试:Cue Semantic Contract v2(§9/§12/§13)。

覆盖:recall floor 公式冻结;合同身份稳定;修正后 q(t) 解析值(尾部
C(t) 边界);MC 与 analytic 一致(小规模合成权重);audit 落盘与
可复现(小规模);三路判据字段完整。
"""

from __future__ import annotations

import json
import math

import pytest

from rl_curriculum.curriculum261_api import CURRICULUM261_EPISODE_BARS
from rl_curriculum.curriculum261_r8_cue_contract import (
    ABSOLUTE_MINIMUM_RECALL,
    AUDIT_MODEL_NAMESPACE,
    AUDIT_VALIDATION_NAMESPACE,
    C2_CUE_SEMANTIC_CONTRACT_VERSION,
    MIN_UNIQUE_POSITIVE_CUES,
    NONINFERIORITY_DELTA,
    _cluster_bootstrap,
    _sentinel_ladder,
    cue_contract_audit_digest,
    cue_semantic_contract_digest,
    cue_semantic_contract_payload,
    q_recall_at_position,
    recall_floor,
    run_cue_contract_audit,
)
from rl_curriculum.curriculum261_r8_noise_replay import (
    mirror_candidate_count,
)

N = int(CURRICULUM261_EPISODE_BARS)


def test_recall_floor_formula_locked():
    assert NONINFERIORITY_DELTA == 0.02
    assert ABSOLUTE_MINIMUM_RECALL == 0.90
    assert recall_floor(0.9504) == pytest.approx(0.9304)
    # p_contract - delta 跌破 0.90 时取绝对下限
    assert recall_floor(0.9100) == 0.90
    assert recall_floor(0.8500) == 0.90


def test_contract_identity_stable():
    d1 = cue_semantic_contract_digest()
    payload = cue_semantic_contract_payload()
    assert payload["version"] == "C2CueDetectionSemanticContract-v2"
    assert payload["semantic_blocks_per_corpus"] == 160
    assert payload["min_unique_positive_cues"] == MIN_UNIQUE_POSITIVE_CUES
    assert "min(t-8, n-17)" in payload["mirror_bound"]
    assert d1.startswith("r8cue-") and len(d1) == 6 + 64
    import rl_curriculum.curriculum261_r8_cue_contract as mod

    assert cue_semantic_contract_digest() == d1
    assert mod.cue_semantic_contract_payload() == payload


def test_q_recall_analytic_values_corrected_tail():
    ladder = _sentinel_ladder()
    vol = float(ladder["D0"]["vol_bps"]) * 1e-4
    pulse = float(ladder["D0"]["pulse_bps"]) * 1e-4
    thr = 0.0105
    # 内部位置:C=9, primary=1
    q_int = q_recall_at_position(100, N, pulse=pulse, cue_thr=thr,
                                 vol=vol)
    assert q_int["mirror_candidates"] == 9
    assert q_int["primary"] == 1
    # 修正后尾部:t=280 → C=8(R7 错算 9);t=287 → C=1
    q280 = q_recall_at_position(280, N, pulse=pulse, cue_thr=thr,
                                vol=vol)
    assert q280["mirror_candidates"] == 8
    assert q280["primary"] == 0  # 280 + 16 >= 288 → 无主项
    q287 = q_recall_at_position(287, N, pulse=pulse, cue_thr=thr,
                                vol=vol)
    assert q287["mirror_candidates"] == 1
    assert q287["primary"] == 0
    # C(t) 与权威实现一致
    assert q_int["mirror_candidates"] == mirror_candidate_count(100, N)
    # 混合均值意义:q 单调于候选数减少(方差更小 → 检出更高,主项在时)
    assert q280["q"] > 0


def test_q_recall_hand_computed_mixture():
    """单点手工复算:K~Bin(C,1/9) 混合 Φ(margin/(vol·sqrt(m+k)))。"""
    vol, pulse, thr = 0.0020, 0.0150, 0.0105
    t = 100
    c = mirror_candidate_count(t, N)
    m = 1
    margin = pulse - math.log1p(thr)
    total = 0.0
    for k in range(c + 1):
        pmf = math.comb(c, k) * (1 / 9) ** k * (8 / 9) ** (c - k)
        sigma = vol * math.sqrt(m + k)
        phi = 0.5 * (1 + math.erf((margin / sigma) / math.sqrt(2)))
        total += pmf * phi
    q = q_recall_at_position(t, N, pulse=pulse, cue_thr=thr, vol=vol)
    assert q["q"] == pytest.approx(total, rel=1e-12)


def test_cluster_bootstrap_two_sided_and_lcb():
    per = [{"n": 10, "hit": 9}, {"n": 10, "hit": 8}, {"n": 10, "hit": 10}]
    boot = _cluster_bootstrap(per)
    assert boot["point"] == pytest.approx(9.0 / 10)
    assert boot["lcb95"] <= boot["point"] <= boot["ci95"][1]
    assert boot["ci95"][0] <= boot["lcb95"]


def test_audit_small_reproducible_and_writes_artifacts(
        tmp_path, monkeypatch):
    """小规模 audit(8 blocks/corpus):plumbing 完整 + 落盘 + 确定性。"""
    import rl_curriculum.curriculum261_r8_cue_contract as mod

    monkeypatch.setattr(mod, "AUDIT_BLOCKS_PER_CORPUS", 8)
    monkeypatch.setattr(mod, "AUDIT_N_EVENTS", 100000)
    r1 = mod.run_cue_contract_audit(tmp_path)
    r2 = mod.run_cue_contract_audit(tmp_path)
    # 确定性:同一配置两次运行逐字段一致(digest 一致)
    assert r1["p_contract"] == r2["p_contract"]
    assert r1["audit_digest"] == r2["audit_digest"]
    assert r1["audit_namespaces"] == {
        "model": AUDIT_MODEL_NAMESPACE,
        "validation": AUDIT_VALIDATION_NAMESPACE}
    assert r1["contract_version"] == C2_CUE_SEMANTIC_CONTRACT_VERSION
    # MC 与 analytic 一致(|diff| <= 0.001 预注册容差,即使小规模)
    assert abs(r1["monte_carlo"]["p_hat"] - r1["p_contract"]) <= 0.001
    for name in ("model", "validation"):
        c = r1["direct_generator"][name]
        assert c["n_blocks"] == 8
        assert c["replay_ok"] and c["bounds_ok"]
        assert c["cue_table_consistent_across_rungs"]
        assert c["n_unique_positive_cues"] > 100
    # 落盘完整性(§11/§37)
    audit = json.loads(
        (tmp_path / "cue_contract_audit.json").read_text(encoding="utf-8"))
    assert audit["audit_digest"] == cue_contract_audit_digest(audit)
    lines = (tmp_path / "cue_event_trace.jsonl").read_text(
        encoding="utf-8").splitlines()
    assert len(lines) == sum(
        r1["direct_generator"][x]["n_unique_positive_cues"]
        for x in ("model", "validation"))
    for fname in ("cue_k_distribution.json", "tail_mirror_validation.json",
                  "noise_replay_validation.json"):
        assert (tmp_path / fname).is_file()
    ev = json.loads(lines[0])
    assert {"corpus", "block_index", "cue_bar", "primary_present",
            "k_actual", "mirror_positions", "effective_sigma_bps",
            "actual_noise", "cue_read", "detected"} <= set(ev)
