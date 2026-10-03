"""修复轮 R2 追加验证(ChatGPT R1 复审 A.1 / C.1 / C.2)。

- A.1 状态根一致性:链侧 resolve_r17_state_root_for_chain 与
  registry.r17_state_root 同源同序;真实 execute_workflow_chain_r17
  循环(子进程/会话以显式哨兵替代,前置产物解析为真实代码)在
  启动器实际环境(DEPLOYED 根,STATE_ROOT 剥除)下消费生产者根
  上的 qualification plan——preflight-sealed 不再误报缺失;错根/
  外部重定向仍拒绝。
- C.1 悬置 started 后继门:进程无终态退出(os._exit)、封存前
  失败(completed 无 seal)阻塞后续坐标;seal 在场的合法统计
  负结果继续 collect_all_k。
- C.2 并发预占互斥:两个重叠预占请求在账本锁上串行化,恰好
  一个成功、最终账本无 lost update。
"""

from __future__ import annotations

import importlib.util
import json
import multiprocessing as mp
import os
import sys
from pathlib import Path

import pytest

from rl_curriculum.curriculum261_qprod_context import QProdContextError
from rl_curriculum.curriculum261_qprod_coordinate import (
    QPROD_COORDINATE_SEAL_NAME, mark_native_completed,
    reserve_native_execution)
from rl_curriculum.curriculum261_r17_registry import r17_state_root
from rl_curriculum.curriculum261_r17_workflow import (
    build_workflow_plan_r17, execute_workflow_chain_r17,
    resolve_r17_state_root_for_chain)

FREEZE = "a" * 40


# ── A.1 状态根解析一致性 ──────────────────────────────────────────


class TestA1StateRootResolution:
    def test_resolver_order_matches_registry(self, tmp_path,
                                              monkeypatch):
        import rl_curriculum.curriculum261_r17_registry as reg
        deployed = tmp_path / "deployed_state"
        deployed.mkdir()
        eng = tmp_path / "eng_state"
        eng.mkdir()
        chain_out = tmp_path / "chain"

        monkeypatch.setenv("CURRICULUM261_R17_DEPLOYED_STATE_ROOT",
                           str(deployed))
        monkeypatch.setattr(reg, "R17_DEPLOYED_STATE_ROOT",
                            str(deployed))
        # 启动器形态:仅 DEPLOYED——registry 与链侧必须同根
        assert r17_state_root() == deployed.resolve()
        assert resolve_r17_state_root_for_chain(
            chain_out) == deployed.resolve()

        # 工程隔离优先(与 registry 同序)
        monkeypatch.setenv("CURRICULUM261_R17_STATE_ROOT", str(eng))
        assert r17_state_root() == eng.resolve()
        assert resolve_r17_state_root_for_chain(
            chain_out) == eng.resolve()

        # 两者都无:legacy out_dir/state 兜底(registry 写入面此时
        # 拒绝,前置检查自然 fail closed)
        monkeypatch.delenv("CURRICULUM261_R17_STATE_ROOT",
                           raising=False)
        monkeypatch.delenv("CURRICULUM261_R17_DEPLOYED_STATE_ROOT",
                           raising=False)
        assert resolve_r17_state_root_for_chain(
            chain_out) == chain_out / "state"

    def _run_chain_to_preflight_sealed(self, tmp_path, monkeypatch,
                                       deployed_root, plan_written):
        """真实 execute_workflow_chain_r17 循环,步骤子进程与会话
        以显式哨兵替代(零业务);被测边界=preflight-sealed 的
        requires_artifacts 根解析(真实生产代码)。"""
        import rl_curriculum.curriculum261_r17_registry as reg
        import rl_curriculum.curriculum261_r17_workflow as wf

        out_dir = tmp_path / "chain"
        out_dir.mkdir(parents=True)
        # out_dir 侧前置(参数包);计划件=state root 侧
        (out_dir / "r17_parameter_pack.json").write_text(
            json.dumps({"format": "TEST-PACK"}), encoding="utf-8")
        if plan_written:
            deployed_root.mkdir(parents=True, exist_ok=True)
            (deployed_root / "qualification_plan_r17.json").write_text(
                json.dumps({"format": "TEST"}), encoding="utf-8")
            (deployed_root /
             "qualification_plan_digest_r17.txt").write_text(
                "TESTDIGEST\n", encoding="utf-8")

        monkeypatch.setenv("CURRICULUM261_R17_DEPLOYED_STATE_ROOT",
                           str(deployed_root))
        monkeypatch.setattr(reg, "R17_DEPLOYED_STATE_ROOT",
                            str(deployed_root))
        monkeypatch.delenv("CURRICULUM261_R17_STATE_ROOT",
                           raising=False)

        plan = build_workflow_plan_r17(
            "formal", out_dir=str(out_dir), freeze_sha=FREEZE,
            formal_attempt="qaf_v1")
        # 只保留 preflight-sealed(被测边界;其真实子进程以哨兵
        # 替代,前置产物解析为真实代码)
        plan["steps"] = [s for s in plan["steps"]
                         if s["name"] == "preflight-sealed"]
        def _stub_subproc(argv, *, cwd, env, log_path, err_path,
                          step, session, plan, profile, out_dir,
                          stop_state):
            # 哨兵:零业务;仅补齐步骤日志文件(链记录需要)
            Path(log_path).write_text("SENTINEL rc=0\n",
                                      encoding="utf-8")
            Path(err_path).write_text("", encoding="utf-8")
            return (0, None, None)

        monkeypatch.setattr(wf, "_run_step_subprocess",
                            _stub_subproc)

        class _FakeSession:
            session_hash = "TEST-SESSION"

            def record_design_data_started(self, **k):
                pass

            def record_step_started(self, name):
                pass

            def record_step_completed(self, name, rc=0):
                pass

            def record_step_failed(self, name, rc=0):
                pass

        log_dir = tmp_path / "logs"
        result = execute_workflow_chain_r17(
            plan, session=_FakeSession(), log_dir=log_dir)
        return result

    def test_producer_root_plan_consumed_by_chain(self, tmp_path,
                                                  monkeypatch):
        """启动器实际环境:计划在生产者根(注册表解析)→
        preflight-sealed 前置检查通过(哨兵子进程 rc=0 全绿)。"""
        deployed = tmp_path / "deploy" / "qprod_a_formal_v1" / \
            "artifacts" / "route_c_stage2_6_1_repair17" / "state"
        res = self._run_chain_to_preflight_sealed(
            tmp_path, monkeypatch, deployed, plan_written=True)
        assert res["ok"] is True
        assert res.get("failed_step") is None

    def test_missing_plan_on_producer_root_fails_closed(
            self, tmp_path, monkeypatch):
        """对照:生产者根无计划 → preflight-sealed rc=2 前置拒绝
        (正确根上的 fail closed,不得绕过)。"""
        deployed = tmp_path / "deploy" / "x" / "state"
        res = self._run_chain_to_preflight_sealed(
            tmp_path, monkeypatch, deployed, plan_written=False)
        assert res["ok"] is False
        assert res["failed_step"] == "preflight-sealed"
        rec = next(r for r in res["records"]
                   if r["step"] == "preflight-sealed")
        assert rec["rc"] == 2

    def test_external_state_root_redirect_refused(self, tmp_path,
                                                  monkeypatch):
        """外部重定向拒绝:STATE_ROOT 指向别处(工程隔离根)时,
        部署根上的计划不得被消费——前置检查在重定向根上找不到
        计划,fail closed。"""
        deployed = tmp_path / "deploy" / "qprod_a_formal_v1" / \
            "artifacts" / "route_c_stage2_6_1_repair17" / "state"
        deployed.mkdir(parents=True)
        (deployed / "qualification_plan_r17.json").write_text(
            json.dumps({"format": "TEST"}), encoding="utf-8")
        (deployed / "qualification_plan_digest_r17.txt").write_text(
            "TESTDIGEST\n", encoding="utf-8")
        other = tmp_path / "redirect_state"
        other.mkdir()

        out_dir = tmp_path / "chain2"
        out_dir.mkdir(parents=True)
        (out_dir / "r17_parameter_pack.json").write_text(
            json.dumps({"format": "TEST-PACK"}), encoding="utf-8")
        monkeypatch.setenv("CURRICULUM261_R17_DEPLOYED_STATE_ROOT",
                           str(deployed))
        monkeypatch.setenv("CURRICULUM261_R17_STATE_ROOT",
                           str(other))
        # registry 与链侧同根=重定向根;生产者计划在部署根,
        # 消费必须在重定向根上找不到 → 拒绝
        assert r17_state_root() == other.resolve()

        import rl_curriculum.curriculum261_r17_workflow as wf
        plan = build_workflow_plan_r17(
            "formal", out_dir=str(out_dir), freeze_sha=FREEZE,
            formal_attempt="qaf_v1")
        plan["steps"] = [s for s in plan["steps"]
                         if s["name"] == "preflight-sealed"]
        monkeypatch.setattr(
            wf, "_run_step_subprocess",
            lambda *a, **k: (0, None, None))

        class _FakeSession:
            session_hash = "TEST-SESSION"

            def record_design_data_started(self, **k):
                pass

            def record_step_started(self, name):
                pass

            def record_step_completed(self, name, rc=0):
                pass

            def record_step_failed(self, name, rc=0):
                pass

        res = execute_workflow_chain_r17(
            plan, session=_FakeSession(),
            log_dir=tmp_path / "logs2")
        assert res["ok"] is False
        assert res["failed_step"] == "preflight-sealed"


# ── C.1 悬置 started 后继门 / C.2 并发互斥 ────────────────────────


def _manifest(n=2):
    return [{"coordinate_id": f"c0{i}",
             "artifact_subdir": f"coord_c0{i}"} for i in range(1,
                                                               n + 1)]


def _init_budget(path: Path, mx: int):
    path.write_text(json.dumps(
        {"max_runs": mx, "consumed_runs": 0, "started": {}}),
        encoding="utf-8")


class TestC1DanglingStartedGate:
    def test_hard_exit_dangling_blocks_next(self, tmp_path):
        """进程无终态退出(os._exit)后:started 无 seal → 后续
        坐标启动拒绝(剩余额度无关)。"""
        state = tmp_path / "state"
        state.mkdir()
        art = tmp_path / "artifacts"
        budget = state / "qprod_native_budget.json"
        _init_budget(budget, mx=11)
        man = _manifest()
        # 模拟 c01 已预占后进程 os._exit(23)(无 interrupted/seal)
        reserve_native_execution(budget, coordinate_id="c01")
        with pytest.raises(QProdContextError) as ei:
            reserve_native_execution(
                budget, coordinate_id="c02",
                artifact_root=art, coordinate_manifest=man)
        assert "无有效 seal" in str(ei.value)
        doc = json.loads(budget.read_text(encoding="utf-8"))
        assert set(doc["started"]) == {"c01"}  # 不清空/不补抽

    def test_completed_without_seal_still_blocks(self, tmp_path):
        """返回后/封存前失败:completed 已记但 seal 未写 → 技术未
        终态,后续拒绝。"""
        state = tmp_path / "state"
        state.mkdir()
        budget = state / "qprod_native_budget.json"
        _init_budget(budget, mx=11)
        reserve_native_execution(budget, coordinate_id="c01")
        mark_native_completed(budget, coordinate_id="c01")
        with pytest.raises(QProdContextError) as ei:
            reserve_native_execution(
                budget, coordinate_id="c02",
                artifact_root=tmp_path / "artifacts",
                coordinate_manifest=_manifest())
        assert "无有效 seal" in str(ei.value)

    def test_sealed_coordinate_allows_next_collect_all_k(self,
                                                          tmp_path):
        """合法终态(seal 在场;含统计负结果)→ collect_all_k
        继续收下一坐标。"""
        state = tmp_path / "state"
        state.mkdir()
        art = tmp_path / "artifacts"
        budget = state / "qprod_native_budget.json"
        _init_budget(budget, mx=11)
        man = _manifest()
        reserve_native_execution(budget, coordinate_id="c01")
        mark_native_completed(budget, coordinate_id="c01")
        d = art / "coord_c01"
        d.mkdir(parents=True)
        (d / QPROD_COORDINATE_SEAL_NAME).write_text(
            json.dumps({
                "format": "cur261-qprod-coordinate-seal-v1",
                "coordinate_id": "c01",
                "research_plan_digest": "qbpl-" + "0" * 64,
                "coordinate_audit_plan_digest": "qcap-" + "b" * 64,
                "audit_digest": "sha256-" + "c" * 64,
                "members_sha256": {"cue_contract_audit.json":
                                   "d" * 64},
                "summary": {"audit_pass": False},
            }), encoding="utf-8")
        out = reserve_native_execution(
            budget, coordinate_id="c02",
            artifact_root=art, coordinate_manifest=man)
        assert out["started"] == ["c01", "c02"]

    def test_manifest_foreign_started_blocks(self, tmp_path):
        """清单外 started 条目(无坐标目录)按悬置拒绝。"""
        state = tmp_path / "state"
        state.mkdir()
        budget = state / "qprod_native_budget.json"
        _init_budget(budget, mx=11)
        reserve_native_execution(budget, coordinate_id="zz")
        with pytest.raises(QProdContextError) as ei:
            reserve_native_execution(
                budget, coordinate_id="c01",
                artifact_root=tmp_path / "artifacts",
                coordinate_manifest=_manifest())
        assert "不在清单" in str(ei.value)

    def test_entry_os_exit_then_next_rc96(self, tmp_path,
                                          monkeypatch):
        """入口级复现(ChatGPT C.1 探针形态):真实 cmd_run_coordinate
        经哨兵替身到达业务边界后 os._exit(23);确认子进程退出后,
        下一坐标 c02 在入口被拒(rc=96,零叶调用)。"""
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from tests.route_c_stage2_6_1 import (
            test_curriculum261_qprod_formal_launch as _launch_helpers,
        )
        _b_namespaces = _launch_helpers._b_namespaces
        _write_formal_permit = _launch_helpers._write_formal_permit
        _approval_payload = _launch_helpers._approval_payload
        from rl_curriculum.curriculum261_qprod_context import harden_root
        from rl_curriculum.curriculum261_qprod_permit import (
            consume_permit)
        from rl_curriculum.curriculum261_qprod_plan import (
            freeze_research_plan, research_plan_digest)
        from rl_curriculum.curriculum261_qprod_formal import (
            QPROD_FORMAL_LEVEL_B_ITERATION_ID, build_formal_context,
            build_formal_level_b_plan)
        from rl_curriculum.curriculum261_qprod_coordinate import (
            qprod_coordinate_code_identity)

        for var in ("CURRICULUM261_QPROD_ART_ROOT",
                    "CURRICULUM261_QPROD_STATE_ROOT"):
            monkeypatch.delenv(var, raising=False)
        deploy, art, state, authority = \
            _launch_helpers._make_deploy(tmp_path, level="level_b")
        payload = build_formal_level_b_plan(
            code_freeze_sha=FREEZE,
            code_identity=qprod_coordinate_code_identity())
        digest = research_plan_digest(payload)
        approval = _approval_payload(
            level="level_b", digest=digest, art=art, state=state,
            authority=authority, namespaces=_b_namespaces(),
            coordinate_ids=[c["coordinate_id"] for c in
                            payload["coordinate_manifest"]],
            quota=payload["quota"], sha=FREEZE)
        (authority / f"qprod_formal_approval_level_b_"
         f"{QPROD_FORMAL_LEVEL_B_ITERATION_ID}.json").write_text(
            json.dumps(approval, ensure_ascii=False),
            encoding="utf-8")
        ctx = build_formal_context(
            deploy, level="level_b",
            iteration_id=QPROD_FORMAL_LEVEL_B_ITERATION_ID,
            code_freeze_sha=FREEZE, research_plan_digest=digest,
            approval_digest=approval["approval_digest"])
        _write_formal_permit(authority, ctx, approval)
        harden_root(state, label="state_root", create=True)
        harden_root(art, label="artifact_root", create=True)
        freeze_research_plan(state, payload)
        consume_permit(ctx.permit_path, context=ctx)
        budget = state / "qprod_native_budget.json"
        _init_budget(budget, mx=11)

        base = Path(__file__).resolve().parents[2]
        for cand in (base / "stage2_6_1_runner", base / "runner",
                     base / "stage2_6_1" / "runner"):
            if (cand / "qprod_formal_level_b_entry.py").is_file():
                runner = cand / "qprod_formal_level_b_entry.py"
                break
        else:
            raise FileNotFoundError("runner 入口未找到")

        child_src = f'''
import importlib.util, json, os, sys
spec = importlib.util.spec_from_file_location(
    "b_entry_child", r"{runner}")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

def stub_core(ctx, live, cid, coord_dir=None, ledger_path=None):
    # 到达业务替身边界:写到达证据后硬退出(无 interrupted/seal)
    from pathlib import Path as P
    d = P(coord_dir); d.mkdir(parents=True, exist_ok=True)
    (d / "reached.json").write_text("boundary", encoding="utf-8")
    os._exit(23)

mod.run_coordinate_audit_locked = stub_core
class A:
    deploy_root = r"{deploy}"
    code_freeze_sha = "{FREEZE}"
    coordinate_id = "c01"
rc = mod.cmd_run_coordinate(A())
print("UNEXPECTED-RETURN", rc)
'''
        child = tmp_path / "child_exit.py"
        child.write_text(child_src, encoding="utf-8")
        import subprocess
        proc = subprocess.run(
            [sys.executable, str(child)],
            capture_output=True, text=True, timeout=120)
        assert proc.returncode == 23  # 硬退出复现(非正常返回)
        assert (art / "coord_c01" / "reached.json").is_file()
        doc = json.loads(budget.read_text(encoding="utf-8"))
        assert "c01" in doc["started"]
        assert not (art / "coord_c01" /
                    QPROD_COORDINATE_SEAL_NAME).is_file()

        spec = importlib.util.spec_from_file_location(
            "b_entry_parent", runner)
        pmod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(pmod)

        def refuse_core(*a, **k):  # 不应被调用
            raise AssertionError("business leaf reached")

        monkeypatch.setattr(pmod, "run_coordinate_audit_locked",
                            refuse_core)
        args = type("A", (), {
            "deploy_root": str(deploy),
            "code_freeze_sha": FREEZE,
            "coordinate_id": "c02"})()
        rc = pmod.cmd_run_coordinate(args)
        assert rc == 96  # 悬置 c01 阻塞后继(零叶调用)
        doc2 = json.loads(budget.read_text(encoding="utf-8"))
        assert set(doc2["started"]) == {"c01"}


def _concurrent_reserve_worker(budget_str, cid, out_q):
    try:
        r = reserve_native_execution(Path(budget_str),
                                     coordinate_id=cid)
        out_q.put(("ok", cid, r))
    except Exception as exc:  # noqa: BLE001
        out_q.put(("refused", cid, str(exc)))


class TestC2ConcurrentReserve:
    def test_two_overlapping_reserves_single_winner(self, tmp_path):
        """max_runs=1,两个重叠预占请求:恰好一个成功,另一个零业务
        进入;最终账本无 lost update(仅一个 started)。"""
        budget = tmp_path / "qprod_native_budget.json"
        _init_budget(budget, mx=1)
        ctx = mp.get_context("fork")
        q = ctx.Queue()
        procs = [ctx.Process(
            target=_concurrent_reserve_worker,
            args=(str(budget), cid, q)) for cid in ("c01", "c02")]
        for p in procs:
            p.start()
        for p in procs:
            p.join(timeout=60)
        assert all(p.exitcode == 0 for p in procs)
        results = [q.get_nowait() for _ in range(2)]
        winners = [r for r in results if r[0] == "ok"]
        refusals = [r for r in results if r[0] == "refused"]
        assert len(winners) == 1
        assert len(refusals) == 1
        doc = json.loads(budget.read_text(encoding="utf-8"))
        assert len(doc["started"]) == 1  # 无 lost update
        assert list(doc["started"])[0] == winners[0][1]
        # 拒绝者拿到的必须是最新账本语义(耗尽/同坐标),而非
        # 基于过期读的成功
        assert ("耗尽" in refusals[0][2]
                or "已有 started" in refusals[0][2])
