"""阶段 2.6.1 Repair R4:V2 observation schema 与 reference 等价路径。

V2 的 observation 数值与 R3 scaled 路径逐位一致(同一 vendor pipeline
数值),区别在:
- schema 版本(route-c-production-obs-r4-v2)与 normalization 绑定
  V2 的 preprocessor bundle hash(而非仅 state hash);
- 正式 observation space 由外层 RouteCPreprocessingEnvV2 声明
  (feature 无界 + position [0,1]);
- PreprocessingAwarePolicy / wrap_policy_set / scaled_episode /
  reference_equivalence_check 直接复用 R3 实现(数值合同不变),
  本模块只做 V2 适配入口。
"""

from __future__ import annotations

from typing import Any

from rl_curriculum.curriculum261_production_obs import (
    PRODUCTION_FEATURE_COLUMNS,
    _PRODUCTION_FEATURE_HISTORY,
)
from rl_curriculum.curriculum261_r3_obs import (  # noqa: F401  (复用)
    PreprocessingAwarePolicy,
    reference_equivalence_check,
    scaled_episode,
    wrap_policy_set,
)
from rl_curriculum.curriculum261_r4_preprocessing import (
    OBSERVATION_SPACE_SEMANTICS_V2,
    POSITION_SLOT_SEMANTICS_V2,
    ROUTE_C_FEATURE_PREPROCESSING_V2,
    RouteCPreprocessorV2,
)
from rl_curriculum.observation_schema import FeatureSpec, ObservationSchema

R4_OBS_SCHEMA_VERSION = "route-c-production-obs-r4-v2"

R4_NORMALIZATION_METHOD = "vendor-freqai-minmax-(-1,1)-v1"


def _bundle_or_state_hash(preproc: Any) -> str:
    if isinstance(preproc, RouteCPreprocessorV2):
        return preproc.bundle_hash
    return preproc.state_hash()


def r4_observation_schema(preproc: Any) -> ObservationSchema:
    """R4 正式 observation schema(normalization 绑定 bundle hash)。"""
    feats = tuple(
        FeatureSpec(
            name=name,
            available_at="close_of_bar_t",
            max_history_bars=_PRODUCTION_FEATURE_HISTORY[name],
            signal_group="production",
            normalization=R4_NORMALIZATION_METHOD,
        )
        for name in PRODUCTION_FEATURE_COLUMNS
    )
    return ObservationSchema(
        schema_version=R4_OBS_SCHEMA_VERSION,
        features=feats,
        window_size=1,
        dtype="float32",
        includes_cost_context=False,
        normalization_method=R4_NORMALIZATION_METHOD,
        normalization_pipeline_hash=_bundle_or_state_hash(preproc),
    )


def r4_observation_identity(preproc: Any) -> dict[str, Any]:
    """R4 observation 完整身份(schema + V2 preprocessing 身份)。"""
    schema = r4_observation_schema(preproc)
    ident = {
        "schema_version": R4_OBS_SCHEMA_VERSION,
        "schema_hash": schema.schema_hash(),
        "normalization_method": R4_NORMALIZATION_METHOD,
        "preprocessing_contract": ROUTE_C_FEATURE_PREPROCESSING_V2,
        "feature_columns": list(PRODUCTION_FEATURE_COLUMNS),
        "observation_dim": 9,
        "position_slot": POSITION_SLOT_SEMANTICS_V2,
        "observation_space": OBSERVATION_SPACE_SEMANTICS_V2,
        "normalization_pipeline_hash": _bundle_or_state_hash(preproc),
    }
    if isinstance(preproc, RouteCPreprocessorV2):
        ident["preprocessing_identity"] = preproc.identity()
    return ident
