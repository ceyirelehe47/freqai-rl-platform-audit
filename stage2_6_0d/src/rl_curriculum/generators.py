"""工作包 D + 阶段 2.6.0a 工作包 L + 阶段 2.6.0b 工作包 A/H:审计探针生成器与多类 Null Control。

- 探针 A probe_segmented_drift:分段漂移(横盘/正/负随机段);
- 探针 B probe_smooth_latent_drift:缓慢变化的潜在漂移(OU 过程);
- 探针 C probe_null_control:全排列 Null(保留为探针;阶段 2.6.0 唯一
  Null 构造,正式结论不得只依赖它);
- 严格 Null(阶段 2.6.0b 工作包 H;三种不同机制,全部切断方向预测):
  * probe_null_sign     符号随机化(保留 |收益| 与波动聚集,切断方向);
  * probe_null_volstate 波动状态条件随机化(档内置换+独立符号翻转);
  * probe_null_stochvol 独立实现的随机波动率零漂移市场(马尔可夫波动
    状态切换 + 重尾幅度 + iid 方向;不依赖任何源轨迹变换);
- probe_null_block 分块重排:阶段 2.6.0b 重新分类为
  partial_dependency_destruction(局部结构鲁棒性诊断;保留块内方向
  关系,不得作为"完全无信号 Null"硬门,见 PARTIAL_DEPENDENCY_TESTS)。

Fourier 相位替身在阶段 2.6.0a 验证中被否决:相位随机化保留自协方差
(线性可预测性),趋势规则基线在其上仍有稳定正超额,不构成无信号
Null(见 ProbeNullVolStateShuffleGenerator 备注与主报告)。

可观察特征统一为尺度不变量 ret_1/ret_4/ret_12/vol_24/ma_ratio,外加
预注册 nuisance 槽位 nuisance_0/1/2(独立 counter-hash 噪声,声明语义
"不应含预测信息";固定 observation 维度,反事实考试只改槽位内容,
不新增列)。vol_24 是正式市场特征,不再被硬编码为"无关特征"。

每个 Null 家族在 meta 中记录:保留了哪些统计性质 / 破坏了哪些预测
关系 / 与源环境的分布差异 / 局限性。严格 Null 进入正式最小集合前
必须通过 null_qualification 资格审查(独立于本模块运行)。
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
from rl_curriculum.param_resolution import resolve_generator_params

PROBE_MARKET_FEATURES = ["ret_1", "ret_4", "ret_12", "vol_24", "ma_ratio"]
PROBE_NUISANCE_SLOTS = ["nuisance_0", "nuisance_1", "nuisance_2"]
PROBE_FEATURE_COLUMNS = PROBE_MARKET_FEATURES + PROBE_NUISANCE_SLOTS


def effective_params_of(
    params: dict[str, Any], timeframe: str,
) -> dict[str, Any]:
    """反事实重建使用的 resolved effective params(与 generate() 一致)。

    nuisance counter-hash 与 OHLCV wick 噪声都按 effective params 派生;
    任何重建路径(拼接/镜像/收益替换)必须用本函数解析,否则共同
    前缀一致性检查会暴露不一致。
    """
    return resolve_generator_params(params, timeframe).effective_params


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
    """nuisance 槽位逐行 counter-hash 噪声(与 BaseMarketGenerator 共用公式)。

    params 必须是 resolved effective params(generate() 侧由统一解析
    产生;重建侧由 effective_params_of 产生)。
    """
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
    params: dict[str, Any], seed: int, timeframe: str,
) -> pd.DataFrame:
    """从价格列重算探针特征 + nuisance 槽位(前缀逐位一致;白名单齐整)。

    阶段 2.6.0b:params 为原始 spec 参数;内部经 effective_params_of
    统一解析(与 generate() 相同通道),保证 nuisance counter-hash 一致。
    """
    keep = [c for c in df.columns
            if c in ("date", "open", "high", "low", "close", "volume")]
    out = _attach_probe_features(
        df[keep].copy().reset_index(drop=True)
    )
    return fill_nuisance_slots(
        out, family=family, family_version=family_version,
        params=effective_params_of(params, timeframe), seed=seed,
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
    阶段 2.6.0b:使用与原生成相同的 resolved effective params。
    """
    effective = effective_params_of(
        source.spec.params, source.spec.timeframe)
    rng = np.random.default_rng(
        generator.derive_seed(effective, source.spec.seed)
    )
    params = dict(effective)
    params["initial_price"] = float(source.df["open"].iloc[0])
    df = generator._build_ohlcv(new_returns, params, rng)  # noqa: SLF001
    df = _attach_probe_features(df)
    df = fill_nuisance_slots(
        df, family=source.spec.family,
        family_version=source.family_version,
        params=effective, seed=source.spec.seed,
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

    参数(真实时间由统一解析物化,见 param_resolution):
    - episode_bars / duration_hours:Episode 长度(generate() 统一注入);
    - regime_duration_hours_range(可选):regime 持续时长范围(小时)
      -> regime_len_range(bars);
    - regimes(可选,显式):[[direction, strength_bps, length_bars], ...]
      供 regime 顺序随机化反事实使用;缺省时随机生成;
    - n_regimes_range / regime_len_range / direction_weights /
      drift_bps_range / vol_bps_range / initial_price / wick_fraction。

    隐藏状态:regime_direction / regime_strength_bps /
    bars_to_regime_end / regime_index(仅 Oracle 与评估可见)。
    """

    family = "probe_segmented_drift"
    family_version = "probe-A-v2"
    feature_columns = list(PROBE_FEATURE_COLUMNS)
    hidden_columns = [
        "regime_direction", "regime_strength_bps", "bars_to_regime_end",
        "regime_index",
    ]
    nuisance_slot_names = tuple(PROBE_NUISANCE_SLOTS)

    def _generate(self, params, seed, rng):
        n = int(params["episode_bars"])  # 统一解析注入;缺键即失败
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
        """按 regime_len_range(可由真实时长字段解析)严格生成段长。

        阶段 2.6.0b 工作包 A:段长一律取自 [lo_len, hi_len](声明即物化);
        不足一整段的余量(remaining < lo_len)并入上一段(轻微超上界,
        记录在 meta)。n_regimes_range 仅作元信息,不再驱动"一大段兜底"。
        """
        lo_len, hi_len = params.get("regime_len_range", [12, 40])
        lo_len, hi_len = int(lo_len), int(hi_len)
        weights = np.asarray(
            params.get("direction_weights", [0.3, 0.35, 0.35]), dtype=float
        )
        d_lo, d_hi = params.get("drift_bps_range", [18.0, 30.0])
        regimes: list[list] = []
        total = 0
        while total < n:
            remaining = n - total
            if remaining < lo_len and regimes:
                regimes[-1][2] += remaining  # 余量并入上一段
                total = n
                break
            seg_hi = min(hi_len, remaining)
            length = int(rng.integers(lo_len, seg_hi + 1)) \
                if seg_hi >= lo_len else remaining
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
    family_version = "probe-B-v2"
    feature_columns = list(PROBE_FEATURE_COLUMNS)
    hidden_columns = ["latent_drift_bps"]
    nuisance_slot_names = tuple(PROBE_NUISANCE_SLOTS)

    def _generate(self, params, seed, rng):
        n = int(params["episode_bars"])
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
    """以相同 (params, seed) 重现探针 A 轨迹(隐藏标签保留)。

    阶段 2.6.0b:params 必须是 resolved effective params(与 generate()
    注入的一致);Null 变换与源轨迹在同一 effective 参数下重算。
    """
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
            "不构成检验;与独立随机波动率 Null 联合使用"),
    },
    "probe_null_block": {
        "classification": (
            "partial_dependency_destruction(阶段 2.6.0b 重新分类:"
            "保留块内趋势与短周期方向关系,只是跨块关系被破坏;"
            "不是完全无信号 Null)"),
        "preserves": "块内(默认 8 bars)局部收益结构:短程自相关与块内漂移段",
        "destroys": "跨块可预测关系:块顺序随机重排后,块边界处的方向不可预测",
        "distribution_difference": (
            "块切分处若 n 不被块长整除,补零再截断使边际分布有微小差异"),
        "limitations": (
            "块内残存局部趋势与方向关系:短周期策略可在其上获利;"
            "仅可用于诊断模型依赖长期关系还是短期关系,"
            "不得作为正式 Null 硬门(required_null_families 不含本族)"),
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
    "probe_null_stochvol": {
        "preserves": (
            "波动率聚集(马尔可夫波动状态切换的自相关结构)与重尾收益"
            "边际(标准化 t 分布自由度 4);与真实市场类似的波动状态持续性"),
        "destroys": (
            "全部方向可预测性:零漂移 + iid 对称符号;任何以历史方向/"
            "波动状态预测未来方向的线性/非线性关系被切断"),
        "distribution_difference": (
            "独立实现,不从任何源轨迹变换:收益边际是对称重尾混合,"
            "波动状态由三态马尔可夫链驱动"),
        "limitations": (
            "波动状态本身可预测(这是保留的结构);若课程能力是"
            "'波动率择时'而非方向择时,方向 Null 不构成其检验;"
            "与符号随机化/波动状态条件随机化联合覆盖"),
        "independence": (
            "实现机制与前两族不同:不依赖 probe A 源轨迹,"
            "不依赖置换/符号翻转变换——收益过程直接由状态切换"
            "波动率 + 重尾 iid 增量构造"),
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
        n = int(params["episode_bars"])
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
    family_version = "probe-C-v2"
    transform_note = "returns = rng.permutation(source_returns)"

    def _generate(self, params, seed, rng):
        n = int(params["episode_bars"])
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
    family_version = "probe-null-sign-v2"
    transform_note = "returns = source_returns * iid_sign(+-1)"

    def _transform_returns(self, returns, params, rng):
        signs = rng.choice(np.asarray([-1.0, 1.0]), size=len(returns))
        return np.asarray(returns, dtype=np.float64) * signs


class ProbeNullBlockShuffleGenerator(_ProbeNullBase):
    """块重排:partial_dependency_destruction(阶段 2.6.0b 重新分类)。

    保留块内局部结构(块内趋势/短程方向关系残存),破坏跨块关系。
    用途:诊断考试(模型依赖长期关系还是短期关系;跨块关系破坏后的
    性能变化)。不得进入 required_null_families(不是完全无信号 Null),
    其上获利的短周期策略不构成 Null 作弊证据。
    """

    family = "probe_null_block"
    family_version = "probe-null-block-v2"
    is_null_family = False  # 诊断族,不是严格 Null
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
    """正式 Null 家族 2:波动状态条件方向随机化。

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


class ProbeNullStochasticVolGenerator(BaseMarketGenerator):
    """正式 Null 家族 3:独立实现的随机波动率零漂移市场(H2 第三机制)。

    与前两族实现完全不同——不从任何源轨迹变换,收益过程直接构造:

    - 波动状态:三态(low/mid/high)马尔可夫链,粘性转移矩阵
      (对角概率高 -> 波动率聚集,状态持续性可预测);
    - 幅度:vol_state * 标准化 t(自由度 4)增量 -> 重尾边际;
    - 方向:iid 对称(零漂移,符号独立同分布);
    - 隐藏状态:当前波动状态(仅供审计;方向恒为 0,对 Oracle 无
      方向信息)。

    切断:一切方向可预测性(零漂移 + iid 符号)。
    保留:波动率聚集(状态自相关)与重尾边际(真实市场常见特征)。
    """

    family = "probe_null_stochvol"
    family_version = "probe-null-stochvol-v1"
    feature_columns = list(PROBE_FEATURE_COLUMNS)
    hidden_columns = [
        "regime_direction", "regime_strength_bps", "bars_to_regime_end",
        "regime_index",
    ]
    is_null_family = True
    nuisance_slot_names = tuple(PROBE_NUISANCE_SLOTS)

    #: 三态波动率(bps)与粘性转移矩阵
    VOL_STATES_BPS: tuple[float, float, float] = (12.0, 24.0, 48.0)
    STICKY_PROB: float = 0.92

    def _generate(self, params, seed, rng):
        n = int(params["episode_bars"])
        if n < 12:
            raise GeneratorError(f"episode_bars 过短: {n}")
        vols = np.asarray(
            params.get("stochvol_states_bps", self.VOL_STATES_BPS),
            dtype=float,
        ) * 1e-4
        if vols.shape != (3,) or np.any(vols <= 0):
            raise GeneratorError(
                f"stochvol_states_bps 必须为三个正数(bps),收到 {vols}")
        sticky = float(params.get("stochvol_sticky_prob", self.STICKY_PROB))
        if not (0.5 < sticky < 1.0):
            raise GeneratorError(
                f"stochvol_sticky_prob 必须在 (0.5, 1.0),收到 {sticky}")
        t_df = float(params.get("stochvol_t_df", 4.0))
        if t_df <= 2.0:
            raise GeneratorError(
                f"stochvol_t_df 必须 > 2(方差有限的重尾),收到 {t_df}")
        # 马尔可夫状态链(粘性:留在原状态 sticky,否则均匀跳到其他两态)
        states = np.empty(n, dtype=int)
        states[0] = int(rng.integers(0, 3))
        for t in range(1, n):
            if rng.random() < sticky:
                states[t] = states[t - 1]
            else:
                others = [s for s in (0, 1, 2) if s != states[t - 1]]
                states[t] = int(others[int(rng.integers(0, len(others)))])
        # 重尾 iid 增量(标准化 t:方差为 1)+ 零漂移
        # 标准化: t_sample / sqrt(df/(df-2))
        scale = math.sqrt(t_df / (t_df - 2.0))
        increments = rng.standard_t(t_df, size=n) / scale
        returns = vols[states] * increments  # 符号 iid 对称,零漂移
        # 隐藏状态:波动状态(方向恒 0——本族无方向信息)
        to_end = np.empty(n, dtype=int)
        run_start = 0
        for t in range(n):
            if t + 1 >= n or states[t + 1] != states[t]:
                to_end[run_start:t + 1] = np.arange(t - run_start, -1, -1)
                run_start = t + 1
        hidden = pd.DataFrame(
            {
                "regime_direction": np.zeros(n, dtype=int),
                "regime_strength_bps": np.zeros(n),  # 零漂移:无方向强度
                "bars_to_regime_end": to_end,
                "regime_index": states.astype(int),
            }
        )
        meta = {
            "mode": self.family,
            "episode_bars": n,
            "predictability": "cut(zero drift + iid symmetric signs)",
            "null_doc": _NULL_META_DOC[self.family],
            "vol_states_bps": [float(v / 1e-4) for v in vols],
            "sticky_prob": sticky,
            "t_df": t_df,
        }
        return returns, hidden, meta

    def _attach_features(self, df):
        return _attach_probe_features(df)


# 正式严格 Null 家族集合(结论必须跨家族一致;H2:三种不同机制,
# 全部切断方向预测能力,且必须先通过 null_qualification 资格审查)。
# probe_null_block 已重新分类为 partial_dependency_destruction,
# 不在严格集合中(见 PARTIAL_DEPENDENCY_TESTS)。
FORMAL_NULL_FAMILIES: tuple[str, ...] = (
    "probe_null_sign", "probe_null_volstate", "probe_null_stochvol",
)

# 诊断考试族(保留块内方向关系;只用于局部结构鲁棒性诊断,
# 不构成"完全无信号环境不得盈利"硬门)。全排列为探针。
PARTIAL_DEPENDENCY_TESTS: tuple[str, ...] = ("probe_null_block",)
PROBE_ONLY_NULLS: tuple[str, ...] = ("probe_null_control",)


# 生成器注册表(评估器/考试包按 family 名解析)
DEFAULT_GENERATOR_REGISTRY: dict[str, BaseMarketGenerator] = {
    g.family: g for g in (
        ProbeSegmentedDriftGenerator(),
        ProbeSmoothLatentDriftGenerator(),
        ProbeNullControlGenerator(),
        ProbeNullSignGenerator(),
        ProbeNullBlockShuffleGenerator(),
        ProbeNullVolStateShuffleGenerator(),
        ProbeNullStochasticVolGenerator(),
    )
}
