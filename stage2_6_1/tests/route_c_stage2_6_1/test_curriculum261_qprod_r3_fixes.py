# QProd 返修轮3(R3)钉测试:ChatGPT 第三次 NOT_CLOSED 四点。
# Q1 公共业务数值/必需检查集合/17步权威序列;Q2 异常不丢账+
# 许可vs需求动作前拦截;Q3 有效统计负结果保留+范围贯通;
# R01 E01 归档实执行(不 skip)。零原生/零 fit/零 optimizer。
from __future__ import annotations

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
from rl_curriculum.curriculum261_qprod_coordinate import (
    _GenerationLedger, qprod_required_cue_check_names,
)
from rl_curriculum.curriculum261_qprod_levela import (
    judge_qualification_gates, run_level_a_rehearsal,
)
from rl_curriculum.curriculum261_qprod_plan import load_research_plan
from rl_curriculum.curriculum261_r17_cue_contract import (
    cue_contract_audit_digest,
)
from rl_curriculum.ppo262_qprod_export import (
    QProdExportError, export_qualification_delivery,
)

import test_ppo262_qprod_export as te


def _rehearse(tmp_path):
    ctx = tl._ctx(tmp_path)
    session = QProdRunSession(ctx.state_root, level="level_a",
                              iteration_id=ctx.iteration_id)
    session.acquire({"entry": "t"})
    run_level_a_rehearsal(ctx, session, tl._fixture_inputs(tmp_path))
    return ctx


# ---------------------------------------------------------------- Q1
def test_r3q1_authority_check_names_single_source():
    """权威检查集合单一事实源对拍(8 键)。"""
    names = qprod_required_cue_check_names()
    assert len(names) == 8
    assert "mc_close_to_analytic" in names
    assert "global_k_audit_not_indeterminate" in names


def test_r3q1_mc_numbers_fail_but_checks_true_rejected(tmp_path):
    """MC 数值实际失败(|p_hat-p_contract|>tolerance)但 checks
    全 True+顶层 PASS+digest 重算自洽 → gate1 数值重算拒。"""
    ctx = _rehearse(tmp_path)
    cue_p = ctx.artifact_root / "cue_contract_audit.json"
    cue = json.loads(cue_p.read_text(encoding="utf-8"))
    # 数值破坏:MC p_hat 偏离 p_contract 超容差(数据失败)
    cue["monte_carlo"]["p_hat"] = (
        float(cue["p_contract"]) + 0.05)
    # checks/顶层保持"成功"伪装,SHA(digest)重算自洽
    cue["checks"]["mc_close_to_analytic"] = True
    cue["pass"] = True
    cue["audit_digest"] = cue_contract_audit_digest(cue)
    cue_p.write_text(json.dumps(cue), encoding="utf-8")
    plan = json.loads((ctx.state_root / "qprod_qualification_plan.json"
                       ).read_text(encoding="utf-8"))
    raw = judge_qualification_gates(ctx.artifact_root, plan)
    g = raw["gates"]["cue_audit_pass"]
    assert raw["verdict"] == "FAIL"
    assert g["pass"] is False
    assert g["observed"]["frozen_semantics_recomputed"][
        "mc_close_to_analytic"] is False
    assert g["observed"]["semantics_consistent"] is False


def test_r3q1_corpus_numbers_fail_but_checks_true_rejected(tmp_path):
    """validation 语料 emp-analytic 偏离超 max(3SE,0.005) 但
    checks True → 数值重算拒。"""
    ctx = _rehearse(tmp_path)
    cue_p = ctx.artifact_root / "cue_contract_audit.json"
    cue = json.loads(cue_p.read_text(encoding="utf-8"))
    v = cue["direct_generator"]["validation"]
    v["empirical_recall"] = float(v["analytic_conditional"]) + 0.2
    cue["checks"]["validation_corpus_ok"] = True
    cue["pass"] = True
    cue["audit_digest"] = cue_contract_audit_digest(cue)
    cue_p.write_text(json.dumps(cue), encoding="utf-8")
    plan = json.loads((ctx.state_root / "qprod_qualification_plan.json"
                       ).read_text(encoding="utf-8"))
    raw = judge_qualification_gates(ctx.artifact_root, plan)
    assert raw["verdict"] == "FAIL"
    assert raw["gates"]["cue_audit_pass"]["observed"][
        "semantics_consistent"] is False


def test_r3q1_required_check_removed_rejected(tmp_path):
    """删减必需 check(键集合 != 权威 8)→ 拒(即使剩余全 True)。"""
    ctx = _rehearse(tmp_path)
    cue_p = ctx.artifact_root / "cue_contract_audit.json"
    cue = json.loads(cue_p.read_text(encoding="utf-8"))
    cue["checks"].pop("global_k_audit_not_indeterminate")
    cue["pass"] = True
    cue["audit_digest"] = cue_contract_audit_digest(cue)
    cue_p.write_text(json.dumps(cue), encoding="utf-8")
    plan = json.loads((ctx.state_root / "qprod_qualification_plan.json"
                       ).read_text(encoding="utf-8"))
    raw = judge_qualification_gates(ctx.artifact_root, plan)
    assert raw["verdict"] == "FAIL"
    obs = raw["gates"]["cue_audit_pass"]["observed"]
    assert obs["checks_set_matches_authority"] is False


def _exportable(tmp_path):
    ctx, _ = te._producer(tmp_path)
    return ctx


def test_r3q1_duplicated_same_step_17_times_rejected(tmp_path):
    """17 步账本复制同一步 17 次(全 ok=True)→ 权威序列核验拒。"""
    ctx = _exportable(tmp_path)
    led_p = ctx.artifact_root / "level_a_step_ledger.json"
    led = json.loads(led_p.read_text(encoding="utf-8"))
    template = led["steps"][0]
    led["steps"] = [dict(template, step="provenance-verify")
                    for _ in range(17)]
    led_p.write_text(json.dumps(led), encoding="utf-8")
    with pytest.raises(QProdExportError):
        export_qualification_delivery(
            ctx.artifact_root, ctx.state_root, tmp_path / "d",
            expected_scope="engineering")


def test_r3q1_step_order_swap_rejected(tmp_path):
    """步骤换序(依赖破坏)→ 拒。"""
    ctx = _exportable(tmp_path)
    led_p = ctx.artifact_root / "level_a_step_ledger.json"
    led = json.loads(led_p.read_text(encoding="utf-8"))
    steps = led["steps"]
    steps[3], steps[4] = steps[4], steps[3]
    led_p.write_text(json.dumps(led), encoding="utf-8")
    with pytest.raises(QProdExportError):
        export_qualification_delivery(
            ctx.artifact_root, ctx.state_root, tmp_path / "d",
            expected_scope="engineering")


# ---------------------------------------------------------------- Q2
class _FakeEp:
    def __init__(self):
        import pandas as pd

        self.df = pd.DataFrame({"x": [1.0]})
        self.hidden = pd.DataFrame({"y": [1.0]})


def _fake_once(ladder, seed, ns):
    return {r: {"A": _FakeEp(), "B": _FakeEp()}
            for r in ("D0", "D1", "D2", "D3")}


class _Block3:
    """3 attempt 成功 block(attempts_made=3 → 24 动作)。"""
    block_index = 0

    class _Log:
        selected_attempt = 2
        attempts = [0, 1, 2]
        seed_namespace = "calibration_r3"
        block_index = 0

    attempt_log = _Log()
    episodes = {}


class _BlockExploding:
    """抛一般异常的 attempts block(内部已发生 attempt 数未知)。"""
    block_index = 0

    def __init__(self):
        raise RuntimeError("simulated mid-attempt crash")


def _patched_ledger(monkeypatch_module, once=_fake_once,
                    attempts=None, explode=None):
    ledger = _GenerationLedger(quota_max_episode_leaf_calls=640,
                               coordinate_id="cx")
    monkeypatch_module.generate_matched_block_once = once
    monkeypatch_module.generate_matched_block_with_attempts = (
        attempts or (lambda *a, **k: _Block3()))
    if explode is not None:
        monkeypatch_module.generate_matched_block_with_attempts = explode
    return ledger


def test_r3q2_exception_keeps_uncertain_upper_not_zero(tmp_path):
    """一般异常:不确定预占不退 0(保守上界保留),异常向上传播。"""
    import rl_curriculum.curriculum261_r6_tape as r6

    ledger = _GenerationLedger(quota_max_episode_leaf_calls=640,
                               coordinate_id="cx")
    orig_att = r6.generate_matched_block_with_attempts
    orig_once = r6.generate_matched_block_once
    r6.generate_matched_block_once = _fake_once
    r6.generate_matched_block_with_attempts = (
        lambda *a, **k: _BlockExploding())
    try:
        h = ledger.bind()
        with pytest.raises(RuntimeError):
            h["generate_attempts"]({}, namespace="calibration_r3",
                                   block_index=0)
        # 未结算预占保留(不退 0):C2_BLOCK_MAX_ATTEMPTS(5)x8=40
        assert ledger.episode_leaf_calls >= 40
        assert ledger._inflight_upper == 40
        assert ledger.uncertain_blocks == 1
        assert ledger._episode_actions == 0  # 无可结算精确数
    finally:
        r6.generate_matched_block_with_attempts = orig_att
        r6.generate_matched_block_once = orig_once


def test_r3q2_settled_then_exception_cumulative_no_escape(tmp_path):
    """24 个动作成功结算后再异常:精确 24 入账 + 异常上界 40
    保留;后续累计包含两者(不逃账)。"""
    import rl_curriculum.curriculum261_r6_tape as r6

    ledger = _GenerationLedger(quota_max_episode_leaf_calls=640,
                               coordinate_id="cx")
    orig_att = r6.generate_matched_block_with_attempts
    orig_once = r6.generate_matched_block_once
    r6.generate_matched_block_once = _fake_once
    calls = {"n": 0}

    def attempts3(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            return _Block3()
        raise RuntimeError("simulated later crash")

    r6.generate_matched_block_with_attempts = attempts3
    try:
        h = ledger.bind()
        h["generate_attempts"]({}, namespace="calibration_r3",
                               block_index=0)
        assert ledger._episode_actions == 24  # 3 attempt x 8
        assert ledger._inflight_upper == 0
        with pytest.raises(RuntimeError):
            h["generate_attempts"]({}, namespace="calibration_r3",
                                   block_index=1)
        # 累计 = 已结算 24 + 不确定上界 40(不退 0,不逃账)
        assert ledger.episode_leaf_calls == 64
        t = ledger.totals()
        assert t["episode_leaf_actions_settled"] == 24
        assert t["episode_leaf_actions_uncertain_upper"] == 40
        assert t["uncertain_blocks"] == 1
    finally:
        r6.generate_matched_block_with_attempts = orig_att
        r6.generate_matched_block_once = orig_once


def test_r3q2_interrupt_preserves_reservation(tmp_path):
    """中断(KeyboardInterrupt)同样保留不确定预占。"""
    import rl_curriculum.curriculum261_r6_tape as r6

    ledger = _GenerationLedger(quota_max_episode_leaf_calls=640,
                               coordinate_id="cx")
    orig_att = r6.generate_matched_block_with_attempts
    orig_once = r6.generate_matched_block_once

    def interrupted(*a, **k):
        raise KeyboardInterrupt

    r6.generate_matched_block_once = _fake_once
    r6.generate_matched_block_with_attempts = interrupted
    try:
        h = ledger.bind()
        with pytest.raises(KeyboardInterrupt):
            h["generate_attempts"]({}, namespace="calibration_r3",
                                   block_index=0)
        assert ledger.episode_leaf_calls >= 40
        assert ledger.uncertain_blocks == 1
    finally:
        r6.generate_matched_block_with_attempts = orig_att
        r6.generate_matched_block_once = orig_once


def _run_with_permit_quota(tmp_path, quota):
    import test_curriculum261_qprod_coordinate as tc

    ctx, payload = tc._setup(tmp_path)
    d = tmp_path / "base" / "qprod_level_b_i1" / "artifacts" / "coord_c01"
    d.mkdir(parents=True, exist_ok=True)
    tc.lock_coordinate_audit_plan(
        d, coordinate=dict(tc.C01), research_plan=payload)
    permit = tc._FakePermit(quota=quota)
    return tc, ctx, permit, d, payload


def test_r3q2_permit_positive_but_insufficient_mc_rejected(tmp_path):
    """许可为正(mc=1)但需求 4096 → run 动作前拒绝(零叶调用)。"""
    from rl_curriculum.curriculum261_qprod_context import (
        QProdContextError,
    )

    quota = {"max_leaf_calls_per_coordinate": 640,
             "max_successful_episodes_total": 128,
             "mc_events_per_coordinate": 1,
             "max_native_executions": 2}
    tc, ctx, permit, d, payload = _run_with_permit_quota(tmp_path, quota)
    with pytest.raises(QProdContextError, match="动作前拒绝"):
        tc.run_coordinate_audit_locked(
            ctx, permit, "c01", coord_dir=d,
            ledger_path=tmp_path / "l.jsonl")
    ref = json.loads(sorted(
        (tmp_path / "base" / "qprod_level_b_i1" / "artifacts"
         ).glob("refusal_c01.json"))[-1].read_text(encoding="utf-8"))
    assert ref["leaf_calls_snapshot"]["leaf_calls_total"] == 0


def test_r3q2_permit_positive_but_insufficient_episodes_rejected(
        tmp_path):
    """许可为正(正文=1)但需求 32 → run 动作前拒绝。"""
    from rl_curriculum.curriculum261_qprod_context import (
        QProdContextError,
    )

    quota = {"max_leaf_calls_per_coordinate": 640,
             "max_successful_episodes_total": 1,
             "mc_events_per_coordinate": 4096,
             "max_native_executions": 2}
    tc, ctx, permit, d, payload = _run_with_permit_quota(tmp_path, quota)
    with pytest.raises(QProdContextError, match="动作前拒绝"):
        tc.run_coordinate_audit_locked(
            ctx, permit, "c01", coord_dir=d,
            ledger_path=tmp_path / "l.jsonl")


# ---------------------------------------------------------------- Q3
def _coords_art(tmp_path, *, n_valid=11, audit_fail_ids=(),
                stop_mode="collect_all_k", se_zero_ids=()):
    art, state, digest = ta._setup_plan(
        tmp_path, stop_mode=stop_mode)
    plan = load_research_plan(state)
    for i, coord in enumerate(plan["coordinate_manifest"]):
        if i >= n_valid:
            break
        kw = {"seed_tag": i}
        if i in se_zero_ids:
            # SE 退化构造:所有事件全命中 → 每 block recall=1.0,
            # block 间零方差 → bootstrap se=0(数值真实退化,非伪造)
            kw = {"events_override": ta._events_for(
                2, hits_per_block=55, n_events=55, seed_tag=i)}
        ta._build_coordinate(art, coord["artifact_subdir"],
                             plan_digest=digest, **kw)
        if i in audit_fail_ids:
            seal_p = art / coord["artifact_subdir"] / \
                "qprod_coordinate_seal.json"
            seal = json.loads(seal_p.read_text(encoding="utf-8"))
            seal["summary"]["audit_pass"] = False
            seal_p.write_text(json.dumps(seal), encoding="utf-8")
    return art, state, plan


def test_r3q3_valid_negative_result_retained_in_collect_all(tmp_path):
    """统计 gate FAIL(结构合法)在 collect-all 保留进主分析。"""
    art, state, plan = _coords_art(
        tmp_path, n_valid=11, audit_fail_ids=(0, 3))
    agg = aggregate_research(art, state_root=state)
    assert agg["valid_coordinate_count"] == 11
    failed_ids = agg["stats_gate_failed_coordinate_ids"]
    assert set(failed_ids) == {"c01", "c04"}
    c0 = agg["coordinates"][0]
    assert c0.get("negative_result_valid") is True
    assert "audit_fail_excluded" not in c0


def test_r3q3_k_insufficient_honestly_inconclusive(tmp_path):
    """K 不足(2<11):保留两坐标数值,primary 如实 inconclusive
    (不删样凑绿)。"""
    art, state, plan = _coords_art(tmp_path, n_valid=2)
    agg = aggregate_research(art, state_root=state)
    assert agg["valid_coordinate_count"] == 2
    assert agg["primary"]["magnitude"] == "inconclusive"
    note = json.dumps(agg["primary"], ensure_ascii=False)
    assert "K" in note or "planned" in note or "不足" in note


def test_r3q3_se_degraded_honestly_inconclusive(tmp_path):
    """SE 退化(=0):如实不决,不产出伪精确估计。"""
    art, state, plan = _coords_art(tmp_path, n_valid=11,
                                   se_zero_ids=(2, 5))
    agg = aggregate_research(art, state_root=state)
    assert agg["primary"]["magnitude"] == "inconclusive"


def test_r3q3_full_synthetic_k_produces_estimate(tmp_path):
    """完整合成 K=11(结构+数值合法正例)→ 正常主分析输出。"""
    art, state, plan = _coords_art(tmp_path, n_valid=11)
    agg = aggregate_research(art, state_root=state)
    assert agg["valid_coordinate_count"] == 11
    assert agg["primary"]["magnitude"] not in (
        "inconclusive", "halted_technically_corrupt")


def test_r3q3_early_stop_uses_pristine_definition(tmp_path):
    """early-stop:事前定义(delta>margin);audit_fail 坐标照常
    参与统计触发(结构合法的有效负结果不因 gate FAIL 被排除,
    也不冒充技术损坏)。"""
    # 构造 c01 recall 低且有 block 间方差(se>0,v4 适用条件),
    # delta=0.9504-recall > margin 触发(不用全 miss——se=0 属退化
    # 不判负,是既有正确语义,由 se 退化用例单独覆盖)
    art, state, plan = _coords_art(
        tmp_path, n_valid=11, stop_mode="early_stop_on_first_negative",
        audit_fail_ids=(0,))
    cd = art / "c01" / "cue_event_trace.jsonl"
    events = [json.loads(x) for x in
              cd.read_text(encoding="utf-8").splitlines() if x.strip()]
    # block0 命中 3,block1 命中 7(双语料同改保持对账一致)
    for e in events:
        e["detected"] = (
            e["block_index"] == 0 and e["cue_bar"] % 18 < 3) or (
            e["block_index"] == 1 and e["cue_bar"] % 18 < 7)
    cd.write_text("\n".join(json.dumps(e, sort_keys=True)
                            for e in events) + "\n", encoding="utf-8")
    # 重算 recall 一致性:报告与 seal 同步(结构合法)
    from rl_curriculum.curriculum261_r17_cue_contract import (
        _cluster_bootstrap, _per_block_event_counts,
        cue_contract_audit_digest as _digest,
    )
    from rl_curriculum.curriculum261_qprod_coordinate import (
        _per_block_event_digests as _pbd,
    )
    import hashlib
    boot = _cluster_bootstrap(_per_block_event_counts(
        [e for e in events if e["corpus"] == "validation"]))
    mboot = _cluster_bootstrap(_per_block_event_counts(
        [e for e in events if e["corpus"] == "model"]))
    rp = art / "c01" / "cue_contract_audit.json"
    rep = json.loads(rp.read_text(encoding="utf-8"))
    rep["direct_generator"]["validation"]["empirical_recall"] = (
        boot["point"])
    rep["direct_generator"]["validation"]["block_cluster"][
        "point"] = boot["point"]
    rep["direct_generator"]["validation"]["block_cluster"][
        "se"] = boot["se"]
    rep["direct_generator"]["model"]["empirical_recall"] = (
        mboot["point"])
    rep["audit_digest"] = _digest(rep)
    rp.write_text(json.dumps(rep), encoding="utf-8")
    seal_p = art / "c01" / "qprod_coordinate_seal.json"
    seal = json.loads(seal_p.read_text(encoding="utf-8"))
    seal["summary"]["recall_validation"] = boot["point"]
    seal["summary"]["se_validation"] = boot["se"]
    seal["audit_digest"] = rep["audit_digest"]
    for name in seal["members_sha256"]:
        f = art / "c01" / name
        if f.is_file():
            seal["members_sha256"][name] = hashlib.sha256(
                f.read_bytes()).hexdigest()
    seal["per_block_event_digests"] = _pbd(cd)
    seal_p.write_text(json.dumps(seal), encoding="utf-8")

    agg = aggregate_research(art, state_root=state)
    c0 = agg["coordinates"][0]
    # audit_fail 坐标结构合法 → 参与早停统计判定
    assert c0["state"] == "valid"
    assert c0.get("audit_fail") is True
    assert agg["early_stopped_at"] == "c01"
    for c in agg["coordinates"][1:]:
        if c["state"] == "valid" and c.get("post_stop_unlaunched"):
            pass  # 启动边界由 coordinate run 层另测


def test_r3q3_manifest_qcap_range_linkage(tmp_path):
    """清单↔qcap↔报告↔两语料范围矛盾(qcap count≠报告)→ 拒。"""
    art, state, digest = ta._setup_plan(tmp_path)
    plan = load_research_plan(state)
    coord = plan["coordinate_manifest"][0]
    cd = art / coord["artifact_subdir"]
    ta._build_coordinate(art, coord["artifact_subdir"],
                         plan_digest=digest)
    from rl_curriculum.curriculum261_qprod_coordinate import (
        coordinate_audit_plan_digest,
    )
    qcap_p = cd / "qprod_coordinate_audit_plan.json"
    qcap = json.loads(qcap_p.read_text(encoding="utf-8"))
    qcap["block_range"] = {"start_index": 0, "count": 7}
    qcap.pop("coordinate_audit_plan_digest", None)
    qcap["coordinate_audit_plan_digest"] = (
        coordinate_audit_plan_digest(qcap))
    qcap_p.write_text(json.dumps(qcap), encoding="utf-8")
    (cd / "qprod_coordinate_audit_plan_digest.txt").write_text(
        qcap["coordinate_audit_plan_digest"], encoding="utf-8")
    seal_p = cd / "qprod_coordinate_seal.json"
    seal = json.loads(seal_p.read_text(encoding="utf-8"))
    seal["coordinate_audit_plan_digest"] = qcap[
        "coordinate_audit_plan_digest"]
    seal_p.write_text(json.dumps(seal), encoding="utf-8")
    v = _verify_coordinate(cd, coord, plan)
    assert v["state"] != "valid"
    assert any("block_range.count" in p or "范围" in p
               for p in v["problems"])
