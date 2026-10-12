# -*- coding: utf-8 -*-
"""RouteC_PositionControl 工程域冻结版本常量。

新域全部 ENGINEERING_ONLY;正式资格不能从本域推定。
旧二元域(RouteCEnvCore-v1.0.0)不受任何影响。

R1(2026-10-12)语义变更与版本升级(旧 v1 存档/模型只读,不自动迁移):
- ENV_CORE v2 / EXECUTION v2:开盘偿付/维护保证金检查先于模型动作
  (HOLD 与 REBALANCE 同经济状态一致;非正开盘净值显式经济失败,
  正净值但维护不足走开盘风险平仓);
- OBSERVATION v2:账户特征数值变换(exposure=asinh(x)/4 原始值不截断;
  solvency=asinh(min(s,40))/4;去掉 1e6 占位);原始经济值保留在 info;
- POLICY v2:连续分量改为"截断尾质量并入边界原子"的精确执行映射
  (ε=2^-25 float32 碰撞界,0 单元质量,熵同分布闭式);
- CURRICULUM v2/C123 v2/BANKS v2:噪声律改为方差匹配有界均匀
  (a=√3·σ),C4 四档真实参数化,参考=可观察状态 MDP 精确 DP;
- REWARD/ACTION/LEDGER 语义未变(奖励定义、动作编码、账本不变)。
"""

POSCTL_ENV_CORE_VERSION = "PosctlEnvCore-v2"
POSCTL_LEDGER_VERSION = "TwoSidedLinearLedger-v1"
POSCTL_OBSERVATION_SPEC_VERSION = "PosctlObs-v2"
POSCTL_ACTION_SPEC_VERSION = "HybridHoldRebalanceAction-v1"
POSCTL_REWARD_SPEC_VERSION = "NetLogEquityReward-v2"
POSCTL_EXECUTION_SPEC_VERSION = "MarketOpenCausalLinear-v2"
POSCTL_POLICY_SPEC_VERSION = "HybridAtomBetaPolicy-v2"
POSCTL_REPLAY_SPEC_VERSION = "PosctlReplay-v2"
POSCTL_C4_CURRICULUM_VERSION = "PosctlC4Curriculum-v2"
POSCTL_C123_ADAPTER_VERSION = "PosctlC123TwoSidedAdapter-v2"
POSCTL_SERIES_MODEL_VERSION = "PosctlSeriesCandidates-v2"
POSCTL_BANKS_VERSION = "PosctlEngBanks-v2"
POSCTL_PROFILE_VERSION = "PosctlDevPlan-v2"

# 观察账户特征(exposure/solvency 的数值变换;原始值保留在 info 日志)。
POSCTL_ACCOUNT_FEATURES = ("exposure_asinh4", "solvency_asinh4")

# R1 修复轮资源上限(SCOPE_AND_BUDGET;旧轮 18 格/容量结果不重跑、
# 旧预算违规留档不清零——见上轮 RETURN 与 usage_by_tag)。
POSCTL_R1_BUDGET = {
    "ppo_learn_attempts": 8,       # 主/reviewer/新增测试合计(含失败暖机)
    "ppo_steps_total": 16_384,     # PPO 环境交互步合计
    "ppo_steps_single": 2_048,     # 单次 learn 上限(SB3 取整事前控制)
    "bc_fits": 1,
    "bc_epochs": 20,
    "bc_minibatch_updates": 320,
    "eval_steps": 65_536,          # 无梯度环境评估步
    "gen_calls": 2_560,            # 新工程 bank 生成调用(失败/重复同计)
    "episodes": 512,               # 成功 episode
}
