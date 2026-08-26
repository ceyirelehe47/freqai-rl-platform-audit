"""工作包 C + 阶段 2.6.0a 工作包 E2/K + 阶段 2.6.0b 工作包 A:可插拔人工市场生成器协议。

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

阶段 2.6.0b 工作包 A(真实时长实际物化):
- generate() 是唯一参数入口:先 resolve_generator_params()(统一解析
  全部真实时间字段),把 resolved episode_bars 注入 effective params,
  再调用 _generate——子类不再执行 params.get("episode_bars", 96) 之类
  的静默默认;
- 生成后强校验 len(df) == duration["resolved_bars"](不一致即
  GeneratorError,不得产出 96 行默认 Episode);
- episode.meta["resolution"] 记录原始参数与解析参数的分离 trace
  (原始真实时长/timeframe/取整规则/resolved bars/实际行数)。

阶段 2.6.0a 加固(保留):
- EpisodeSpec 必须显式携带 timeframe(不得依赖默认 15m);
- 真实时长 <-> bars 的解析结果(resolved duration)可规范化进入
  考试包哈希(原始值与解析结果全部入哈希);
- verify_episode 在 generate() 后自动执行正式校验(K):
  OHLCV 合法性 / NaN-Inf / hidden 行数 / observation 精确 whitelist
  (declared feature columns 之外的字段一律拒绝,无论命名如何)/
  hidden 与 observation 无交集 / 特征因果可用时点(前缀重算一致)。
  字段名黑名单(FORBIDDEN_OBSERVATION_PATTERNS)仅作辅助报告。
"""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

# 阶段 2.6.0b:resolve_duration 移至 param_resolution(统一解析通道的
# 一部分);此处 re-export 保持既有导入路径兼容
from rl_curriculum.param_resolution import (  # noqa: F401
    ParamResolutionError,
    ResolvedParams,
    resolve_duration,
    resolve_generator_params,
)

# 观察列中禁止出现的隐藏语义模式(辅助审计;主隔离机制是精确 whitelist)
FORBIDDEN_OBSERVATION_PATTERNS: tuple[str, ...] = (
    "regime", "hidden", "future", "latent", "steps_to", "bars_to",
    "episode_length", "n_rows", "seed", "generator_state", "exam_type",
    "direction_next", "drift",  # 漂移标签是隐藏状态
)

PRICE_COLUMNS = ("open", "high", "low", "close", "volume")

# wick/volume 噪声派生盐(与收益过程 RNG 分离;进入共同前缀一致性)
WICK_VOLUME_SALT = 0xC0FFEE


class GeneratorError(RuntimeError):
    """生成器协议违反(非法 OHLC / 泄漏 / 非确定 / 时长未物化)。"""


def _require_timeframe(timeframe: Any) -> str:
    from rl_curriculum.timebase import SUPPORTED_TIMEFRAMES

    if not isinstance(timeframe, str) or timeframe not in SUPPORTED_TIMEFRAMES:
        raise GeneratorError(
            f"timeframe 必须显式给出且属于 {SUPPORTED_TIMEFRAMES},"
            f"收到 {timeframe!r}(EpisodeSpec 不得依赖默认 timeframe)")
    return timeframe


@dataclass(frozen=True)
class EpisodeSpec:
    """考试包中的一个 Episode 条目(可规范化哈希;timeframe 必填)。"""

    family: str
    params: dict[str, Any]
    seed: int
    split: str  # train / dev_seed_holdout / param_extrapolation / family_holdout / null_control
    timeframe: str

    def __post_init__(self) -> None:
        _require_timeframe(self.timeframe)

    def canonical(self) -> str:
        return json.dumps(
            {
                "family": self.family,
                "params": self.params,
                "seed": int(self.seed),
                "split": self.split,
                "timeframe": self.timeframe,
            },
            sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        )

    def canonical_duration(self) -> str:
        """真实时长解析的规范化形式(进入考试包哈希)。"""
        return json.dumps(
            resolve_duration(self.params, self.timeframe),
            sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        )

    def resolved_duration(self) -> dict[str, Any]:
        return resolve_duration(self.params, self.timeframe)


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
    declared_feature_columns: tuple[str, ...] = ()  # 精确 observation whitelist

    def observation_columns(self) -> list[str]:
        return [
            c for c in self.df.columns
            if c not in PRICE_COLUMNS and c != "date"
        ]


class BaseMarketGenerator(ABC):
    """生成器协议:子类声明族名/版本/特征列/隐藏列并实现 _generate。

    阶段 2.6.0b 工作包 A:_generate 收到的 params 已由 generate() 统一
    解析(effective params,含 resolved episode_bars);子类必须直接
    读取 params["episode_bars"] 等 bar 参数,不得提供静默默认值——
    缺键即 KeyError(fail closed),而不是退回 96。
    """

    family: str = ""
    family_version: str = ""
    feature_columns: list[str] = []
    hidden_columns: list[str] = []
    is_null_family: bool = False
    # 预注册 nuisance 槽位列(由 generate() 统一填充独立噪声;
    # 必须同时出现在 feature_columns 中,以保证 observation 维度固定)
    nuisance_slot_names: tuple[str, ...] = ()

    # ------------------------------------------------------------------ API
    def generate(self, params: dict[str, Any], seed: int, split: str = "train",
                 *, timeframe: str) -> GeneratedEpisode:
        """确定性入口:相同 (family, params, seed, timeframe) 完全一致。

        timeframe 必填(不得静默使用默认 15m)。
        工作包 A:参数先经 resolve_generator_params 统一解析,生成器
        实际使用的 bars 与声明真实时长一致;生成后校验实际行数。
        """
        if self.family == "" or self.family_version == "":
            raise GeneratorError(f"{type(self).__name__} 未声明 family/family_version")
        timeframe = _require_timeframe(timeframe)
        missing = [c for c in self.nuisance_slot_names if c not in self.feature_columns]
        if missing:
            raise GeneratorError(
                f"{type(self).__name__} nuisance 槽位 {missing} 未列入 "
                f"feature_columns(observation 维度必须固定)")
        # A1:统一解析流程——原始课程参数 -> resolved generator params
        try:
            resolved = resolve_generator_params(params, timeframe)
        except ParamResolutionError as exc:
            raise GeneratorError(
                f"{self.family} 参数解析失败(真实时间字段与 bars 声明"
                f"不一致或非法): {exc}") from exc
        effective = resolved.effective_params
        rng = np.random.default_rng(self.derive_seed(effective, seed))
        returns, hidden_frame, meta = self._generate(effective, seed, rng)
        df = self._build_ohlcv(returns, effective, rng)
        df = self._attach_features(df)
        df = self._attach_nuisance_slots(df, effective, seed)
        # A2/A4:实际行数必须等于 resolved bars(禁止静默退回默认长度)
        resolved_bars = int(resolved.duration["resolved_bars"])
        if len(df) != resolved_bars:
            raise GeneratorError(
                f"{self.family} 实际生成 {len(df)} 行 != resolved "
                f"episode_bars {resolved_bars}(时长声明未物化;EXAM_INVALID)")
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
        trace = resolved.trace()
        trace["effective_params"] = {
            k: effective[k] for k in sorted(effective)
            if k in ("episode_bars", "regime_len_range", "feature_window_bars",
                     "delayed_reward_phase_bars", "drawdown_phase_bars")
        }
        trace["actual_rows"] = int(len(df))
        trace["rows_match_resolved"] = True
        meta = dict(meta)
        meta["resolution"] = trace
        episode = GeneratedEpisode(
            spec=EpisodeSpec(self.family, dict(params), int(seed), split, timeframe),
            df=df,
            hidden=hidden_frame,
            family_version=self.family_version,
            timeframe=timeframe,
            is_null=self.is_null_family,
            generator_fingerprint=self.fingerprint(),
            meta=meta,
            declared_feature_columns=tuple(self.feature_columns),
        )
        if len(episode.hidden) != len(df):
            raise GeneratorError(
                f"{self.family} hidden 行数 {len(episode.hidden)} != df 行数 "
                f"{len(df)}")
        verify_episode(episode, self)  # 生成后立即正式校验(K,fail closed)
        return episode

    def derive_seed(self, params: dict[str, Any], seed: int) -> int:
        """从 (family, params, seed) 派生确定性 RNG 种子。

        阶段 2.6.0b:params 必须是 resolved effective params(generate()
        统一传入);原始 duration_hours 与解析 episode_bars 不再产生
        不同的 RNG 流(声明形式不影响生成内容,只影响 manifest)。
        """
        payload = json.dumps(
            [self.family, self.family_version, params, int(seed)],
            sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        )
        return int.from_bytes(
            hashlib.sha256(payload.encode("utf-8")).digest()[:8], "big"
        )

    def fingerprint(self) -> str:
        """生成器身份哈希:族名+版本(版本变化必须改变哈希)。

        注意(阶段 2.6.0b 工作包 F):这只是族名+版本的轻量指纹;
        sealed commitment 绑定的实现身份由 generator_binding
        implementation_hash 提供(逐族绑定真实实现模块)。
        """
        return "g-" + hashlib.sha256(
            f"{self.family}|{self.family_version}".encode("utf-8")
        ).hexdigest()

    # ------------------------------------------------------------ 子类实现
    @abstractmethod
    def _generate(
        self, params: dict[str, Any], seed: int, rng: np.random.Generator
    ) -> tuple[np.ndarray, pd.DataFrame, dict[str, Any]]:
        """返回 (每根 bar 的对数收益, 隐藏状态帧, 元信息)。

        params 已由 generate() 统一解析(effective params);子类直接
        读取 params["episode_bars"] 等 bar 参数,禁止静默默认值。
        """

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

    def _attach_nuisance_slots(
        self, df: pd.DataFrame, params: dict[str, Any], seed: int,
    ) -> pd.DataFrame:
        """填充预注册 nuisance 槽位:与收益过程独立盐派生的确定性噪声。

        逐行 counter-hash 构造(不依赖 RNG 消费顺序):
        - 同一 (family, params, seed) 下前缀逐位稳定(共同前缀一致);
        - 与收益过程使用不同盐,声明语义为"不应含预测信息"。

        阶段 2.6.0b:params 为 resolved effective params(generate()
        统一传入);反事实重建必须使用同一 effective params 重算,否则
        前缀一致性会被 self-check 抓获。
        """
        if not self.nuisance_slot_names:
            return df
        out = df.copy()
        n = len(out)
        base = json.dumps(
            [self.family, self.family_version, params, int(seed),
             "_nuisance_salt"],
            sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        )
        for slot in self.nuisance_slot_names:
            col = np.empty(n, dtype=np.float64)
            for i in range(n):
                h = hashlib.sha256(f"{base}|{slot}|{i}".encode("utf-8")).digest()
                col[i] = (int.from_bytes(h[:8], "big") / 2.0**64 - 0.5) * 2.0
            out[slot] = col
        return out


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
    episode: GeneratedEpisode, generator: BaseMarketGenerator | None = None,
) -> dict[str, Any]:
    """辅助审计:枚举观察字段,报告隐藏字段与禁止命名模式命中。

    主隔离机制是 verify_episode 的精确 whitelist(额外列一律拒绝);
    本函数仅产生人工可读报告。
    """
    obs_fields = episode.observation_columns()
    declared = list(episode.declared_feature_columns) or \
        (list(generator.feature_columns) if generator is not None else [])
    hidden_fields = list(generator.hidden_columns) if generator is not None \
        else list(episode.hidden.columns)
    issues: list[str] = []
    leaked = sorted(set(obs_fields) & set(hidden_fields))
    if leaked:
        issues.append(f"隐藏列出现在观察 df 中: {leaked}")
    for f in obs_fields:
        for pat in FORBIDDEN_OBSERVATION_PATTERNS:
            if pat in f:
                issues.append(f"观察字段 {f!r} 命中禁止模式 {pat!r}")
                break
    if declared:
        extra = sorted(set(obs_fields) - set(declared))
        missing = sorted(set(declared) - set(obs_fields))
        if extra:
            issues.append(f"whitelist 之外的额外观察列: {extra}")
        if missing:
            issues.append(f"whitelist 声明但 df 缺失的列: {missing}")
    return {
        "observation_fields": obs_fields,
        "declared_whitelist": declared,
        "declared_hidden_fields": hidden_fields,
        "leaked_fields": leaked,
        "issues": issues,
        "pass": not issues,
    }


def _verify_feature_causality(
    episode: GeneratedEpisode, generator: BaseMarketGenerator,
) -> list[str]:
    """特征因果可用时点校验:对截断前缀重算特征,必须与原前缀逐位一致。

    因果滚动特征(只依赖过去)在任意前缀上重算值不变;任何依赖未来
    行的特征(如中心化窗口)都会在此暴露。nuisance 槽位由逐行
    counter-hash 填充,同样按前缀重算验证。

    阶段 2.6.0b:重算使用与原生成相同的 resolved effective params
    (episode.meta["resolution"] 记录了 effective 参数键),否则 nuisance
    counter-hash 不一致会被本校验直接暴露。
    """
    issues: list[str] = []
    n = len(episode.df)
    price_like = [c for c in ("date",) + tuple(PRICE_COLUMNS)
                  if c in episode.df.columns]
    feature_cols = episode.observation_columns()
    resolution = (episode.meta or {}).get("resolution") or {}
    effective_params = dict(resolution.get("effective_params") or {})
    effective_params.update({
        k: v for k, v in episode.spec.params.items()
        if k not in ("duration_hours", "duration_rounding",
                     "regime_duration_hours_range", "feature_window_hours",
                     "decision_interval_minutes",
                     "delayed_reward_phase_hours", "drawdown_phase_hours")
    })
    from rl_curriculum.param_resolution import resolve_generator_params

    try:
        resolved = resolve_generator_params(
            episode.spec.params, episode.spec.timeframe)
        effective_params = resolved.effective_params
    except ParamResolutionError:
        pass  # spec 参数无法重解析时保留上面的近似(spec 物化时已验证过)
    for cut in sorted({max(n // 2, 1), n}):
        if cut < 1:
            continue
        prefix = episode.df.iloc[:cut][price_like].copy().reset_index(drop=True)
        rebuilt = generator._attach_features(prefix)  # noqa: SLF001
        rebuilt = generator._attach_nuisance_slots(  # noqa: SLF001
            rebuilt, effective_params, episode.spec.seed)
        for col in feature_cols:
            if col not in rebuilt.columns:
                issues.append(
                    f"截断重算缺少特征列 {col}(cut={cut})——特征并非由"
                    f"生成器因果公式重建")
                continue
            a = episode.df[col].iloc[:cut].to_numpy(dtype=np.float64)
            b = rebuilt[col].to_numpy(dtype=np.float64)
            if a.shape != b.shape or not np.allclose(a, b, rtol=0, atol=0):
                issues.append(
                    f"特征 {col} 前缀重算不一致(cut={cut}):特征依赖了"
                    f"未来行或重建非确定")
    return issues


def verify_episode(
    episode: GeneratedEpisode,
    generator: BaseMarketGenerator | None = None,
) -> None:
    """generate() 后自动执行的正式校验(任何失败即 GeneratorError)。

    检查项(K + 阶段 2.6.0b A2):
    - OHLCV 合法性;
    - 特征 NaN/Inf;
    - hidden 行数 == df 行数;
    - 实际行数 == resolved episode_bars(时长声明物化);
    - observation 精确 whitelist:df 特征列集合必须与
      declared_feature_columns(或 generator.feature_columns)完全一致,
      额外列(无论命名 factor_x / signal_quality / state_7)一律拒绝;
    - hidden 列与 observation 列无交集;
    - 特征因果可用时点(generator 给出时):前缀重算逐位一致。
    """
    ohlc_issues = validate_ohlcv(episode.df)
    if ohlc_issues:
        raise GeneratorError(
            f"{episode.spec.family} 生成非法 OHLCV: {ohlc_issues}"
        )
    feature_cols = episode.observation_columns()
    arr = episode.df[feature_cols].to_numpy(dtype=np.float64) if feature_cols else None
    if arr is not None and not np.isfinite(arr).all():
        raise GeneratorError(f"{episode.spec.family} 特征存在 NaN/inf")
    if len(episode.hidden) != len(episode.df):
        raise GeneratorError(
            f"{episode.spec.family} hidden 行数 {len(episode.hidden)} "
            f"!= df 行数 {len(episode.df)}"
        )
    # A2:Episode 实际行数 == 声明真实时长解析出的 bars
    resolution = (episode.meta or {}).get("resolution") or {}
    duration = resolution.get("duration") or {}
    resolved_bars = duration.get("resolved_bars")
    if resolved_bars is not None and len(episode.df) != int(resolved_bars):
        raise GeneratorError(
            f"{episode.spec.family} 实际行数 {len(episode.df)} != resolved "
            f"episode_bars {resolved_bars}(duration 声明未物化)")
    # 精确 whitelist(fail closed;命名黑名单只是辅助)
    declared = list(episode.declared_feature_columns)
    if generator is not None and not declared:
        declared = list(generator.feature_columns)
    if declared:
        extra = sorted(set(feature_cols) - set(declared))
        missing = sorted(set(declared) - set(feature_cols))
        if extra:
            raise GeneratorError(
                f"{episode.spec.family} observation 出现 whitelist 之外的"
                f"额外特征列 {extra}(fail closed:命名无关,凡不在预注册"
                f"whitelist 中的字段一律拒绝)")
        if missing:
            raise GeneratorError(
                f"{episode.spec.family} observation 缺少 whitelist 声明的"
                f"特征列 {missing}")
    hidden_overlap = sorted(set(episode.hidden.columns) & set(feature_cols))
    if hidden_overlap:
        raise GeneratorError(
            f"{episode.spec.family} 隐藏列进入 observation: {hidden_overlap}")
    if generator is not None:
        causal_issues = _verify_feature_causality(episode, generator)
        if causal_issues:
            raise GeneratorError(
                f"{episode.spec.family} 特征因果性校验失败: {causal_issues}")


def determinism_check(
    generator: BaseMarketGenerator, params: dict[str, Any], seed: int,
    *, timeframe: str,
) -> dict[str, Any]:
    """相同 seed+参数完全确定 / 不同 seed 产生不同 Episode 的证据。"""
    e1 = generator.generate(params, seed, timeframe=timeframe)
    e2 = generator.generate(params, seed, timeframe=timeframe)
    same = e1.df.equals(e2.df) and e1.hidden.equals(e2.hidden)
    different_seed = True
    if generator.is_null_family is False:
        e3 = generator.generate(params, seed + 1, timeframe=timeframe)
        different_seed = not e1.df.equals(e3.df)
    return {
        "family": generator.family,
        "seed": seed,
        "timeframe": timeframe,
        "reproducible": bool(same),
        "different_seed_differs": bool(different_seed),
        "pass": bool(same and different_seed),
    }
