# -*- coding: utf-8 -*-
"""PSC_P0_v1 存取身份与预算面(P10/P01;纯构造/临时计数账本)。

save/load:旧 posctl 档、A↔B 互载、错 bank_ref 在权重反序列化前拒绝;
新进程只读对拍确定性一致;同 seed 两臂公共 trunk 初始权重摘要一致
(动作头宽度差如实)。预算:PSC_P0_v1 面完整性、单次/分项/派生总项
拒绝语义(临时纯计数账本,零业务资源)。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import torch as th

from rl_posctl.policy import (
    make_posctl_ppo, save_posctl_model)
from rl_posctl.skill_p0.p0env import P0FiniteTimeEnv
from rl_posctl.skill_p0.p0policy import (
    P0_HEADER_KEY, make_p0_ppo, p0_code_digest,
    p0_hyperparams_digest, save_p0_model, trunk_digest)
from rl_posctl.skill_p0.p0spec import (
    C1_FEE, FUNDING_SCHEDULE, HIDDEN, INITIAL_CASH,
    MAINTENANCE_MARGIN, REWARD_SCALE)

SRC = str(Path(__file__).resolve().parents[2] / "src")
ROOT = Path(__file__).resolve().parents[2]


def _bank_item(n: int = 9, seed: int = 5):
    rng = np.random.default_rng(seed)
    r = np.concatenate(
        [[0.0], 0.002 + 0.004 * rng.uniform(-1, 1, n - 1)])
    close = 100.0 * np.cumprod(1.0 + r)
    open_ = np.empty_like(close)
    open_[0] = 100.0
    open_[1:] = close[:-1]
    return (pd.DataFrame({"open": open_, "close": close}),
            pd.DataFrame({"s": np.zeros(n), "c": np.ones(n),
                          "q": np.full(n, 0.5), "g": np.zeros(n)}),
            {"pair_index": 0, "variant": 0, "horizon": n - 1,
             "sha256": "0" * 64, "seed_pair": [0, 0]})


def _p0_env():
    p, f, _ = _bank_item()
    return P0FiniteTimeEnv(
        features=f, prices=p, fee=C1_FEE, window_size=1,
        funding_schedule=dict(FUNDING_SCHEDULE),
        maintenance_margin=MAINTENANCE_MARGIN,
        initial_cash=INITIAL_CASH, reward_scale=REWARD_SCALE)


def test_budget_face_matches_package():
    from rl_posctl.budget import task_registry
    face = task_registry()["PSC_P0_v1"]
    lim = face["limits"]
    assert lim["ppo_steps_main"] == 786_432
    assert lim["ppo_steps_smoke"] == 2_048
    assert lim["ppo_steps_techretry"] == 65_536
    assert lim["ppo_learn_main_attempts"] == 6
    assert lim["ppo_learn_smoke_attempts"] == 4
    assert lim["ppo_learn_techretry_attempts"] == 2
    assert lim["ppo_optimizer_steps"] == 33_360
    assert lim["eval_steps"] == 524_288
    assert lim["gen_calls"] == 2_048
    assert lim["episodes"] == 1_024
    assert lim["bc_fits"] == 14
    assert lim["bc_minibatch_updates"] == 8_192
    assert lim["supervised_rows"] == 8_192
    assert lim["dist_sample_actions"] == 1_048_576
    assert lim["bootstrap_draws"] == 1_000_000
    assert lim["evidence_kib"] == 524_288
    d = {name: cap for name, parts, cap in face["derived_totals"]}
    assert d["ppo_steps_total"] == 854_016
    assert d["ppo_learn_total"] == 12
    assert d["economic_total"] == 1_378_304
    sc = face["single_caps"]
    assert sc["ppo_steps_main"] == 131_072
    assert sc["ppo_steps_smoke"] == 512
    assert sc["ppo_steps_techretry"] == 32_768
    assert sc["ppo_optimizer_steps"] == 5_120


def test_tmp_ledger_gates(tmp_path):
    """纯计数临时账本:单次/分项/派生总项拒绝语义(零业务资源)。"""
    from rl_posctl.budget import BudgetExceeded, TaskLedger
    led = TaskLedger.create(
        tmp_path / "p0_face.jsonl", "PSC_P0_v1",
        binding={"task": "pytest-pure-counting"})
    # 单次上限:main 一次预约 > 131,072 拒
    with pytest.raises(BudgetExceeded):
        led.reserve("t0", ppo_steps_main=131_073,
                    ppo_learn_main_attempts=1)
    # 分项总额:6 × 131,072 恰满;第 7 次拒
    for k in range(6):
        rid = led.reserve(f"t{k}", ppo_steps_main=131_072,
                          ppo_learn_main_attempts=1)
        led.commit(rid, f"t{k}", ppo_steps_main=131_072,
                   ppo_learn_main_attempts=1)
    with pytest.raises(BudgetExceeded):     # 分项 main 已满
        led.reserve("t7", ppo_steps_main=1,
                    ppo_learn_main_attempts=1)
    with pytest.raises(BudgetExceeded):     # learn 尝试派生 7>6
        led.reserve("t8", ppo_steps_smoke=1,
                    ppo_learn_main_attempts=1)
    # smoke 4 次 × 512 满;techretry 分项独立(不可挪用)
    for k in range(4):
        rid = led.reserve(f"s{k}", ppo_steps_smoke=512,
                          ppo_learn_smoke_attempts=1)
        led.commit(rid, f"s{k}", ppo_steps_smoke=512,
                   ppo_learn_smoke_attempts=1)
    with pytest.raises(BudgetExceeded):
        led.reserve("s5", ppo_steps_smoke=1,
                    ppo_learn_smoke_attempts=1)
    rid = led.reserve("r1a", ppo_steps_techretry=32_768,
                      ppo_learn_techretry_attempts=1)
    led.commit(rid, "r1a", ppo_steps_techretry=32_768,
               ppo_learn_techretry_attempts=1)
    rid = led.reserve("r1b", ppo_steps_techretry=32_766,
                      ppo_learn_techretry_attempts=1)
    led.commit(rid, "r1b", ppo_steps_techretry=32_766,
               ppo_learn_techretry_attempts=1)
    # 派生总项 ppo_steps_total 已满(786,432+2,048+65,534=854,014,
    # 剩 2):再加 3 拒(经济总项同界)
    with pytest.raises(BudgetExceeded):
        led.reserve("r2", ppo_steps_techretry=3,
                    ppo_learn_techretry_attempts=1)
    snap = led.snapshot()
    assert snap["committed"]["ppo_steps_smoke"] == 2_048
    assert snap["committed"]["ppo_steps_main"] == 786_432


def test_header_and_trunk(tmp_path):
    env = _p0_env()
    mA = make_p0_ppo(env, arm="A", seed=270201, bank_ref="r" * 64,
                     horizon=64)
    mB = make_p0_ppo(env, arm="B", seed=270201, bank_ref="r" * 64,
                     horizon=64)
    hA = getattr(mA, P0_HEADER_KEY)
    hB = getattr(mB, P0_HEADER_KEY)
    assert hA["policy_spec"] == "P0SymBetaControl-v1"
    assert hB["policy_spec"] == "P0AsymBeta-v1"
    assert hA["n_dist_params"] == 7 and hB["n_dist_params"] == 8
    assert hA["observation_spec"] == "PosctlObsP0Time-v1"
    assert hA["obs_dim"] == 8
    assert hA["gamma"] == 1.0
    assert hA["decode_rule"] == "P0CategoryMax-v1"
    assert hA["task_id"] == "PSC_P0_v1"
    assert hA["account_features"][-2:] == [
        "remaining_decisions_frac128", "original_horizon_frac128"]
    assert any(isinstance(m, th.nn.Tanh)
               for m in mA.policy.mlp_extractor.policy_net)
    pi = mA.policy.mlp_extractor.policy_net
    assert [m.out_features for m in pi
            if isinstance(m, th.nn.Linear)] == list(HIDDEN)
    # 同 seed 两臂公共 trunk(mlp_extractor)初始权重摘要一致
    assert trunk_digest(mA) == trunk_digest(mB)
    # 参数量:动作头宽度差如实(latent 128:8−7 行 ×(128+1))
    pa = sum(p.numel() for p in mA.policy.parameters())
    pb = sum(p.numel() for p in mB.policy.parameters())
    assert pb - pa == 129
    save_p0_model(mA, tmp_path / "A.zip")
    save_p0_model(mB, tmp_path / "B.zip")


def test_load_rejections(tmp_path):
    env = _p0_env()
    mA = make_p0_ppo(env, arm="A", seed=1, bank_ref="r" * 64,
                     horizon=64)
    save_p0_model(mA, tmp_path / "A.zip")
    from rl_posctl.skill_p0.p0policy import load_p0_model
    with pytest.raises(RuntimeError):       # A 档载入 B 臂
        load_p0_model(tmp_path / "A.zip", env, arm="B",
                      bank_ref="r" * 64, horizon=64)
    with pytest.raises(RuntimeError):       # 错 bank_ref
        load_p0_model(tmp_path / "A.zip", env, arm="A",
                      bank_ref="x" * 64, horizon=64)
    # 旧 posctl 档(无 P0 header)拒绝
    old = make_posctl_ppo(env, seed=1)
    save_posctl_model(old, tmp_path / "old.zip")
    with pytest.raises(RuntimeError):
        load_p0_model(tmp_path / "old.zip", env, arm="A",
                      bank_ref="r" * 64, horizon=64)


def test_new_process_deterministic_reload(tmp_path):
    """新进程只读载入:公共解码动作精确一致(冻结前后同一 zip)。"""
    env = _p0_env()
    mB = make_p0_ppo(env, arm="B", seed=270202, bank_ref="r" * 64,
                     horizon=64)
    save_p0_model(mB, tmp_path / "B.zip")
    obs, _ = env.reset()
    act, _ = mB.predict(obs, deterministic=True)
    probe = tmp_path / "probe.json"
    probe.write_text(json.dumps(
        {"obs": [float(x) for x in obs],
         "act": [float(x) for x in act],
         "path": str(tmp_path / "B.zip"),
         "bank_ref": "r" * 64}, ensure_ascii=False), encoding="utf-8")
    code = (
        "import json,sys\n"
        "sys.path.insert(0, %r)\n" % SRC +
        "import numpy as np, pandas as pd, torch as th\n"
        "th.set_num_threads(1)\n"
        "from rl_posctl.skill_p0.p0policy import load_p0_model\n"
        "from rl_posctl.skill_p0.p0env import P0FiniteTimeEnv\n"
        "d = json.load(open(sys.argv[1]))\n"
        "n = 9\n"
        "rng = np.random.default_rng(5)\n"
        "r = np.concatenate([[0.0], "
        "0.002 + 0.004 * rng.uniform(-1, 1, n - 1)])\n"
        "close = 100.0 * np.cumprod(1.0 + r)\n"
        "open_ = np.empty_like(close); open_[0] = 100.0\n"
        "open_[1:] = close[:-1]\n"
        "env = P0FiniteTimeEnv(\n"
        "    features=pd.DataFrame({'s': np.zeros(n), "
        "'c': np.ones(n), 'q': np.full(n, 0.5), "
        "'g': np.zeros(n)}),\n"
        "    prices=pd.DataFrame({'open': open_, "
        "'close': close}), fee=0.001, window_size=1,\n"
        "    funding_schedule={}, maintenance_margin=0.05,\n"
        "    initial_cash=100.0, reward_scale=1.0)\n"
        "m = load_p0_model(d['path'], env, arm='B',"
        "bank_ref=d['bank_ref'], horizon=64)\n"
        "a, _ = m.predict(np.asarray(d['obs'], dtype=np.float32),"
        "deterministic=True)\n"
        "print(json.dumps([float(x) for x in a]))\n")
    script = tmp_path / "reload_probe.py"
    script.write_text(code, encoding="utf-8")
    out = subprocess.run(
        [sys.executable, str(script), str(probe)],
        capture_output=True, text=True, cwd=str(ROOT),
        env={"PYTHONPATH": SRC, "PATH": "/usr/bin:/bin",
             "OMP_NUM_THREADS": "1"})
    assert out.returncode == 0, out.stderr[-2000:]
    got = json.loads(out.stdout.strip().splitlines()[-1])
    assert got == [float(x) for x in act]


def test_checkpoint_binds_code_and_data(tmp_path):
    env = _p0_env()
    m = make_p0_ppo(env, arm="A", seed=1, bank_ref="d" * 64,
                    horizon=64)
    h = getattr(m, P0_HEADER_KEY)
    assert h["code_digest"] == p0_code_digest()
    assert h["bank_ref"] == "d" * 64
    assert h["horizon"] == 64
