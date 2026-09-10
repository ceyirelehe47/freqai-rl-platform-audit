"""阶段 2.6.2:PPO candidate 配置预注册与选择规则(运行前锁定)。

- 最多 3 个完整 PPO candidate(§9):全部 PPO + MlpPolicy,只比较
  网络宽度 / 学习率 / 熵系数 / rollout / batch;
- 不做网格搜索 / 贝叶斯优化 / final-eval 调参;staged 与 mixed、
  三族使用完全相同的超参数;
- 不修改 reward scale,不用 reward normalization / VecNormalize;
- rollout 对齐约束:n_steps = 287×k(episode 决策步数 287 的倍数,
  且 bank 预算 = 287 的倍数)——rollout 块边界与 episode 边界对齐,
  total_timesteps 恰好在 bank 最后一个 done 处停止,训练后可断言
  "不跳过/不重复/不越界";
- 选择规则(运行前锁定):主指标 = mean normalized reference-gap
  capture across C1/C2/C3(在 ppo_config_dev_262 评估集上,
  capture 定义见 ppo262_metrics);并列时选熵诊断更健康
  (未坍塌)者;若全部 candidate 无基础学习信号 -> Stage FAIL。
"""

from __future__ import annotations

from typing import Any

#: 决策步数(episode bars 288 - window 1;rollout 对齐的原子单位)
PPO262_DECISION_STEPS = 287

#: 预注册 candidate(运行前写入 config-development plan,不得追加)
PPO262_CANDIDATES: dict[str, dict[str, Any]] = {
    "cand_a_center": {
        "policy": "MlpPolicy",
        "learning_rate": 3e-4,
        "n_steps": 574,            # 287 x 2
        "batch_size": 287,
        "n_epochs": 10,
        "gamma": 0.99,
        "gae_lambda": 0.95,
        "clip_range": 0.2,
        "ent_coef": 0.01,
        "vf_coef": 0.5,
        "max_grad_norm": 0.5,
        "net_arch": [128, 128],
        "activation_fn": "Tanh",
        "device": "cpu",
        "notes": "中心候选:仓库路线 [128,128] + 标准 PPO clipping",
    },
    "cand_b_lowentropy": {
        "policy": "MlpPolicy",
        "learning_rate": 1e-4,
        "n_steps": 574,
        "batch_size": 287,
        "n_epochs": 10,
        "gamma": 0.99,
        "gae_lambda": 0.95,
        "clip_range": 0.2,
        "ent_coef": 0.003,
        "vf_coef": 0.5,
        "max_grad_norm": 0.5,
        "net_arch": [128, 128],
        "activation_fn": "Tanh",
        "device": "cpu",
        "notes": "低熵+低学习率变体(更保守的策略更新)",
    },
    "cand_c_highentropy": {
        "policy": "MlpPolicy",
        "learning_rate": 3e-4,
        "n_steps": 574,
        "batch_size": 287,
        "n_epochs": 10,
        "gamma": 0.99,
        "gae_lambda": 0.95,
        "clip_range": 0.2,
        "ent_coef": 0.02,
        "vf_coef": 0.5,
        "max_grad_norm": 0.5,
        "net_arch": [128, 128],
        "activation_fn": "Tanh",
        "device": "cpu",
        "notes": "高熵探索变体(更强的 exploration 压力)",
    },
}

#: config-development 预算(§10:每 candidate 总计约 <=60k env steps)
PPO262_CONFIG_DEV_EPISODES_PER_FAMILY = 70   # 70 x 287 = 20,090 steps
PPO262_CONFIG_DEV_FAMILIES = ("c1_opportunity", "c2_context", "c3_cost")
PPO262_CONFIG_DEV_RUNG = "D1"
PPO262_CONFIG_DEV_TOTAL_STEPS = (
    len(PPO262_CONFIG_DEV_FAMILIES)
    * PPO262_CONFIG_DEV_EPISODES_PER_FAMILY * PPO262_DECISION_STEPS)
#: config dev 内部评估集(同 namespace 独立 pair 区间;仅用于选 config)
PPO262_CONFIG_DEV_EVAL_PAIRS_PER_FAMILY = 4
PPO262_CONFIG_DEV_TRAIN_PAIR_BASE = 0
PPO262_CONFIG_DEV_EVAL_PAIR_BASE = 100

#: 选择规则(锁定):主指标 + 并列打破 + 全败语义
PPO262_CONFIG_SELECTION_RULE = {
    "primary_metric": "mean_normalized_reference_gap_capture_c1c2c3",
    "eval_namespace": "ppo_config_dev_262",
    "eval_scope": "C1/C2/C3 各 D1,独立 4-pair 评估集",
    "tie_break": [
        "更高 aggregate capture 胜出",
        "并列(capture 差 < 0.02)时选三族 capture 方差更小者",
        "仍并列时选行为熵未坍塌(评估期 action 多样性 > 0)者",
    ],
    "all_fail_semantics": (
        "若全部 candidate 在 development corpus 上无基础学习信号"
        "(aggregate capture <= 0 且无任何 family capture > 0.05),"
        "Stage 2.6.2 = FAIL,不烧 core 预算"),
}

#: probe 预算预注册(§13;episode 数 = 287 的倍数以对齐 rollout)
PPO262_PROBE_BUDGETS: dict[str, dict[str, int]] = {
    "c1_opportunity": {"D0": 32, "D1": 48, "D2": 64, "D3": 16},   # 160 eps
    "c2_context": {"D0": 24, "D1": 72, "D2": 96, "D3": 48},      # 240 eps
    "c3_cost": {"D0": 24, "D1": 72, "D2": 96, "D3": 48},         # 240 eps
}
#: probe gate(§13):core capture > 0.10 且 intended behavior gap > 0.10
PPO262_PROBE_GATE_CAPTURE = 0.10
PPO262_PROBE_GATE_BEHAVIOR_GAP = 0.10

#: dev evaluation bank(§19:family x rung x 4 pairs x A/B)
PPO262_DEV_EVAL_PAIRS_PER_RUNG = 4

#: final evaluation bank(§20:3 x 4 x 10 pairs x A/B = 240 episodes)
PPO262_FINAL_EVAL_PAIRS_PER_RUNG = 10

#: checkpoint 计划(§18):episode 边界 0 / 160 / 400 / 640
PPO262_CHECKPOINT_EPISODES = (0, 160, 400, 640)


def candidate_digest(name: str) -> str:
    """candidate 配置摘要哈希(plan 绑定用)。"""
    import hashlib
    import json
    payload = json.dumps(
        [name, PPO262_CANDIDATES[name]], sort_keys=True,
        separators=(",", ":"), ensure_ascii=False)
    return "pc-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_ppo(config: dict[str, Any], seed: int, env):
    """按 candidate 配置构造 SB3 PPO(net_arch/activation 显式固定)。"""
    import torch
    from stable_baselines3 import PPO

    act_fn = {"Tanh": torch.nn.Tanh,
              "ReLU": torch.nn.ReLU}[config["activation_fn"]]
    return PPO(
        policy=config["policy"], env=env,
        learning_rate=config["learning_rate"],
        n_steps=config["n_steps"],
        batch_size=config["batch_size"],
        n_epochs=config["n_epochs"],
        gamma=config["gamma"],
        gae_lambda=config["gae_lambda"],
        clip_range=config["clip_range"],
        ent_coef=config["ent_coef"],
        vf_coef=config["vf_coef"],
        max_grad_norm=config["max_grad_norm"],
        policy_kwargs={
            "net_arch": list(config["net_arch"]),
            "activation_fn": act_fn,
        },
        seed=int(seed),
        verbose=0,
        device=config["device"],
    )
