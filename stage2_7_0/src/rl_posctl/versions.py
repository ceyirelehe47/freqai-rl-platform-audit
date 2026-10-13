# -*- coding: utf-8 -*-
"""RouteC_PositionControl 工程域冻结版本常量。

新域全部 ENGINEERING_ONLY;正式资格不能从本域推定。
旧二元域(RouteCEnvCore-v1.0.0)不受任何影响。

R1(2026-10-12)语义变更与版本升级(旧 v1 存档/模型只读,不自动迁移):
- ENV_CORE v2 / EXECUTION v2:开盘偿付/维护保证金检查先于模型动作
  (HOLD 与 REBALANCE 对同经济状态一致;非正开盘净值显式经济失败,
  正净值但维护不足走开盘风险平仓);
- OBSERVATION v2:账户特征数值变换(exposure=asinh(x)/4 原始值不截断;
  solvency=asinh(min(s,40))/4;去掉 1e6 占位);原始经济值保留在 info;
- POLICY v2:连续分量改为"截断尾质量并入边界原子"的精确执行映射
  (ε=2^-25 float32 碰撞界,0 单元质量,熵同分布闭式);
- CURRICULUM v2/C123 v2/BANKS v2:噪声律改为方差匹配有界均匀
  (a=√3·σ),C4 四档真实参数化,参考=可观察状态 MDP 精确 DP;
- REWARD/ACTION/LEDGER 语义未变(奖励定义、动作编码、账本不变)。

R2(2026-10-13,FiniteRepair R2;旧 v2 存档/模型只读,不自动迁移):
- ENV_CORE v3 / EXECUTION v3:开盘风险平仓**扣费后**偿付复查——强制
  风险成交使净值≤0 时统一经济失败终态(保全已发生成交/费用,不再执行
  模型动作;HOLD/清仓/正负目标一致;旧 v2 该分支为未定义崩溃)。
  失败 phase 细分(open/open_risk_flatten/funding/close_risk_flatten/
  terminal_liquidation/post_execution,归因首个不可偿付事件)。
- CURRICULUM v3:参考递推改为**真实账户状态转移**——固定数量 HOLD
  撤销"保持 w 列"假设:w_next = w(1+r)/(1+w·r);扣费后口径调仓费、
  终端清算费、维持保证金强制平仓与真实账本/env 一致(数值 V 插值 +
  Gauss-Legendre 求积;网格/节点/收敛误差显式声明)。41 点动作网格 =
  模型动作集限制,**不称连续最优上界**;撤销 v2"精确 DP"措辞。
- BANKS v3:生成额度绑定任务共享账本(TaskLedger 先预约后生成;
  同 seed 重建计生成调用);QuotaLedger 降级为来源日志。
- 评分:资金费现金流符号修正(净成本 = 费用 − 资金费现金流,收到
  资金费允许抵扣),见 evalreport;
  REWARD/ACTION/LEDGER/OBSERVATION/POLICY 语义不变。
R3(2026-10-13,FiniteRepair R3;不改任何经济/课程科学参数):
- 预算/日志/参考适用性/封包四工程面修复(budget/banks/runlog/
  curriculum 缓存与细化校验/打包器),语义详见各模块;
- R3 任务账本面见 POSCTL_R3_BUDGET(与 R1/R2 分离;R2 账本只读)。
"""

POSCTL_ENV_CORE_VERSION = "PosctlEnvCore-v3"
POSCTL_LEDGER_VERSION = "TwoSidedLinearLedger-v1"
POSCTL_OBSERVATION_SPEC_VERSION = "PosctlObs-v2"
POSCTL_ACTION_SPEC_VERSION = "HybridHoldRebalanceAction-v1"
POSCTL_REWARD_SPEC_VERSION = "NetLogEquityReward-v2"
POSCTL_EXECUTION_SPEC_VERSION = "MarketOpenCausalLinear-v3"
POSCTL_POLICY_SPEC_VERSION = "HybridAtomBetaPolicy-v2"
POSCTL_REPLAY_SPEC_VERSION = "PosctlReplay-v2"
POSCTL_C4_CURRICULUM_VERSION = "PosctlC4Curriculum-v3"
POSCTL_C123_ADAPTER_VERSION = "PosctlC123TwoSidedAdapter-v2"
POSCTL_SERIES_MODEL_VERSION = "PosctlSeriesCandidates-v2"
POSCTL_BANKS_VERSION = "PosctlEngBanks-v3"
POSCTL_PROFILE_VERSION = "PosctlDevPlan-v3"

# 观察账户特征(exposure/solvency 的数值变换;原始值保留在 info 日志)。
POSCTL_ACCOUNT_FEATURES = ("exposure_asinh4", "solvency_asinh4")

# R1 修复轮资源上限(SCOPE_AND_BUDGET;旧轮 18 格/容量结果不重跑、
# 旧预算违规留档不清零——见上轮 RETURN 与 usage_by_tag)。
# R2 起新入口不得再引用本面(R1 账本已耗尽超限,读到应拒绝)。
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

# R2 有限正确性复验预算面(FiniteRepair R2 SCOPE_AND_BUDGET;与 R1 面
# 完全分离:R2 账本由任务身份显式创建,R1 账本及其事故原字节不动)。
# 分项各自生效不可挪额;synthetic_total 为 ppo_steps+eval_steps 派生
# 总项(TaskLedger.reserve 机械复算,与任务预算一一对应)。
POSCTL_R2_BUDGET = {
    "ppo_learn_attempts": 8,       # 真实 PPO learn 尝试合计(含原 16 步单测)
    "ppo_steps_total": 1_024,      # 真 PPO 接口单测环境步合计
    "ppo_steps_single": 128,       # 单次 learn 实际 rollout 步上限
    "bc_fits": 0,                  # R2 不重训 BC(复用已有标签/模型证据)
    "bc_epochs": 0,
    "bc_minibatch_updates": 0,
    "eval_steps": 32_768,          # 无梯度 env 交互(边界/重放/受影响单测/reviewer)
    "gen_calls": 2_048,            # 固定工程夹具生成(失败/同 seed 重建均计)
    "episodes": 512,               # 成功 episode
    "synthetic_total": 33_792,     # ppo_steps+eval_steps 合计上限(派生检查)
}

# R2 任务身份(TaskLedger 绑定;防止误开/误续旧账本)。
POSCTL_R2_TASK_ID = "PosCtl_R2_20261012"

# R3 任务身份(FiniteRepair R3;与 R1/R2 面完全分离,历史账本只读)。
POSCTL_R3_TASK_ID = "PosCtl_R3_20261013"

# R3 有限工程修复预算面(本包 SCOPE_AND_BUDGET 表;主 Agent/reviewer/
# 新增测试合并计量,不得另开账本绕开)。分项各自生效不可挪额;
# synthetic_total = ppo_steps+eval_steps 派生总项(4,224)。
POSCTL_R3_BUDGET = {
    "ppo_learn_attempts": 2,       # 新 PPO learn 尝试(含失败)
    "ppo_steps_total": 128,        # 新 PPO 实际环境步合计
    "ppo_steps_single": 64,        # 单次 learn 实际 rollout 步上限
    "bc_fits": 0,                  # 不重新训练
    "bc_epochs": 0,
    "bc_minibatch_updates": 0,
    "eval_steps": 4_096,           # 无梯度 env.step(防回归/接口验证)
    "gen_calls": 64,               # 真工程生成调用(失败/重复同计)
    "episodes": 64,                # 成功 episode(各角色合计)
    "synthetic_total": 4_224,      # ppo_steps+eval_steps(128+4,096)
}

# R4 任务身份(FiniteRepair R4;真实训练/生成为零的收口轮)。
POSCTL_R4_TASK_ID = "PosCtl_R4_20261013"

# R4 面(本包 SCOPE_AND_BUDGET):0 真实 PPO/BC/生成;仅固定手工
# 序列无梯度 env.step ≤128(主 Agent/reviewer/测试共享);派生
# 总项 = ppo+eval = 128。
POSCTL_R4_BUDGET = {
    "ppo_learn_attempts": 0,
    "ppo_steps_total": 0,
    "ppo_steps_single": 0,
    "bc_fits": 0,
    "bc_epochs": 0,
    "bc_minibatch_updates": 0,
    "eval_steps": 128,
    "gen_calls": 0,
    "episodes": 0,
    "synthetic_total": 128,
}

# PSC_P0_v1(渐进式技能课程 P0;2026-10-14;与 R1–R4 面完全分离,
# 历史账本只读不作为余额来源)。
#
# P0 新观察身份(PosctlObsP0Time-v1):旧 6 维(4 市场+2 账户)尾部追加
# 2 时间维(remaining_decisions/128, original_horizon/128)→ 8 维;
# 仅 P0 路径使用,旧 PosctlObs-v2 观察与旧存档拒载规则不变。
POSCTL_PSC_P0_OBS_SPEC_VERSION = "PosctlObsP0Time-v1"
# P0 双臂分布家族身份(互载拒绝开关;A 复用对称 Beta 数学,新身份):
POSCTL_PSC_P0_ARM_A_FAMILY = "P0SymBetaControl-v1"
POSCTL_PSC_P0_ARM_B_FAMILY = "P0AsymBeta-v1"
POSCTL_PSC_P0_DECODE_RULE = "P0CategoryMax-v1"
POSCTL_PSC_P0_TIME_FEATURES = (
    "remaining_decisions_frac128", "original_horizon_frac128")

POSCTL_PSC_P0_TASK_ID = "PSC_P0_v1"

# P0 预算面(SCOPE_AND_BUDGET.md 表逐项;上限非目标,分项独立生效
# 不可挪额;*single = 预约单次上限)。派生总项:
#   ppo_steps_total = main+smoke+techretry = 854,016
#   ppo_learn_total = 6+4+2 = 12
#   economic_total  = ppo_steps_total 分项 + eval_steps = 1,378,304
# optimizer 上界按 rollout 几何:主 128rollout×10epoch×4batch=5,120/格
# (6 格 30,720),smoke 4×20=80,技术复验 2×1,280=2,560,合计 33,360。
POSCTL_PSC_P0_BUDGET = {
    "ppo_steps_main": 786_432,          # 2 臂×3 seed×131,072
    "ppo_steps_main_single": 131_072,
    "ppo_steps_smoke": 2_048,           # 工程 smoke(单次≤512)
    "ppo_steps_smoke_single": 512,
    "ppo_steps_techretry": 65_536,      # 技术复验(单次≤32,768)
    "ppo_steps_techretry_single": 32_768,
    "ppo_learn_main_attempts": 6,
    "ppo_learn_smoke_attempts": 4,
    "ppo_learn_techretry_attempts": 2,
    "ppo_optimizer_steps": 33_360,
    "ppo_optimizer_steps_single": 5_120,
    "eval_steps": 524_288,              # 非 PPO 经济交互(全体合计)
    "gen_calls": 2_048,                 # 真实课程生成调用
    "episodes": 1_024,                  # 物化 episode(镜像端点各计 1)
    "bc_fits": 14,
    "bc_epochs": 8_192,
    "bc_epochs_single": 1_024,
    "bc_minibatch_updates": 8_192,
    "bc_minibatch_updates_single": 1_024,
    "supervised_rows": 8_192,           # 人工/教师监督输入行(表行去重)
    "dist_sample_actions": 1_048_576,   # 非 env 的分布采样行动
    "bootstrap_draws": 1_000_000,
    "evidence_kib": 524_288,            # 新证据与模型文件(512MiB)
    "ppo_steps_total": 854_016,
    "ppo_learn_total": 12,
    "economic_total": 1_378_304,
}
