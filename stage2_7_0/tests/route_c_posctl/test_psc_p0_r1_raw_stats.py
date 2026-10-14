# -*- coding: utf-8 -*-
"""PSC_P0_v1 FiniteRepair R1 / F3:原始行持久化、正例门可达与更正。

固定行夹具口径(记录型账本/固定结果;零 env.step、零真实重采样):
- raw 逐 episode 行先于聚合落盘,读回原件可重算汇总;中断不丢件;
- 生产者-消费者 valid 语义一致:全正例臂级门可达,逐门破坏必失败;
- 失败分母/身份/成本字段完整保留。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from test_psc_p0_r1_resource_order import (
    RecLedger, _fake_env_factory, _fake_runner, _items)

class TestRawBeforeAggregate:
    """raw 行先于聚合持久化;读回可重算;中断不丢件。"""


    def _run(self, tmp_path, n_eps=4, fail_at=None):
        from rl_posctl.skill_p0.p0eval import eval_on_bank
        raw_path = tmp_path / "model_rows.jsonl"
        fh = raw_path.open("x", encoding="utf-8")
        events = []

        def sink(row):
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            fh.flush()
            events.append("raw")

        led = RecLedger(available=100)
        counter = {"env_created": 0, "work_units": 0}
        rows = None
        try:
            rows = eval_on_bank(
                _items(n_eps, rows=3), lambda *a: 0.0,
                ledger=led, tag="t", raw_sink=sink,
                env_factory=_fake_env_factory(counter),
                runner=_fake_runner(counter, fail_at=fail_at),
                summarizer=self._fake_summarizer(events))
            events.append("aggregate")
        finally:
            fh.close()
        return rows, raw_path, events

    @staticmethod
    def _fake_summarizer(events):
        i = {"n": 0}

        def s(infos):
            i["n"] += 1
            return {"n_steps": 2,
                    "net_log_return": 0.01 * i["n"],
                    "net_log_return_valid": True,
                    "economic_failure": False,
                    "fees_cum": 0.001 * i["n"]}
        return s

    def test_raw_rows_written_and_recomputable(self, tmp_path):
        rows, raw_path, events = self._run(tmp_path)
        assert events[-1] == "aggregate"
        assert events[:-1] == ["raw"] * 4, "每行先落盘再聚合"
        back = [json.loads(x) for x in
                raw_path.read_text(encoding="utf-8").splitlines()]
        assert len(back) == 4
        # 读回原件重算汇总 == 内存聚合
        mean_back = sum(r["net_log_return"] for r in back) / len(back)
        mean_mem = sum(r["net_log_return"] for r in rows) / len(rows)
        assert mean_back == mean_mem
        # 身份/成本/失败字段完整
        for r in back:
            assert {"episode", "pair_index", "variant",
                    "net_log_return", "economic_failure",
                    "reward_valid", "steps"} <= set(r)
            assert "fees_cum" in r["summary"]

    def test_interrupt_keeps_partial_raw(self, tmp_path):
        """中断:已写原件不消失;聚合未发生;重开 create-only 拒绝。"""
        with pytest.raises(RuntimeError, match="中断反例"):
            self._run(tmp_path, n_eps=4, fail_at=2)
        raw_path = tmp_path / "model_rows.jsonl"
        back = [json.loads(x) for x in
                raw_path.read_text(encoding="utf-8").splitlines()]
        assert len(back) == 2, "中断前已发生的行必须保留"
        with pytest.raises(FileExistsError):
            # 恢复不得覆盖已有原件(open "x" create-only)
            raw_path.open("x", encoding="utf-8")


class TestPairMatrixIdentity:
    """pair 聚合的身份绑定与失败保留(固定行)。"""

    @staticmethod
    def _rows(values, failures=None):
        failures = failures or {}
        out = []
        for i, v in enumerate(values):
            out.append({
                "episode": i, "pair_index": i // 2,
                "variant": i % 2,
                "net_log_return": (
                    None if failures.get(i) else v),
                "economic_failure": bool(failures.get(i)),
                "reward_valid": not failures.get(i)})
        return out

    def test_pair_values_grouped_by_identity(self):
        from rl_posctl.skill_p0.p0eval import pair_advantage_matrix
        base = self._rows([0.10, 0.12, 0.08, 0.10])
        model = self._rows([0.20, 0.24, 0.18, 0.22])
        mat = pair_advantage_matrix({"m": model}, base)
        assert mat["valid"] is True
        assert mat["n_pairs"] == 2
        # 差值 [0.10,0.12,0.10,0.12] → pair0=pair1=0.11
        assert mat["pair_values"] == pytest.approx(
            [0.11, 0.11])

    def test_failure_kept_not_dropped(self):
        from rl_posctl.skill_p0.p0eval import pair_advantage_matrix
        base = self._rows([0.10, 0.12, 0.08, 0.10])
        model = self._rows([0.2, 0.24, 0.18, 0.3],
                           failures={3: "margin"})
        mat = pair_advantage_matrix({"m": model}, base)
        assert mat["valid"] is False
        assert "episode 3" in mat["reason"], "失败分母不删除"

    def test_length_mismatch_rejected(self):
        from rl_posctl.skill_p0.p0eval import pair_advantage_matrix
        base = self._rows([0.1, 0.2])
        model = self._rows([0.3])
        with pytest.raises(ValueError, match="行数"):
            pair_advantage_matrix({"m": model}, base)


class TestArmGatePositiveReachable:
    """臂级门正例可达 + 逐门破坏必失败(生产者-消费者一致)。"""

    @staticmethod
    def _boot(valid=True, lower=True):
        return {b: {"deterministic": {
                        "valid": valid, "reason":
                            None if valid else "r",
                        "lower_positive": lower},
                    "sampled": {
                        "valid": valid, "reason":
                            None if valid else "r",
                        "lower_positive": lower}}
                for b in ("flat", "const+1", "const-1",
                          "const+0.5", "const-0.5")}

    def test_all_positive_passes(self):
        from rl_posctl.skill_p0.p0eval import (
            bootstrap_results_all_valid_positive)
        assert bootstrap_results_all_valid_positive(
            self._boot()) is True

    def test_missing_valid_fails(self):
        """旧断路反例:生产者缺 valid(旧版 paired_bootstrap 返回)
        → 消费者必须判败,不得默认有效。"""
        from rl_posctl.skill_p0.p0eval import (
            bootstrap_results_all_valid_positive)
        boot = self._boot()
        del boot["flat"]["sampled"]["valid"]
        assert bootstrap_results_all_valid_positive(boot) is False

    def test_each_broken_gate_fails(self):
        from rl_posctl.skill_p0.p0eval import (
            bootstrap_results_all_valid_positive)
        assert bootstrap_results_all_valid_positive(
            self._boot(valid=False)) is False
        assert bootstrap_results_all_valid_positive(
            self._boot(lower=False)) is False
        assert bootstrap_results_all_valid_positive({}) is False
        boot = self._boot()
        boot["const-0.5"] = {}
        assert bootstrap_results_all_valid_positive(boot) is False

    def test_arm_gate_full_chain_positive(self):
        """2/3 种子过门 + 无经济失败 + 全 bootstrap 正 → 臂级 PASS。

        与 psc_p0_confirm 相同的判定组合(n_seed>=2 ∧ no_fail
        ∧ bootstrap_results_all_valid_positive)。
        """
        from rl_posctl.skill_p0.p0eval import (
            bootstrap_results_all_valid_positive)
        seeds_pass = [True, True, False]
        n_ok = sum(seeds_pass)
        no_fail = True
        boot = self._boot()
        assert bool(n_ok >= 2 and no_fail
                    and bootstrap_results_all_valid_positive(
                        boot)) is True
        # 破坏:只有 1/3 种子过门
        assert bool(1 >= 2 and no_fail
                    and bootstrap_results_all_valid_positive(
                        boot)) is False
        # 破坏:任一 bootstrap 下界非正
        boot2 = self._boot()
        boot2["const+1"]["sampled"]["lower_positive"] = False
        assert bool(n_ok >= 2 and no_fail
                    and bootstrap_results_all_valid_positive(
                        boot2)) is False

    def test_bootstrap_invalid_no_meter_no_gate(self):
        """失败/缺样本 → valid=False 不消耗采样且臂门必失败。"""
        from rl_posctl.skill_p0.p0eval import paired_bootstrap
        meter = []
        out = paired_bootstrap(
            [0.1, float("nan")], seed=1, draws=10,
            meter=meter.append,
            rng_factory=lambda s: (_ for _ in ()).throw(
                AssertionError("不应采样")))
        assert out["valid"] is False
        assert meter == []


class TestReportCorrectionsContent:
    """R1 更正文档在场且包含任务要求的更正点(内容验收锚)。"""

    def test_corrections_file_documents_required_claims(self):
        rep = (Path(__file__).resolve().parents[2]
               / "report" / "P0_R1_FINITE_REPAIR_REPORT.md")
        assert rep.exists(), "R1 工程报告必须在场"
        text = rep.read_text(encoding="utf-8")
        for anchor in (
                "5/6",            # 两侧方向门 5/6(A_270202 未过)
                "0.374",          # A_270202 正向 min P
                "0/6",            # 中性 0/6
                "184/216",        # 空仓反事实网格确定性 ±1
                "99%",            # 99% 主张限定
                "期限",           # 期限泛化主张降级
        ):
            assert anchor in text, f"更正锚点缺失:{anchor}"
