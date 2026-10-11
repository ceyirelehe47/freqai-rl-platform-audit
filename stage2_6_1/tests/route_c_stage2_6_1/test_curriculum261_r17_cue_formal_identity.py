# -*- coding: utf-8 -*-
"""RouteC_CueAudit_FormalIdentityClosure_v1:CI01–CI07 工程测试。

覆盖(qaf_v3 A2 第 4 步 cue-audit 技术失败的正式身份闭合):
- CI01/CI02:注册族 namespace + 锁定计划 → 正式 core 入口(旧缺陷
  关闭);未注册/混族/单边/缩减规模/免锁占用全部在科学叶前拒绝。
- CI03:锁定计划与实际执行参数三方一致(namespace/规模错配拒绝;
  篡改 plan 规模即使 digest 重算一致也拒绝)。
- CI04:正式分支 Global-K 50k→200k、500+500、MC 1e6 冻结值不变;
  工程分支继续 2000/None。
- CI05:注册族正式报告记录实际 namespace/预算(report_actual_
  values);digest 复算一致;design plan payload 等下游消费者接受。
- CI06:legacy 全缺省正式/rehearsal rt 坐标/工程显式参数/coordinate
  的既有行为不变;显式等价参数=工程(即使数值等于默认)政策固化。

科学重叶(生成/统计)以记录型替身替代(边界见各 stub);被验的
分类/守卫/计划/报告/消费者合同全部真实。零正式签发/零正式
namespace 语料生成(替身不产生真实 corpus)。
"""

import json
import sys
from pathlib import Path

import numpy as np
import pytest

#: 布局自适应(仓树/部署树)
_BASE = Path(__file__).resolve().parents
TREE = next(b for b in _BASE if (b / "src" / "rl_curriculum").is_dir()
            or (b / "stage2_6_1" / "src" / "rl_curriculum").is_dir())
SRC_DIR = (TREE / "src" if (TREE / "src" / "rl_curriculum").is_dir()
           else TREE / "stage2_6_1" / "src")
sys.path.insert(0, str(SRC_DIR))

import rl_curriculum.curriculum261_r17_cue_contract as cue_mod  # noqa: E402
from rl_curriculum.curriculum261_qaf_attempt import (  # noqa: E402
    QAF3_ATTEMPT_ID, QAF_ATTEMPTS, qaf_attempt_family,
)
from rl_curriculum.curriculum261_r17_cue_contract import (  # noqa: E402
    AUDIT_BLOCKS_PER_CORPUS, AUDIT_MODEL_NAMESPACE,
    AUDIT_N_EVENTS, AUDIT_VALIDATION_NAMESPACE,
    cue_audit_plan_digest_r17, cue_contract_audit_digest,
    lock_cue_audit_plan_r17, registered_cue_contract_family,
    run_cue_contract_audit,
)

FAM3 = qaf_attempt_family(QAF3_ATTEMPT_ID)


class _CoreCapture:
    """记录型替身:捕获 core 入参,不执行科学叶。"""

    def __init__(self):
        self.calls = []

    def __call__(self, out_dir, **kwargs):
        self.calls.append({"out_dir": out_dir, **kwargs})
        return {"format": "cur261-r17-cue-contract-audit-v1",
                "pass": True, "audit_digest": "r15ca-sentinel",
                "p_contract": 0.5}


@pytest.fixture()
def core_capture(monkeypatch):
    cap = _CoreCapture()
    monkeypatch.setattr(cue_mod, "_run_cue_contract_audit_core", cap)
    return cap


# ================= CI02:正式身份分类 =================
def test_registered_pair_resolver():
    for fam in QAF_ATTEMPTS.values():
        got = registered_cue_contract_family(
            fam.cue_contract_model, fam.cue_contract_validation)
        assert got is fam
    # 混族/单边/任意串/rt 坐标/缺省都不构成注册身份
    assert registered_cue_contract_family(
        FAM3.cue_contract_model, "cue_contract_validation_qaf_v2") is None
    assert registered_cue_contract_family(FAM3.cue_contract_model,
                                          None) is None
    assert registered_cue_contract_family(
        None, FAM3.cue_contract_validation) is None
    assert registered_cue_contract_family(
        "cue_contract_model_bogus", "cue_contract_validation_bogus") is None
    assert registered_cue_contract_family(
        "rt_cue_model_r17", "rt_cue_validation_r17") is None


def test_qaf_v3_family_formal_path_reaches_core(tmp_path, core_capture):
    """CI01/CI02 核心:旧 A 失败调用形态(注册族 ns+锁定计划)在
    新候选通过分类与计划核验,到达正确正式 core 入口。"""
    lock_cue_audit_plan_r17(
        tmp_path, model_namespace=FAM3.cue_contract_model,
        validation_namespace=FAM3.cue_contract_validation)
    report = run_cue_contract_audit(
        tmp_path, require_locked_plan=True,
        model_namespace=FAM3.cue_contract_model,
        validation_namespace=FAM3.cue_contract_validation)
    assert report["pass"] is True
    (call,) = core_capture.calls
    assert call["formal"] is True
    assert call["model_ns"] == FAM3.cue_contract_model
    assert call["validation_ns"] == FAM3.cue_contract_validation
    assert call["n_blocks_per_corpus"] == AUDIT_BLOCKS_PER_CORPUS
    assert call["n_mc_events"] == AUDIT_N_EVENTS
    assert call["report_actual_values"] is True
    assert call["audit_plan_digest_value"].startswith("r15ap-")


@pytest.mark.parametrize("attempt_id", list(QAF_ATTEMPTS))
def test_all_registered_families_formal(tmp_path, core_capture,
                                        attempt_id):
    fam = QAF_ATTEMPTS[attempt_id]
    lock_cue_audit_plan_r17(
        tmp_path, model_namespace=fam.cue_contract_model,
        validation_namespace=fam.cue_contract_validation)
    run_cue_contract_audit(
        tmp_path, require_locked_plan=True,
        model_namespace=fam.cue_contract_model,
        validation_namespace=fam.cue_contract_validation)
    (call,) = core_capture.calls
    assert call["formal"] is True
    assert call["model_ns"] == fam.cue_contract_model


def test_unregistered_explicit_ns_with_plan_refused(tmp_path,
                                                    core_capture):
    with pytest.raises(RuntimeError, match="非正式"):
        run_cue_contract_audit(
            tmp_path, require_locked_plan=True,
            model_namespace="cue_contract_model_bogus",
            validation_namespace="cue_contract_validation_bogus")
    assert core_capture.calls == []


def test_mixed_family_pair_refused(tmp_path, core_capture):
    fam2 = QAF_ATTEMPTS["qaf_v2"]
    with pytest.raises(RuntimeError, match="非正式"):
        run_cue_contract_audit(
            tmp_path, require_locked_plan=True,
            model_namespace=FAM3.cue_contract_model,
            validation_namespace=fam2.cue_contract_validation)
    assert core_capture.calls == []


def test_single_side_namespace_refused(tmp_path, core_capture):
    with pytest.raises(RuntimeError, match="非正式"):
        run_cue_contract_audit(
            tmp_path, require_locked_plan=True,
            model_namespace=FAM3.cue_contract_model,
            validation_namespace=None)
    with pytest.raises(RuntimeError, match="非正式"):
        run_cue_contract_audit(
            tmp_path, require_locked_plan=True, model_namespace=None,
            validation_namespace=FAM3.cue_contract_validation)
    assert core_capture.calls == []


def test_family_without_locked_plan_refused(core_capture):
    """未经授权跳过锁定:注册族身份不得以免锁形态执行。"""
    with pytest.raises(RuntimeError, match="正式锁定计划形态"):
        run_cue_contract_audit(
            model_namespace=FAM3.cue_contract_model,
            validation_namespace=FAM3.cue_contract_validation,
            require_locked_plan=False)
    assert core_capture.calls == []


@pytest.mark.parametrize("overrides", [
    {"blocks_per_corpus": 10},
    {"mc_events": 2_000_000},
])
def test_family_reduced_or_oversized_scale_refused(overrides,
                                                   core_capture):
    """缩减/超额规模不得占用注册族正式身份。"""
    with pytest.raises(RuntimeError, match="正式锁定计划形态"):
        run_cue_contract_audit(
            model_namespace=FAM3.cue_contract_model,
            validation_namespace=FAM3.cue_contract_validation,
            require_locked_plan=True, **overrides)
    assert core_capture.calls == []


def test_explicit_equivalent_params_policy(tmp_path, core_capture):
    """既定政策(可测边界):显式参数=工程模式,即使数值恰等于
    正式默认(显式等价不获正式权限;带锁定计划即拒绝)。"""
    with pytest.raises(RuntimeError, match="非正式"):
        run_cue_contract_audit(
            tmp_path, require_locked_plan=True,
            model_namespace=AUDIT_MODEL_NAMESPACE,
            validation_namespace=AUDIT_VALIDATION_NAMESPACE)
    # 免锁显式(数值等价)按工程分类,不获 formal
    run_cue_contract_audit(
        model_namespace=AUDIT_MODEL_NAMESPACE,
        validation_namespace=AUDIT_VALIDATION_NAMESPACE,
        require_locked_plan=False)
    (call,) = core_capture.calls
    assert call["formal"] is False
    assert call["report_actual_values"] is False


# ================= CI03:计划三方一致 =================
def test_plan_namespace_mismatch_refused(tmp_path, core_capture):
    fam2 = QAF_ATTEMPTS["qaf_v2"]
    lock_cue_audit_plan_r17(
        tmp_path, model_namespace=fam2.cue_contract_model,
        validation_namespace=fam2.cue_contract_validation)
    with pytest.raises(RuntimeError, match="不一致"):
        run_cue_contract_audit(
            tmp_path, require_locked_plan=True,
            model_namespace=FAM3.cue_contract_model,
            validation_namespace=FAM3.cue_contract_validation)
    assert core_capture.calls == []


def test_tampered_plan_scale_refused(tmp_path, core_capture):
    """篡改 plan 规模(重算 digest 一致)仍被三方一致核验拒绝。"""
    lock_cue_audit_plan_r17(
        tmp_path, model_namespace=FAM3.cue_contract_model,
        validation_namespace=FAM3.cue_contract_validation)
    path = tmp_path / "cue_audit_plan.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["blocks_per_corpus"] = AUDIT_BLOCKS_PER_CORPUS - 1
    payload["cue_audit_plan_digest"] = cue_audit_plan_digest_r17(payload)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                    encoding="utf-8")
    (tmp_path / "cue_audit_plan_digest.txt").write_text(
        payload["cue_audit_plan_digest"], encoding="utf-8")
    with pytest.raises(RuntimeError, match="不一致"):
        run_cue_contract_audit(
            tmp_path, require_locked_plan=True,
            model_namespace=FAM3.cue_contract_model,
            validation_namespace=FAM3.cue_contract_validation)
    assert core_capture.calls == []


# ================= CI06:兼容(legacy/rehearsal/工程) =================
def test_legacy_default_formal_with_locked_plan(tmp_path, core_capture):
    """legacy 全缺省 + 锁定计划:逐字节历史行为(formal=True、
    常量命名空间、report_actual_values=False)。"""
    lock_cue_audit_plan_r17(tmp_path)
    run_cue_contract_audit(tmp_path, require_locked_plan=True)
    (call,) = core_capture.calls
    assert call["formal"] is True
    assert call["model_ns"] == AUDIT_MODEL_NAMESPACE
    assert call["validation_ns"] == AUDIT_VALIDATION_NAMESPACE
    assert call["report_actual_values"] is False
    assert call["n_blocks_per_corpus"] == AUDIT_BLOCKS_PER_CORPUS
    assert call["n_mc_events"] == AUDIT_N_EVENTS


def test_engineering_explicit_small_and_rehearsal_ns(core_capture):
    """工程显式小规模与 rehearsal rt 坐标继续非正式(历史行为)。"""
    run_cue_contract_audit(
        None, blocks_per_corpus=2, mc_events=4096,
        model_namespace="rt_cue_model_r17",
        validation_namespace="rt_cue_validation_r17",
        require_locked_plan=False)
    (call,) = core_capture.calls
    assert call["formal"] is False
    assert call["n_blocks_per_corpus"] == 2
    assert call["n_mc_events"] == 4096
    assert call["report_actual_values"] is False


def test_coordinate_path_guard_unchanged():
    """coordinate wrapper 专属守卫原样:coordinate_context 仅在
    report_actual_values 模式合法(core 级合同)。"""
    from rl_curriculum.curriculum261_r17_cue_contract import (
        _run_cue_contract_audit_core,
    )
    with pytest.raises(RuntimeError, match="coordinate_context"):
        _run_cue_contract_audit_core(
            None, n_blocks_per_corpus=2, n_mc_events=100,
            model_ns="rt_cue_model_r17",
            validation_ns="rt_cue_validation_r17", formal=False,
            coordinate_context={"x": 1})


# ================= CI04/CI05:正式 core 分支与报告 =================
class _StubGen:
    """记录型科学叶替身:只产生最小合法结构,不生成真实 corpus。"""

    def __init__(self):
        self.once_calls = []
        self.attempts_calls = 0
        self.tier_calls = []

    def gen_once(self, ladder, seed, ns):
        self.once_calls.append((ns, seed))
        import pandas as pd
        ep = type("EP", (), {})()
        ep.hidden = {"cue_dir": pd.Series([0, 0, 0, 0])}
        ep.df = None
        return {r: {"A": ep, "B": ep}
                for r in ("D0", "D1", "D2", "D3")}

    def gen_attempts(self, ladder, *, namespace, block_index):
        self.attempts_calls += 1
        block = type("BLK", (), {})()
        block.block_index = block_index
        block.attempt_log = type("LOG", (), {})()
        block.attempt_log.selected_attempt = 0
        block.episodes = self.gen_once(ladder, 0, namespace)
        return block


def _install_core_stubs(monkeypatch):
    """科学重叶替身(边界:生成/event trace/统计聚簇/global-K null)。

    保留真实:MC 解析核对、analytic 积分、mirror/primary 边界、
    报告构建/序列化/audit digest、正式分支选择。
    """
    stub = _StubGen()
    events = [{"block_index": 0, "cue_bar": 10, "detected": True,
               "k_actual": 2, "primary_present": True,
               "mirror_candidates": 1, "mirror_positions": [2],
               "effective_sigma_bps": 9.0, "actual_noise": 0.0,
               "cue_read": 1.0},
              {"block_index": 0, "cue_bar": 11, "detected": True,
               "k_actual": 2, "primary_present": True,
               "mirror_candidates": 1, "mirror_positions": [3],
               "effective_sigma_bps": 9.0, "actual_noise": 0.0,
               "cue_read": 1.0}]

    def _trace(ep, ladder, seed, bi):
        return {"events": list(events), "max_replay_abs_error": 0.0,
                "replay_ok": True, "bounds_ok": True}

    def _trace_blocks(blocks, ladder):
        return {"events": list(events),
                "block_traces": [_trace(None, ladder, 0, i)
                                 for i in range(len(blocks))]}

    def _summarize(evs, n):
        dist = {}
        for e in evs:
            dist[e["cue_bar"]] = dist.get(e["cue_bar"], 0) + 1
        return {"n_events": len(evs),
                "n_detected": sum(1 for e in evs if e["detected"]),
                "recall": 1.0, "cue_position_distribution": dist,
                "k_mean": 2.0, "tail": {"recall": 1.0}}

    def _boot(counts):
        return {"point": 1.0, "se": 0.01, "ci95": [0.5, 1.0],
                "lcb95": 0.9, "n_events": 2}

    monkeypatch.setattr(cue_mod, "generate_matched_block_once",
                        stub.gen_once)
    monkeypatch.setattr(
        cue_mod, "generate_matched_block_with_attempts",
        stub.gen_attempts)
    monkeypatch.setattr(cue_mod, "cue_event_trace", _trace)
    monkeypatch.setattr(cue_mod, "trace_matched_blocks", _trace_blocks)
    monkeypatch.setattr(cue_mod, "summarize_events", _summarize)
    monkeypatch.setattr(cue_mod, "_cluster_bootstrap",
                        lambda counts: _boot(counts))
    monkeypatch.setattr(
        cue_mod, "_once_vs_attempts_bitwise_check_r17",
        lambda *a, **k: {"bitwise_ok": True, "n_blocks_checked": 2})
    monkeypatch.setattr(cue_mod, "block_attempt_statistics",
                        lambda blocks: {"n_blocks": len(blocks)})
    monkeypatch.setattr(cue_mod, "matched_block_seed_of",
                        lambda b: 7)
    monkeypatch.setattr(cue_mod, "_tail_k_position_checks",
                        lambda evs, n: {})
    monkeypatch.setattr(cue_mod, "_tail_mirror_bound_integrity",
                        lambda evs, r, b, n: {"pass": True})

    import rl_curriculum.curriculum261_r17_global_k as gk

    def _run_gk(evs, *, b_tier1, b_tier2=None, n=None):
        stub.tier_calls.append({"b_tier1": b_tier1,
                                "b_tier2": b_tier2})
        return {"contract_version": "stub", "contract_digest": "d",
                "graph_integrity_ok": True, "n_eligible_cells": 1,
                "T_obs": 0.1, "argmax_cell": "c", "final": "tier1",
                "verdict": "REJECT", "pass": True}

    monkeypatch.setattr(gk, "run_global_k_audit", _run_gk)
    monkeypatch.setattr(gk, "cell_diagnostics_from_result",
                        lambda res, evs, n=None: [])
    return stub


def _run_core(stubs_dir, formal, ns_model, ns_validation,
              report_actual_values, blocks=4, mc=50_000):
    return cue_mod._run_cue_contract_audit_core(
        stubs_dir, n_blocks_per_corpus=blocks, n_mc_events=mc,
        model_ns=ns_model, validation_ns=ns_validation,
        formal=formal, report_actual_values=report_actual_values)


def test_formal_core_branch_tiers_and_report(tmp_path, monkeypatch):
    """CI04/CI05:正式分支 Global-K 50k/200k、规模与报告实际值。"""
    stub = _install_core_stubs(monkeypatch)
    report = _run_core(tmp_path, True, FAM3.cue_contract_model,
                       FAM3.cue_contract_validation, True)
    (tier,) = stub.tier_calls
    from rl_curriculum.curriculum261_r17_global_k import NULL_B_TIER1
    assert tier["b_tier1"] == NULL_B_TIER1 == 50_000
    assert tier["b_tier2"] == 4 * NULL_B_TIER1 == 200_000
    assert report["formal_audit"] is True
    assert report["audit_namespaces"] == {
        "model": FAM3.cue_contract_model,
        "validation": FAM3.cue_contract_validation}
    assert report["audit_blocks_per_corpus"] == 4  # stub 规模透传
    assert report["audit_n_events_mc"] == 50_000
    assert report["report_mode"] == "actual_values"
    assert "coordinate_execution" not in report  # 非 B 坐标
    assert report["audit_digest"] == cue_contract_audit_digest(report)
    # 原件落盘 + digest 可复算(真实 serializer)
    saved = json.loads(
        (tmp_path / "cue_contract_audit.json").read_text("utf-8"))
    assert saved["audit_digest"] == report["audit_digest"]


def test_engineering_core_branch_tiers_and_report(tmp_path,
                                                  monkeypatch):
    """CI04/CI06:工程分支 2000/None 与常量命名空间报告不变。"""
    stub = _install_core_stubs(monkeypatch)
    report = _run_core(tmp_path, False, "rt_cue_model_r17",
                       "rt_cue_validation_r17", False)
    (tier,) = stub.tier_calls
    assert tier["b_tier1"] == 2000 and tier["b_tier2"] is None
    assert report["formal_audit"] is False
    assert report["audit_namespaces"] == {
        "model": AUDIT_MODEL_NAMESPACE,
        "validation": AUDIT_VALIDATION_NAMESPACE}
    assert "report_mode" not in report
    assert "coordinate_execution" not in report


def test_wrapper_family_full_path_with_stubs(tmp_path, monkeypatch):
    """wrapper→core 全链(科学叶替身):计划核验+实际值报告。"""
    _install_core_stubs(monkeypatch)
    lock_cue_audit_plan_r17(
        tmp_path, model_namespace=FAM3.cue_contract_model,
        validation_namespace=FAM3.cue_contract_validation)
    report = run_cue_contract_audit(
        tmp_path, require_locked_plan=True,
        model_namespace=FAM3.cue_contract_model,
        validation_namespace=FAM3.cue_contract_validation)
    assert report["formal_audit"] is True
    assert report["audit_namespaces"]["model"] == (
        FAM3.cue_contract_model)
    assert report["cue_audit_plan_digest"].startswith("r15ap-")
    assert report["audit_digest"] == cue_contract_audit_digest(report)


# ================= CI07:正式形态 CLI/工作流透传 =================
def test_cli_cue_audit_family_attempt_real_path(tmp_path, monkeypatch):
    """真实 cmd_cue_audit 路径(qaf_v3 注册族;core 以替身截停):
    预算门(工程目录豁免语义)→计划锁定→namespace 校验→wrapper。"""
    _install_core_stubs(monkeypatch)
    from rl_curriculum.curriculum261_r17_cli import main as cli_main
    rc = cli_main(["cue-audit", "--out-dir", str(tmp_path),
                   "--formal-namespace-attempt", QAF3_ATTEMPT_ID])
    assert rc == 0
    report = json.loads(
        (tmp_path / "cue_contract_audit.json").read_text("utf-8"))
    assert report["formal_audit"] is True
    assert report["audit_namespaces"] == {
        "model": FAM3.cue_contract_model,
        "validation": FAM3.cue_contract_validation}
    plan = json.loads(
        (tmp_path / "cue_audit_plan.json").read_text("utf-8"))
    assert plan["audit_namespaces"]["model"] == FAM3.cue_contract_model


def test_cli_cue_audit_rehearsal_no_plan(tmp_path, monkeypatch):
    """rehearsal 坐标不锁 plan(历史行为);rt 命名空间非正式。"""
    _install_core_stubs(monkeypatch)
    from rl_curriculum.curriculum261_r17_cli import main as cli_main
    rc = cli_main(["cue-audit", "--out-dir", str(tmp_path),
                   "--rehearsal"])
    assert rc == 0
    assert not (tmp_path / "cue_audit_plan.json").exists()
    report = json.loads(
        (tmp_path / "cue_contract_audit.json").read_text("utf-8"))
    assert report["formal_audit"] is False


def test_cli_cue_audit_locked_plan_mismatch_rc2(tmp_path, monkeypatch):
    """错计划拒绝:已锁 v2 计划 + 传 qaf_v3 尝试 → rc=2(零叶)。"""
    _install_core_stubs(monkeypatch)
    fam2 = QAF_ATTEMPTS["qaf_v2"]
    lock_cue_audit_plan_r17(
        tmp_path, model_namespace=fam2.cue_contract_model,
        validation_namespace=fam2.cue_contract_validation)
    from rl_curriculum.curriculum261_r17_cli import main as cli_main
    rc = cli_main(["cue-audit", "--out-dir", str(tmp_path),
                   "--formal-namespace-attempt", QAF3_ATTEMPT_ID])
    assert rc == 2


def test_cli_budget_gate_missing_fail_closed(tmp_path, monkeypatch,
                                             core_capture):
    """正式部署上下文缺预算门 → rc=2 零叶调用(R3 修复 B-1)。"""
    from rl_curriculum.curriculum261_r17_cli import main as cli_main
    monkeypatch.setenv("CURRICULUM261_R17_DEPLOYED_STATE_ROOT",
                       str(tmp_path))
    rc = cli_main(["cue-audit", "--out-dir", str(tmp_path),
                   "--formal-namespace-attempt", QAF3_ATTEMPT_ID])
    assert rc == 2
    assert core_capture.calls == []


def test_formal_workflow_plan_step_argv_passthrough(tmp_path,
                                                    monkeypatch):
    """CI07:正式 17 步 argv 真实经过 r17_cli 解析器与派发面。

    handler 以记录型替身截停(边界:不执行步骤科学/工程动作);
    被验:真实 argparse 接受每步正式形态 argv,attempt 身份经
    解析面抵达全部 10 个身份消费步骤。
    """
    import rl_curriculum.curriculum261_r17_cli as cli
    from rl_curriculum.curriculum261_r17_workflow import (
        build_workflow_plan_r17, r17_workflow_step_names,
    )
    monkeypatch.setenv("CURRICULUM261_R17_STATE_ROOT",
                       str(tmp_path / "state"))
    plan = build_workflow_plan_r17(
        profile="formal", out_dir=str(tmp_path),
        freeze_sha="c0fb685823eb4733bda9f5920601311228d55fde",
        formal_attempt=QAF3_ATTEMPT_ID)
    assert [s["name"] for s in plan["steps"]] == list(
        r17_workflow_step_names())
    identity_steps = {
        "determinism-matrix", "audit", "cue-audit", "preplan-smoke",
        "design-plan-lock", "design", "calibrate", "preflight-static",
        "qualify", "smoke"}
    seen = set()
    for step in plan["steps"]:
        argv = list(step["argv"])
        cmd_name = argv[0]
        fn_name = "cmd_" + cmd_name.replace("-", "_")
        recorder = {}

        def _rec(ns, _rn=cmd_name):
            recorder["ns"] = ns
            return 0

        orig = getattr(cli, fn_name, None)
        assert orig is not None, fn_name
        monkeypatch.setattr(cli, fn_name, _rec)
        try:
            rc = cli.main(argv)
        finally:
            monkeypatch.setattr(cli, fn_name, orig)
        assert rc == 0 and "ns" in recorder, cmd_name
        if cmd_name in identity_steps:
            ns = recorder["ns"]
            assert getattr(
                ns, "formal_namespace_attempt", None) == (
                QAF3_ATTEMPT_ID), cmd_name
            seen.add(cmd_name)
    assert seen == identity_steps


# ================= CI05:下游消费者 =================
def test_design_plan_payload_accepts_actual_values_report(tmp_path,
                                                          monkeypatch):
    """plan-roundtrip/design-plan-lock 的 cue_audit 消费面接受
    注册族实际值报告(digest/关键字段;真实 payload 构建)。"""
    _install_core_stubs(monkeypatch)
    lock_cue_audit_plan_r17(
        tmp_path, model_namespace=FAM3.cue_contract_model,
        validation_namespace=FAM3.cue_contract_validation)
    report = run_cue_contract_audit(
        tmp_path, require_locked_plan=True,
        model_namespace=FAM3.cue_contract_model,
        validation_namespace=FAM3.cue_contract_validation)
    from rl_curriculum.curriculum261_r17_design import (
        design_plan_digest_r17, design_plan_payload_r17,
    )
    payload = design_plan_payload_r17(
        baseline_commit="x" * 40, vendor_pin="v" * 40,
        v2_contract_digest="d" * 64, prior_r2_plan_digest="p",
        prior_diag262r2_plan_digest="q", cue_audit=report,
        preplan_smoke_identity={"sentinel_digest": "s",
                                "cue_contract_digest": "c",
                                "audit_digest": report["audit_digest"]},
        dependency_identity={"digest": "d", "n_declared": 1,
                             "pass": True},
        artifact_writer_identity={"w": True},
        preplan_rehearsal_digest="r15pr-" + "0" * 64,
        r8_abort_evidence={"e": True},
        cue_audit_plan_digest=report["cue_audit_plan_digest"],
    )
    digest = design_plan_digest_r17(payload)
    assert digest.startswith("r17dp-")
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False,
                      default=float)
    # 实际值报告的 digest/通过位进入 design 合同(真实绑定面)
    assert report["audit_digest"] in blob
    assert '"audit_pass": true' in blob
