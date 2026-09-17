"""R18 formal attempt governance tests (R17 framework + new namespaces).

The aborted r17 journal's §11 prescription ("下一轮必须 R17 + 全新
namespace") is implemented by curriculum261_r18_attempt: a brand-new
namespace family registered in the api/registry dual whitelist, fresh
deployed state root (repair18), and admission tail version table. No R17
namespace is reused and no terminal state is revived.
"""
from __future__ import annotations

from pathlib import Path

from rl_curriculum import curriculum261_r18_attempt as a
from rl_curriculum.curriculum261_api import (
    CURRICULUM261_R17_FORMAL_NAMESPACES,
    CURRICULUM261_R17_NAMESPACES,
)
from rl_curriculum.curriculum261_r17_admission import deploy_root_of
from rl_curriculum.curriculum261_r17_orchestrator import (
    formal_holdout_profile_r17,
    formal_main_profile_r17,
    rt_holdout_profile_r17,
    rt_main_profile_r17,
)
from rl_curriculum.curriculum261_r17_registry import (
    R17_ALL_NAMESPACES,
    R17_FORMAL_QUALIFICATION_NAMESPACES,
    require_r17_formal_namespace,
    require_r17_namespace_registered,
)


def test_r18_family_is_fresh_and_registered():
    assert len(set(a.R18_ALL_NEW)) == len(a.R18_ALL_NEW) == 30
    assert not any(n.endswith("_r17") for n in a.R18_ALL_NEW)
    assert set(a.R18_ALL_NEW) <= set(CURRICULUM261_R17_NAMESPACES)
    assert set(a.R18_ALL_NEW) <= set(R17_ALL_NAMESPACES)
    assert set(a.R18_FORMAL_FOUR) <= set(
        CURRICULUM261_R17_FORMAL_NAMESPACES)
    assert set(a.R18_FORMAL_FOUR) <= set(
        R17_FORMAL_QUALIFICATION_NAMESPACES)
    for name in a.R18_ALL_NEW:
        require_r17_namespace_registered(name)
    for name in a.R18_FORMAL_FOUR:
        require_r17_formal_namespace(name)


def test_old_formal_four_stay_registered_but_unused():
    # R17 旧四件套保持注册(历史未消费), 与 R18 四件套零重叠。
    old_four = {"qualification_r17", "preprocess_fit_qualification_r17",
                "c2_independent_qualification_r17",
                "cue_semantic_qualification_r17"}
    assert old_four <= set(R17_FORMAL_QUALIFICATION_NAMESPACES)
    assert not old_four & set(a.R18_ALL_NEW)


def test_profiles_wire_r18_family():
    main = formal_main_profile_r17(20)
    hold = formal_holdout_profile_r17(20)
    assert main.c13_eval_namespace == a.R18_C13_MAIN
    assert main.supervised_namespace == a.R18_SUPERVISED_MAIN
    assert main.semantic_namespace == a.R18_SEMANTIC_MAIN
    assert main.c2_independent_namespace == a.R18_C2_INDEPENDENT_MAIN
    assert hold.c13_eval_namespace == a.R18_C13_HOLDOUT
    assert hold.semantic_namespace == a.R18_SEMANTIC_HOLDOUT
    rt_main = rt_main_profile_r17()
    rt_hold = rt_holdout_profile_r17()
    assert rt_main.c13_eval_namespace == a.R18_RT_CALIBRATION_MAIN
    assert rt_main.semantic_namespace == a.R18_RT_SEMANTIC_MAIN
    assert rt_hold.c13_eval_namespace == a.R18_RT_CALIBRATION_HOLDOUT
    assert rt_hold.c2_independent_namespace == (
        a.R18_RT_C2_INDEPENDENT_HOLDOUT)
    wired = {main.c13_eval_namespace, main.supervised_namespace,
             main.semantic_namespace, main.c2_matched_namespace,
             main.c2_independent_namespace, hold.c13_eval_namespace,
             hold.supervised_namespace, hold.semantic_namespace,
             hold.c2_matched_namespace, hold.c2_independent_namespace,
             rt_main.c13_eval_namespace, rt_main.supervised_namespace,
             rt_main.semantic_namespace, rt_main.c2_independent_namespace,
             rt_hold.c13_eval_namespace, rt_hold.supervised_namespace,
             rt_hold.semantic_namespace,
             rt_hold.c2_independent_namespace}
    assert wired <= set(a.R18_ALL_NEW)


def test_admission_tail_version_table():
    deploy = Path("/home/cryptorl/projects/crypto_rl")
    r17 = deploy / "artifacts/route_c_stage2_6_1_repair17/state"
    r18 = deploy / "artifacts/route_c_stage2_6_1_repair18/state"
    assert deploy_root_of(r17) == deploy
    assert deploy_root_of(r18) == deploy
    assert deploy_root_of(
        deploy / "artifacts/route_c_stage2_6_1_repair19/state") is None
    assert deploy_root_of(deploy / "somewhere/state") is None


def test_r18_final_profile_namespaces():
    from rl_curriculum.curriculum261_r17_cli import R17_RT_FINAL_PROFILE
    values = {v for v in R17_RT_FINAL_PROFILE.values()
              if isinstance(v, str)}
    assert values <= set(a.R18_RT_FAMILY)
    assert R17_RT_FINAL_PROFILE["final_namespace"] == a.R18_RT_QUALIFICATION
