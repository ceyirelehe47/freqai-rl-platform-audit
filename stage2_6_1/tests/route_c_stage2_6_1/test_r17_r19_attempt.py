"""R19 formal attempt governance tests (R17 framework + new namespaces).

Mirrors test_r17_r18_attempt.py for the R19 attempt family per the R19
prescription (§1): fresh namespace family, dual-whitelist registration,
profile wiring, admission tail versioning, and the single-consumption
entry contract. Preconditions asserted elsewhere: review gates §4.1/§4.2
closed at 7776aa9d (report/route_c_stage2_6_1_open_gate_closure_
20260920.md) — per erratum 勘误四 these closures precede any r19
identity creation.
"""
from __future__ import annotations

from pathlib import Path

from rl_curriculum import curriculum261_r19_attempt as a
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
from rl_curriculum.curriculum261_r17_routing import (
    R17_EVAL_NAMESPACE_ROLE,
    R17_ROLE_FIT_NAMESPACE,
)


def test_r19_family_is_fresh_and_registered():
    assert len(set(a.R19_ALL_NEW)) == len(a.R19_ALL_NEW) == 30
    assert not any(n.endswith("_r17") or n.endswith("_r18")
                   for n in a.R19_ALL_NEW)
    assert set(a.R19_ALL_NEW) <= set(CURRICULUM261_R17_NAMESPACES)
    assert set(a.R19_ALL_NEW) <= set(R17_ALL_NAMESPACES)
    assert set(a.R19_FORMAL_FOUR) <= set(
        CURRICULUM261_R17_FORMAL_NAMESPACES)
    assert set(a.R19_FORMAL_FOUR) <= set(
        R17_FORMAL_QUALIFICATION_NAMESPACES)
    for name in a.R19_ALL_NEW:
        require_r17_namespace_registered(name)
    for name in a.R19_FORMAL_FOUR:
        require_r17_formal_namespace(name)


def test_old_formal_fours_stay_registered_but_unused():
    # R17/R18 旧四件套保持注册(历史未消费), 与 R19 四件套零重叠。
    old = {"qualification_r17", "preprocess_fit_qualification_r17",
           "c2_independent_qualification_r17",
           "cue_semantic_qualification_r17",
           "qualification_r18", "preprocess_fit_qualification_r18",
           "c2_independent_qualification_r18",
           "cue_semantic_qualification_r18"}
    assert old <= set(R17_FORMAL_QUALIFICATION_NAMESPACES)
    assert not old & set(a.R19_ALL_NEW)


def test_profiles_wire_r19_family():
    main = formal_main_profile_r17(20)
    hold = formal_holdout_profile_r17(20)
    assert main.c13_eval_namespace == a.R19_C13_MAIN
    assert main.supervised_namespace == a.R19_SUPERVISED_MAIN
    assert main.semantic_namespace == a.R19_SEMANTIC_MAIN
    assert main.c2_independent_namespace == a.R19_C2_INDEPENDENT_MAIN
    assert hold.c13_eval_namespace == a.R19_C13_HOLDOUT
    assert hold.semantic_namespace == a.R19_SEMANTIC_HOLDOUT
    rt_main = rt_main_profile_r17()
    rt_hold = rt_holdout_profile_r17()
    assert rt_main.c13_eval_namespace == a.R19_RT_CALIBRATION_MAIN
    assert rt_main.semantic_namespace == a.R19_RT_SEMANTIC_MAIN
    assert rt_hold.c13_eval_namespace == a.R19_RT_CALIBRATION_HOLDOUT
    assert rt_hold.c2_independent_namespace == (
        a.R19_RT_C2_INDEPENDENT_HOLDOUT)
    wired = {main.c13_eval_namespace, main.supervised_namespace,
             main.semantic_namespace, main.c2_matched_namespace,
             main.c2_independent_namespace, hold.c13_eval_namespace,
             hold.supervised_namespace, hold.semantic_namespace,
             hold.c2_matched_namespace, hold.c2_independent_namespace,
             rt_main.c13_eval_namespace, rt_main.supervised_namespace,
             rt_main.semantic_namespace, rt_main.c2_matched_namespace,
             rt_main.c2_independent_namespace,
             rt_hold.c13_eval_namespace, rt_hold.supervised_namespace,
             rt_hold.semantic_namespace, rt_hold.c2_matched_namespace,
             rt_hold.c2_independent_namespace}
    assert wired <= set(a.R19_ALL_NEW)


def test_routing_maps_r19_family():
    assert R17_ROLE_FIT_NAMESPACE == {
        "main": a.R19_FIT_MAIN,
        "holdout": a.R19_FIT_HOLDOUT,
        "final": a.R19_FIT_QUALIFICATION,
    }
    eval_expected = (
        a.R19_C13_MAIN, a.R19_C13_HOLDOUT, a.R19_QUALIFICATION,
        a.R19_C2_INDEPENDENT_MAIN, a.R19_C2_INDEPENDENT_HOLDOUT,
        a.R19_C2_INDEPENDENT_QUALIFICATION,
        a.R19_SEMANTIC_QUALIFICATION) + tuple(
        n for n in a.R19_RT_FAMILY
        if n not in (a.R19_RT_FIT_MAIN, a.R19_RT_FIT_HOLDOUT,
                     a.R19_RT_FIT_QUALIFICATION, a.R19_RT_STRESS))
    for name in eval_expected:
        assert name in R17_EVAL_NAMESPACE_ROLE, name
    # fit/stress/fresh_holdout 非 eval namespace(路由表不收录;与
    # R18 接线同口径)
    assert not {a.R19_FIT_MAIN, a.R19_STRESS,
                a.R19_FRESH_HOLDOUT} & set(R17_EVAL_NAMESPACE_ROLE)


def test_admission_tail_version_table():
    deploy = Path("/home/cryptorl/projects/crypto_rl")
    for tail in ("route_c_stage2_6_1_repair17",
                 "route_c_stage2_6_1_repair18",
                 "route_c_stage2_6_1_repair19"):
        assert deploy_root_of(deploy / "artifacts" / tail / "state") \
            == deploy
    assert deploy_root_of(
        deploy / "artifacts/route_c_stage2_6_1_repair20/state") is None
    assert deploy_root_of(deploy / "somewhere/state") is None


def test_r19_final_profile_namespaces():
    from rl_curriculum.curriculum261_r17_cli import R17_RT_FINAL_PROFILE
    values = {v for v in R17_RT_FINAL_PROFILE.values()
              if isinstance(v, str)}
    assert values <= set(a.R19_RT_FAMILY)
    assert R17_RT_FINAL_PROFILE["final_namespace"] == a.R19_RT_QUALIFICATION


def _find_runner_dir() -> Path:
    for cand in (Path("/mnt/f/trading/freqai-rl-audit/stage2_6_1/runner"),
                 Path("F:/trading/freqai-rl-audit/stage2_6_1/runner"),
                 Path(__file__).resolve().parents[2] / "runner"):
        if (cand / "r19_formal_chain.sh").is_file():
            return cand
    return Path(__file__).resolve().parents[2] / "runner"


def test_r19_entry_gate_validates_without_consuming():
    """单次消费合同(R18 双消费教训;R19 处方 §1.4):入口闸门只校验;
    唯一消费点=CLI formal 分支;链外前置守卫(勘误二)在准入闸门前。"""
    sh = (_find_runner_dir() / "r19_formal_chain.sh").read_text(
        encoding="utf-8")
    assert "\r" not in sh, "入口脚本必须保持 LF 行尾"
    assert "route_c_stage2_6_1_repair19" in sh
    start = sh.index('ADMISSION_PY" gate')
    end = sh.index('"; then', start)
    call = sh[start:end]
    assert "--freeze-sha" in call and "--state-root" in call
    assert "--consume" not in call
    # 链外前置守卫先于准入闸门(零消费早拒 rc=96)
    guard = sh.index("gate_topology_reconciliation.json")
    assert guard < start
    # 协调者 CLI 仍是 formal 分支的唯一消费点(enforce_formal_admission)。
    cli = (Path(__file__).resolve().parents[2] / "src" / "rl_curriculum"
           / "curriculum261_r17_cli.py").read_text(encoding="utf-8")
    assert "enforce_formal_admission(" in cli
