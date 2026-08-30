"""阶段 2.6.1 repair 工作包 R1:课程 observation 切换到冻结生产路径。

上一轮 qualification(FAIL,commit c6e37af)的 Blocker A:课程实际使用
旧课程自制 11 特征 schema,而生产 Route C 的 policy
observation 是:

    OHLCV
      -> RouteCStrategy.feature_engineering_standard(生产特征构造,
         8 列:%-ret-1 / %-ret-4 / %-vol-24 / %-price-ma-ratio /
         %-raw_open / %-raw_high / %-raw_low / %-raw_close)
      -> BaseReinforcementLearningModel.train 的 data_dictionary[
         "train_features"](列集合与顺序即策略赋值序)
      -> AlignedLongFlatEnv(features=..., window_size=CONV_WIDTH=1)
      -> observation = [特征行, 仓位槽位](ObservationSpec-v1)

本模块把课程生成器的特征源与 observation schema 切换为上述生产路径:

- attach_production_features:直接调用真实 RouteCStrategy 的
  feature_engineering_standard(本仓库 user_data/strategies/
  RouteCStrategy.py 的生产代码本体,绝不重新实现);
- production_observation_schema:与生产 train_features 逐列同名的
  ObservationSchema(8 特征 + window 1 + target_position 槽位);
- route_c_strategy_identity / production_observation_identity:
  生产特征构造代码的身份哈希(文件字节 + 函数源码),进入
  qualification plan 与 final qualification artifact;
- assert_production_observation_binding:防回退守卫——对拍 episode
  特征列与生产代码的独立重算结果,任一不一致即 fail closed。

与生产的两处显式口径差异(记录于 plan 与报告,不属于 observation
构造合同):

1. FreqAI feature_pipeline 的 MinMaxScaler((-1,1)) 是训练窗统计的
   数据准备步骤(每训练窗 fit、推理期 transform),不属于
   ObservationSpec-v1 的 observation 构造合同(env.py 冻结的合同只是
   "特征窗口展平 + 仓位槽位");且单 episode 内用全序列统计做缩放
   会把未来信息引入 observation(前缀因果性破坏)。因此课程以未缩放
   因果特征构造 observation,与 2.6.0 泛化审计 evaluator 同一惯例。
   价格水平取 O(1)(initial_price=1.0)保证 raw_* 特征落在冻结环境
   observation_space Box(-10, 10) 内;
2. 生产管线以 startup_candle_count 丢弃 rolling(24) 的暖修行;
   课程 episode 是独立短窗,以 fillna(0.0) 保留暖修行(因果:只用
   过去),t >= 24 后与生产逐位一致。
"""

from __future__ import annotations

import hashlib
import importlib.util
import inspect
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from rl_curriculum.generator_api import PRICE_COLUMNS
from rl_curriculum.observation_schema import FeatureSpec, ObservationSchema

#: 课程级 production observation schema 版本(区别于环境核心
#: ObservationSpec-v1 与已废弃的旧课程自制 schema)
PRODUCTION_OBS_SCHEMA_VERSION = "route-c-production-obs-v1"

#: 生产特征列(顺序 = RouteCStrategy.feature_engineering_standard 的
#: 赋值序 = BaseReinforcementLearningModel.train_features 的列序)。
#: available_at / max_history_bars 由各特征定义直接给出。
PRODUCTION_FEATURE_COLUMNS: tuple[str, ...] = (
    "%-ret-1",          # close.pct_change()(1 bar)
    "%-ret-4",          # close.pct_change(4)
    "%-vol-24",         # ret-1.rolling(24).std()
    "%-price-ma-ratio",  # close / close.rolling(24).mean() - 1
    "%-raw_open",
    "%-raw_high",
    "%-raw_low",
    "%-raw_close",
)

#: 每个特征的因果窗口(bars;raw_* 为 1,vol-24/price-ma-ratio 为 24)
_PRODUCTION_FEATURE_HISTORY: dict[str, int] = {
    "%-ret-1": 1, "%-ret-4": 4, "%-vol-24": 24, "%-price-ma-ratio": 24,
    "%-raw_open": 1, "%-raw_high": 1, "%-raw_low": 1, "%-raw_close": 1,
}

#: 生产策略文件路径(项目根/user_data/strategies/RouteCStrategy.py)
def route_c_strategy_path() -> Path:
    """生产 RouteCStrategy 的绝对路径(从 rl_curriculum 包位置推导)。"""
    import rl_curriculum

    root = Path(rl_curriculum.__file__).resolve().parents[2]
    return root / "user_data" / "strategies" / "RouteCStrategy.py"


_STRATEGY_CLASS_CACHE: dict[str, Any] = {}


class _NoSelf:
    """免实例化调用生产特征函数的占位 self。

    feature_engineering_standard 不触碰 self(已由守卫测试对拍证明),
    以占位对象显式传入 self 即可在不构造 IStrategy 实例(不触发
    hyperopt 参数文件加载等 freqtrade runtime 行为)的前提下执行
    生产代码本体。
    """


def load_route_c_strategy_class() -> type:
    """加载真实 RouteCStrategy 类(惰性,模块级缓存)。

    feature_engineering_standard 不触碰实例状态,加载类即可调用
    (无需实例化、无需 freqtrade runtime 配置)。
    """
    if "cls" in _STRATEGY_CLASS_CACHE:
        return _STRATEGY_CLASS_CACHE["cls"]
    path = route_c_strategy_path()
    if not path.is_file():
        raise FileNotFoundError(
            f"生产 RouteCStrategy 不存在: {path}(production observation "
            f"路径必须绑定真实生产代码,缺失即 fail closed)")
    spec = importlib.util.spec_from_file_location(
        "_route_c_strategy_production_load", path)
    if spec is None or spec.loader is None:  # pragma: no cover - 防御
        raise ImportError(f"无法加载生产 RouteCStrategy: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    cls = getattr(module, "RouteCStrategy", None)
    if cls is None:
        raise ImportError(
            f"{path} 中未找到 RouteCStrategy 类(生产代码结构变化,"
            f"production observation 身份无法绑定)")
    _STRATEGY_CLASS_CACHE["cls"] = cls
    return cls


def route_c_strategy_identity() -> dict[str, str]:
    """生产特征构造代码身份(文件字节 + 函数源码哈希)。

    进入 qualification plan(code_identity)与 final qualification
    artifact;final 运行时复算比对,防止运行间隙生产代码被修改。
    """
    path = route_c_strategy_path()
    cls = load_route_c_strategy_class()
    src = inspect.getsource(cls.feature_engineering_standard)
    return {
        "strategy_path": str(path),
        "strategy_file_sha256": hashlib.sha256(
            path.read_bytes()).hexdigest(),
        "feature_engineering_standard_sha256": hashlib.sha256(
            src.encode("utf-8")).hexdigest(),
    }


def attach_production_features(df: pd.DataFrame) -> pd.DataFrame:
    """用真实生产特征构造函数为 episode 附加 8 个生产特征列。

    - 直接调用 RouteCStrategy.feature_engineering_standard(生产本体);
    - rolling/pct_change 的暖机 NaN 以 0 填充(因果;生产为丢暖修行,
      见模块 docstring 的口径差异记录);
    - 返回列 = 原 OHLCV + 8 生产特征列(无任何课程专属特征列)。
    """
    cls = load_route_c_strategy_class()
    base = df.copy()
    out = cls.feature_engineering_standard(_NoSelf(), base, {})
    missing = [c for c in PRODUCTION_FEATURE_COLUMNS if c not in out.columns]
    if missing:
        raise RuntimeError(
            f"生产 feature_engineering_standard 未产出特征列 {missing}"
            f"(生产代码与冻结特征清单不一致,fail closed)")
    for c in PRODUCTION_FEATURE_COLUMNS:
        out[c] = out[c].fillna(0.0).astype(np.float64)
    return out


def production_observation_schema() -> ObservationSchema:
    """生产 observation schema(与生产 train_features 逐列同名)。"""
    feats = tuple(
        FeatureSpec(
            name=name, available_at="close_of_bar_t",
            max_history_bars=_PRODUCTION_FEATURE_HISTORY[name],
            signal_group="production",
        )
        for name in PRODUCTION_FEATURE_COLUMNS
    )
    return ObservationSchema(
        schema_version=PRODUCTION_OBS_SCHEMA_VERSION,
        features=feats,
        window_size=1,
        dtype="float32",
        includes_cost_context=False,
    )


def production_observation_identity() -> dict[str, Any]:
    """production observation 完整身份(schema + 生产代码 + 环境合同)。"""
    from rl_platform.versions import (
        ENV_CORE_VERSION,
        OBSERVATION_SPEC_VERSION,
    )

    schema = production_observation_schema()
    identity: dict[str, Any] = dict(route_c_strategy_identity())
    identity.update({
        "schema_version": PRODUCTION_OBS_SCHEMA_VERSION,
        "schema_hash": schema.schema_hash(),
        "feature_columns": list(PRODUCTION_FEATURE_COLUMNS),
        "observation_dim": int(schema.observation_dim),
        "env_core_version": ENV_CORE_VERSION,
        "observation_spec_version": OBSERVATION_SPEC_VERSION,
        "window_size": 1,
    })
    return identity


def assert_production_observation_binding(
    schema: ObservationSchema, df: pd.DataFrame, *,
    context: str = "production_obs_binding",
) -> None:
    """防回退守卫:schema 与特征帧都必须绑定生产路径(fail closed)。

    - schema 必须就是 production_observation_schema()(逐列同名);
    - df 的 8 个特征列必须与"独立重跑生产特征函数"逐位一致
      (证明特征来自生产构造路径,不是课程重新实现);
    - 特征值必须落在冻结环境 observation_space Box(-10, 10) 内
      (initial_price=1.0 的水平合同)。
    任何失败抛 RuntimeError——qualification 入口与守卫测试共用。
    """
    prod = production_observation_schema()
    schema.assert_same_semantics(prod, context=context)
    schema.assert_hash_binding(prod.schema_hash(), context=context)
    ohlcv = df[list(PRICE_COLUMNS)].reset_index(drop=True)
    rebuilt = attach_production_features(ohlcv)
    for col in PRODUCTION_FEATURE_COLUMNS:
        a = df[col].to_numpy(dtype=np.float64)
        b = rebuilt[col].to_numpy(dtype=np.float64)
        if a.shape != b.shape or not np.array_equal(a, b):
            raise RuntimeError(
                f"[{context}] 特征列 {col!r} 与生产路径独立重算不一致:"
                f"课程特征并非来自 RouteCStrategy.feature_engineering_"
                f"standard(production observation binding 失效)")
        if not np.isfinite(a).all():
            raise RuntimeError(
                f"[{context}] 特征列 {col!r} 含非有限值")
        if a.max(initial=0.0) >= 10.0 or a.min(initial=0.0) <= -10.0:
            raise RuntimeError(
                f"[{context}] 特征列 {col!r} 超出冻结环境 "
                f"observation_space Box(-10, 10):"
                f"[{a.min()}, {a.max()}](水平合同 initial_price=1.0 "
                f"被破坏)")
