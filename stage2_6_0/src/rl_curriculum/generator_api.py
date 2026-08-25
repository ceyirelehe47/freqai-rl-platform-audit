"""工作包 C:可插拔人工市场生成器协议。

生成器输出:
- 合法、因果、时间连续的 OHLCV(open[t] == close[t-1]);
- 模型可观察特征(因果滚动,无 NaN);
- 仅用于 Oracle 和评估的隐藏状态(与观察严格隔离);
- 生成器族名称和版本、参数与随机种子、Episode 元信息;
- Null 版本声明;
- 可执行的反事实变换(见 counterfactual.py,通过重生成/成对拼接实现)。

严格隔离:模型观察(df 的特征列)不得包含当前隐藏 regime 标签、
距离 regime 结束步数、下一段方向、Episode 总长度、未来收益、
未来 high/low、生成器内部状态编号、隐藏考试类型编号。
本模块提供自动审计(audit_observation_isolation / verify_episode)。
"""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

# 观察列中禁止出现的隐藏语义模式(字段名审计用)
FORBIDDEN_OBSERVATION_PATTERNS: tuple[str, ...] = (
    "regime", "hidden", "future", "latent", "steps_to", "bars_to",
    "episode_length", "n_rows", "seed", "generator_state", "exam_type",
    "direction_next", "drift",  # 漂移标签是隐藏状态
)

PRICE_COLUMNS = ("open", "high", "low", "close", "volume")

# wick/volume 噪声派生盐(与收益过程 RNG 分离;进入共同前缀一致性)
WICK_VOLUME_SALT = 0xC0FFEE


class GeneratorError(RuntimeError):
    """生成器协议违反(非法 OHLC / 泄漏 / 非确定)。"""


@dataclass(frozen=True)
class EpisodeSpec:
    """考试包中的一个 Episode 条目(可规范化哈希)。"""

    family: str
    params: dict[str, Any]
    seed: int
    split: str  # train / dev_seed_holdout / param_extrapolation / family_holdout / null_control

    def canonical(self) -> str:
        return json.dumps(
            {
                "family": self.family,
                "params": self.params,
                "seed": int(self.seed),
                "split": self.split,
            },
            sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        )


@dataclass
class GeneratedEpisode:
    """生成器单次输出。df 列 = PRICE_COLUMNS + 特征列;hidden 仅评估可见。"""

    spec: EpisodeSpec
    df: pd.DataFrame
    hidden: pd.DataFrame
    family_version: str
    timeframe: str
    is_null: bool
    generator_fingerprint: str
    meta: dict[str, Any] = field(default_factory=dict)


class BaseMarketGenerator(ABC):
    """生成器协议:子类声明族名/版本/特征列/隐藏列并实现 _generate。"""

    family: str = ""
    family_version: str = ""
    feature_columns: list[str] = []
    hidden_columns: list[str] = []
    is_null_family: bool = False

    # ------------------------------------------------------------------ API
    def generate(self, params: dict[str, Any], seed: int, split: str = "train",
                 timeframe: str = "15m") -> GeneratedEpisode:
        """确定性入口:相同 (family, params, seed) 必须产生完全一致的 Episode。"""
        if self.family == "" or self.family_version == "":
            raise GeneratorError(f"{type(self).__name__} 未声明 family/family_version")
        rng = np.random.default_rng(self.derive_seed(params, seed))
        returns, hidden_frame, meta = self._generate(params, seed, rng)
        df = self._build_ohlcv(returns, params, rng)
        df = self._attach_features(df)
        # 时间戳:固定 epoch 起始按 timeframe 递增(仅供诊断与时间平移
        # 反事实;课程章程未允许日历特征,策略不得读 date)
        from rl_curriculum.timebase import timeframe_to_seconds

        df.insert(
            0, "date",
            pd.date_range(
                "2026-01-01T00:00:00Z", periods=len(df),
                freq=f"{timeframe_to_seconds(timeframe)}s",
            ),
        )
        episode = GeneratedEpisode(
            spec=EpisodeSpec(self.family, dict(params), int(seed), split),
            df=df,
            hidden=hidden_frame,
            family_version=self.family_version,
            timeframe=timeframe,
            is_null=self.is_null_family,
            generator_fingerprint=self.fingerprint(),
            meta=meta,
        )
        verify_episode(episode)  # 生成后立即校验(合法 OHLC / 无 NaN / 无泄漏命名)
        return episode

    def derive_seed(self, params: dict[str, Any], seed: int) -> int:
        """从 (family, params, seed) 派生确定性 RNG 种子。"""
        payload = json.dumps(
            [self.family, self.family_version, params, int(seed)],
            sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        )
        return int.from_bytes(
            hashlib.sha256(payload.encode("utf-8")).digest()[:8], "big"
        )

    def fingerprint(self) -> str:
        """生成器身份哈希:族名+版本(版本变化必须改变哈希)。"""
        return "g-" + hashlib.sha256(
            f"{self.family}|{self.family_version}".encode("utf-8")
        ).hexdigest()

    # ------------------------------------------------------------ 子类实现
    @abstractmethod
    def _generate(
        self, params: dict[str, Any], seed: int, rng: np.random.Generator
    ) -> tuple[np.ndarray, pd.DataFrame, dict[str, Any]]:
        """返回 (每根 bar 的对数收益, 隐藏状态帧, 元信息)。"""

    # ------------------------------------------------------------ 共享工具
    def _build_ohlcv(
        self, log_returns: np.ndarray, params: dict[str, Any],
        rng: np.random.Generator,
    ) -> pd.DataFrame:
        """从对数收益构造时间连续、合法的 OHLCV。

        open[t] = close[t-1](时间连续,无跳空)。wick/volume 噪声使用
        只依赖 (family, params, wick-salt) 的独立派生 RNG——保证同一
        (params, returns 前缀) 重建时 OHLC 前缀逐位一致(共同前缀
        反事实的基础);主 rng 只驱动收益过程本身。
        """
        p0 = float(params.get("initial_price", 100.0))
        if p0 <= 0:
            raise GeneratorError(f"initial_price 必须为正,收到 {p0}")
        wick_fraction = float(params.get("wick_fraction", 0.002))
        wick_rng = np.random.default_rng(
            self.derive_seed(
                {**params, "_noise": "wick"}, int(WICK_VOLUME_SALT)
            )
        )
        log_close = np.log(p0) + np.cumsum(log_returns)
        close = np.exp(log_close)
        open_ = np.empty_like(close)
        open_[0] = p0
        open_[1:] = close[:-1]
        wick = np.abs(
            wick_rng.normal(0.0, max(wick_fraction, 1e-9), size=len(close))
        ) + 1e-12
        high = np.maximum(open_, close) * np.exp(np.minimum(wick, 0.05))
        low = np.minimum(open_, close) * np.exp(-np.minimum(wick, 0.05))
        # 合法性硬保证(数值裕量):high>=max(o,c), low<=min(o,c), high>=low
        high = np.maximum(high, np.maximum(open_, close) * (1 + 1e-12))
        low = np.minimum(low, np.minimum(open_, close) * (1 - 1e-12))
        volume = wick_rng.uniform(100.0, 1000.0, size=len(close))
        df = pd.DataFrame(
            {"open": open_, "high": high, "low": low, "close": close, "volume": volume}
        )
        return df

    def _attach_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """默认:无额外特征(子类覆盖,必须因果且无 NaN)。"""
        return df


# ---------------------------------------------------------------- 审计工具
def validate_ohlcv(df: pd.DataFrame) -> list[str]:
    """合法 OHLCV 检查:返回问题清单(空 = 合法)。"""
    issues: list[str] = []
    for col in PRICE_COLUMNS:
        if col not in df.columns:
            issues.append(f"缺少列 {col}")
    if issues:
        return issues
    o, h, l, c = df["open"], df["high"], df["low"], df["close"]
    if not (h >= np.maximum(o, c)).all():
        issues.append("存在 high < max(open, close)")
    if not (l <= np.minimum(o, c)).all():
        issues.append("存在 low > min(open, close)")
    if not (h >= l).all():
        issues.append("存在 high < low")
    if not ((df[list(PRICE_COLUMNS[:4])] > 0).all().all()):
        issues.append("存在非正价格")
    if (df["volume"] < 0).any():
        issues.append("存在负 volume")
    # 时间连续:open[t] == close[t-1]
    if len(df) > 1:
        gaps = np.abs(df["open"].to_numpy()[1:] - df["close"].to_numpy()[:-1])
        if not np.all(gaps <= 1e-9 * np.maximum(1.0, np.abs(df["close"].to_numpy()[:-1]))):
            issues.append("open[t] != close[t-1](时间不连续)")
    return issues


def audit_observation_isolation(
    episode: GeneratedEpisode, generator: BaseMarketGenerator
) -> dict[str, Any]:
    """自动审计:枚举观察字段,检查隐藏字段没有进入 observation。"""
    obs_fields = [
        c for c in episode.df.columns
        if c not in PRICE_COLUMNS and c != "date"
    ]
    hidden_fields = list(generator.hidden_columns)
    issues: list[str] = []
    leaked = sorted(set(obs_fields) & set(hidden_fields))
    if leaked:
        issues.append(f"隐藏列出现在观察 df 中: {leaked}")
    for f in obs_fields:
        for pat in FORBIDDEN_OBSERVATION_PATTERNS:
            if pat in f:
                issues.append(f"观察字段 {f!r} 命中禁止模式 {pat!r}")
                break
    return {
        "observation_fields": obs_fields,
        "declared_hidden_fields": hidden_fields,
        "leaked_fields": leaked,
        "issues": issues,
        "pass": not issues,
    }


def verify_episode(episode: GeneratedEpisode) -> None:
    """生成后立即校验(任何失败即 GeneratorError,fail closed)。"""
    ohlc_issues = validate_ohlcv(episode.df)
    if ohlc_issues:
        raise GeneratorError(
            f"{episode.spec.family} 生成非法 OHLCV: {ohlc_issues}"
        )
    feature_cols = [c for c in episode.df.columns if c not in PRICE_COLUMNS]
    arr = episode.df[feature_cols].to_numpy(dtype=np.float64) if feature_cols else None
    if arr is not None and not np.isfinite(arr).all():
        raise GeneratorError(f"{episode.spec.family} 特征存在 NaN/inf")
    if len(episode.hidden) != len(episode.df):
        raise GeneratorError(
            f"{episode.spec.family} hidden 行数 {len(episode.hidden)} "
            f"!= df 行数 {len(episode.df)}"
        )


def determinism_check(
    generator: BaseMarketGenerator, params: dict[str, Any], seed: int,
) -> dict[str, Any]:
    """相同 seed+参数完全确定 / 不同 seed 产生不同 Episode 的证据。"""
    e1 = generator.generate(params, seed)
    e2 = generator.generate(params, seed)
    same = e1.df.equals(e2.df) and e1.hidden.equals(e2.hidden)
    different_seed = True
    if generator.is_null_family is False:
        e3 = generator.generate(params, seed + 1)
        different_seed = not e1.df.equals(e3.df)
    return {
        "family": generator.family,
        "seed": seed,
        "reproducible": bool(same),
        "different_seed_differs": bool(different_seed),
        "pass": bool(same and different_seed),
    }
