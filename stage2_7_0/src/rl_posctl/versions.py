# -*- coding: utf-8 -*-
"""RouteC_PositionControl_IntegratedUpgrade_v1 工程域冻结版本常量。

新域全部 ENGINEERING_ONLY;正式资格不能从本域推定。
旧二元域(RouteCEnvCore-v1.0.0)不受任何影响。
"""

POSCTL_ENV_CORE_VERSION = "PosctlEnvCore-v1"
POSCTL_LEDGER_VERSION = "TwoSidedLinearLedger-v1"
POSCTL_OBSERVATION_SPEC_VERSION = "PosctlObs-v1"
POSCTL_ACTION_SPEC_VERSION = "HybridHoldRebalanceAction-v1"
POSCTL_REWARD_SPEC_VERSION = "NetLogEquityReward-v2"
POSCTL_EXECUTION_SPEC_VERSION = "MarketOpenCausalLinear-v1"
POSCTL_POLICY_SPEC_VERSION = "HybridAtomBetaPolicy-v1"
POSCTL_REPLAY_SPEC_VERSION = "PosctlReplay-v1"
POSCTL_C4_CURRICULUM_VERSION = "PosctlC4Curriculum-v1"
POSCTL_C123_ADAPTER_VERSION = "PosctlC123TwoSidedAdapter-v1"
POSCTL_SERIES_MODEL_VERSION = "PosctlSeriesCandidates-v1"
POSCTL_BANKS_VERSION = "PosctlEngBanks-v1"
POSCTL_PROFILE_VERSION = "PosctlDevPlan-v1"

# 新观察账户特征(exposure_ratio, solvency_ratio)替代旧单仓位槽;
# 输入维数不再假定为 9,一律按实际观察面统计。
POSCTL_ACCOUNT_FEATURES = ("exposure_ratio", "solvency_ratio")
