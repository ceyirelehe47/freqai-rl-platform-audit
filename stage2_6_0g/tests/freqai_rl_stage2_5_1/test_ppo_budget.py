"""工作包 A 测试:PPO 显式训练预算(任务书四/五/六节)。"""

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from rl_platform.ppo_params import (
    DEFAULT_ROUTE_C_PPO,
    RouteCPPOConfigError,
    compute_budget,
    resolve_ppo_params,
    run_ppo_fit,
)
from freqai_rl_stage2_5.util import build_env, make_values

ART = Path(__file__).resolve().parents[2] / "artifacts" / "freqai_rl_stage2_5_1"


# ---------------------------------------------------------------- 步数语义
def test_budget_rounding_semantics():
    # 482 行(阶段 2.5 实际每窗训练特征行数)必须 rounded 到 512
    b = compute_budget(1, 482, 128)
    assert b["base_budget"] == 482
    assert b["rounded_budget"] == 512
    assert b["rounded_budget"] % b["n_steps"] == 0
    assert b["n_rollouts"] == 4
    # 恰好整除时不进位
    b2 = compute_budget(1, 384, 128)
    assert b2["rounded_budget"] == 384
    # 多训练周期
    b3 = compute_budget(2, 482, 128)
    assert b3["base_budget"] == 964
    assert b3["rounded_budget"] == 1024
    # 通用性质
    for base, steps in ((30, 128), (1, 128), (999, 128), (513, 128)):
        r = compute_budget(1, base, steps)
        assert r["rounded_budget"] >= base
        assert r["rounded_budget"] % steps == 0
        assert r["rounded_budget"] - base < steps


def test_resolved_params_complete_and_defaulted():
    r = resolve_ppo_params({"route_c": {"ppo": {}}})
    assert r["constructor"] == DEFAULT_ROUTE_C_PPO
    assert r["runtime"]["policy_type"] == "MlpPolicy"
    assert r["runtime"]["device"] == "cpu"
    assert r["runtime"]["n_envs"] == 1
    assert r["runtime"]["seed"] == 42
    # 覆盖单键
    r2 = resolve_ppo_params({"route_c": {"ppo": {"gamma": 0.95}, "seed": 7}})
    assert r2["constructor"]["gamma"] == 0.95
    assert r2["runtime"]["seed"] == 7


def test_resolved_params_conflict_detection():
    # rl_config 出现 PPO 构造参数 -> 报错(不得静默覆盖)
    with pytest.raises(RouteCPPOConfigError, match="rl_config"):
        resolve_ppo_params({"rl_config": {"n_steps": 64}, "route_c": {"ppo": {}}}, strict=True)
    # model_training_parameters 出现 PPO 构造参数 -> 报错
    with pytest.raises(RouteCPPOConfigError, match="model_training_parameters"):
        resolve_ppo_params({
            "model_training_parameters": {"learning_rate": 0.001},
            "route_c": {"ppo": {}},
        }, strict=True)
    # net_arch 重复配置同样报错(上游 rl_config 的 net_arch 必须移除)
    with pytest.raises(RouteCPPOConfigError):
        resolve_ppo_params({"rl_config": {"net_arch": [64]}, "route_c": {"ppo": {}}}, strict=True)
    # 未知键
    with pytest.raises(RouteCPPOConfigError, match="未知键"):
        resolve_ppo_params({"route_c": {"ppo": {"not_a_ppo_key": 1}}})
    # n_envs != 1
    with pytest.raises(RouteCPPOConfigError, match="n_envs"):
        resolve_ppo_params({"route_c": {"n_envs": 4, "ppo": {}}})


# ---------------------------------------------------------------- 真实训练
def test_run_ppo_fit_budget_enforced(tmp_path):
    """30 行环境:base=30 -> rounded=128;num_timesteps 必须等于 128。"""
    env = build_env(make_values("zigzag"), fee=0.001, slippage_bps=0.0)
    resolved = resolve_ppo_params({"route_c": {"ppo": {}}})
    record_path = tmp_path / "ppo_budget.json"
    model, record = run_ppo_fit(
        env=env,
        resolved=resolved,
        train_cycles=1,
        n_train_rows=30,
        tensorboard_log=None,
        record_path=record_path,
    )
    assert record["base_budget"] == 30
    assert record["rounded_budget"] == 128
    assert record["actual_num_timesteps"] == int(model.num_timesteps) == 128
    assert record["rounded_budget"] % record["n_steps"] == 0
    assert record["n_rollouts"] == 1
    assert record["device"] == "cpu"
    assert record["episode_resets"] == env.episode_reset_count >= 1
    on_disk = json.loads(record_path.read_text())
    assert on_disk["actual_num_timesteps"] == 128


def test_run_ppo_fit_tensorboard_log(tmp_path):
    """TensorBoard 日志目录生成(任务书六节:tags 由证据脚本另行校验)。"""
    env = build_env(make_values("constant"))
    resolved = resolve_ppo_params({"route_c": {"ppo": {}}})
    tb = tmp_path / "tb"
    model, record = run_ppo_fit(
        env=env, resolved=resolved, train_cycles=1, n_train_rows=20,
        tensorboard_log=tb, record_path=None,
    )
    assert record["actual_num_timesteps"] == 128
    event_files = list(tb.rglob("events.out.tfevents.*"))
    assert event_files, "TensorBoard event 文件未生成"


def test_ppo_evidence_artifact(tmp_path):
    ART.mkdir(parents=True, exist_ok=True)
    env = build_env(make_values("zigzag"))
    resolved = resolve_ppo_params({"route_c": {"ppo": {}}})
    _, record = run_ppo_fit(
        env=env, resolved=resolved, train_cycles=1, n_train_rows=30,
        tensorboard_log=None, record_path=ART / "ppo_budget_unit.json",
    )
    # 证据:resolved 参数全集(与 manifest 中字段一致)
    (ART / "resolved_ppo_parameters.json").write_text(
        json.dumps(resolved, indent=2, ensure_ascii=False)
    )
    assert not any(
        v != v for v in record.values() if isinstance(v, float)
    ), "记录中出现 NaN"
    assert math.isfinite(record["rounded_budget"])
