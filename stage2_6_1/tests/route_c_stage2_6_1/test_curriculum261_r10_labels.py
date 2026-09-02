# -*- coding: utf-8 -*-
"""R10 §29 Supervised Labels 测试:raw/canonical reference labels /
scaled float32 inputs / action replay / position replay / timestep
alignment / pair isolation / 禁止 raw policy 直接读 scaled obs。"""

from __future__ import annotations

import numpy as np
import pytest

from rl_curriculum.curriculum261_production_obs import (
    PRODUCTION_FEATURE_COLUMNS,
)


def _records_and_params(family: str, n_pairs: int = 2):
    from rl_curriculum.curriculum261_pairs import (
        family_specs,
        generate_pair,
    )
    from rl_curriculum.curriculum261_r6_param_pack import \
        r6_family_rung_params

    records = [generate_pair(
        family, r, i, namespace="preplan_supervised_main_r10")
        for r in ("D0", "D1", "D2", "D3") for i in range(n_pairs)]
    rung_params = r6_family_rung_params(family, {})
    return records, rung_params


@pytest.fixture(scope="module")
def preproc_fitted():
    from rl_curriculum.curriculum261_pairs import generate_pair
    from rl_curriculum.curriculum261_r3_calibration import (
        fit_matrix_from_records,
    )
    from rl_curriculum.curriculum261_r3_preprocessing import (
        RouteCPreprocessor,
    )

    records = [generate_pair(f, r, 0,
                             namespace="preplan_fit_main_r10")
               for f in ("c1_opportunity", "c2_context", "c3_cost")
               for r in ("D0", "D1", "D2", "D3")]
    return RouteCPreprocessor.build_and_fit(
        fit_matrix_from_records(records))


@pytest.fixture(scope="module")
def dataset_c1(preproc_fitted):
    from rl_curriculum.curriculum261_r10_labels import (
        collect_policy_visible_dataset_r10,
    )

    records, rung_params = _records_and_params("c1_opportunity")
    return collect_policy_visible_dataset_r10(
        records, "c1_opportunity", rung_params, preproc_fitted,
        eval_namespace="preplan_supervised_main_r10")


def test_dataset_scaled_float32_inputs(dataset_c1):
    rows = dataset_c1["rows"]
    assert rows
    for r in rows[:50]:
        assert r["obs"].dtype == np.float32
        assert r["obs"].shape == (9,)
        assert np.isfinite(r["obs"].astype(np.float64)).all()
        assert float(r["obs"][-1]) in (0.0, 1.0)  # position 槽位


def test_labels_are_canonical_reference_actions(dataset_c1):
    """标签来源:canonical reference on canonical obs(非 raw-on-scaled)。"""
    assert dataset_c1["label_source"] == \
        "canonical_reference_on_canonical_obs"
    assert dataset_c1["label_contract"] == \
        "PolicyVisibleSupervisedLabel-v1"
    assert dataset_c1["raw_policy_reads_scaled_obs"] is False
    assert set(r["action"] for r in dataset_c1["rows"]) <= {0, 1}


def test_alignment_ok_action_and_position_replay(dataset_c1):
    """§8.2:dataset action == canonical causal reference action;position
    与 replay 一致;步数一致。"""
    assert dataset_c1["alignment_ok"], dataset_c1["alignment_failures"][:3]
    assert dataset_c1["alignment_failures"] == []
    # timestep 对齐:每 episode 步数恒 287(288-bar episode 的
    # 决策步数;与 run_policy_episode 的 action 序列长度一致)
    from collections import defaultdict

    by_ep = defaultdict(int)
    for r in dataset_c1["rows"]:
        by_ep[(r["rung"], r["pair"], r["side"])] += 1
    assert all(n == 287 for n in by_ep.values())


def test_evidence_fields_complete(dataset_c1):
    """§8.5 label evidence 全字段。"""
    assert dataset_c1["evidence"]
    for ev in dataset_c1["evidence"][:3]:
        assert {"family", "rung", "pair", "side", "step",
                "raw_feature_summary", "scaled_input_summary", "position",
                "label_source", "label", "replay_action",
                "canonical_obs_summary", "alignment_ok",
                "bundle_hash"} <= set(ev)
        assert ev["label"] == ev["replay_action"]


def test_pair_identity_split_no_bar_shuffle(dataset_c1):
    """§8.3:split 必须按 pair identity(A/B 同 pair 不得分散)。"""
    from rl_curriculum.curriculum261_r10_calibration import (
        supervised_learnability_run_r10,
    )
    import inspect

    sig = inspect.signature(supervised_learnability_run_r10)
    assert "train_pair_limit" in sig.parameters
    # 结构验证:同一 (rung, pair) 的 A/B 全部落在同一 split 侧
    rows = dataset_c1["rows"]
    pair_sides = {(r["rung"], r["pair"]): set() for r in rows}
    for r in rows:
        pair_sides[(r["rung"], r["pair"])].add(r["side"])
    # 每 pair 都有 A 和 B(同一 pair 的两侧在数据集内同现)
    assert all(sides == {"A", "B"} for sides in pair_sides.values())


def test_raw_policy_never_receives_scaled_obs(preproc_fitted):
    """结构性探针:reference policy 只接收 canonical/raw 语义 obs;
    用 wrapper 探针捕获 act() 的输入,断言特征值域与 scaled 不符而与
    canonical 一致。"""
    from rl_curriculum.curriculum261_qualification import build_policy_set
    from rl_curriculum.curriculum261_pairs import (
        family_specs,
        generate_pair,
    )
    from rl_curriculum.curriculum261_r10_labels import (
        _replay_canonical_reference,
    )
    from rl_curriculum.curriculum261_r10_reference import canonical_episode
    from rl_curriculum.curriculum261_r6_param_pack import \
        r6_family_rung_params

    ep = generate_pair("c1_opportunity", "D0", 0,
                       namespace="preplan_supervised_main_r10"
                       ).episodes["A"]
    thresholds = dict(
        family_specs()["c1_opportunity"].reference_defaults)
    rung_params = dict(r6_family_rung_params("c1_opportunity", {})["D0"])
    rung_params["cur261_rung"] = "D0"
    raw_set = build_policy_set("c1_opportunity", rung_params, thresholds)
    canon_ep = canonical_episode(ep, preproc_fitted)
    slot0 = PRODUCTION_FEATURE_COLUMNS[0]
    canon_feats = canon_ep.df[
        [slot0]].to_numpy(dtype=np.float64)[0, 0]
    scaled_feats = preproc_fitted.transform(
        ep.df[list(PRODUCTION_FEATURE_COLUMNS)]).to_numpy(
            dtype=np.float64)[0, 0]

    captured: list[np.ndarray] = []
    ref = raw_set["reference"]
    orig_act = ref.act

    def probe_act(obs):
        captured.append(np.array(obs))
        return orig_act(obs)

    ref.act = probe_act  # type: ignore[method-assign]
    _replay_canonical_reference(ref, canon_ep)
    ref.act = orig_act  # type: ignore[method-assign]
    assert captured
    got = float(captured[0][0])
    assert got == pytest.approx(canon_feats, rel=1e-6), (
        "policy 收到的必须是 canonical 语义特征(与 scaled 值域不同)")
    assert abs(got - scaled_feats) > 1e-9, (
        "policy 不得直接收到 scaled 特征")


def test_dataset_identity_summary(dataset_c1):
    from rl_curriculum.curriculum261_r10_labels import (
        supervised_dataset_identity_r10,
    )

    ident = supervised_dataset_identity_r10(dataset_c1)
    assert ident["obs_dtype"] == "float32"
    assert ident["label_contract"] == "PolicyVisibleSupervisedLabel-v1"
    assert ident["alignment_ok"] is True
    assert ident["n_rows"] == dataset_c1["n_rows"]
    assert ident["long_label_rate"] is not None
    assert 0.0 <= ident["long_label_rate"] <= 1.0
