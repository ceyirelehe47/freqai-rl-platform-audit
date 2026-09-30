# QProd 返修轮5(R5)钉测试:C14 后第五次 NOT_CLOSED,Q1 公共判据三洞。
# (a) ova consistent=True 但数值与 direct_generator 矛盾/差值超冻结
#     容差 → 拒(不采信声明布尔,从在场数值重算);
# (b) tail 完整性子输入 exact_noise_replay_ok=False 而 ok/pass=True →
#     由真实子条件拒(不只看上层 ok);
# (c) max_replay_abs_error 坏数值保留+删除 replay_ok 字段 → fixture
#     委托被否决(缺失不能豁免在场坏数值)。
# 通用原则:八门派生声明必须与在场子输入/数值影子一致;生产与复验
# 共享 core 冻结纯判据。R4 四反例与合法对照保持(见 r4_fixes)。
# 零原生/零生成/零 MC/零 fit/零 optimizer。
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]
                       / "route_c_stage2_6_2"))

import test_curriculum261_qprod_levela as tl
from rl_curriculum.curriculum261_qprod_context import QProdRunSession
from rl_curriculum.curriculum261_qprod_levela import (
    judge_qualification_gates, run_level_a_rehearsal,
)
from rl_curriculum.curriculum261_r17_cue_contract import (
    _REPLAY_TOL_REF, cue_contract_audit_digest,
    recompute_audit_semantics_from_report,
)
from rl_curriculum.curriculum261_r17_noise_replay import REPLAY_TOL


def _rehearse(tmp_path):
    ctx = tl._ctx(tmp_path)
    session = QProdRunSession(ctx.state_root, level="level_a",
                              iteration_id=ctx.iteration_id)
    session.acquire({"entry": "t"})
    run_level_a_rehearsal(ctx, session, tl._fixture_inputs(tmp_path))
    return ctx


def _mutate_and_redigest(ctx, mutator):
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


def test_r5_replay_tol_ref_matches_frozen_contract():
    """数值影子判据与生成内核 REPLAY_TOL 冻结同源(交叉断言)。"""
    assert _REPLAY_TOL_REF == REPLAY_TOL == 1e-12


def test_r5q1a_legal_control_still_passes(tmp_path):
    """合法对照(未篡改)通过;R5 收紧不误伤。"""
    ctx = _rehearse(tmp_path)
    raw = _gate1(ctx)
    obs = raw["gates"]["cue_audit_pass"]["observed"]
    assert raw["gates"]["cue_audit_pass"]["pass"] is True
    assert obs["semantics_consistent"] is True
    assert obs["threshold_drift"] == []


def test_r5q1b_ova_declared_consistent_but_numbers_contradict(tmp_path):
    """ova recall 字段与 direct_generator 矛盾+自身差值超冻结容差+
    consistent=True+checks/digest 自洽 → 拒(数值重算,非声明)。"""
    def mut(cue):
        cue["once_vs_attempts"] = {
            "recall_model": 0.30, "recall_validation": 0.95,
            "recall_modes_consistent": True,
            "k_modes_consistent": True,
            "first_pass_bitwise_check": {"bitwise_ok": True}}

    ctx = _rehearse(tmp_path)
    _mutate_and_redigest(ctx, mut)
    raw = _gate1(ctx)
    obs = raw["gates"]["cue_audit_pass"]["observed"]
    assert raw["verdict"] == "FAIL"
    assert obs["semantics_consistent"] is False
    assert obs["frozen_semantics_recomputed"][
        "once_vs_attempts_consistent"] is False
    drift = " ".join(obs["threshold_drift"])
    assert "矛盾" in drift or "冻结容差" in drift


def test_r5q1c_tail_subinput_false_overrides_declared_ok(tmp_path):
    """tail 完整性子输入 exact_noise_replay_ok=False 而 ok/pass=True、
    violations 空 → 由真实子条件拒。"""
    def mut(cue):
        cue["tail_mirror_bound_integrity"] = {
            "pass": True,
            "per_corpus": {
                n: {"ok": True, "violations": [], "n_violations": 0,
                    "exact_noise_replay_ok": False,
                    "bounds_ok_all_positions": True}
                for n in ("model", "validation")}}

    ctx = _rehearse(tmp_path)
    _mutate_and_redigest(ctx, mut)
    raw = _gate1(ctx)
    obs = raw["gates"]["cue_audit_pass"]["observed"]
    assert raw["verdict"] == "FAIL"
    assert obs["frozen_semantics_recomputed"][
        "tail_mirror_bound_integrity_pass"] is False
    assert any("子输入矛盾" in d
               for d in obs["threshold_drift"])


def test_r5q1d_bad_replay_number_with_field_deleted(tmp_path):
    """max_replay_abs_error=0.25 保留、replay_ok 删除 → fixture 委托
    被否决,不得 FAIL 变 PASS。"""
    def mut(cue):
        for n in ("model", "validation"):
            c = cue["direct_generator"][n]
            c["max_replay_abs_error"] = 0.25
            c.pop("replay_ok", None)

    ctx = _rehearse(tmp_path)
    _mutate_and_redigest(ctx, mut)
    raw = _gate1(ctx)
    obs = raw["gates"]["cue_audit_pass"]["observed"]
    assert raw["verdict"] == "FAIL"
    detail = obs["frozen_semantics_detail"]["detail"]
    assert detail["model_replay_bitwise_ok"] is False
    assert "fixture_delegated" not in json.dumps(
        ["model.replay_ok"]) or "model.replay_ok" not in obs[
        "frozen_semantics_detail"]["fixture_delegated"]
    assert any("数值影子" in d or "数值失败" in d
               for d in obs["threshold_drift"])


def test_r5q1e_bad_replay_number_with_false_flag_still_rejected(tmp_path):
    """对照:replay_ok=False 保留(原 R4 路径)不变拒。"""
    def mut(cue):
        cue["direct_generator"]["model"]["replay_ok"] = False

    ctx = _rehearse(tmp_path)
    _mutate_and_redigest(ctx, mut)
    raw = _gate1(ctx)
    assert raw["verdict"] == "FAIL"


def test_r5q1f_formal_report_missing_support_field_false():
    """正式报告(无 fixture 标记)缺支撑字段 → False(不委托);
    直调 helper 的无 fixture 控制正确拒绝。"""
    base = {
        "p_contract": 0.5,
        "monte_carlo": {"p_hat": 0.5, "tolerance": 0.001},
        "direct_generator": {
            n: {
                "block_cluster": {"se": 0.01, "ci95": [0.45, 0.55]},
                "empirical_recall": 0.5,
                "analytic_conditional": 0.5,
                "diff_tolerance": 0.03,
                # replay_ok/bounds_ok/cue_table 缺失 → 正式 False
                "tail": {"n_events": 0},
            } for n in ("model", "validation")},
        "tail_mirror_bound_integrity": {
            "pass": True,
            "per_corpus": {n: {"ok": True, "violations": []}
                           for n in ("model", "validation")}},
        "global_k_audit": {"pass": True, "verdict": "CP"},
        "once_vs_attempts": {
            "recall_model": 0.5, "recall_validation": 0.5,
            "recall_modes_consistent": True,
            "k_modes_consistent": True,
            "first_pass_bitwise_check": {"bitwise_ok": True}},
        "aggregate_recompute_ok": True,
        "checks": {},
    }
    from rl_curriculum.curriculum261_r17_cue_contract import (
        AUDIT_REQUIRED_CHECK_NAMES,
    )
    base["checks"] = {k: True for k in AUDIT_REQUIRED_CHECK_NAMES}
    r = recompute_audit_semantics_from_report(base)
    assert r["all_consistent"] is False
    assert r["recomputed"]["model_corpus_ok"] is False
    assert r["recomputed"]["validation_corpus_ok"] is False
    assert r["fixture_mode"] is False
    assert r["fixture_delegated"] == []
