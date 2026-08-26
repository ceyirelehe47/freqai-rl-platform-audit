"""工作包 D + 阶段 2.6.0a 工作包 L:审计探针生成器与多类 Null Control。

- 探针 A probe_segmented_drift:分段漂移(横盘/正/负随机段);
- 探针 B probe_smooth_latent_drift:缓慢变化的潜在漂移(OU 过程);
- 探针 C probe_null_control:全排列 Null(保留为探针;阶段 2.6.0 唯一
  Null 构造,正式结论不得只依赖它);
- 正式多类 Null(阶段 2.6.0a 工作包 L,三类结构不同的构造):
  * probe_null_sign    符号随机化(保留 |收益| 与波动聚集,切断方向);
  * probe_null_block   分块重排(保留块内局部结构,切断跨块关系);
  * probe_null_volstate 波动状态条件随机化(档内置换,保边际与波动聚集)。

Fourier 相位替身在阶段 2.6.0a 验证中被否决:相位随机化保留自协方差
(线性可预测性),趋势规则基线在其上仍有稳定正超额,不构成无信号
Null(见 ProbeNullVolStateShuffleGenerator 备注与主报告)。

可观察特征统一为尺度不变量 ret_1/ret_4/ret_12/vol_24/ma_ratio,外加
预注册 nuisance 槽位 nuisance_0/1/2(独立 counter-hash 噪声,声明语义
"不应含预测信息";固定 observation 维度,反事实考试只改槽位内容,
不新增列)。vol_24 是正式市场特征,不再被硬编码为"无关特征"。

每个 Null 家族在 meta 中记录:保留了哪些统计性质 / 破坏了哪些预测
关系 / 与源环境的分布差异 / 局限性。
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

import numpy as np
import pandas as pd

from rl_curriculum.generator_api import (
    BaseMarketGenerator,
    GeneratedEpisode,
    GeneratorError,
)

PROBE_MARKET_FEATURES = ["ret_1", "ret_4", "ret_12", "vol_24", "ma_ratio"]
PROBE_NUISANCE_SLOTS = ["nuisance_0", "nuisance_1", "nuisance_2"]
PROBE_FEATURE_COLUMNS = PROBE_MARKET_FEATURES + PROBE_NUISANCE_SLOTS


def _attach_probe_features(df: pd.DataFrame) -> pd.DataFrame:
    """探针课程统一市场特征(因果滚动、无 NaN、价格尺度不变)。"""
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


def nuisance_column_values(
    *, family: str, family_version: str, params: dict[str, Any],
    seed: int, slot: str, n: int,
) -> np.ndarray:
    """nuisance 槽位逐行 counter-hash 噪声(与 BaseMarketGenerator 共用公式)。"""
    base = json.dumps(
        [family, family_version, params, int(seed), "_nuisance_salt"],
        sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    )
    col = np.empty(n, dtype=np.float64)
    for i in range(n):
        h = hashlib.sha256(f"{base}|{slot}|{i}".encode("utf-8")).digest()
        col[i] = (int.from_bytes(h[:8], "big") / 2.0**64 - 0.5) * 2.0
    return col


def fill_nuisance_slots(
    df: pd.DataFrame, *, family: str, family_version: str,
    params: dict[str, Any], seed: int,
    slots: list[str] | tuple[str, ...] = PROBE_NUISANCE_SLOTS,
) -> pd.DataFrame:
    out = df.copy()
    for slot in slots:
        out[slot] = nuisance_column_values(
            family=family, family_version=family_version, params=params,
            seed=seed, slot=slot, n=len(out),
        )
    return out


def recompute_probe_features(
    df: pd.DataFrame, *, family: str, family_version: str,
    params: dict[str, Any], seed: int,
) -> pd.DataFrame:
    """从价格列重算探针特征 + nuisance 槽位(前缀逐位一致;白名单齐整)。"""
    keep = [c for c in df.columns
            if c in ("date", "open", "high", "low", "close", "volume")]
    out = _attach_probe_features(
        df[keep].copy().reset_index(drop=True)
    )
    return fill_nuisance_slots(
        out, family=family, family_version=family_version,
        params=params, seed=seed,
    )


def rebuild_episode_with_returns(
    generator: BaseMarketGenerator,
    source: GeneratedEpisode,
    new_returns: np.ndarray,
    new_hidden: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """以新收益序列重建 df(保留 source 的 OHLCV 噪声形状之外的参数)。

    反事实变换的公共入口:价格水平连续推进,特征按同一因果公式重算,
    nuisance 槽位按同一 counter-hash 重填(whitelist 保持齐整)。
    """
    rng = np.random.default_rng(
        generator.derive_seed(source.spec.params, source.spec.seed)
    )
    params = dict(source.spec.params)
    params["initial_price"] = float(source.df["open"].iloc[0])
    df = generator._build_ohlcv(new_returns, params, rng)  # noqa: SLF001
    df = _attach_probe_features(df)
    df = fill_nuisance_slots(
        df, family=source.spec.family,
        family_version=source.family_version,
        params=source.spec.params, seed=source.spec.seed,
    )
    if new_hidden is not None:
        # 隐藏帧长度必须与新收益一致
        if len(new_hidden) != len(df):
            raise GeneratorError(
                f"重建 hidden 行数 {len(new_hidden)} != df 行数 {len(df)}"
            )
    return df


# --------------------------------------------------------------- 探针 A/B
class ProbeSegmentedDriftGenerator(BaseMarketGenerator):
    """探针 A:分段漂移。

    参数(真实时间由 timeframe 解析,见 generator_api.resolve_duration):
    - episode_bars:      Episode 长度(bars;24h@15m = 96);
    - regimes(可选,显式):[[direction, strength_bps, length_bars], ...]
      供 regime 顺序随机化反事实使用;缺省时随机生成;
    - n_regimes_range / regime_len_range / direction_weights /
      drift_bps_range / vol_bps_range / initial_price / wick_fraction。

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
    nuisance_slot_names = tuple(PROBE_NUISANCE_SLOTS)

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

    隐藏状态:latent_drift_bps(连续值,仅 Oracle 与评估可见)。
    """

    family = "probe_smooth_latent_drift"
    family_version = "probe-B-v1"
    feature_columns = list(PROBE_FEATURE_COLUMNS)
    hidden_columns = ["latent_drift_bps"]
    nuisance_slot_names = tuple(PROBE_NUISANCE_SLOTS)

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


# --------------------------------------------------------------- Null 家族
def _source_probe_a(params: dict[str, Any], seed: int):
    """以相同 (params, seed) 重现探针 A 轨迹(隐藏标签保留)。"""
    probe_a = ProbeSegmentedDriftGenerator()
    src_returns, src_hidden, meta = probe_a._generate(  # noqa: SLF001
        params, seed, np.random.default_rng(probe_a.derive_seed(params, seed))
    )
    return np.asarray(src_returns, dtype=np.float64), src_hidden, meta


_NULL_META_DOC = {
    "probe_null_control": {
        "preserves": "收益精确边际分布(全排列,同一多重集合)",
        "destroys": "全部时序结构:方向、自相关、波动聚集(过度破坏市场结构)",
        "distribution_difference": "边际完全一致,联合分布完全不同",
        "limitations": (
            "阶段 2.6.0 唯一 Null;保留为探针。正式 Null 结论不得只依赖"
            "全排列——它破坏过多市场结构,可能让模型'识别表面形态'"),
    },
    "probe_null_sign": {
        "preserves": (
            "每根 bar 收益的绝对值序列(|r_t| 逐位不变,即波动聚集的幅度"
            "结构保留)与非高斯边际形状"),
        "destroys": "收益符号(方向):任何以历史方向预测未来方向的线性/非线性关系被切断",
        "distribution_difference": "符号独立重采样;|r| 序列与源一致",
        "limitations": (
            "保留了幅度结构;若课程能力依赖'波动率本身'而非方向,该 Null "
            "不构成检验;与块重排/Fourier 联合使用"),
    },
    "probe_null_block": {
        "preserves": "块内(默认 8 bars)局部收益结构:短程自相关与块内漂移段",
        "destroys": "跨块可预测关系:块顺序随机重排后,块边界处的方向不可预测",
        "distribution_difference": (
            "块切分处若 n 不被块长整除,补零再截断使边际分布有微小差异"),
        "limitations": (
            "块内残存局部趋势,极短周期策略可能仍有微弱优势;块长必须"
            "显著小于 regime 长度才有效"),
    },
    "probe_null_volstate": {
        "preserves": (
            "每个时间槽的波动档位(|r| 滚动三分位 -> 波动聚集在档位分辨率"
            "下保留)与档内 |收益| 多重集合(|r| 边际分布不变)"),
        "destroys": (
            "方向/漂移可预测性:档内置换打乱时序后叠加独立符号翻转,"
            "符号与隐藏标签、与历史方向独立(Oracle 优势被切断)"),
        "distribution_difference": (
            "|r| 边际一致;带符号边际经符号随机化(对称化)"),
        "limitations": (
            "档内相邻短程的 |r| 模式部分残存;三分位边界归档噪声;"
            "波动代理窗口(默认 12 bars)内的估计误差"),
    },
}


class _ProbeNullBase(BaseMarketGenerator):
    """Null 家族公共基类:探针 A 源轨迹 + 变换钩子 + 文档化 meta。"""

    feature_columns = list(PROBE_FEATURE_COLUMNS)
    hidden_columns = list(ProbeSegmentedDriftGenerator.hidden_columns)
    is_null_family = True
    nuisance_slot_names = tuple(PROBE_NUISANCE_SLOTS)

    #: 变换说明(子类覆盖;写入 episode.meta)
    transform_note: str = ""

    def _transform_returns(
        self, returns: np.ndarray, params: dict[str, Any],
        rng: np.random.Generator,
    ) -> np.ndarray:
        raise NotImplementedError

    def _generate(self, params, seed, rng):
        n = int(params.get("episode_bars", 96))
        if n < 12:
            raise GeneratorError(f"episode_bars 过短: {n}")
        src_returns, src_hidden, _meta = _source_probe_a(params, seed)
        if len(src_returns) != n:
            raise GeneratorError(
                f"源轨迹长度 {len(src_returns)} != episode_bars {n}")
        returns = self._transform_returns(src_returns, params, rng)
        doc = _NULL_META_DOC.get(self.family, {})
        meta = {
            "mode": self.family,
            "episode_bars": n,
            "predictability": "cut",
            "null_doc": doc,
            "transform": self.transform_note,
        }
        return returns, src_hidden, meta

    def _attach_features(self, df):
        return _attach_probe_features(df)


class ProbeNullControlGenerator(_ProbeNullBase):
    """探针 C:全排列 Null(保留为探针;见 _NULL_META_DOC 的局限性声明)。"""

    family = "probe_null_control"
    family_version = "probe-C-v1"
    transform_note = "returns = rng.permutation(source_returns)"

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
            meta = {"mode": mode, "episode_bars": n, "predictability": "cut"}
        else:
            src_returns, src_hidden, _m = _source_probe_a(params, seed)
            returns = rng.permutation(src_returns)
            hidden = src_hidden
            meta = {
                "mode": "shuffle_probe_a", "episode_bars": n,
                "predictability": "cut(returns phase-randomized;hidden labels kept)",
                "null_doc": _NULL_META_DOC["probe_null_control"],
                "transform": self.transform_note,
            }
        return returns, hidden, meta


class ProbeNullSignGenerator(_ProbeNullBase):
    """正式 Null 家族 1:符号随机化(方向随机化,保留 |收益| 与波动聚集)。"""

    family = "probe_null_sign"
    family_version = "probe-null-sign-v1"
    transform_note = "returns = source_returns * iid_sign(+-1)"

    def _transform_returns(self, returns, params, rng):
        signs = rng.choice(np.asarray([-1.0, 1.0]), size=len(returns))
        return np.asarray(returns, dtype=np.float64) * signs


class ProbeNullBlockShuffleGenerator(_ProbeNullBase):
    """正式 Null 家族 2:分块重排(块内结构保留,块顺序随机)。"""

    family = "probe_null_block"
    family_version = "probe-null-block-v1"
    transform_note = "returns = block_shuffle(source_returns, block_size)"

    def _transform_returns(self, returns, params, rng):
        block = int(params.get("null_block_size", 8))
        if block < 2:
            raise GeneratorError(f"null_block_size 必须 >= 2,收到 {block}")
        n = len(returns)
        n_blocks = int(math.ceil(n / block))
        pad = n_blocks * block - n
        padded = np.concatenate([
            np.asarray(returns, dtype=np.float64), np.zeros(pad)])
        blocks = padded.reshape(n_blocks, block)
        order = rng.permutation(n_blocks)
        return blocks[order].reshape(-1)[:n]


class ProbeNullVolStateShuffleGenerator(_ProbeNullBase):
    """正式 Null 家族 3:波动状态条件方向随机化(方向 1 实现)。

    构造:按因果滚动波动代理(|r| 滚动均值)把时间槽分为三分位档;
    档内置换收益后叠加独立符号翻转。
    保留:每个时间槽的波动档位(波动聚集在三分位分辨率下保留)与
    档内 |收益| 多重集合;破坏:方向/漂移可预测性(符号与隐藏标签、
    与历史方向独立)。

    验证记录:仅做档内置换时,Oracle 保留稳定正超额(桶与 regime
    强度相关 -> 置换非符号盲);叠加符号随机化后切断。另:阶段
    2.6.0a 曾实现 Fourier 相位替身,验证发现规则趋势基线在其上仍有
    稳定正超额——相位随机化保留自协方差(线性可预测性),对自相关源
    不构成"无信号"Null,按任务书对 surrogate 方法的验证要求被否决
    (见报告多 Null 一节)。
    """

    family = "probe_null_volstate"
    family_version = "probe-null-volstate-v2"
    transform_note = (
        "returns = iid_sign * within-volatility-tercile permutation(source)")

    def _transform_returns(self, returns, params, rng):
        r = np.asarray(returns, dtype=np.float64)
        w = int(params.get("null_vol_window", 12))
        if w < 2:
            raise GeneratorError(f"null_vol_window 必须 >= 2,收到 {w}")
        vol_proxy = pd.Series(np.abs(r)).rolling(
            w, min_periods=1).mean().to_numpy()
        q1, q2 = np.quantile(vol_proxy, [1.0 / 3.0, 2.0 / 3.0])
        buckets = (
            np.where(vol_proxy <= q1)[0],
            np.where((vol_proxy > q1) & (vol_proxy <= q2))[0],
            np.where(vol_proxy > q2)[0],
        )
        out = r.copy()
        for idx in buckets:
            if len(idx) == 0:
                continue
            out[idx] = rng.permutation(r[idx])
        # 方向随机化:符号与(保留的)隐藏标签、与历史方向独立
        signs = rng.choice(np.asarray([-1.0, 1.0]), size=len(out))
        return out * signs


# 正式 Null 家族集合(结论必须跨家族一致;全排列 probe_null_control
# 保留为探针,不计入正式多 Null 一致性要求的最小集合)
FORMAL_NULL_FAMILIES: tuple[str, ...] = (
    "probe_null_sign", "probe_null_block", "probe_null_volstate",
)


# 生成器注册表(评估器/考试包按 family 名解析)
DEFAULT_GENERATOR_REGISTRY: dict[str, BaseMarketGenerator] = {
    g.family: g for g in (
        ProbeSegmentedDriftGenerator(),
        ProbeSmoothLatentDriftGenerator(),
        ProbeNullControlGenerator(),
        ProbeNullSignGenerator(),
        ProbeNullBlockShuffleGenerator(),
        ProbeNullVolStateShuffleGenerator(),
    )
}
