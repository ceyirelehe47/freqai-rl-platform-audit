"""R2 诊断 namespace 隔离与 seed 派生测试(s262_diag_r2)。"""

from __future__ import annotations

import pytest

from rl_curriculum.ppo262_r2_namespaces import (
    DIAG262R2_INTEGRITY_NS, DIAG262R2_SMOKE_NS,
    DIAG262R2_NAMESPACES, derive262r2_seed,
    verify_r2_namespace_isolation,
)


def test_r2_namespaces_no_overlap_with_official_r1_261():
    art = verify_r2_namespace_isolation(
        pair_range=range(0, 64),
        official_pair_range=range(0, 256),
        r1_pair_range=range(0, 64),
        pair_range_261=range(0, 256))
    assert art["pass"], art["problems"][:5]


def test_r2_seed_rejects_non_r2_namespaces():
    for bad in ("ppo_config_dev_262", "ppo_final_eval_262",
                "qualification_r2", "diag262r1_preprocess_train", "diag262r2_smoke",
                "curriculum261_train"):
        with pytest.raises(ValueError):
            derive262r2_seed(bad, "c1_opportunity", "D0", 0, 0)


def test_r2_seed_deterministic_and_pair_variant_free():
    a = derive262r2_seed(DIAG262R2_SMOKE_NS, "c1_opportunity", "D0", 7, 0)
    b = derive262r2_seed(DIAG262R2_SMOKE_NS, "c1_opportunity", "D0", 7, 0)
    assert a == b
    # 不同 namespace / pair / attempt 必须不同
    assert a != derive262r2_seed(
        DIAG262R2_INTEGRITY_NS, "c1_opportunity", "D0", 7, 0)
    assert a != derive262r2_seed(
        DIAG262R2_SMOKE_NS, "c1_opportunity", "D0", 8, 0)
    assert a != derive262r2_seed(
        DIAG262R2_SMOKE_NS, "c1_opportunity", "D0", 7, 1)


def test_r2_namespace_enumeration_contract():
    assert len(DIAG262R2_NAMESPACES) == 16
    joined = " ".join(DIAG262R2_NAMESPACES)
    assert "ppo_final_eval_262" not in joined
    assert "qualification_r2" not in joined
    assert "diag262r1" not in joined
    # train/eval 成对分离
    for ns in DIAG262R2_NAMESPACES:
        if ns.endswith("_train"):
            assert ns.replace("_train", "_eval") in DIAG262R2_NAMESPACES \
                or ns == "diag262r2_1_supervised_train"
