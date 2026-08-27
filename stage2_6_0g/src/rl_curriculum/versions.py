"""rl_curriculum 版本来源:环境核心冻结版本 re-export + 基础设施自身版本。"""

from __future__ import annotations

from rl_platform.versions import (  # noqa: F401
    ACTION_SPEC_VERSION,
    CHECKPOINT_REQUIRED_VERSIONS,
    ENV_CORE_VERSION,
    EXECUTION_CONTRACT_VERSION,
    OBSERVATION_SPEC_VERSION,
    REWARD_SPEC_VERSION,
    SPEC_VERSION_KEYS,
    TERMINAL_LIQUIDATION_VERSION,
    SpecVersionMismatchError,
    assert_versions_compatible,
    spec_versions,
)

# 课程/审计基础设施自身版本(评估代码版本的一部分;阶段 2.6.0c)
CURRICULUM_INFRA_VERSION = "rl-curriculum-stage2_6_0c-v1"
