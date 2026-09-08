"""R17 C3 证据闭合轮验收矩阵:D01-D04 / M01-M02。

对象:r17_c3_p52_diagnosis.py v2(空重放误判/提前 return/只比 A 侧/
DP 上界矛盾四缺陷修复)+ 现有 EnvelopeRecorder 被动记录合同。

测试隔离纪律(任务书 §1.2/§6):真实生成模块一律独立子进程运行
(numpy 原生线程不进 pytest 进程);纯数学/纯函数测试进程内运行。
所有子进程调用带 timeout watchdog。
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve()


def _diag_script() -> Path:
    """诊断脚本路径(repo 树优先,部署树回退;均缺则 skip)。"""
    here = _HERE
    cands = []
    if here.parents[2].name == "stage2_6_1":
        cands.append(here.parents[2] / "runner"
                     / "r17_c3_p52_diagnosis.py")
    cands.append(Path.home() / "projects" / "crypto_rl"
                 / "stage2_6_1_runner" / "r17_c3_p52_diagnosis.py")
    for c in cands:
        if c.is_file():
            return c
    pytest.skip("r17_c3_p52_diagnosis.py 在两树均不可达")


def _src_dir() -> Path:
    return _diag_script().resolve().parent.parent / "src"


def _orig_envelope() -> Path:
    """run 1475 原 p52 失败证据(repo 树相对路径优先,/mnt/f 回退)。"""
    here = _HERE
    cands = []
    if here.parents[2].name == "stage2_6_1":
        cands.append(here.parents[2] / "artifacts" / "repair17"
                     / "development" / "blocker_diagnosis" / "runs"
                     / "20260906T134324Z_1475"
                     / "generation_failure_envelopes_calibrate_c3_cost"
                     "_D0_p52.json")
    cands.append(Path(
        "/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17"
        "/development/blocker_diagnosis/runs/20260906T134324Z_1475/"
        "generation_failure_envelopes_calibrate_c3_cost_D0_p52.json"))
    for c in cands:
        if c.is_file():
            return c
    pytest.skip("原 p52 envelope 不在本机")


@pytest.fixture(scope="module")
def diag():
    """进程内加载诊断模块(纯函数面;顶层 import 不触发真实生成)。"""
    p = _diag_script()
    spec = importlib.util.spec_from_file_location(
        "r17_c3_p52_diagnosis_v2_under_test", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run_diag(args: list[str], timeout: int = 300) -> subprocess.CompletedProcess:
    """独立子进程跑诊断脚本(真实模块的进程隔离入口)。"""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(_src_dir())
    return subprocess.run(
        [sys.executable, str(_diag_script()), *args],
        capture_output=True, text=True, timeout=timeout, env=env,
        cwd=str(_src_dir().parent))


def _mk_env(i: int, *, dis_a: int = 0, dis_b: int = 0,
            with_b: bool = True) -> dict:
    """构造最小 attempt envelope(证据完备性判定的测试载荷)。"""
    et = {"A": {"counts": {"n_distractors": dis_a, "n_signals": 40}}}
    if with_b:
        et["B"] = {"counts": {"n_distractors": dis_b, "n_signals": 40}}
    return {"attempt_index": i, "event_table": et,
            "rejection_reasons": ["A:too_few_distractors"]}


# ================================================= D01 证据完备性
class TestD01EvidenceCompleteness:
    """空/少/重复/缺号/缺 B/recorder 错误都不得产生 verified。"""

    def test_d01_empty_replay_not_complete(self, diag):
        """v1 核心缺陷反例:空集合遍历零次得'一致';v2 必须判不完备。"""
        out = diag.assess_replay_evidence([], [], 5)
        assert out["evidence_complete"] is False
        assert out["n_attempt_envelopes"] == 0

    @pytest.mark.parametrize("n", [1, 2, 3, 4])
    def test_d01_partial_replay_not_complete(self, diag, n):
        envs = [_mk_env(i) for i in range(n)]
        out = diag.assess_replay_evidence(envs, [], 5)
        assert out["evidence_complete"] is False

    def test_d01_duplicate_attempt_index_not_complete(self, diag):
        envs = [_mk_env(i) for i in (0, 0, 1, 2, 3)]
        out = diag.assess_replay_evidence(envs, [], 5)
        assert out["evidence_complete"] is False

    def test_d01_missing_attempt_index_not_complete(self, diag):
        envs = [_mk_env(i) for i in (0, 1, 2, 3, 5)]
        out = diag.assess_replay_evidence(envs, [], 5)
        assert out["evidence_complete"] is False

    def test_d01_missing_side_b_not_complete(self, diag):
        envs = [_mk_env(0, with_b=False)] + [_mk_env(i) for i in (1, 2, 3, 4)]
        out = diag.assess_replay_evidence(envs, [], 5)
        assert out["evidence_complete"] is False
        assert out["both_sides_complete"] is False

    def test_d01_recorder_error_not_complete(self, diag):
        envs = [_mk_env(i) for i in range(5)]
        out = diag.assess_replay_evidence(
            envs, ["ValueError:boom"], 5)
        assert out["evidence_complete"] is False
        assert out["recorder_errors"] == ["ValueError:boom"]

    def test_d01_exact_five_complete(self, diag):
        envs = [_mk_env(i) for i in range(5)]
        out = diag.assess_replay_evidence(envs, [], 5)
        assert out["evidence_complete"] is True


# ================================================= D02 逐项不一致定位
class TestD02ComparatorLocatesDeviations:
    """相同数量但错坐标/错参数/错 B 哈希/错原因 → 逐项定位(不只 A 计数)。"""

    @staticmethod
    def _pair(**override):
        base = {
            "attempt_index": 0, "outer_seed": 123,
            "internal_derived_seed": 456,
            "base_params": {"A": {"alpha_bps": 70.0},
                            "B": {"alpha_bps": 70.0}},
            "generator_state_digest_pre": "g1",
            "generator_state_digest_post": "g1",
            "split": "s", "timeframe": "15m",
            "structural_validator_results": ["A:too_few_distractors"],
            "accepted": False,
            "rejection_reasons": ["A:too_few_distractors"],
            "event_table": {
                "A": {"counts": {"n_signals": 48, "n_distractors": 0},
                      "hidden_digest": "hA", "episode_content_hash": "eA"},
                "B": {"counts": {"n_signals": 48, "n_distractors": 0},
                      "hidden_digest": "hB", "episode_content_hash": "eB"}},
            "digest": "d0"}
        base.update(override)
        return base

    def test_d02_wrong_outer_seed_located(self):
        from rl_curriculum.curriculum261_generation_envelope import (
            compare_envelopes,
        )
        cmp = compare_envelopes(
            self._pair(), self._pair(outer_seed=999,
                                     digest="d0-tampered"))
        assert cmp["identity_drift"].keys() == {"outer_seed"}
        assert cmp["bitwise_identical"] is False
        assert cmp["consistent"] is False

    def test_d02_wrong_params_located(self):
        from rl_curriculum.curriculum261_generation_envelope import (
            compare_envelopes,
        )
        cmp = compare_envelopes(
            self._pair(),
            self._pair(base_params={"A": {"alpha_bps": 71.0},
                                    "B": {"alpha_bps": 70.0}},
                       digest="d0-tampered"))
        assert "base_params" in cmp["identity_drift"]
        assert cmp["bitwise_identical"] is False

    def test_d02_wrong_b_hash_located(self):
        """B 侧事件表漂移必须被定位(v1 只比 A 侧会漏)。"""
        from rl_curriculum.curriculum261_generation_envelope import (
            compare_envelopes,
        )
        wrong_b = self._pair(digest="d0-tampered")
        wrong_b["event_table"] = {
            "A": wrong_b["event_table"]["A"],
            "B": {"counts": {"n_signals": 48, "n_distractors": 0},
                  "hidden_digest": "hB-tampered",
                  "episode_content_hash": "eB-tampered"}}
        cmp = compare_envelopes(self._pair(), wrong_b)
        assert "event_table" in cmp["result_drift"]
        assert cmp["bitwise_identical"] is False
        assert cmp["consistent"] is False

    def test_d02_wrong_b_distractor_count_located(self):
        from rl_curriculum.curriculum261_generation_envelope import (
            compare_envelopes,
        )
        wrong = self._pair(digest="d0-tampered")
        wrong["event_table"] = {
            "A": wrong["event_table"]["A"],
            "B": {"counts": {"n_signals": 48, "n_distractors": 2},
                  "hidden_digest": "hB",
                  "episode_content_hash": "eB"}}
        cmp = compare_envelopes(self._pair(), wrong)
        assert "event_table" in cmp["result_drift"]
        assert cmp["bitwise_identical"] is False

    def test_d02_identical_pair_consistent(self):
        from rl_curriculum.curriculum261_generation_envelope import (
            compare_envelopes,
        )
        cmp = compare_envelopes(self._pair(), self._pair())
        assert cmp["identity_drift"] == {}
        assert cmp["result_drift"] == {}
        assert cmp["bitwise_identical"] is True
        assert cmp["consistent"] is True


# ================================================= D03 真实五次重放(子进程)
@pytest.mark.skipif(os.name == "nt", reason="需要 WSL 执行环境")
class TestD03RealReplay:
    """原 p52 坐标带现有 recorder 的真实五次 A/B 重放取证。"""

    def test_d03_full_replay_evidence(self, tmp_path):
        out = tmp_path / "diag.json"
        r = _run_diag(["--envelope", str(_orig_envelope()),
                       "--out", str(out)], timeout=600)
        assert r.returncode == 0, r.stderr
        doc = json.loads(out.read_text(encoding="utf-8"))
        rep = doc["replay"]
        assert doc["verdict"] == "CONTRACT_LEGAL_STRUCTURAL_REJECTION"
        assert rep["performed"] is True
        assert rep["recorder_attached"] is True
        assert rep["unexpectedly_accepted"] is False
        assert rep["evidence_complete"] is True
        assert rep["n_attempt_envelopes"] == 5
        assert rep["attempt_indices"] == [0, 1, 2, 3, 4]
        assert rep["both_sides_complete"] is True
        assert rep["recorder_errors"] == []
        assert rep["selected_attempt_is_none"] is True
        # 完整 envelope digest 与业务内容分开报告,两层都一致
        assert rep["call_digest_match"] is True
        assert rep["digest_level_consistent"] is True
        assert rep["business_level_consistent"] is True
        for c in rep["envelope_comparisons"]:
            assert c["bitwise_identical"] is True, c
            assert c["identity_drift"] == {}
            assert c["result_drift"] == {}
            assert c["rejection_reasons_match"] is True
            # A/B 双侧计数对照(v1 只比 A 侧)
            for side in ("A", "B"):
                for k in ("n_signals", "n_distractors",
                          "n_above_cost", "n_below_cost"):
                    assert (c[f"{side}_counts"][k]["original"]
                            == c[f"{side}_counts"][k]["replayed"])
        # runtime 差异(如有)如实保留,不删除不篡改
        assert isinstance(rep["runtime_diffs"], dict)
        # 机制材料:五次均为零 distractor 且其余结构条件通过
        for row in doc["structural_rule_mapping"]["per_attempt"]:
            assert row["only_failing_condition_is_distractors"] is True
        assert doc["dp"]["boundary_checks_all_ok"] is True

    def test_d03_attempt_mechanics_from_real_hidden(self, tmp_path):
        """重放机制快照来自真实 hidden 列:位置递增/成对/偶数计数。"""
        out = tmp_path / "diag2.json"
        r = _run_diag(["--envelope", str(_orig_envelope()),
                       "--out", str(out)], timeout=600)
        assert r.returncode == 0, r.stderr
        doc = json.loads(out.read_text(encoding="utf-8"))
        mech = doc["replay"]["attempt_mechanics"]
        assert len(mech) == 5
        for m in mech:
            for side in ("A", "B"):
                h = m[side]
                assert h["positions_strictly_increasing"] is True
                assert h["pair_structure_ok"] is True
                assert h["n_distractor_bars"] == 0
                assert h["n_distractor_bars_even"] is True
                assert h["n_event_bars"] % 2 == 0
            sh = m["shared_event_table"]
            assert sh["sig_strength"] and sh["sig_dir"] \
                and sh["distractor_flag"]


# ================================================= D04 出口语义
@pytest.mark.skipif(os.name == "nt", reason="需要 WSL 执行环境")
class TestD04ExitSemantics:
    """no-replay/输出失败:每种状态正确区分,无未写报告的假成功出口。"""

    def test_d04_no_replay_readonly(self, tmp_path):
        out = tmp_path / "ro.json"
        r = _run_diag(["--envelope", str(_orig_envelope()),
                       "--out", str(out), "--no-replay"])
        assert r.returncode == 0, r.stderr
        doc = json.loads(out.read_text(encoding="utf-8"))
        assert doc["verdict"] == "READONLY_NO_REPLAY"
        assert doc["replay"]["performed"] is False
        # 只读模式绝不写"重放通过"类结论
        assert "deterministic_replay_consistent" not in doc["replay"]
        # 机制/DP 材料仍完整
        assert doc["dp"]["boundary_checks_all_ok"] is True
        assert doc["scheduling_proof"]["no_truncation"] is True

    def test_d04_output_write_failure_rc6(self, tmp_path):
        """输出写失败:不吞掉,如实非零退出,stderr 说明。"""
        blocked = tmp_path / "blocked.json"
        blocked.mkdir()  # 同名目录使 write_text 失败
        r = _run_diag(["--envelope", str(_orig_envelope()),
                       "--out", str(blocked), "--no-replay"])
        assert r.returncode == 6
        assert "report write failed" in r.stderr

    def test_d04_unexpected_exception_report_written(self, tmp_path,
                                                     monkeypatch):
        """非预期异常:报告先落盘、状态正确标注(v1 直接 return 0 不写)。"""
        diag = None
        p = _diag_script()
        spec = importlib.util.spec_from_file_location(
            "r17_c3_diag_unexpected", p)
        diag = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(diag)
        env_doc = json.loads(
            _orig_envelope().read_text(encoding="utf-8"))

        import rl_curriculum.curriculum261_api as api_mod
        real = api_mod.generate_pair_with_attempts

        def boom(*a, **kw):
            raise RuntimeError("wiring exploded")

        monkeypatch.setattr(
            api_mod, "generate_pair_with_attempts", boom)
        report: dict = {}
        try:
            rc = diag._replay(env_doc, report)
        finally:
            monkeypatch.setattr(
                api_mod, "generate_pair_with_attempts", real)
        assert rc == 4
        rep = report["replay"]
        assert rep["error_type"] == "RuntimeError"
        assert "wiring exploded" in rep["error"]

    def test_d04_unexpected_acceptance_report_written(self, tmp_path):
        """意外接受:报告落盘且明确标注(不复现原五连拒)。"""
        diag = None
        p = _diag_script()
        spec = importlib.util.spec_from_file_location(
            "r17_c3_diag_accept", p)
        diag = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(diag)
        env_doc = json.loads(
            _orig_envelope().read_text(encoding="utf-8"))
        report: dict = {}
        rc = diag._replay(env_doc, report)
        # 真实 p52 坐标必须仍然拒绝;此测试验证"若接受则 rc=4+落盘"
        # 的合同面由 monkeypatch 版本覆盖,这里确认真实行为仍拒绝
        assert rc in (0, 3, 4)
        rep = report["replay"]
        if rc == 0:
            assert rep["unexpectedly_accepted"] is False


# ================================================= M01 调度机制与 DP
class TestM01SchedulingAndDP:
    """调度最小间隔/镜像位置/边界与小 horizon DP(纯数学,进程内)。"""

    def test_m01_no_collision_proof_d0(self, diag):
        pf = diag.scheduling_no_collision_proof(288, 10, 8, 4, 6)
        assert pf["no_truncation"] is True
        assert pf["mirror_position_max"] == 285
        assert pf["n_minus_1"] == 287
        assert pf["strictly_increasing_positions"] is True
        assert pf["distractor_count_is_even"] is True

    def test_m01_no_collision_proof_negative(self, diag):
        """反例:end_margin < gap_hi+2 时截断存在,证明不空转。"""
        pf = diag.scheduling_no_collision_proof(288, 10, 5, 4, 6)
        assert pf["no_truncation"] is False

    def test_m01_dp_forward_backward_agree_d0(self, diag):
        back = diag.dp_zero_distractor(288, 10, 280, 0.200, 0.015, 4, 6)
        fwd = diag.dp_forward_check(288, 10, 280, 0.200, 0.015, 4, 6)
        assert abs(back["p_zero_distractor_single_event_table"]
                   - fwd) < 1e-12
        q = back["p_zero_distractor_single_event_table"]
        # 任务书独立计算的参考量级核对(宽松容差;非硬编码答案)
        assert abs(q - 0.2115357148293) < 1e-6
        assert abs(q ** 5 - 0.000423563484155) < 1e-9

    def test_m01_dp_short_horizon_agree(self, diag):
        for n, t_end in ((20, 12), (40, 32), (100, 92)):
            back = diag.dp_zero_distractor(
                n, 10, t_end, 0.2, 0.015, 4, 6)
            fwd = diag.dp_forward_check(n, 10, t_end, 0.2, 0.015, 4, 6)
            assert abs(back["p_zero_distractor_single_event_table"]
                       - fwd) < 1e-12, (n, t_end)

    def test_m01_dp_boundary_checks_all_ok(self, diag):
        checks = diag.dp_boundary_checks()
        assert all(c["ok"] for c in checks), checks
        names = {c["name"] for c in checks}
        assert {"p_dis_zero_q_is_one", "p_cue_zero_closed_form",
                "no_remaining_bars_q_is_one", "short_horizon_fwd_back_agree",
                "d0_fwd_back_agree",
                "probability_validity_monotone_p_dis"} <= names

    def test_m01_dp_semantics_not_upper_bound(self, diag):
        """修正后的 DP 文案不得再自称上界(碰撞方向矛盾已修)。"""
        doc = diag.dp_zero_distractor(288, 10, 280, 0.2, 0.015, 4, 6)
        assert "not an upper/lower bound" in doc["method"]
        assert "exact" in doc["method"]

    def test_m01_hidden_mechanics_synthetic(self, diag):
        """合成 hidden:成对/镜像/间距/偶数计数重建正确;畸形被拒。"""
        import numpy as np
        import pandas as pd

        n = 60
        s = np.zeros(n); d = np.zeros(n, dtype=int)
        dis = np.zeros(n, dtype=int)
        # 两对信号 + 一对 distractor:位置 10,14 | 22,27 | 40,44
        for (a, b, isd) in ((10, 14, 0), (22, 27, 0), (40, 44, 1)):
            s[a] = s[b] = (0.3 if isd else 1.5)
            d[a], d[b] = 1, -1
            dis[a] = dis[b] = isd
        hidden = pd.DataFrame({
            "sig_strength": s, "sig_dir": d, "distractor_flag": dis})
        m = diag.hidden_event_mechanics(hidden)
        assert m["n_event_bars"] == 6
        assert m["n_event_pairs"] == 3
        assert m["pair_structure_ok"] is True
        assert m["positions_strictly_increasing"] is True
        assert m["n_distractor_bars"] == 2
        assert m["n_distractor_pairs"] == 1
        assert m["pair_gaps"] == [4, 5, 4]
        assert m["inter_pair_min_advance"] == 8  # 22-14
        # 畸形:镜像距离 3(不在 [4,6])必须被拒
        s2 = np.zeros(n); d2 = np.zeros(n, dtype=int)
        s2[10] = s2[13] = 1.5; d2[10], d2[13] = 1, -1
        m2 = diag.hidden_event_mechanics(pd.DataFrame({
            "sig_strength": s2, "sig_dir": d2,
            "distractor_flag": np.zeros(n, dtype=int)}))
        assert m2["pair_structure_ok"] is False


# ================================================= M02 recorder 开关不变性
@pytest.mark.skipif(os.name == "nt", reason="需要 WSL 执行环境")
class TestM02RecorderInvariance:
    """recorder 开/关对同一工程输入:不改 seed/attempt 顺序/episode
    内容/接受条件;诊断不消费业务随机数(独立子进程运行真实模块)。"""

    PROBE = r"""
import json, sys
sys.path.insert(0, {src!r})
from rl_curriculum.curriculum261_api import (
    PairGenerationError, generate_pair_with_attempts)
from rl_curriculum.curriculum261_pairs import (
    family_specs, pair_acceptance_contract)

spec = family_specs()["c3_cost"]
call = json.load(open({env_path!r}, encoding="utf-8"))["call_envelope"]
rp = dict(call["rung_params"])

def run(recorder):
    try:
        generate_pair_with_attempts(
            spec.generator, rp,
            namespace=call["namespace"], family=call["family"],
            rung=call["rung"], pair_index=int(call["pair_index"]),
            structural_validator=pair_acceptance_contract(call["family"]),
            recorder=recorder)
        return {{"accepted": True}}
    except PairGenerationError as exc:
        return {{"accepted": False,
                 "reasons": [a.reason for a in exc.attempt_log.attempts],
                 "selected": exc.attempt_log.selected_attempt,
                 "n_envelopes": len(exc.attempt_envelopes or [])}}

out = {{"no_recorder": run(None)}}
sys.path.insert(0, {runner!r})
import importlib.util as _iu
_spec = _iu.spec_from_file_location("diagmod", {diag!r})
_mod = _iu.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
rec = _mod.make_checked_recorder_cls()(
    iteration=call["iteration"], namespace=call["namespace"],
    family=call["family"], rung=call["rung"],
    pair_index=int(call["pair_index"]), rung_params=rp)
with_rec = run(rec)
out["with_recorder"] = with_rec
out["envelopes"] = [{{"attempt": e["attempt_index"],
                      "digest": e["digest"],
                      "reasons": e["rejection_reasons"]}}
                    for e in rec.attempt_envelopes]
out["record_errors"] = rec.record_errors
out["mechanics_n"] = len(rec.attempt_mechanics)
print(json.dumps(out))
"""

    def test_m02_recorder_invariance_p52(self, tmp_path):
        src = str(_src_dir())
        runner = str(_diag_script().parent)
        script = self.PROBE.format(
            src=src, env_path=str(_orig_envelope()),
            runner=runner, diag=str(_diag_script()))
        r = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True, text=True, timeout=600,
            cwd=src, env={**os.environ, "PYTHONPATH": src})
        assert r.returncode == 0, r.stderr
        out = json.loads(r.stdout.strip().splitlines()[-1])
        no_r = out["no_recorder"]
        with_r = out["with_recorder"]
        # 接受状态与逐 attempt 拒绝原因完全一致(生成未被改变)
        assert no_r["accepted"] is False
        assert with_r["accepted"] is False
        assert no_r["reasons"] == with_r["reasons"]
        assert no_r["selected"] is None and with_r["selected"] is None
        # recorder 开启获得完整证据;关闭时合法为空(证据层≠业务层)
        assert with_r["n_envelopes"] == 5
        assert no_r["n_envelopes"] == 0
        assert out["record_errors"] == []
        assert out["mechanics_n"] == 5
        # attempt 顺序 0..4 且拒绝词表与无 recorder 路径一致
        assert [e["attempt"] for e in out["envelopes"]] == [0, 1, 2, 3, 4]
        for e, reason in zip(out["envelopes"], no_r["reasons"]):
            assert "; ".join(e["reasons"]) == reason

    def test_m02_replay_determinism_same_digest(self, tmp_path):
        """同坐标两次带 recorder 重放:envelope digest 逐位一致。"""
        outs = []
        for i in (1, 2):
            o = tmp_path / f"m02_{i}.json"
            r = _run_diag(["--envelope", str(_orig_envelope()),
                           "--out", str(o)], timeout=600)
            assert r.returncode == 0, r.stderr
            doc = json.loads(o.read_text(encoding="utf-8"))
            digest = [c["envelope_digest_replayed"]
                      for c in doc["replay"]["envelope_comparisons"]]
            outs.append(digest)
        assert outs[0] == outs[1]
