# -*- coding: utf-8 -*-
"""R7 §34 测试:Cue Semantic Contract(§9)——recall floor 公式锁定、
delta/absolute floor 预注册、解析 q(t) 数值正确性、audit 可复现、
audit 不访问 design/final namespace、bridge/MC 一致性。"""

from __future__ import annotations

import math

import pytest

from rl_curriculum.curriculum261_api import derive261_seed
from rl_curriculum.curriculum261_r7_cue_contract import (
    ABSOLUTE_MINIMUM_RECALL,
    AUDIT_NAMESPACE,
    C2_CUE_SEMANTIC_CONTRACT_VERSION,
    MIN_UNIQUE_POSITIVE_CUES,
    NONINFERIORITY_DELTA,
    cue_contract_audit_digest,
    cue_semantic_contract_digest,
    cue_semantic_contract_payload,
    q_recall_at_position,
    recall_floor,
    run_cue_contract_audit,
)


def test_recall_floor_formula_locked():
    """公式 = max(0.90, p_contract - 0.02);预注册常量不可漂移。"""
    assert NONINFERIORITY_DELTA == 0.02
    assert ABSOLUTE_MINIMUM_RECALL == 0.90
    assert recall_floor(0.951) == pytest.approx(0.931)
    assert recall_floor(0.937) == pytest.approx(0.917)
    assert recall_floor(0.905) == pytest.approx(0.90)  # 下限托底
    assert recall_floor(0.5) == pytest.approx(0.90)
    assert recall_floor(1.0) == pytest.approx(0.98)


def test_contract_identity_stable():
    d1 = cue_semantic_contract_digest()
    assert d1.startswith("r7cue-") and len(d1) == 6 + 64
    assert cue_semantic_contract_digest() == d1
    payload = cue_semantic_contract_payload()
    assert payload["version"] == C2_CUE_SEMANTIC_CONTRACT_VERSION
    assert payload["canonical_observation"] == ["D0", "A"]
    assert payload["cluster_unit"] == "matched_block"
    assert "unique_event_key" in payload
    # delta/absolute floor 属于合同身份——数据后修改会改变 digest
    assert payload["noninferiority_delta"] == NONINFERIORITY_DELTA
    assert payload["absolute_minimum_recall"] == (
        ABSOLUTE_MINIMUM_RECALL)
    assert MIN_UNIQUE_POSITIVE_CUES >= 400


def test_q_recall_analytic_values():
    """解析层 q(t) 与手算对照。

    - 无镜像候选(C=0)且有主项:q = Φ(margin_log/vol),
      margin_log = 0.015 - ln(1.0105) ≈ 0.0045549;
    - C=0 且无主项(尾部 bar):q = Φ(margin_log/0) 退化为 1(σ=0,
      margin>0 恒检出);
    - C=9:q 是 Bin(9,1/9) 混合,必严格低于 C=0 的 q(更多噪声方差)。
    """
    margin_log = 0.015 - math.log1p(0.0105)
    vol = 0.0020
    q0 = q_recall_at_position(4, 288, pulse=0.015, cue_thr=0.0105,
                              vol=vol)
    assert q0["mirror_candidates"] == 0 and q0["primary"] == 1
    assert q0["q"] == pytest.approx(
        0.5 * (1 + math.erf((margin_log / vol) / math.sqrt(2))),
        abs=1e-12)
    tail = q_recall_at_position(287, 288, pulse=0.015, cue_thr=0.0105,
                                vol=vol)
    assert tail["primary"] == 0
    q_mid = q_recall_at_position(100, 288, pulse=0.015, cue_thr=0.0105,
                                 vol=vol)
    assert q_mid["mirror_candidates"] == 9
    assert q_mid["q"] < q0["q"]
    assert 0.85 < q_mid["q"] < 0.99
    # 混合权重和为 1
    assert sum(t["pmf"] for t in q_mid["terms"]) == pytest.approx(1.0)


def test_audit_reproducible_and_namespaces_clean(monkeypatch, tmp_path):
    """audit 完整运行(monkeypatch 缩小规模):同配置两次输出逐位一致;
    audit 过程不派生任何 design/calibration/holdout/final namespace
    seed;audit digest 稳定。"""
    import rl_curriculum.curriculum261_r7_cue_contract as mod

    monkeypatch.setattr(mod, "AUDIT_BRIDGE_BLOCKS", 3)
    monkeypatch.setattr(mod, "AUDIT_N_EVENTS", 20000)
    derived: list[str] = []
    orig = derive261_seed

    def spy(namespace, *a, **k):
        derived.append(namespace)
        return orig(namespace, *a, **k)

    import rl_curriculum.curriculum261_api as api

    monkeypatch.setattr(api, "derive261_seed", spy)
    r1 = run_cue_contract_audit()
    r2 = run_cue_contract_audit()
    # 派生只允许 audit namespace(block seed 派生走
    # derive261_block_seed -> derive261_seed(spy 可见))
    forbidden = [ns for ns in derived if not ns.startswith(
        ("cue_contract_audit",))]
    assert not forbidden, f"audit 派生了非 audit namespace: {forbidden}"
    assert AUDIT_NAMESPACE == "cue_contract_audit_r7"
    assert r1["p_contract"] == pytest.approx(r2["p_contract"],
                                             abs=1e-15)
    assert r1["audit_digest"] == r2["audit_digest"]
    assert cue_contract_audit_digest(r1) == r1["audit_digest"]
    assert r1["monte_carlo"]["n_events"] == 20000
    assert abs(r1["monte_carlo"]["p_hat"] - r1["p_contract"]) < (
        5 * r1["monte_carlo"]["se"] + 1e-3)
    assert 0.85 < r1["p_contract"] < 0.99
    floor = r1["noninferiority"]["recall_floor"]
    assert floor == pytest.approx(recall_floor(r1["p_contract"]))


def test_audit_writes_artifact(monkeypatch, tmp_path):
    import rl_curriculum.curriculum261_r7_cue_contract as mod

    monkeypatch.setattr(mod, "AUDIT_BRIDGE_BLOCKS", 2)
    monkeypatch.setattr(mod, "AUDIT_N_EVENTS", 5000)
    report = run_cue_contract_audit(tmp_path)
    path = tmp_path / "cue_contract_audit.json"
    assert path.is_file()
    import json

    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["audit_digest"] == report["audit_digest"]
    assert loaded["frozen_detector"]["cue_thr"] == pytest.approx(
        0.0105)
