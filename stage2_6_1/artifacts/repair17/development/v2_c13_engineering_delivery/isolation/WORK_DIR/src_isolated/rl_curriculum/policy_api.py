"""阶段 2.6.0a 工作包 A/C + 阶段 2.6.0b 工作包 B:正式策略能力隔离与 Episode 生命周期。

阶段 2.6.0 的单一 ActContext 把完整 df / n_rows / tick / hidden /
future_returns 交给了每一个策略(包括普通候选),使候选在接口层就能
读到隐藏与未来数据。2.6.0a 把评估路径拆为四类互不继承的接口。

阶段 2.6.0b 工作包 B(移除候选 Episode 身份 token):
- reset_episode() 不再接收任何参数。2.6.0a 的
  reset_episode(derived_seed) 会向候选泄漏一个由隐藏 EpisodeSpec
  派生的稳定身份 token——候选可用它区分/识别隐藏试题;
- 正式候选生命周期为 reset_episode() / act(observation) / close():
  reset 只用于清空 RNN 状态/action 历史/缓存,不携带 seed、Episode
  hash、attempt id、pack hash、split、family、params、Episode 长度
  或任何稳定题目身份 token;
- 随机基线的确定性改由 ObservableBaselinePolicy.episode_instance()
  工厂承载:评估器每 Episode 调用 episode_instance(episode_seed)
  构造独立实例(seed 只进入基线通道,永不进入 CandidatePolicy);
  正式候选评估路径对该工厂不可达。

四类接口(互不继承):
1. CandidatePolicy(正式候选,含 SB3 checkpoint):
   reset_episode() / act(observation) / close();
2. ObservableBaselinePolicy(可信规则基线):
   同一冻结 observation + schema 名称->槽位映射 + episode_instance 工厂;
3. OraclePolicy(独立接口与独立上下文):
   act(ctx) 收到 OracleActContext——仅当前时刻隐藏状态行与当前仓位;
4. TestOnlyLeakProbe(独立测试 harness,probes.py)。
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
    """obs-only 策略公共基类:Episode 生命周期 + 只收 observation。

    工作包 B:reset_episode() 无参数——任何 Episode 身份 token
    (seed/hash/id/split/family/params/长度)都不得进入正式策略接口。
    """

    name: str = "obs_only_policy"
    reads_hidden: bool = False

    @abstractmethod
    def reset_episode(self) -> None:
        """Episode 开始:清除一切跨 Episode 状态(RNN/RNG/仓位假设)。

        不接收任何参数:没有 seed、Episode hash、attempt id、pack hash、
        split、family、params、Episode 长度或任何稳定身份 token。
        """

    @abstractmethod
    def act(self, observation: np.ndarray) -> int:
        """单步决策:输入只有 observation(含当前目标仓位槽位)。"""

    def close(self) -> None:  # 可选清理
        return None


class CandidatePolicy(ObservationOnlyPolicy):
    """正式候选模型接口(SB3 checkpoint 适配等)。

    act(observation) -> action ∈ {0, 1};deterministic 标志由评估器
    控制(正式评估默认 deterministic=True)。reset_episode() 无参数:
    候选无法通过 reset 区分或识别隐藏 Episode(工作包 B)。
    """


class ObservableBaselinePolicy(ObservationOnlyPolicy):
    """可信规则基线:同一冻结 observation + schema 槽位映射,无完整 df。

    episode_instance(episode_seed):评估器每 Episode 调用的工厂方法。
    只有基线通道接收 episode_seed(用于随机基线的确定性);默认返回
    self(无状态基线复用同一实例)。正式 CandidatePolicy 上不存在该
    通道——候选永不收到任何 seed。
    """

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

    def episode_instance(self, episode_seed: int) -> "ObservableBaselinePolicy":
        """每 Episode 的基线实例(默认:同一对象;随机基线覆盖)。"""
        return self


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
    def reset_episode(self) -> None: ...

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
    reset_episode() 同样无参数(与正式生命周期一致)。
    """

    name: str = "test_only_probe"
    is_test_only_harness: bool = True

    def reset_episode(self) -> None:  # noqa: B027
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
