"""工作包 D:审计探针生成器(仅用于验证审计系统,不是正式课程)。

- 探针 A probe_segmented_drift:分段漂移(横盘/正/负随机段,
  regime 长度与顺序随机,高斯噪声);隐藏状态 = 当前漂移方向和强度;
- 探针 B probe_smooth_latent_drift:缓慢变化的潜在漂移(OU 过程),
  无明确分段边界,趋势强度连续变化,与 A 独立的代码路径;
- 探针 C probe_null_control:与 A 尽可能相似的收益分布/波动率/
  Episode 长度/特征边际分布,但切断 可观察信息 -> 未来收益 的
  可预测关系(默认对 A 轨迹收益做相位随机化重排)。

可观察特征统一为尺度不变量:ret_1/ret_4/ret_12/vol_24/ma_ratio。
训练探针与模拟隐藏探针可以公开,但模拟隐藏探针只用于测试隐藏考试
基础设施,不能作为未来正式期末考试(正式隐藏生成器将在课程冻结后由
独立评估 Agent 在另一工作区创建)。
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from rl_curriculum.generator_api import (
    BaseMarketGenerator,
    GeneratedEpisode,
    GeneratorError,
)

PROBE_FEATURE_COLUMNS = ["ret_1", "ret_4", "ret_12", "vol_24", "ma_ratio"]


def _attach_probe_features(df: pd.DataFrame) -> pd.DataFrame:
    """探针课程统一特征(因果滚动、无 NaN、价格尺度不变)。"""
    log_close = np.log(df["close"].to_numpy(dtype=np.float64))
    out = df.copy()
    out["ret_1"] = pd.Series(log_close).diff(1).fillna(0.0)
    out["ret_4"] = pd.Series(log_close).diff(4).fillna(0.0)
    out["ret_12"] = pd.Series(log_close).diff(12).fillna(0.0)
    out["vol_24"] = (
        pd.Series(log_close).diff(1).rolling(24, min_periods=1).std().fillna(0.0)
    )
    out["ma_ratio"] = (
        df["close"] / df["close"].rolling(24, min_periods=1).mean() - 1.0
    )
    return out


def rebuild_episode_with_returns(
    generator: BaseMarketGenerator,
    source: GeneratedEpisode,
    new_returns: np.ndarray,
    new_hidden: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """以新收益序列重建 df(保留 source 的 OHLCV 噪声形状之外的参数)。

    反事实变换的公共入口:价格水平连续推进,特征按同一因果公式重算。
    wick 噪声由派生 RNG 重新采样(确定性依赖 source 的 spec)。
    """
    rng = np.random.default_rng(
        generator.derive_seed(source.spec.params, source.spec.seed)
    )
    params = dict(source.spec.params)
    params["initial_price"] = float(source.df["open"].iloc[0])
    df = generator._build_ohlcv(new_returns, params, rng)  # noqa: SLF001
    df = _attach_probe_features(df)
    if new_hidden is not None:
        # 隐藏帧长度必须与新收益一致
        if len(new_hidden) != len(df):
            raise GeneratorError(
                f"重建 hidden 行数 {len(new_hidden)} != df 行数 {len(df)}"
            )
    return df


class ProbeSegmentedDriftGenerator(BaseMarketGenerator):
    """探针 A:分段漂移。

    参数(默认 15m;真实时间换算见 timebase):
    - episode_bars:      Episode 长度(bars;24h@15m = 96);
    - regimes(可选,显式):[[direction, strength_bps, length_bars], ...]
      供 regime 顺序随机化反事实使用;缺省时随机生成;
    - n_regimes_range:   随机 regime 数量范围(默认 [3, 6]);
    - regime_len_range:  每段长度范围(bars;2h~8h@15m = [8, 32]);
    - direction_weights: [横盘, 正, 负] 权重(默认 [0.3, 0.35, 0.35]);
    - drift_bps_range:   漂移强度范围(默认 [6.0, 20.0] bps/bar);
    - vol_bps_range:     噪声波动率范围(默认 [25.0, 60.0] bps/bar);
    - initial_price, wick_fraction。

    隐藏状态:regime_direction / regime_strength_bps /
    bars_to_regime_end / regime_index(仅 Oracle 与评估可见)。
    """

    family = "probe_segmented_drift"
    family_version = "probe-A-v1"
    feature_columns = list(PROBE_FEATURE_COLUMNS)
    hidden_columns = [
        "regime_direction", "regime_strength_bps", "bars_to_regime_end",
        "regime_index",
    ]

    def _generate(self, params, seed, rng):
        n = int(params.get("episode_bars", 96))
        if n < 12:
            raise GeneratorError(f"episode_bars 过短: {n}")
        regimes = params.get("regimes")
        if regimes is None:
            regimes = self._random_regimes(n, params, rng)
        returns, directions, strengths, to_end, indices = \
            self._realize(regimes, n, params, rng)
        hidden = pd.DataFrame(
            {
                "regime_direction": directions,
                "regime_strength_bps": strengths,
                "bars_to_regime_end": to_end,
                "regime_index": indices,
            }
        )
        meta = {
            "regimes": [[int(d), float(s), int(l)] for d, s, l in regimes],
            "n_regimes": len(regimes),
            "episode_bars": n,
        }
        return returns, hidden, meta

    @staticmethod
    def _random_regimes(n, params, rng):
        lo, hi = params.get("n_regimes_range", [3, 6])
        lo_len, hi_len = params.get("regime_len_range", [12, 40])
        weights = np.asarray(
            params.get("direction_weights", [0.3, 0.35, 0.35]), dtype=float
        )
        d_lo, d_hi = params.get("drift_bps_range", [18.0, 30.0])
        total = 0
        regimes: list[list] = []
        guard = 0
        while total < n and guard < 200:
            guard += 1
            remaining = n - total
            k = int(rng.integers(int(lo), int(hi) + 1))
            if k * int(lo_len) > remaining + int(hi_len):
                k = max(1, remaining // max(int(lo_len), 1))
            lengths = []
            for _ in range(k - 1):
                lengths.append(int(rng.integers(int(lo_len), int(hi_len) + 1)))
            last = remaining - sum(lengths)
            if last < int(lo_len) and last > 0:
                lengths[-1] += last  # 并入最后一段
            elif last >= int(lo_len):
                lengths.append(last)
            for length in lengths:
                if length <= 0:
                    continue
                direction = int(
                    rng.choice([0, 1, -1], p=weights / weights.sum())
                )
                strength = 0.0 if direction == 0 else float(
                    rng.uniform(float(d_lo), float(d_hi))
                )
                regimes.append([direction, strength, length])
                total += length
        if not regimes:
            regimes.append([0, 0.0, n])
        return regimes

    @staticmethod
    def _realize(regimes, n, params, rng):
        v_lo, v_hi = params.get("vol_bps_range", [20.0, 32.0])
        vol = float(rng.uniform(float(v_lo), float(v_hi))) * 1e-4
        returns = np.empty(n)
        directions = np.empty(n, dtype=int)
        strengths = np.empty(n, dtype=float)
        to_end = np.empty(n, dtype=int)
        indices = np.empty(n, dtype=int)
        t = 0
        for idx, (direction, strength_bps, length) in enumerate(regimes):
            mu = int(direction) * float(strength_bps) * 1e-4
            seg = int(length)
            end = min(t + seg, n)
            returns[t:end] = mu + vol * rng.standard_normal(end - t)
            directions[t:end] = int(direction)
            strengths[t:end] = float(strength_bps)
            to_end[t:end] = np.arange(end - 1 - t, -1, -1)
            indices[t:end] = idx
            t = end
            if t >= n:
                break
        if t < n:  # regimes 总长不足时以横盘补齐(显式 regimes 场景)
            returns[t:] = vol * rng.standard_normal(n - t)
            directions[t:] = 0
            strengths[t:] = 0.0
            to_end[t:] = 0
            indices[t:] = len(regimes)
        return returns, directions, strengths, to_end, indices

    def _attach_features(self, df):
        return _attach_probe_features(df)


class ProbeSmoothLatentDriftGenerator(BaseMarketGenerator):
    """探针 B:平滑潜在趋势(OU 潜在漂移,独立代码路径,无分段边界)。

    参数:
    - episode_bars: Episode 长度(bars);
    - theta:        OU 均值回复速度(默认 0.02);
    - sigma_mu_bps: 潜在漂移扩散(默认 2.5 bps/bar);
    - mu_max_bps:   潜在漂移截断幅度(默认 25 bps/bar);
    - vol_bps:      价格噪声(默认 40 bps/bar);
    - initial_price, wick_fraction。

    隐藏状态:latent_drift_bps(连续值,仅 Oracle 与评估可见)。
    """

    family = "probe_smooth_latent_drift"
    family_version = "probe-B-v1"
    feature_columns = list(PROBE_FEATURE_COLUMNS)
    hidden_columns = ["latent_drift_bps"]

    def _generate(self, params, seed, rng):
        n = int(params.get("episode_bars", 96))
        if n < 12:
            raise GeneratorError(f"episode_bars 过短: {n}")
        theta = float(params.get("theta", 0.015))
        sigma_mu = float(params.get("sigma_mu_bps", 4.0)) * 1e-4
        mu_max = float(params.get("mu_max_bps", 25.0)) * 1e-4
        vol = float(params.get("vol_bps", 28.0)) * 1e-4
        mu = np.empty(n)
        returns = np.empty(n)
        mu[0] = 0.0
        returns[0] = vol * rng.standard_normal()
        for t in range(1, n):
            mu[t] = mu[t - 1] + theta * (0.0 - mu[t - 1]) + sigma_mu * rng.standard_normal()
            mu[t] = np.clip(mu[t], -mu_max, mu_max)
            returns[t] = mu[t] + vol * rng.standard_normal()
        hidden = pd.DataFrame({"latent_drift_bps": mu / 1e-4})
        meta = {"theta": theta, "sigma_mu_bps": sigma_mu / 1e-4,
                "vol_bps": vol / 1e-4, "episode_bars": n}
        return returns, hidden, meta

    def _attach_features(self, df):
        return _attach_probe_features(df)


class ProbeNullControlGenerator(BaseMarketGenerator):
    """探针 C:Null Control(无可预测信号 + 有费用)。

    构造:先按探针 A 的随机 regime 机制生成一条轨迹(相同的收益
    分布/波动率/Episode 长度/特征边际分布),再对收益序列做确定性
    相位随机化重排(保留精确边际分布,切断 可观察信息 -> 未来收益 的
    可预测关系);OHLCV 由重排后的收益按同一规则重建。

    隐藏状态:保留源 A 轨迹的 regime 标签——标签仍在,但其与(已重排
    的)未来收益之间的预测关系已被切断;用于验证 Oracle 在 Null 环境
    中不保留预测优势。Null 环境中合理结果应接近:少交易、空仓、
    扣费后无稳定超额收益。
    """

    family = "probe_null_control"
    family_version = "probe-C-v1"
    feature_columns = list(PROBE_FEATURE_COLUMNS)
    hidden_columns = list(ProbeSegmentedDriftGenerator.hidden_columns)
    is_null_family = True

    def _generate(self, params, seed, rng):
        n = int(params.get("episode_bars", 96))
        if n < 12:
            raise GeneratorError(f"episode_bars 过短: {n}")
        mode = params.get("mode", "shuffle_probe_a")
        if mode == "iid_zero_drift":
            v_lo, v_hi = params.get("vol_bps_range", [20.0, 32.0])
            vol = float(rng.uniform(float(v_lo), float(v_hi))) * 1e-4
            returns = vol * rng.standard_normal(n)
            hidden = pd.DataFrame(
                {"regime_direction": np.zeros(n, dtype=int),
                 "regime_strength_bps": np.zeros(n),
                 "bars_to_regime_end": np.zeros(n, dtype=int),
                 "regime_index": np.zeros(n, dtype=int)}
            )
        else:
            # 与探针 A 完全相同的 regime 采样(相同参数/种子),
            # 然后重排收益(相位随机化):边际分布不变,时序依赖切断。
            # 隐藏 regime 标签保留(与重排后收益独立 -> Oracle 无优势)。
            probe_a = ProbeSegmentedDriftGenerator()
            src_returns, src_hidden, _meta = probe_a._generate(  # noqa: SLF001
                params, seed, np.random.default_rng(
                    probe_a.derive_seed(params, seed))
            )
            returns = rng.permutation(np.asarray(src_returns, dtype=np.float64))
            hidden = src_hidden
        meta = {"mode": mode, "episode_bars": n,
                "predictability": "cut(returns phase-randomized;hidden labels kept)"}
        return returns, hidden, meta

    def _attach_features(self, df):
        return _attach_probe_features(df)


# 生成器注册表(评估器/考试包按 family 名解析)
DEFAULT_GENERATOR_REGISTRY: dict[str, BaseMarketGenerator] = {
    g.family: g for g in (
        ProbeSegmentedDriftGenerator(),
        ProbeSmoothLatentDriftGenerator(),
        ProbeNullControlGenerator(),
    )
}
