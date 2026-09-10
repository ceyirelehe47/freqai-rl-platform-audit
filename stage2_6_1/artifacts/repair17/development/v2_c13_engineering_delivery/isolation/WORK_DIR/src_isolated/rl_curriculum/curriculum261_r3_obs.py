"""阶段 2.6.1 Repair R3:预处理感知的 observation 与 reference 路径(WP-C/D)。

WP-C(observation wrapper):
- scaled_episode_frame:episode 的 8 个生产特征列替换为 frozen
  preprocessor 的 transform 输出(OHLCV 价格列保留 raw);
- r3_observation_schema:正式 R3 ObservationSchema(normalization 字段
  绑定 pipeline hash —— 使用 observation_schema.py 现成的合同载体);
- validate_observation_containment:production MinMaxScaler 不 clip,
  observation_space = Box(-10, 10)(生产 env 冻结 layout)的 containment
  以实测验证(fit/calibration/holdout/final/stress 全 corpus);
- position slot 由 env._observation 追加(第 9 维,不缩放,合同不变)。

WP-D(reference-aware transform,方式 B —— inverse-transform wrapper):
- PreprocessingAwarePolicy:reference/baseline 只接收
  (transformed policy-visible observation, frozen preprocessor state),
  先把前 8 维仿射逆变换回 raw 特征语义,再运行原 reference policy;
  不访问 raw env side channel / latent / future / episode 元数据;
- reference_equivalence_check:同一 episode 上 raw reference 与
  preprocessing-aware reference 逐 bar action 相等、net return 相等
  (C1/C2/C3 全部策略对)。
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from rl_curriculum.curriculum261_production_obs import (
    PRODUCTION_FEATURE_COLUMNS,
    _PRODUCTION_FEATURE_HISTORY,
)
from rl_curriculum.curriculum261_r3_preprocessing import (
    OBSERVATION_SPACE_SEMANTICS,
    POSITION_SLOT_SEMANTICS,
    ROUTE_C_FEATURE_PREPROCESSING_VERSION,
    RouteCPreprocessor,
)
from rl_curriculum.observation_schema import FeatureSpec, ObservationSchema
from rl_curriculum.policy_api import ObservableBaselinePolicy

#: R3 课程级 observation schema 版本(区别于 R2 的
#: route-c-production-obs-v1:数值经过 RouteCFeaturePreprocessing-v1)。
R3_OBS_SCHEMA_VERSION = "route-c-production-obs-r3-v1"

#: 归一化语义名(写入 schema normalization_method 与每个 feature)。
R3_NORMALIZATION_METHOD = "vendor-freqai-minmax-(-1,1)-v1"

#: position slot 之外不需要 wrap 的无输入基线。
_UNSCALED_BASELINES = ("always_flat", "always_long")


def scaled_episode_frame(episode_df: pd.DataFrame,
                         preproc: RouteCPreprocessor) -> pd.DataFrame:
    """episode 特征列替换为 scaled 值(prices 保留 raw;dim 语义不变)。"""
    return preproc.transform_episode_df(episode_df)


def r3_observation_schema(preproc: RouteCPreprocessor) -> ObservationSchema:
    """R3 正式 observation schema(normalization 绑定 pipeline state)。"""
    feats = tuple(
        FeatureSpec(
            name=name,
            available_at="close_of_bar_t",
            max_history_bars=_PRODUCTION_FEATURE_HISTORY[name],
            signal_group="production",
            normalization=R3_NORMALIZATION_METHOD,
        )
        for name in PRODUCTION_FEATURE_COLUMNS
    )
    return ObservationSchema(
        schema_version=R3_OBS_SCHEMA_VERSION,
        features=feats,
        window_size=1,
        dtype="float32",
        includes_cost_context=False,
        normalization_method=R3_NORMALIZATION_METHOD,
        normalization_pipeline_hash=preproc.state_hash(),
    )


def r3_observation_identity(preproc: RouteCPreprocessor) -> dict[str, Any]:
    """R3 observation 完整身份(schema + preprocessing 合同身份)。"""
    schema = r3_observation_schema(preproc)
    return {
        "schema_version": R3_OBS_SCHEMA_VERSION,
        "schema_hash": schema.schema_hash(),
        "normalization_method": R3_NORMALIZATION_METHOD,
        "preprocessing_contract": ROUTE_C_FEATURE_PREPROCESSING_VERSION,
        "preprocessing_state_hash": preproc.state_hash(),
        "feature_columns": list(PRODUCTION_FEATURE_COLUMNS),
        "observation_dim": 9,
        "position_slot": POSITION_SLOT_SEMANTICS,
        "observation_space": OBSERVATION_SPACE_SEMANTICS,
    }


def validate_observation_containment(
    episodes_scaled_dfs: list[pd.DataFrame],
    prices_frames: list[pd.DataFrame],
    eval_cfg: Any,
    seeds: list[int],
    context: str = "containment",
) -> dict[str, Any]:
    """observation_space.contains(observation) 全 corpus 实测验证。

    对每个 scaled episode 构造 AlignedLongFlatEnv(与评估路径一致),
    reset + 全 step 收集 observation,断言:dim=9、float32、finite、
    |x| < 10(position 槽位恒 ∈ {0,1} 且为最后一维)。
    """
    from rl_platform.env import AlignedLongFlatEnv

    n_obs = 0
    max_abs = 0.0
    position_ok = True
    violations: list[str] = []
    for df, prices, seed in zip(
            episodes_scaled_dfs, prices_frames, seeds):
        features = df[list(PRODUCTION_FEATURE_COLUMNS)]
        env = AlignedLongFlatEnv(
            features=features, prices=prices[list(
                ("open", "close"))] if "high" not in prices.columns
            else prices[["open", "high", "low", "close"]],
            fee=eval_cfg.fee, slippage_bps=eval_cfg.slippage_bps,
            initial_cash=eval_cfg.initial_cash,
            reward_scale=eval_cfg.reward_scale,
            window_size=eval_cfg.window_size,
            price_tick=eval_cfg.price_tick,
            execution_mode="market_open_causal",
        )
        obs, _ = env.reset(seed=seed)
        while True:
            n_obs += 1
            if obs.shape != (9,) or str(obs.dtype) != "float32":
                violations.append(
                    f"{context}: obs shape/dtype {obs.shape}/{obs.dtype}")
                break
            if not np.isfinite(obs).all():
                violations.append(f"{context}: obs 含非有限值")
                break
            if float(np.max(np.abs(obs))) >= 10.0:
                violations.append(
                    f"{context}: |obs|={float(np.max(np.abs(obs)))} 超出 "
                    f"Box(-10,10)")
                break
            if float(obs[-1]) not in (0.0, 1.0):
                position_ok = False
                violations.append(f"{context}: position 槽位非 0/1")
                break
            max_abs = max(max_abs, float(np.max(np.abs(obs))))
            obs, _, terminated, truncated, _ = env.step(0)
            if terminated or truncated:
                break
    return {
        "format": "cur261-r3-observation-containment-v1",
        "n_observations": n_obs,
        "max_abs_value": max_abs,
        "bounds": [-10.0, 10.0],
        "clip_by_pipeline": False,
        "position_slot_valid": position_ok,
        "violations": violations[:20],
        "pass": bool(not violations and position_ok and n_obs > 0),
    }


class PreprocessingAwarePolicy(ObservableBaselinePolicy):
    """方式 B inverse-transform wrapper(§13)。

    包装 raw 语义的 reference/baseline policy:
    act(transformed_obs) = base.act(inverse(transformed_obs[:8])
    ++ [position])。仅依赖 scaled observation 与 frozen preprocessor
    state;不触碰 raw env side channel / latent truth / future data /
    episode metadata / generator hidden state。
    """

    def __init__(self, base: ObservableBaselinePolicy,
                 preproc: RouteCPreprocessor) -> None:
        super().__init__()
        self.base = base
        self.preproc = preproc
        self.name = f"{base.name}+r3inv"

    def bind_observation_schema(self, schema: ObservationSchema) -> None:
        # base 读取 raw 语义槽位;R3 schema 的特征槽位序与 raw schema
        # 完全一致(PRODUCTION_FEATURE_COLUMNS 同序),绑定任一均可。
        super().bind_observation_schema(schema)
        self.base.bind_observation_schema(schema)

    def episode_instance(self, episode_seed: int) -> ObservableBaselinePolicy:
        inst = self.base.episode_instance(episode_seed)
        if inst is self.base:
            return self
        wrapped = PreprocessingAwarePolicy(inst, self.preproc)
        wrapped.bind_observation_schema(self.schema)
        return wrapped

    def reset_episode(self) -> None:
        self.base.reset_episode()

    def act(self, observation: np.ndarray) -> int:
        obs = np.asarray(observation)
        raw_feats = self.preproc.inverse_features(
            obs[: len(PRODUCTION_FEATURE_COLUMNS)].astype(
                np.float64).reshape(1, -1))[0]
        raw_obs = np.concatenate([
            raw_feats, [float(obs[-1])]]).astype(np.float32)
        return int(self.base.act(raw_obs))

    # 诊断/等价测试用:直接读取 raw 语义槽位(经同一逆变换)。
    def read(self, observation: np.ndarray, feature_name: str) -> float:
        obs = np.asarray(observation)
        raw_feats = self.preproc.inverse_features(
            obs[: len(PRODUCTION_FEATURE_COLUMNS)].astype(
                np.float64).reshape(1, -1))[0]
        idx = self.slot(feature_name)
        return float(raw_feats[idx])


def wrap_policy_set(policies: dict[str, Any],
                    preproc: RouteCPreprocessor) -> dict[str, Any]:
    """把 observation-aware 策略包装为 preprocessing-aware;无输入基线
    (always_flat/always_long)原样保留。"""
    out: dict[str, Any] = {}
    for name, pol in policies.items():
        if name in _UNSCALED_BASELINES or not isinstance(
                pol, ObservableBaselinePolicy):
            out[name] = pol
        else:
            wrapped = PreprocessingAwarePolicy(pol, preproc)
            out[name] = wrapped
    return out


def scaled_episode(episode: Any, preproc: RouteCPreprocessor) -> Any:
    """episode 的 df 特征列替换为 scaled 值(其余字段/spec 不变)。

    返回的 episode 可直接走 evaluator.run_observation_episode / _build_env
    —— env 收到的 features 即 transform 后矩阵(与 production 一致)。
    """
    import dataclasses

    return dataclasses.replace(
        episode, df=scaled_episode_frame(episode.df, preproc))


def reference_equivalence_check(
    episode: Any, family: str, rung_params: dict[str, Any],
    thresholds: dict[str, Any], preproc: RouteCPreprocessor,
    eval_cfg: Any, raw_schema: ObservationSchema,
) -> dict[str, Any]:
    """§13 强制等价:raw reference == preprocessing-aware reference。

    同一 episode:
    - raw 路径:原 policy + raw episode + raw schema;
    - scaled 路径:wrapped policy + scaled episode + r3 schema;
    断言全部 observation-aware 策略(含 reference 与 family 基线)
    逐 bar action 相等、net return 相等(fail closed)。
    """
    from rl_curriculum.curriculum261_qualification import build_policy_set
    from rl_curriculum.evaluator import run_policy_episode

    raw_set = build_policy_set(family, rung_params, thresholds)
    scaled_set = wrap_policy_set(raw_set, preproc)
    r3_schema = r3_observation_schema(preproc)
    scaled_ep = scaled_episode(episode, preproc)
    report: dict[str, Any] = {}
    all_ok = True
    for name, raw_pol in raw_set.items():
        if name in _UNSCALED_BASELINES:
            continue
        r_raw = run_policy_episode(
            raw_pol, episode, eval_cfg, raw_schema, return_actions=True)
        r_scl = run_policy_episode(
            scaled_set[name], scaled_ep, eval_cfg, r3_schema,
            return_actions=True)
        actions_equal = bool(
            list(r_raw[1]) == list(r_scl[1]))
        return_equal = bool(
            float(r_raw[0].net_return) == float(r_scl[0].net_return))
        ok = actions_equal and return_equal
        all_ok = all_ok and ok
        report[name] = {
            "actions_equal": actions_equal,
            "net_return_equal": return_equal,
            "n_decisions": len(r_raw[1]),
            "raw_net_return": float(r_raw[0].net_return),
            "scaled_net_return": float(r_scl[0].net_return),
        }
    return {
        "format": "cur261-r3-reference-equivalence-v1",
        "family": family,
        "episode_seed": int(episode.spec.seed),
        "policies": report,
        "pass": bool(all_ok),
    }
