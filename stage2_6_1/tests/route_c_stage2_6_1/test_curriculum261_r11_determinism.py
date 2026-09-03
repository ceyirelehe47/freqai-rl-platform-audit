# -*- coding: utf-8 -*-
"""R11 工作包 A 测试:跨进程确定性与 mutable state(§12 类别
7/8/9/10/13/14)。

全部场景通过 curriculum261_r11_determinism 的 probe 入口在
fresh subprocess 中执行(同一 invocation envelope 的逐字段对比,
不只比较最终 PASS)。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from rl_curriculum.curriculum261_api import derive261_seed
from rl_curriculum.curriculum261_r11_determinism import (
    R10_FAILURE,
    ROOT_CAUSE_STATEMENT,
    _run_probe,
    _extract,
)

DET_MOD = Path(
    __import__("rl_curriculum.curriculum261_r11_determinism",
               fromlist=["__file__"]).__file__).resolve()


def _probe(tmp_path, name, *, target="r11", prelude="",
           env_extra=None):
    return _run_probe(tmp_path, name, target=target, prelude=prelude,
                      env_extra=env_extra)


def _base(tmp_path):
    return _extract(_probe(tmp_path, "base", target="r11"))


def _requires_src():
    src = DET_MOD.parents[2] / "src"
    return src.is_dir()


# ------------------------------------------------ 7: PYTHONHASHSEED
def test_same_invocation_different_pythonhashseed(tmp_path):
    base = _base(tmp_path)
    got = _extract(_probe(
        tmp_path, "hash", target="r11",
        env_extra={"PYTHONHASHSEED": "424242"}))
    assert got["attempt_digests"] == base["attempt_digests"]
    assert got["attempt_event_digests"] == base["attempt_event_digests"]
    assert got["attempt_accepted"] == base["attempt_accepted"]


# ------------------------------------------------ 8: torch import 前后
def test_same_invocation_torch_import_first(tmp_path):
    base = _base(tmp_path)
    got = _extract(_probe(
        tmp_path, "torch", target="r11", prelude="import_torch_first"))
    assert got["attempt_digests"] == base["attempt_digests"]
    assert got["attempt_outer_seeds"] == base["attempt_outer_seeds"]


# ------------------------------------------------ 9: preprocessing battery
def test_same_invocation_after_preprocessing_battery(tmp_path):
    base = _base(tmp_path)
    got = _extract(_probe(
        tmp_path, "battery", target="r11",
        prelude="preprocessing_battery"))
    assert got["attempt_digests"] == base["attempt_digests"]


# ------------------------------------------------ 10: main/holdout bundle
def test_same_invocation_after_main_holdout_bundle(tmp_path):
    base = _base(tmp_path)
    got = _extract(_probe(
        tmp_path, "bundles", target="r11",
        prelude="main_holdout_bundle_flow"))
    assert got["attempt_digests"] == base["attempt_digests"]


# ------------------------------------------------ 13: singleton 污染
def test_family_specs_singleton_not_polluted_by_calls(tmp_path):
    """c1/c2/c3/matched 依次生成后,单例状态摘要回到初始。"""
    code = r"""
import sys, json
sys.path.insert(0, %r)
from rl_curriculum.curriculum261_generation_envelope import (
    generator_state_digest, family_spec_identity, stable_digest)
from rl_curriculum.curriculum261_pairs import family_specs, generate_pair
from rl_curriculum.curriculum261_r6_tape import (
    generate_matched_block_with_attempts,
)
before = {f: generator_state_digest(s.generator)
          for f, s in sorted(family_specs().items())}
for fam in ("c1_opportunity", "c2_context", "c3_cost"):
    generate_pair(fam, "D1", 0, namespace="stress_r11")
ladder = {r: dict(family_specs()["c2_context"].rung_params[r])
          for r in ("D0", "D1", "D2", "D3")}
generate_matched_block_with_attempts(
    ladder, namespace="stress_r11", block_index=0)
after = {f: generator_state_digest(s.generator)
         for f, s in sorted(family_specs().items())}
print(json.dumps({"before": before, "after": after,
                  "clean": before == after}))
""" % str(DET_MOD.parents[2] / "src")
    import subprocess

    proc = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True,
        timeout=900)
    assert proc.returncode == 0, proc.stderr[-500:]
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    assert out["clean"], out


# ------------------------------------------------ 14: R10 五 seed 重放
def test_r10_five_attempt_seeds_replay(tmp_path):
    """R10 正式失败的五个 outer attempt seeds 逐一重放(确定性)。

    重放按 first_pass 停止:若 attempt 0 即接受,则只执行 1 个
    attempt —— 派生一致性按前缀逐位比较。
    """
    res = _probe(tmp_path, "r10", target="r10")
    assert res["ok"], res.get("stderr_tail", "")
    got = _extract(res)
    seeds = got["attempt_outer_seeds"]
    assert seeds, "至少重放一个 attempt"
    assert seeds == R10_FAILURE["attempt_seeds"][:len(seeds)], (
        "重放的逐 attempt outer seed 必须与 R10 记录逐位一致(前缀)")
    # 再来一次独立冷进程 => envelope 逐位一致
    res2 = _probe(tmp_path, "r10b", target="r10")
    assert _extract(res2)["attempt_digests"] == got["attempt_digests"]
    # 记录的重放结果:R10 失败在重放下不可复现(与 R10 诊断一致);
    # 若未来任何环境复现,矩阵 artifact 会单独标记
    assert "too_few_distractors" not in str(got["generation_error"])


def test_r10_failure_root_cause_statement_is_underdetermined():
    """根因定性合同:不得声称唯一原因是偶发进程内状态。"""
    assert ROOT_CAUSE_STATEMENT == (
        "historically underdetermined due to missing "
        "invocation-state evidence")


# ------------------------------------------------ envelope 外种子一致性
def test_stress_r11_target_seeds_derivable():
    """矩阵目标调用的 outer seeds 可从派生字段独立复算。"""
    base = _base(__import__("tempfile").mkdtemp())
    for seed in base["attempt_outer_seeds"]:
        assert isinstance(seed, int)
    q = derive261_seed("stress_r11", "c3_cost", "D0", 3, 0)
    assert base["attempt_outer_seeds"][0] == q


# ------------------------------------------------ 12: 同进程重复两次
def test_same_process_twice_bitwise(tmp_path):
    res2 = _run_probe(tmp_path, "twice2", target="r11",
                      repeat_twice=True)
    assert res2["ok"], res2.get("stderr_tail", "")
    assert res2["same_process_bitwise"] is True
