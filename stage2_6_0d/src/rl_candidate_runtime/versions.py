"""冻结环境核心规范版本(自包含副本,阶段 2.6.0b)。

最小候选运行时不得导入 rl_platform(那会把环境核心源码挂进沙箱),
因此此处保存冻结版本常量的副本。测试(tests/route_c_stage2_6_0b)
断言本副本与 rl_platform.versions 逐项相等:环境核心升级时副本必须
同步,否则 worker 拒绝加载旧绑定。
"""

ENV_CORE_VERSION = "RouteCEnvCore-v1.0.0"
OBSERVATION_SPEC_VERSION = "ObservationSpec-v1"
ACTION_SPEC_VERSION = "BinaryLongFlatAction-v1"
REWARD_SPEC_VERSION = "NetLogEquityReward-v1"
EXECUTION_CONTRACT_VERSION = "MarketOpenCausalExecution-v1"
TERMINAL_LIQUIDATION_VERSION = "TerminalLiquidation-v1"

CHECKPOINT_REQUIRED_VERSIONS = {
    "env_core_version": ENV_CORE_VERSION,
    "observation_spec_version": OBSERVATION_SPEC_VERSION,
    "action_spec_version": ACTION_SPEC_VERSION,
    "reward_spec_version": REWARD_SPEC_VERSION,
    "execution_contract_version": EXECUTION_CONTRACT_VERSION,
    "terminal_liquidation_version": TERMINAL_LIQUIDATION_VERSION,
}
