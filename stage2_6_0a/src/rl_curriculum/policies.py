"""阶段 2.6.0a 工作包 A:基线策略库 / Oracle / SB3 候选适配(obs-only)。

本模块的每个策略都只通过 observation(或 Oracle 的独立当前行上下文)
决策,不存在 ActContext:完整 Episode df、n_rows、tick、hidden、
future_returns 不再出现在任何正式接口中。故意作弊探针(StepCounter /
AbsolutePrice / Periodic / FutureLeak / NullOvertrader)已移至
rl_curriculum.probes,实现独立的 TestOnlyProbePolicy 协议,正式评估器
对其拒绝执行(assert_formal_candidate)。

合理的课程资格关系应为:
Oracle > 可观察规则策略 > trivial / random 策略。
"""

from __future__ import annotations

import numpy as np

from rl_curriculum.observation_schema import ObservationSchema
from rl_curriculum.policy_api import (
    CandidatePolicy,
    ObservableBaselinePolicy,
    OracleActContext,
    OraclePolicy,
)


# ------------------------------------------------------------------ trivial
class AlwaysFlatPolicy(ObservableBaselinePolicy):
    name = "always_flat"

    def reset_episode(self, derived_seed: int) -> None:
        return None

    def act(self, observation: np.ndarray) -> int:
        return 0


class AlwaysLongPolicy(ObservableBaselinePolicy):
    name = "always_long"

    def reset_episode(self, derived_seed: int) -> None:
        return None

    def act(self, observation: np.ndarray) -> int:
        return 1


class RandomPolicy(ObservableBaselinePolicy):
    """随机基线:每个 Episode 从 derived_seed 派生独立 RNG。

    不受上一 Episode 调用次数影响、不受 Episode 输入顺序影响、
    重复评估完全一致(derived_seed 由 EpisodeSpec 规范化哈希派生)。
    """

    name = "random"

    def __init__(self) -> None:
        self._rng = np.random.default_rng(0)

    def reset_episode(self, derived_seed: int) -> None:
        self._rng = np.random.default_rng(int(derived_seed))

    def act(self, observation: np.ndarray) -> int:
        return int(self._rng.integers(0, 2))


class PeriodicTogglePolicy(ObservableBaselinePolicy):
    """周期切换基线(合法基线语义; Episode 计数器在 reset 清零)。"""

    name = "periodic_toggle"

    def __init__(self, period: int = 8):
        if period < 1:
            raise ValueError(f"period 必须 >= 1,收到 {period}")
        self.period = int(period)
        self._step = 0

    def reset_episode(self, derived_seed: int) -> None:
        self._step = 0

    def act(self, observation: np.ndarray) -> int:
        k = self._step
        self._step += 1
        return int((k // self.period) % 2)


class OneStepGreedyPolicy(ObservableBaselinePolicy):
    """上一根 bar 收益为正即做多(短视贪婪;特征从 observation 槽位读)。"""

    name = "one_step_greedy"

    def reset_episode(self, derived_seed: int) -> None:
        return None

    def act(self, observation: np.ndarray) -> int:
        return int(self.read(observation, "ret_1") > 0.0)


class HighTurnoverPolicy(ObservableBaselinePolicy):
    """每步切换仓位(高频换手基线;当前仓位从 observation 账户槽位读)。"""

    name = "high_turnover"

    def reset_episode(self, derived_seed: int) -> None:
        return None

    def act(self, observation: np.ndarray) -> int:
        return 1 - int(np.asarray(observation)[self.position_slot()])


# ------------------------------------------------------------- 规则 / Oracle
class RuleTrendPolicy(ObservableBaselinePolicy):
    """可观察规则基线:只用模型同样可见的特征槽位(无隐藏状态、无未来)。

    规则:ma_ratio > ma_threshold 且 ret_4 > ret_threshold 时做多。
    阈值在课程章程中冻结,不得依据 PPO 表现调整。
    """

    name = "rule_trend"

    def __init__(self, ma_threshold: float = 0.001, ret_threshold: float = 0.0):
        super().__init__()
        self.ma_threshold = float(ma_threshold)
        self.ret_threshold = float(ret_threshold)

    def reset_episode(self, derived_seed: int) -> None:
        return None

    def act(self, observation: np.ndarray) -> int:
        return int(
            self.read(observation, "ma_ratio") > self.ma_threshold
            and self.read(observation, "ret_4") > self.ret_threshold
        )


class OracleSegmentedDriftPolicy(OraclePolicy):
    """探针 A 的 Oracle:读当前行隐藏 regime 方向(仅课程可解性上限)。"""

    name = "oracle_segmented_drift"

    def reset_episode(self, derived_seed: int) -> None:
        return None

    def act(self, ctx: OracleActContext) -> int:
        return int(ctx.hidden_row.get("regime_direction", 0.0) > 0)


class OracleSmoothLatentDriftPolicy(OraclePolicy):
    """探针 B 的 Oracle:读当前行连续潜在漂移(仅课程可解性上限)。"""

    name = "oracle_smooth_latent_drift"

    def __init__(self, threshold_bps: float = 3.0):
        self.threshold_bps = float(threshold_bps)

    def reset_episode(self, derived_seed: int) -> None:
        return None

    def act(self, ctx: OracleActContext) -> int:
        return int(ctx.hidden_row.get("latent_drift_bps", 0.0) > self.threshold_bps)


# ------------------------------------------------------------- SB3 checkpoint
class SB3CheckpointPolicy(CandidatePolicy):
    """SB3 PPO checkpoint 正式候选适配(observation-only,deterministic)。

    加载即执行 checkpoint 兼容守卫(rl_curriculum.checkpoints):
    - expected_charter_hash 与 expected_observation_schema_hash 为
      必填(调用方无法"忘记传参"而跳过课程/观察绑定校验);
    - sidecar 必须绑定 observation schema(有序特征/shape/window/
      dtype/归一化),不匹配即拒绝加载;
    - act 只接收 observation;shape/dtype 与 schema 不符立即抛错
      (fail closed,绝不吞错继续给分)。
    """

    name = "sb3_checkpoint"

    def __init__(
        self,
        checkpoint_path,
        *,
        expected_charter_hash: str,
        expected_observation_schema_hash: str,
        schema: ObservationSchema | None = None,
        deterministic: bool = True,
        device: str = "cpu",
    ):
        from rl_curriculum.checkpoints import load_guarded_checkpoint

        self.checkpoint_path = str(checkpoint_path)
        self._schema = schema
        self._deterministic = bool(deterministic)
        self.model, self.manifest = load_guarded_checkpoint(
            checkpoint_path,
            expected_charter_hash=expected_charter_hash,
            expected_observation_schema_hash=expected_observation_schema_hash,
        )
        if schema is not None:
            schema.assert_sidecar_binding(
                self.manifest, context=f"sb3:{self.checkpoint_path}")
        self.name = f"sb3:{self.manifest.get('checkpoint_name', self.name)}"

    @property
    def deterministic(self) -> bool:
        return self._deterministic

    def reset_episode(self, derived_seed: int) -> None:
        # 前馈 PPO 无跨 Episode 状态;RNN 候选必须在 reset_episode 清零。
        return None

    def act(self, observation: np.ndarray) -> int:
        obs = np.asarray(observation)
        if self._schema is not None:
            self._schema.assert_observation_array(
                obs, context=f"{self.name} candidate observation")
        action, _ = self.model.predict(
            obs.astype(np.float32).reshape(1, -1),
            deterministic=self._deterministic,
        )
        return int(np.asarray(action).reshape(-1)[0])
