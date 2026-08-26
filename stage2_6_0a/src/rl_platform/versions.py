"""阶段 2.6.0 工作包 0:Route C 环境核心规范版本(冻结)。

在完成两项冻结前修整(终端观察仓位归零 / 缺失预测目录致命化)后,
以下版本号整体冻结为 v1.0.0。冻结后不得为课程、生成器或考试的
方便而修改 env.py / ledger.py / market_execution.py / reward 合同;
任何变化必须生成新版本号并使旧 checkpoint 拒绝加载。

版本号用途:
1. 注入实验 config(进入指纹的 config 哈希)与 manifest;
2. 写入 checkpoint sidecar manifest(rl_curriculum.checkpoints);
3. 模型加载时逐项比对(环境/观察/动作版本),不兼容即拒绝。
"""

from __future__ import annotations

# ---- 冻结版本(阶段 2.6.0,2026-08-26) -------------------------------
ENV_CORE_VERSION = "RouteCEnvCore-v1.0.0"
OBSERVATION_SPEC_VERSION = "ObservationSpec-v1"
ACTION_SPEC_VERSION = "BinaryLongFlatAction-v1"
REWARD_SPEC_VERSION = "NetLogEquityReward-v1"
EXECUTION_CONTRACT_VERSION = "MarketOpenCausalExecution-v1"
TERMINAL_LIQUIDATION_VERSION = "TerminalLiquidation-v1"

# 进入 config(freqai.route_c.*)与 execution_contract manifest 的键名
SPEC_VERSION_KEYS = {
    "env_core_version": ENV_CORE_VERSION,
    "observation_spec_version": OBSERVATION_SPEC_VERSION,
    "action_spec_version": ACTION_SPEC_VERSION,
    "reward_spec_version": REWARD_SPEC_VERSION,
    "execution_contract_version": EXECUTION_CONTRACT_VERSION,
    "terminal_liquidation_version": TERMINAL_LIQUIDATION_VERSION,
}

# checkpoint sidecar 必须携带的环境侧版本(加载守卫逐项检查)
CHECKPOINT_REQUIRED_VERSIONS = {
    "env_core_version": ENV_CORE_VERSION,
    "observation_spec_version": OBSERVATION_SPEC_VERSION,
    "action_spec_version": ACTION_SPEC_VERSION,
    "reward_spec_version": REWARD_SPEC_VERSION,
    "execution_contract_version": EXECUTION_CONTRACT_VERSION,
    "terminal_liquidation_version": TERMINAL_LIQUIDATION_VERSION,
}


def spec_versions() -> dict[str, str]:
    """返回冻结版本字典的副本(manifest / 指纹注入用)。"""
    return dict(SPEC_VERSION_KEYS)


class SpecVersionMismatchError(RuntimeError):
    """checkpoint 携带的规范版本与当前冻结版本不兼容(fail closed)。"""


def assert_versions_compatible(
    stored: dict[str, str] | None,
    required: dict[str, str] | None = None,
    *,
    context: str = "checkpoint",
) -> None:
    """逐项比对版本;缺失或不匹配立即抛错,绝不勉强恢复。

    required 缺省取 CHECKPOINT_REQUIRED_VERSIONS。stored 中多出的键
    (如课程章程哈希)不参与本检查。
    """
    if required is None:
        required = CHECKPOINT_REQUIRED_VERSIONS
    if not isinstance(stored, dict):
        raise SpecVersionMismatchError(
            f"{context}:未携带规范版本元数据,拒绝加载(无法证明兼容)"
        )
    problems: list[str] = []
    for key, expected in required.items():
        actual = stored.get(key)
        if actual is None:
            problems.append(f"缺失 {key}(期望 {expected})")
        elif actual != expected:
            problems.append(f"{key}:checkpoint={actual} 当前冻结={expected}")
    if problems:
        raise SpecVersionMismatchError(
            f"{context}:规范版本不兼容 -> " + "; ".join(problems)
        )
