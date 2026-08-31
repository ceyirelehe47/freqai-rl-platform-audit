"""阶段 2.6.1 Repair R3:RouteCFeaturePreprocessing-v1 预处理合同(WP-A/B)。

R2 已证明(Stage 2.6.2 Repair R2 Diagnostics,C1=Branch B):causal
unscaled observation 的输入尺度支配是 C1 的正式合同 blocker。本轮把
preprocessing 从 2.6.2 diagnostic arm 升级为阶段 2.6.1 正式、版本化、
可序列化、可资格审查的输入合同。

完整路径(与 pinned FreqAI production 数值一致):

    Synthetic OHLCV
      -> RouteCStrategy.feature_engineering_standard(8 列,不变)
      -> ordered production feature columns
      -> fitted-and-frozen preprocessing(本模块,fit 于完整训练
         manifest 的全部 policy-visible feature rows,fit 后冻结)
      -> append unchanged position slot(env._observation,合同不变)
      -> frozen Route C observation layout(dim=9)
      -> reference / baseline / PPO

正式合同 RouteCFeaturePreprocessing-v1 的要素(全部机器可验证,不只
写在 README):

- pipeline implementation identity:直接复用 pinned vendor 的
  IFreqaiModel.define_data_pipeline builder(本模块不重新实现 scaler,
  只做 fit/freeze/serialize/identity 包装);
- runtime config identity:参数来自当前正式 Route C runtime config
  (stage252a 收官 config);
- ordered input columns:PRODUCTION_FEATURE_COLUMNS(策略赋值序);
- retained feature mask:VarianceThreshold(0) 的 get_support;
- fitted state:纯数据(min/max/scale 等),可 JSON 序列化;
- output column order:retained 原列序;
- output dtype:float64(datasieve Pipeline 语义);
- position-slot handling:不参与 fit、不缩放、env 追加为第 9 维;
- observation-space contract:production MinMaxScaler 不 clip,
  eval 越界值线性外推(允许 |x|>1);
- fit manifest hash / serialization hash:state_hash。

fit 协议(offline training-corpus fit -> frozen deployment transform):
一个训练 run -> 一个完整 training episode multiset -> 一个统一
preprocessor -> C1/C2/C3 全部共享。fit 允许读完整训练 manifest,
禁止读 dev/final/qualification corpus、latent truth 与未来数据。
fit 对 manifest 行序不敏感(staged/mixed 同 multiset 必得同 state)。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from rl_curriculum.curriculum261_production_obs import (
    PRODUCTION_FEATURE_COLUMNS,
    PRODUCTION_RUNTIME_CONFIG_REL,
    production_runtime_config_identity,
    route_c_strategy_identity,
)

#: 正式预处理合同版本(R3 冻结语义名)。
ROUTE_C_FEATURE_PREPROCESSING_VERSION = "RouteCFeaturePreprocessing-v1"

#: fit state 序列化格式版本(与合同版本同步演进)。
PREPROCESSING_STATE_FORMAT = "r3-route-c-feature-preprocessing-state-v1"

#: position slot 合同(第 9 维;不参与 fit/不缩放/不 clip)。
POSITION_SLOT_SEMANTICS = {
    "index": 8,
    "values": "0=Flat,1=Long",
    "participates_in_fit": False,
    "scaled": False,
    "clipped": False,
    "appended_by": "rl_platform.env.AlignedLongFlatEnv._observation",
}

#: 生产 scaler 不 clip:transform 对超出 train min/max 的值线性外推。
PRODUCTION_SCALER_CLIPS = False

#: 观察空间语义:production 不 clip -> 允许越界;正式声明沿用生产 env
#: 冻结 layout Box(-10, 10)(float32),containment 以实测验证。
OBSERVATION_SPACE_SEMANTICS = {
    "low": -10.0,
    "high": 10.0,
    "dtype": "float32",
    "dim": 9,
    "clip_by_pipeline": False,
    "out_of_train_range": "linear extrapolation beyond [-1, 1]; "
                          "containment validated empirically per corpus",
    "position_slot": "[0, 1] semantic, appended unscaled",
}


def _project_root() -> Path:
    import rl_curriculum

    return Path(rl_curriculum.__file__).resolve().parents[2]


def load_production_freqai_info() -> dict[str, Any]:
    """当前正式 Route C runtime config 的 freqai 段(参数事实来源)。"""
    root = _project_root()
    cfg_path = root / PRODUCTION_RUNTIME_CONFIG_REL
    if not cfg_path.is_file():
        raise RuntimeError(f"正式 config 不存在: {cfg_path}")
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    return cfg.get("freqai", {})


def build_vendor_feature_pipeline(
    freqai_info: dict[str, Any] | None = None,
) -> Any:
    """直接复用 pinned vendor 的 production feature-pipeline builder。

    调用 IFreqaiModel.define_data_pipeline 的 vendor 代码本体(未绑定
    方式 + 最小 shim 提供 freqai_info),不重新实现任何 scaler。参数
    来自真实 runtime config —— 当前 Route C 配置下
    PCA/SVM/DI/DBSCAN/noise 全部关闭,pipeline 恰为两步:

        ds.VarianceThreshold(threshold=0)
        -> SKLearnWrapper(MinMaxScaler(feature_range=(-1, 1)))
    """
    from freqtrade.freqai.freqai_interface import IFreqaiModel

    if freqai_info is None:
        freqai_info = load_production_freqai_info()

    class _Shim:
        """只为 vendor builder 提供 self.freqai_info 的最小载体。"""

        def __init__(self, info: dict[str, Any]) -> None:
            self.freqai_info = info

    return IFreqaiModel.define_data_pipeline(_Shim(freqai_info), threads=-1)


def production_preprocessing_audit() -> dict[str, Any]:
    """WP-A:pinned vendor + runtime config 的 preprocessing 事实审计。

    全部字段从实际文件/对象读取(不假设);若真实路径与预期不同,
    以本函数记录的事实为准。
    """
    import sklearn
    import datasieve
    import datasieve.transforms as ds
    from sklearn import feature_selection as fs
    from sklearn.preprocessing import MinMaxScaler

    root = _project_root()
    freqai_info = load_production_freqai_info()
    fp = freqai_info.get("feature_parameters", {})
    rl = freqai_info.get("rl_config", {})

    pipeline_src = root / "vendor" / "freqtrade" / "freqtrade" / "freqai" / (
        "freqai_interface.py")
    rl_model_src = root / "vendor" / "freqtrade" / "freqtrade" / "freqai" / (
        "RL") / "BaseReinforcementLearningModel.py"

    # 用 vendor builder 实际构造一次,读取真实 steps
    pipeline = build_vendor_feature_pipeline(freqai_info)
    steps = [(name, type(step).__name__) for name, step in pipeline.steps]

    # 行为探测:MinMaxScaler(-1,1) 是否 clip(超出 train range 的值)
    probe_fit = pd.DataFrame(
        {"a": [0.0, 1.0, 2.0, 3.0], "b": [-5.0, -4.0, -4.0, -4.0]})
    probe = MinMaxScaler(feature_range=(-1, 1)).fit(
        probe_fit.to_numpy(dtype=np.float64))
    transformed = probe.transform(np.array([[10.0, -4.0]]))
    scaler_clips = bool(abs(float(transformed[0, 0])) <= 1.0)

    vt = ds.VarianceThreshold(threshold=0)
    zero_var_fit = pd.DataFrame(
        {"keep": [1.0, 2.0, 3.0, 4.0], "const": [7.0, 7.0, 7.0, 7.0]})
    vt.fit(zero_var_fit.to_numpy(), feature_list=list(
        zero_var_fit.columns))
    zero_var_removed = [str(c) for c in np.asarray(
        list(zero_var_fit.columns))[~np.asarray(vt.mask, dtype=bool)]]

    return {
        "format": "cur261-r3-production-preprocessing-audit-v1",
        "config_path": str((root / PRODUCTION_RUNTIME_CONFIG_REL
                            ).relative_to(root)),
        "config_sha256": hashlib.sha256(
            (root / PRODUCTION_RUNTIME_CONFIG_REL).read_bytes()
        ).hexdigest(),
        "feature_parameters": {
            "principal_component_analysis": bool(
                fp.get("principal_component_analysis", False)),
            "use_SVM_to_remove_outliers": bool(
                fp.get("use_SVM_to_remove_outliers", False)),
            "use_DBSCAN_to_remove_outliers": bool(
                fp.get("use_DBSCAN_to_remove_outliers", False)),
            "DI_threshold": fp.get("DI_threshold", 0),
            "noise_standard_deviation": fp.get(
                "noise_standard_deviation", 0),
            "shuffle_after_split": bool(fp.get("shuffle_after_split",
                                               False)),
        },
        "rl_config": {
            "drop_ohlc_from_features": bool(
                rl.get("drop_ohlc_from_features", False)),
            "add_state_info": bool(rl.get("add_state_info", False)),
            "model_type": rl.get("model_type", ""),
            "conv_width": freqai_info.get("conv_width"),
        },
        "pipeline_built_from_steps": steps,
        "expected_steps": [
            ("const", "VarianceThreshold"), ("scaler", "SKLearnWrapper")],
        "scaler": {
            "type": "sklearn.preprocessing.MinMaxScaler",
            "feature_range": [-1, 1],
            "clips_out_of_train_range": scaler_clips,
            "probe": {
                "fit_col_a_min_max": [0.0, 3.0],
                "eval_value": 10.0,
                "transformed": float(transformed[0, 0]),
            },
        },
        "variance_threshold": {
            "type": "datasieve.transforms.VarianceThreshold",
            "threshold": 0,
            "semantics": "removes features with variance <= 0 "
                         "(constant columns only)",
            "zero_variance_probe_removed": zero_var_removed,
            "mask_source": "sklearn.feature_selection.VarianceThreshold"
                           ".get_support()",
            "column_order": "retained columns keep original input order",
        },
        "transform_input_contract": {
            "columns_must_equal_fit_input_columns": True,
            "dtype_input": "float64 (pandas -> numpy via Pipeline."
                           "_validate_arguments)",
            "dtype_output": "float64 DataFrame(retained columns)",
        },
        "env_receives": "transform 后 features(BaseReinforcement"
                        "LearningModel.train: feature_pipeline."
                        "fit_transform(train_features) -> set_train_"
                        "and_eval_environments(df=scaled))",
        "position_slot": POSITION_SLOT_SEMANTICS,
        "fit_location_in_production": (
            "BaseReinforcementLearningModel.train, fit 于训练窗 "
            "train_features(production 为每训练窗 fit;R3 合同为完整 "
            "训练 manifest 一次性 fit 后冻结,见合同 docstring)"),
        "source_hashes": {
            "freqai_interface_sha256": hashlib.sha256(
                pipeline_src.read_bytes()).hexdigest(),
            "base_rl_model_sha256": hashlib.sha256(
                rl_model_src.read_bytes()).hexdigest(),
            "route_c_strategy_sha256": route_c_strategy_identity()[
                "strategy_file_sha256"],
            "production_runtime_config_identity":
                production_runtime_config_identity(),
        },
        "library_versions": {
            "scikit_learn": sklearn.__version__,
            "numpy": np.__version__,
            "datasieve": getattr(datasieve, "__version__", "unknown"),
            "datasieve_path": str(Path(datasieve.__file__).parent),
        },
        "vendor_pipeline_builder_reused": True,
    }


class RouteCPreprocessor:
    """正式 RouteCFeaturePreprocessing-v1 preprocessor(fit/freeze)。

    内部持有 vendor builder 构造的 datasieve.Pipeline(直接复用,
    非 adapter 重实现);本类只增加:

    - 统一 fit/冻结协议(offline corpus fit -> frozen transform);
    - 纯参数 fitted state 的序列化/重载/哈希(跨进程确定性);
    - retained 列守卫(8 特征必须全部存活);
    - 逆变换(reference wrapper 用,仅依赖 frozen state)。

    不修改 vendor Pipeline 的任何数值行为。
    """

    def __init__(self, pipeline: Any | None = None) -> None:
        self._pipeline = pipeline if pipeline is not None \
            else build_vendor_feature_pipeline()
        self._input_columns: list[str] = list(PRODUCTION_FEATURE_COLUMNS)
        self._fitted = False

    # ---------------------------------------------------------------- fit
    @classmethod
    def build_and_fit(cls, fit_df: pd.DataFrame) -> "RouteCPreprocessor":
        """构造全新 vendor pipeline 并在 fit_df 上一次性 fit(freeze)。"""
        return cls().fit(fit_df)

    def fit(self, fit_df: pd.DataFrame) -> "RouteCPreprocessor":
        """在完整训练 manifest 的 policy-visible feature rows 上 fit。

        fit_df 必须恰好包含 8 个 production 特征列(列集合一致;行序
        任意 —— VarianceThreshold/MinMax 均为置换不变统计,shuffled
        rows 不改变 fitted state)。position slot 不出现在 fit_df。
        """
        cols = list(fit_df.columns)
        if sorted(cols) != sorted(self._input_columns):
            raise RuntimeError(
                f"fit 输入列 {cols} 与 production 特征列 "
                f"{self._input_columns} 不一致(fail closed)")
        ordered = fit_df[list(self._input_columns)].astype(np.float64)
        if not np.isfinite(ordered.to_numpy()).all():
            raise RuntimeError("fit matrix 含非有限值(fail closed)")
        self._pipeline = build_vendor_feature_pipeline()
        self._pipeline.fit(ordered)
        self._fitted = True
        self._assert_all_retained()
        return self

    def _assert_all_retained(self) -> None:
        retained = list(self.retained_columns)
        if retained != self._input_columns:
            raise RuntimeError(
                f"production VarianceThreshold 删除了特征列:"
                f"retained={retained}(8 特征全部存活是 R3 合同的硬性"
                f"要求;动态 observation dimension 不属于本轮)")

    @property
    def fitted(self) -> bool:
        return self._fitted

    @property
    def retained_columns(self) -> list[str]:
        if not self._fitted:
            raise RuntimeError("preprocessor 未 fit")
        return [str(c) for c in self._pipeline.feature_list]

    @property
    def input_columns(self) -> list[str]:
        return list(self._input_columns)

    # ---------------------------------------------------------- transform
    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        """冻结 transform:8 列 raw -> 8 列 scaled(float64,不 clip)。"""
        if not self._fitted:
            raise RuntimeError("preprocessor 未 fit(fail closed)")
        cols = list(df.columns)
        if sorted(cols) != sorted(self._input_columns):
            raise RuntimeError(
                f"transform 输入列 {cols} 与 production 特征列不一致")
        ordered = df[list(self._input_columns)].astype(np.float64)
        out, _, _ = self._pipeline.transform(ordered)
        return out

    def transform_episode_df(self, episode_df: pd.DataFrame,
                             ) -> pd.DataFrame:
        """把 episode 的 8 个特征列替换为 scaled 值(prices 保留 raw)。

        这是 R3 的 observation 注入点:与 production 一致,env 收到的
        就是 transform 后的 features;OHLCV 价格列不动(成交价格语义
        与 Route C 六项冻结合同不变)。输入可含 date/OHLCV 等非特征
        列(production 的 filter_features 语义:只送特征列进 pipeline)。
        """
        missing = [c for c in self._input_columns
                   if c not in episode_df.columns]
        if missing:
            raise RuntimeError(
                f"episode df 缺少生产特征列 {missing}(fail closed)")
        scaled = self.transform(
            episode_df[list(self._input_columns)])
        out = episode_df.copy()
        for c in self._input_columns:
            out[c] = scaled[c].to_numpy(dtype=np.float64)
        return out

    def inverse_features(self, X_scaled: np.ndarray) -> np.ndarray:
        """对 scaled 特征矩阵做精确仿射逆(retained 列)。

        供 preprocessing-aware reference/baseline wrapper 使用:只依赖
        frozen state(scale_/min_),等价于 vendor MinMaxScaler.
        inverse_transform;VarianceThreshold 在 8/8 全保留时为恒等。
        """
        if not self._fitted:
            raise RuntimeError("preprocessor 未 fit(fail closed)")
        scaler = self._pipeline["scaler"]._skl
        return np.asarray(
            scaler.inverse_transform(np.asarray(X_scaled, dtype=np.float64)),
            dtype=np.float64,
        )

    # ---------------------------------------------------------- fitted 状态
    def fitted_state(self) -> dict[str, Any]:
        """fitted state 的纯数据表示(可 JSON 序列化、可哈希)。"""
        if not self._fitted:
            raise RuntimeError("preprocessor 未 fit")
        vt = self._pipeline["const"]
        scaler = self._pipeline["scaler"]._skl
        state = {
            "format": PREPROCESSING_STATE_FORMAT,
            "contract_version": ROUTE_C_FEATURE_PREPROCESSING_VERSION,
            "input_columns": list(self._input_columns),
            "retained_columns": list(self.retained_columns),
            "variance_threshold": {
                "threshold": 0,
                "mask": [bool(m) for m in np.asarray(vt.mask,
                                                     dtype=bool)],
            },
            "scaler": {
                "type": "sklearn.preprocessing.MinMaxScaler",
                "feature_range": [-1, 1],
                "data_min_": [float(v) for v in scaler.data_min_],
                "data_max_": [float(v) for v in scaler.data_max_],
                "data_range_": [float(v) for v in scaler.data_range_],
                "scale_": [float(v) for v in scaler.scale_],
                "min_": [float(v) for v in scaler.min_],
                "n_samples_seen_": int(np.asarray(
                    scaler.n_samples_seen_).item()),
            },
            "dtype_input": "float64",
            "dtype_output": "float64",
            "clips_out_of_train_range": PRODUCTION_SCALER_CLIPS,
            "position_slot": POSITION_SLOT_SEMANTICS,
        }
        return state

    def state_hash(self) -> str:
        """serialization hash:fitted state canonical JSON 的 sha256。"""
        payload = json.dumps(self.fitted_state(), sort_keys=True,
                             separators=(",", ":"), ensure_ascii=False)
        return "r3pre-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def serialize(self, path: Path) -> None:
        """fit -> serialize:写 fitted state JSON(纯参数,无对象 pickle)。"""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.fitted_state(), indent=2,
                                   ensure_ascii=False), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "RouteCPreprocessor":
        """serialize -> new process reload -> transform(逐位一致)。

        重载不依赖 fit 数据与 cloudpickle:从纯参数重建 vendor
        pipeline(VarianceThreshold 注入 mask/feature_list,MinMaxScaler
        注入 scale_/min_ 等 fitted 属性 —— 二者均为 vendor/库公开
        transform 所用的全部状态)。等价由回归测试证明逐位一致。
        """
        from sklearn import feature_selection as fs
        from sklearn.preprocessing import MinMaxScaler
        import datasieve.transforms as ds
        from datasieve.transforms import SKLearnWrapper

        path = Path(path)
        state = json.loads(path.read_text(encoding="utf-8"))
        if state.get("format") != PREPROCESSING_STATE_FORMAT:
            raise RuntimeError(
                f"state format {state.get('format')!r} != "
                f"{PREPROCESSING_STATE_FORMAT!r}")
        obj = cls()
        obj._input_columns = list(state["input_columns"])

        vt = ds.VarianceThreshold(
            threshold=state["variance_threshold"]["threshold"])
        mask = np.asarray(state["variance_threshold"]["mask"], dtype=bool)
        vt.mask = mask
        vt.feature_list = np.asarray(state["retained_columns"])
        vt._skl = fs.VarianceThreshold(
            threshold=state["variance_threshold"]["threshold"])
        # datasieve VT.transform 只经 self.mask 分支选择列;这里让内部
        # sklearn 对象也处于已 fit 状态并覆写为保存的 mask,使任何直接
        # 调用(get_support 等)与保存状态一致,不依赖原始 fit 数据。
        vt._skl.fit(_identity_probe_matrix(len(state["input_columns"])))
        vt._skl.variances_ = np.where(
            mask, 1.0, 0.0).astype(np.float64)

        sc_state = state["scaler"]
        scaler = MinMaxScaler(
            feature_range=tuple(sc_state["feature_range"]))
        scaler.data_min_ = np.asarray(sc_state["data_min_"],
                                      dtype=np.float64)
        scaler.data_max_ = np.asarray(sc_state["data_max_"],
                                      dtype=np.float64)
        scaler.data_range_ = np.asarray(sc_state["data_range_"],
                                        dtype=np.float64)
        scaler.scale_ = np.asarray(sc_state["scale_"], dtype=np.float64)
        scaler.min_ = np.asarray(sc_state["min_"], dtype=np.float64)
        scaler.n_samples_seen_ = sc_state["n_samples_seen_"]

        steps = [("const", vt), ("scaler", SKLearnWrapper(scaler))]
        obj._pipeline = _pipeline_from_steps(steps, obj._input_columns)
        obj._fitted = True
        obj._assert_all_retained()
        return obj

    # -------------------------------------------------------------- identity
    def identity(self) -> dict[str, Any]:
        """合同完整身份(机器可验证;进 plan 与 final artifact)。"""
        from rl_platform.versions import (
            ENV_CORE_VERSION,
            OBSERVATION_SPEC_VERSION,
        )

        state = self.fitted_state()
        return {
            "contract_version": ROUTE_C_FEATURE_PREPROCESSING_VERSION,
            "builder": "pinned vendor IFreqaiModel.define_data_pipeline"
                       "(直接复用,非 adapter 重实现)",
            "pipeline_steps": [
                "ds.VarianceThreshold(threshold=0)",
                "SKLearnWrapper(MinMaxScaler(feature_range=(-1,1)))",
            ],
            "runtime_config": production_runtime_config_identity(),
            "strategy_identity": route_c_strategy_identity(),
            "input_columns": state["input_columns"],
            "retained_columns": state["retained_columns"],
            "variance_mask": state["variance_threshold"]["mask"],
            "scaler_feature_range": state["scaler"]["feature_range"],
            "output_dtype": state["dtype_output"],
            "clips": PRODUCTION_SCALER_CLIPS,
            "position_slot": POSITION_SLOT_SEMANTICS,
            "observation_space": OBSERVATION_SPACE_SEMANTICS,
            "state_hash": self.state_hash(),
            "env_core_version": ENV_CORE_VERSION,
            "observation_spec_version": OBSERVATION_SPEC_VERSION,
            "observation_dim": 9,
            "fit_protocol": "offline training-corpus fit -> frozen "
                            "deployment transform;无 episode 内/family "
                            "切换/eval refit;无 online normalization",
        }


def _identity_probe_matrix(n_cols: int) -> np.ndarray:
    """满秩小矩阵:让重载的 sklearn VT 处于已 fit 状态(全 True mask)。"""
    return np.linspace(1.0, 2.0, n_cols * 4).reshape(4, n_cols)


def _pipeline_from_steps(steps: list[tuple[str, Any]],
                         input_columns: list[str]) -> Any:
    """用已注入状态的 steps 构造 datasieve.Pipeline(fit 语义关闭)。

    与 vendor Pipeline 的差异仅在:feature_list/features_in 直接取
    保存的 retained/input 列(datasieve Pipeline 在 fit 时记录这些;
    transform 路径只读取它们)。数值行为(列选择/缩放)与 vendor
    pipeline 逐位一致,由回归测试保证。
    """
    from datasieve.pipeline import Pipeline

    pipe = Pipeline(steps=steps)
    pipe.pandas_types = True
    pipe.feature_list = list(_retained_of(steps))
    pipe.features_in = list(input_columns)
    return pipe


def _retained_of(steps: list[tuple[str, Any]]) -> list[str]:
    vt = dict(steps)["const"]
    return [str(c) for c in vt.feature_list]


def numerical_equivalence_report(
    fit_df: pd.DataFrame, eval_df: pd.DataFrame,
) -> dict[str, Any]:
    """§6 数值等价证明:R3 preprocessor vs 独立构造的 vendor pipeline。

    同 fit DataFrame、同 transform DataFrame 下逐位比较;另覆盖:
    独立 eval transform、zero-variance 行为、out-of-range 行为、
    float dtype、serialize/reload 一致性、staged/mixed(shuffled
    rows)order invariance。
    """
    checks: dict[str, Any] = {}

    # 基准:独立 vendor pipeline(不经过 RouteCPreprocessor)
    vendor_pipeline = build_vendor_feature_pipeline()
    ordered_fit = fit_df[list(PRODUCTION_FEATURE_COLUMNS)].astype(
        np.float64)
    vendor_out_train, _, _ = vendor_pipeline.fit_transform(ordered_fit)
    vendor_out_eval, _, _ = vendor_pipeline.transform(
        eval_df[list(PRODUCTION_FEATURE_COLUMNS)].astype(np.float64))

    r3 = RouteCPreprocessor.build_and_fit(ordered_fit)
    r3_train = r3.transform(ordered_fit)
    r3_eval = r3.transform(eval_df)

    checks["train_transform_bitwise_equal"] = bool(
        _df_bitwise_equal(vendor_out_train, r3_train))
    checks["eval_transform_bitwise_equal"] = bool(
        _df_bitwise_equal(vendor_out_eval, r3_eval))
    checks["output_shape"] = list(r3_train.shape)
    checks["retained_columns"] = list(r3_train.columns)
    checks["retained_mask_equal"] = bool(
        list(vendor_pipeline.feature_list) == list(r3_train.columns))
    checks["feature_ordering"] = list(r3_train.columns)
    checks["float_dtype"] = bool(
        str(r3_train.to_numpy().dtype) == "float64")

    # zero-variance 行为:加入常数列的独立 fit(vendor VT 删常数列)
    zv_fit = ordered_fit.copy()
    zv_fit["%-constant_probe"] = 3.25
    vendor_zv = build_vendor_feature_pipeline()
    vz_out, _, _ = vendor_zv.fit_transform(
        zv_fit[list(zv_fit.columns)])
    checks["zero_variance_column_removed_by_vendor"] = bool(
        "%-constant_probe" not in list(vz_out.columns))
    # 正式合同 fit(无探针列)不受影响
    checks["zero_variance_absent_in_contract_fit"] = bool(
        len(r3_train.columns) == 8)

    # out-of-training-range 行为:超出 train min/max 的 eval 值线性外推
    lo = float(np.min(ordered_fit.to_numpy()))
    hi = float(np.max(ordered_fit.to_numpy()))
    span = max(hi - lo, 1e-12)
    beyond = pd.DataFrame({
        c: [hi + 3.0 * span] for c in PRODUCTION_FEATURE_COLUMNS})
    out_beyond = r3.transform(beyond).to_numpy()
    checks["out_of_range_linear_extrapolation"] = bool(
        float(out_beyond.max()) > 1.0)
    checks["out_of_range_value"] = float(out_beyond.max())
    checks["clip_behavior_matches_production"] = bool(
        (float(out_beyond.max()) > 1.0) == (not PRODUCTION_SCALER_CLIPS))

    # serialize -> reload -> transform 逐位一致
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "preprocessor_state.json"
        r3.serialize(p)
        reloaded = RouteCPreprocessor.load(p)
        rl_train = reloaded.transform(ordered_fit)
        rl_eval = reloaded.transform(eval_df)
        checks["reload_train_bitwise_equal"] = bool(
            _df_bitwise_equal(r3_train, rl_train))
        checks["reload_eval_bitwise_equal"] = bool(
            _df_bitwise_equal(r3_eval, rl_eval))
        checks["reload_state_hash_equal"] = bool(
            reloaded.state_hash() == r3.state_hash())
        checks["reload_inverse_bitwise_equal"] = bool(
            np.array_equal(
                reloaded.inverse_features(r3_train.to_numpy()),
                r3.inverse_features(r3_train.to_numpy())))

    # staged/mixed order invariance:shuffled rows 不改变 fitted state
    rng = np.random.default_rng(20260901)
    perm = rng.permutation(len(ordered_fit))
    r3_shuffled = RouteCPreprocessor.build_and_fit(
        ordered_fit.iloc[perm])
    checks["shuffled_rows_same_state_hash"] = bool(
        r3_shuffled.state_hash() == r3.state_hash())
    checks["shuffled_rows_same_transform"] = bool(
        _df_bitwise_equal(r3_shuffled.transform(ordered_fit), r3_train))

    checks["all_equal"] = bool(
        checks["train_transform_bitwise_equal"]
        and checks["eval_transform_bitwise_equal"]
        and checks["retained_mask_equal"]
        and checks["reload_train_bitwise_equal"]
        and checks["reload_eval_bitwise_equal"]
        and checks["reload_state_hash_equal"]
        and checks["reload_inverse_bitwise_equal"]
        and checks["shuffled_rows_same_state_hash"]
        and checks["shuffled_rows_same_transform"]
        and checks["zero_variance_absent_in_contract_fit"])
    return {
        "format": "cur261-r3-production-equivalence-v1",
        "contract_version": ROUTE_C_FEATURE_PREPROCESSING_VERSION,
        "n_fit_rows": int(len(ordered_fit)),
        "n_eval_rows": int(len(eval_df)),
        "state_hash": r3.state_hash(),
        "checks": checks,
        "pass": bool(checks["all_equal"]),
    }


def _df_bitwise_equal(a: pd.DataFrame, b: pd.DataFrame) -> bool:
    if list(a.columns) != list(b.columns) or a.shape != b.shape:
        return False
    return bool(np.array_equal(
        a.to_numpy(dtype=np.float64), b.to_numpy(dtype=np.float64)))


def preprocessing_contract_digest() -> str:
    """preprocessing 合同摘要(实现身份,进 plan;与 fitted state 无关)。"""
    payload = {
        "contract_version": ROUTE_C_FEATURE_PREPROCESSING_VERSION,
        "state_format": PREPROCESSING_STATE_FORMAT,
        "input_columns": list(PRODUCTION_FEATURE_COLUMNS),
        "pipeline_steps": [
            "ds.VarianceThreshold(threshold=0)",
            "SKLearnWrapper(MinMaxScaler(feature_range=(-1,1)))",
        ],
        "position_slot": POSITION_SLOT_SEMANTICS,
        "observation_space": OBSERVATION_SPACE_SEMANTICS,
        "clips": PRODUCTION_SCALER_CLIPS,
        "runtime_config": production_runtime_config_identity(),
        "strategy_identity": route_c_strategy_identity(),
    }
    return "r3pc-" + hashlib.sha256(json.dumps(
        payload, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, default=str).encode("utf-8")).hexdigest()
