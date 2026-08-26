"""阶段 2.6.0a 工作包 A/C:正式策略能力隔离与 Episode 生命周期。

阶段 2.6.0 的单一 ActContext 把完整 df / n_rows / tick / hidden /
future_returns 交给了每一个策略(包括普通候选),使候选在接口层就能
读到隐藏与未来数据。本模块把评估路径拆为四类互不继承的接口:

1. CandidatePolicy(正式候选,含 SB3 checkpoint):
   reset_episode(derived_seed) / act(observation) / close();
   只能看到固定 shape 的 observation(当前仓位已在 observation 内),
   看不到 DataFrame、tick、Episode 总长度、seed、split、family、
   params、hidden、future_returns、OHLC、考试类型、剩余时间。

2. ObservableBaselinePolicy(可信规则基线):
   与模型相同的冻结 observation + schema 提供的名称->索引映射;
   不读完整 df;规则所需特征从 observation 对应槽位读取。

3. OraclePolicy(独立接口与独立上下文):
   act(ctx) 收到 OracleActContext——仅当前时刻的隐藏状态行与当前
   实际仓位;不得访问未来隐藏状态或完整未来收益。

4. TestOnlyLeakProbe(独立测试 harness,probes.py):
   FutureLeakProbe / StepCounter 等作弊探针必须实现本协议;
   不得实现或继承 CandidatePolicy;正式候选评估器对 TestOnlyProbePolicy
   一律拒绝(is_test_only_harness 标记 + 类型双检)。

Episode 生命周期(工作包 C):每个 Episode 开始时评估器调用
reset_episode(derived_seed)(derived_seed 由 EpisodeSpec 规范化哈希
派生,与输入顺序无关);随机基线从该种子派生独立 RNG,重复评估完全
一致;策略不得跨 Episode 遗留 hidden state / RNG / 仓位假设 / 动作
历史(RNN 状态必须在 reset_episode 中显式清零)。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Mapping

import numpy as np

from rl_curriculum.observation_schema import ObservationSchema


class CandidateObservationError(RuntimeError):
    """候选收到与 schema 不符的 observation(fail closed,不吞错给分)。"""


class FormalPolicyRejected(RuntimeError):
    """测试专用探针/不合规对象进入正式评估路径。"""


# ------------------------------------------------------------------ 生命周期
class ObservationOnlyPolicy(ABC):
    """obs-only 策略公共基类:Episode 生命周期 + 只收 observation。"""

    name: str = "obs_only_policy"
    reads_hidden: bool = False

    @abstractmethod
    def reset_episode(self, derived_seed: int) -> None:
        """Episode 开始:清除一切跨 Episode 状态(RNN/RNG/仓位假设)。"""

    @abstractmethod
    def act(self, observation: np.ndarray) -> int:
        """单步决策:输入只有 observation(含当前目标仓位槽位)。"""

    def close(self) -> None:  # 可选清理
        return None


class CandidatePolicy(ObservationOnlyPolicy):
    """正式候选模型接口(SB3 checkpoint 适配等)。

    act(observation) -> action ∈ {0, 1};deterministic 标志由评估器
    控制(正式评估默认 deterministic=True)。
    """


class ObservableBaselinePolicy(ObservationOnlyPolicy):
    """可信规则基线:同一冻结 observation + schema 槽位映射,无完整 df。"""

    def __init__(self) -> None:
        self._schema: ObservationSchema | None = None

    def bind_observation_schema(self, schema: ObservationSchema) -> None:
        """评估器注入 schema(提供名称->索引映射;不注入 df)。"""
        self._schema = schema

    @property
    def schema(self) -> ObservationSchema:
        if self._schema is None:
            raise RuntimeError(
                f"{type(self).__name__} 未绑定 observation schema"
                f"(评估器必须先调用 bind_observation_schema)")
        return self._schema

    def slot(self, feature_name: str) -> int:
        """规则特征名 -> observation 槽位索引。"""
        return self.schema.feature_index(feature_name)

    def position_slot(self) -> int:
        """当前目标仓位槽位(observation 尾部)。"""
        return self.schema.account_slot_index("target_position")

    def read(self, observation: np.ndarray, feature_name: str) -> float:
        return float(np.asarray(observation)[self.slot(feature_name)])


# ------------------------------------------------------------------ Oracle
class OracleActContext:
    """Oracle 独立上下文:仅当前时刻隐藏状态行 + 当前实际仓位。

    不得包含:未来隐藏状态、完整未来收益、Episode df、n_rows、
    split/family/params、考试类型。
    """

    __slots__ = ("tick", "position", "_hidden_row")

    def __init__(self, tick: int, position: int,
                 hidden_row: Mapping[str, float]) -> None:
        self.tick = int(tick)
        self.position = int(position)
        self._hidden_row = dict(hidden_row)

    @property
    def hidden_row(self) -> dict[str, float]:
        return dict(self._hidden_row)


class OraclePolicy(ABC):
    """Oracle 接口(课程可解性上限;独立于候选评估路径)。"""

    name: str = "oracle"
    reads_hidden: bool = True

    @abstractmethod
    def reset_episode(self, derived_seed: int) -> None: ...

    @abstractmethod
    def act(self, ctx: OracleActContext) -> int: ...

    def close(self) -> None:
        return None


# ------------------------------------------------------------------ 探针协议
class TestOnlyProbePolicy:
    """测试专用作弊探针协议(独立 harness;绝不进入正式候选接口)。

    注意:本类不是 CandidatePolicy/ObservableBaselinePolicy 的子类,
    act 签名为 act(observation, harness_ctx)(双参),与正式接口不同;
    正式评估器见 is_test_only_harness=True 或本类型直接拒绝。
    """

    name: str = "test_only_probe"
    is_test_only_harness: bool = True

    def reset_episode(self, derived_seed: int) -> None:  # noqa: B027
        return None

    def act(self, observation: np.ndarray, harness_ctx: Any) -> int:
        raise NotImplementedError

    def close(self) -> None:  # noqa: B027
        return None


def assert_formal_candidate(policy: Any) -> None:
    """正式评估入口守卫:拒绝测试探针与非 obs-only 对象。"""
    if getattr(policy, "is_test_only_harness", False):
        raise FormalPolicyRejected(
            f"{type(policy).__name__} 是测试专用探针(TestOnlyProbePolicy),"
            f"不得进入正式候选评估路径")
    if isinstance(policy, TestOnlyProbePolicy):
        raise FormalPolicyRejected(
            f"{type(policy).__name__} 实现 TestOnlyProbePolicy 协议,"
            f"正式评估器拒绝执行")
    if not isinstance(policy, ObservationOnlyPolicy):
        raise FormalPolicyRejected(
            f"{type(policy).__name__} 不是 ObservationOnlyPolicy"
            f"(CandidatePolicy/ObservableBaselinePolicy),正式评估器拒绝执行")
