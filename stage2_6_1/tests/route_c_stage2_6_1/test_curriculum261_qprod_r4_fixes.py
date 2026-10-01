# QProd 返修轮4(R4)钉测试:C13 后 ChatGPT 第四次 NOT_CLOSED 三组。
# Q1 冻结语义重算(CI 含解析值/replay/tail/MC 容限=1.0 四反例,
#   全部 checks+digest 自洽仍拒;合法对照通过);
# Q3 manifest 条目级贯通(条目 500 vs global/qcap/report/实际 2 拒;
#   条目防脱钩);R01 由 r21 v6 流程覆盖(不在本文件)。
# 零原生/零 fit/零 optimizer。
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]
                       / "route_c_stage2_6_2"))

import test_curriculum261_qprod_aggregate as ta
import test_curriculum261_qprod_levela as tl
from rl_curriculum.curriculum261_qprod_aggregate import (
    _verify_coordinate, aggregate_research,
)
from rl_curriculum.curriculum261_qprod_context import QProdRunSession
from rl_curriculum.curriculum261_qprod_levela import (
    judge_qualification_gates, run_level_a_rehearsal,
)
from rl_curriculum.curriculum261_qprod_plan import load_research_plan
from rl_curriculum.curriculum261_r17_cue_contract import (
    cue_contract_audit_digest, recompute_audit_semantics_from_report,
)
from rl_curriculum.ppo262_qprod_export import export_qualification_delivery


def _rehearse(tmp_path):
    ctx = tl._ctx(tmp_path)
    session = QProdRunSession(ctx.state_root, level="level_a",
                              iteration_id=ctx.iteration_id)
    session.acquire({"entry": "t"})
    run_level_a_rehearsal(ctx, session, tl._fixture_inputs(tmp_path))
    return ctx


def _mutate_and_redigest(ctx, mutator):
    """修改 cue 报告后重算 audit_digest 使 hash 通道自洽
    (checks 全 True 保持)——模拟 addendum 要求的'全部反例更新
    公共 hash 且外层 checks 全 True,不靠陈旧 hash 挡住'。"""
    cue_p = ctx.artifact_root / "cue_contract_audit.json"
    cue = json.loads(cue_p.read_text(encoding="utf-8"))
    mutator(cue)
    cue["checks"] = {k: True for k in cue["checks"]}
    cue["pass"] = True
    cue["audit_digest"] = cue_contract_audit_digest(cue)
    cue_p.write_text(json.dumps(cue), encoding="utf-8")
    return cue


def _gate1(ctx):
    plan = json.loads((ctx.state_root / "qprod_qualification_plan.json"
                       ).read_text(encoding="utf-8"))
    return judge_qualification_gates(ctx.artifact_root, plan)


# ---------------------------------------------------------------- Q1
def test_r4q1_legal_control_passes(tmp_path):
    """合法对照(未篡改 rehearse 产物)gate1 通过。"""
    ctx = _rehearse(tmp_path)
    raw = _gate1(ctx)
    assert raw["gates"]["cue_audit_pass"]["pass"] is True
    obs = raw["gates"]["cue_audit_pass"]["observed"]
    assert obs["semantics_consistent"] is True
    assert obs["threshold_drift"] == []


def test_r4q1_ci_excludes_analytic_rejected(tmp_path):
    """CI 排除解析值(p_contract 移出 CI95)但 checks 全 True+
    digest 重算自洽 → 拒。"""
    def mut(cue):
        v = cue["direct_generator"]["validation"]
        lo = float(v["block_cluster"]["ci95"][0])
        # 把 CI 下界抬到 p_contract 之上 → 解析值落在 CI 外
        cue["direct_generator"]["validation"]["block_cluster"][
            "ci95"] = [float(cue["p_contract"]) + 0.02,
                       float(cue["p_contract"]) + 0.05]
        assert lo is not None

    ctx = _rehearse(tmp_path)
    _mutate_and_redigest(ctx, mut)
    raw = _gate1(ctx)
    obs = raw["gates"]["cue_audit_pass"]["observed"]
    assert raw["verdict"] == "FAIL"
    assert obs["semantics_consistent"] is False
    assert obs["frozen_semantics_recomputed"][
        "validation_corpus_ok"] is False


def test_r4q1_replay_false_rejected(tmp_path):
    """replay_ok=False(exact noise replay 失败)但 checks 全 True+
    digest 自洽 → 拒。"""
    def mut(cue):
        cue["direct_generator"]["model"]["replay_ok"] = False

    ctx = _rehearse(tmp_path)
    _mutate_and_redigest(ctx, mut)
    raw = _gate1(ctx)
    obs = raw["gates"]["cue_audit_pass"]["observed"]
    assert raw["verdict"] == "FAIL"
    detail = obs["frozen_semantics_detail"]["detail"]
    assert detail["model_replay_bitwise_ok"] is False
    assert obs["frozen_semantics_recomputed"][
        "model_corpus_ok"] is False


def test_r4q1_tail_numeric_failure_rejected(tmp_path):
    """tail 数值失败(tail emp 远离 analytic,报告自带容差也放大
    试图掩护)但 checks 全 True+digest 自洽 → 冻结公式重算拒。"""
    def mut(cue):
        t = cue["direct_generator"]["validation"]["tail"]
        t["empirical_recall"] = float(t["analytic_conditional"]) + 0.5
        t["diff_tolerance"] = 1.0  # 擅自放大 tail 容差

    ctx = _rehearse(tmp_path)
    _mutate_and_redigest(ctx, mut)
    raw = _gate1(ctx)
    obs = raw["gates"]["cue_audit_pass"]["observed"]
    assert raw["verdict"] == "FAIL"
    detail = obs["frozen_semantics_detail"]["detail"]
    assert detail["validation_tail_numeric_within"] is False
    assert any("tail.diff_tolerance" in d for d in obs["threshold_drift"])


def test_r4q1_mc_tolerance_inflated_to_one_rejected(tmp_path):
    """报告把 MC 容限改为 1.0(p_hat 偏离超真实容差也判过)但
    checks 全 True+digest 自洽 → 冻结容差 0.001 重算拒+阈值漂移
    记录。"""
    def mut(cue):
        mc = cue["monte_carlo"]
        mc["p_hat"] = float(cue["p_contract"]) + 0.05  # 真实失败
        mc["tolerance"] = 1.0                            # 擅自放宽

    ctx = _rehearse(tmp_path)
    _mutate_and_redigest(ctx, mut)
    raw = _gate1(ctx)
    obs = raw["gates"]["cue_audit_pass"]["observed"]
    assert raw["verdict"] == "FAIL"
    assert obs["frozen_semantics_recomputed"][
        "mc_close_to_analytic"] is False
    assert any("冻结值" in d for d in obs["threshold_drift"])


def test_r4q1_recompute_pure_structure_cases():
    """recompute 纯结构用例:阈值漂移与数值矛盾直接可判。"""
    base = {
        "p_contract": 0.5,
        "monte_carlo": {"p_hat": 0.5, "tolerance": 0.001},
        "direct_generator": {
            n: {
                "block_cluster": {"se": 0.01, "ci95": [0.45, 0.55]},
                "empirical_recall": 0.5,
                "analytic_conditional": 0.5,
                "diff_tolerance": 0.03,
                "replay_ok": True, "bounds_ok": True,
                "cue_table_consistent_across_rungs": True,
                "max_replay_abs_error": 0.0,
                "aggregate": {"k_mean": 1.0, "n_detected": 1,
                              "n_events": 2,
                              "k_histogram": {"1": 2}},
                "tail": {"n_events": 0},
            } for n in ("model", "validation")},
        "tail_mirror_bound_integrity": {
            "pass": True,
            "per_corpus": {n: {"ok": True, "violations": [],
                               "n_violations": 0,
                               "exact_noise_replay_ok": True,
                               "bounds_ok_all_positions": True}
                           for n in ("model", "validation")}},
        "global_k_audit": {"pass": True, "verdict": "PASS",
                           "final": {"verdict": "PASS",
                                     "indeterminate": False}},
        "once_vs_attempts": {
            "recall_model": 0.5, "recall_validation": 0.5,
            "abs_diff": 0.0, "tolerance": 0.042426406871192854,
            "recall_modes_consistent": True,
            "k_mean_model": 1.0, "k_mean_validation": 1.0,
            "k_abs_diff": 0.0, "k_tolerance": 0.05,
            "k_modes_consistent": True,
            "first_pass_bitwise_check": {"bitwise_ok": True}},
        "aggregate_recompute_ok": True,
        "checks": {},
    }
    from rl_curriculum.curriculum261_r17_cue_contract import (
        AUDIT_REQUIRED_CHECK_NAMES,
    )
    base["checks"] = {k: True for k in AUDIT_REQUIRED_CHECK_NAMES}
    ok = recompute_audit_semantics_from_report(copy.deepcopy(base))
    assert ok["all_consistent"] is True
    # MC 容限漂移
    m = copy.deepcopy(base)
    m["monte_carlo"]["tolerance"] = 1.0
    m["monte_carlo"]["p_hat"] = 0.55
    r = recompute_audit_semantics_from_report(m)
    assert r["all_consistent"] is False
    assert r["recomputed"]["mc_close_to_analytic"] is False
    # CI 排除解析值
    m = copy.deepcopy(base)
    m["direct_generator"]["model"]["block_cluster"]["ci95"] = [
        0.6, 0.7]
    r = recompute_audit_semantics_from_report(m)
    assert r["recomputed"]["model_corpus_ok"] is False
    # replay False
    m = copy.deepcopy(base)
    m["direct_generator"]["validation"]["replay_ok"] = False
    r = recompute_audit_semantics_from_report(m)
    assert r["recomputed"]["validation_corpus_ok"] is False


# ---------------------------------------------------------------- Q3
def _plan_entry(tmp_path, *, entry_blocks=None):
    """_setup_plan 返回 (art, state, digest);条目级改写后重新冻结
    计划并返回新 digest 供 _build_coordinate 绑定。"""
    from rl_curriculum.curriculum261_qprod_plan import (
        freeze_research_plan,
    )
    art, state, digest = ta._setup_plan(tmp_path)
    plan = load_research_plan(state)
    if entry_blocks is not None:
        # 条目级预算漂移形成**新计划**(冻结计划不可改写)——
        # 新 state 根重锁,模拟攻击面:条目 500 与 global 2 并存
        state2 = tmp_path / "state2"
        state2.mkdir(parents=True, exist_ok=True)
        plan = json.loads(json.dumps(plan))
        plan["coordinate_manifest"][0]["blocks_per_corpus"] = entry_blocks
        plan.pop("research_plan_digest", None)
        freeze_research_plan(state2, plan)
        state = state2
        plan = load_research_plan(state)
    return art, state, plan


def _digest_of(state):
    return (Path(state) / "qprod_research_plan_digest.txt"
            ).read_text(encoding="utf-8").strip()


def test_r4q3_manifest_entry_500_vs_everywhere_2_rejected(tmp_path):
    """条目 500 vs global/qcap/report/实际 2 → aggregate 拒该坐标
    (invalid;完整计划装载路径)。"""
    art, state, plan = _plan_entry(tmp_path, entry_blocks=500)
    coord = plan["coordinate_manifest"][0]
    ta._build_coordinate(art, coord["artifact_subdir"],
                         plan_digest=_digest_of(state))
    v = _verify_coordinate(
        art / coord["artifact_subdir"], coord, plan)
    assert v["state"] != "valid"
    assert any("blocks_per_corpus=500" in p for p in v["problems"])
    agg = aggregate_research(art, state_root=state)
    assert agg["valid_coordinate_count"] == 0
    c0 = agg["coordinates"][0]
    assert c0["state"] != "valid"
    assert any("blocks_per_corpus=500" in p
               for p in c0.get("problems", []))


def test_r4q3_legal_two_block_control_still_valid(tmp_path):
    """合法 2 块对照(global=qcap=report=实际=条目一致)valid。"""
    art, state, plan = _plan_entry(tmp_path)
    coord = plan["coordinate_manifest"][0]
    ta._build_coordinate(art, coord["artifact_subdir"],
                         plan_digest=_digest_of(state))
    v = _verify_coordinate(
        art / coord["artifact_subdir"], coord, plan)
    assert v["state"] == "valid", v.get("problems")


def test_r4q3_decoupled_coordinate_rejected(tmp_path):
    """传入 coordinate 与 manifest 条目内容不一致(脱钩)→ 拒。"""
    art, state, plan = _plan_entry(tmp_path)
    coord = copy.deepcopy(plan["coordinate_manifest"][0])
    ta._build_coordinate(art, coord["artifact_subdir"],
                         plan_digest=_digest_of(state))
    # 脱钩条目:用计划内**另一条目**的合法 namespace(注册过、
    # 不触发生成拒绝)但归属与本条目不一致——防"构造条目绕过
    # 清单审计"的守卫必须拒。
    other_ns = plan["coordinate_manifest"][1]["model_namespace"]
    rogue = dict(coord, model_namespace=other_ns)
    v = _verify_coordinate(art / coord["artifact_subdir"], rogue, plan)
    assert v["state"] != "valid"
    assert any("脱钩" in p for p in v["problems"])
