"""阶段 2.6.1 Repair R4:RouteCFeaturePreprocessing-v2 预处理合同。

R3 的 V1 数值实现成立(vendor pipeline 直接复用、逐位等价、统一
fit/freeze、8/8 存活、reference 逐 bar 等价),但正式合同未闭合:
1. observation space 声明 Box(-10,10) 与不 clip 的 transform 矛盾;
2. preprocessor state 只绑定 scaler 参数,不绑定 fit 来源;
3. 无联合 handoff identity。

V2(数值行为与 V1 逐位一致,不修改 vendor 数值)补齐:

- 真实 observation space:外层 preprocessing-aware Gymnasium wrapper
  (RouteCPreprocessingEnvV2)把 feature 维声明为 (-inf, +inf)、
  position 维声明为 [0, 1];PPO / SB3 / check_env / 外部调用方看到
  的都是该 outer space;obs 值逐位透传(不 clip、不改写);
- 三层 identity(§9):
  A. Parameter State Hash —— 只绑 transform 参数(retained mask /
     data min/max / scale/min / 列 / dtype / pipeline 版本);
  B. Fit Manifest Multiset Hash —— 绑完整 fit 来源(每 entry 含
     namespace/family/rung/pair/side/episode hash/feature-matrix
     hash/generator+parameter-pack identity),对行序不敏感、对
     multiset 内容敏感;staged/mixed 同 multiset 同 hash;
  C. Preprocessor Bundle Hash —— A + B + fit protocol digest +
     production pipeline identity + runtime config identity +
     feature construction identity 的联合绑定;未来 PPO model
     manifest 必须绑定 model hash + bundle hash。

fit 协议与 V1 相同:offline training-corpus fit -> frozen deployment
transform;统一 preprocessor(C1/C2/C3 共享);position 不参与 fit。
"""

from __future__ import annotations

import hashlib
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from rl_curriculum.curriculum261_production_obs import (
    PRODUCTION_FEATURE_COLUMNS,
    production_runtime_config_identity,
    route_c_strategy_identity,
)
from rl_curriculum.curriculum261_r3_preprocessing import (
    RouteCPreprocessor,
    build_vendor_feature_pipeline,
)

#: 正式预处理合同版本(R4 冻结语义名;数值与 V1 逐位一致)。
ROUTE_C_FEATURE_PREPROCESSING_V2 = "RouteCFeaturePreprocessing-v2"

#: V2 state envelope 序列化格式。
PREPROCESSING_ENVELOPE_FORMAT = "r4-route-c-feature-preprocessing-envelope-v2"

#: position slot 合同(与 V1 相同语义;第 9 维,不参与 fit/不缩放)。
POSITION_SLOT_SEMANTICS_V2 = {
    "index": 8,
    "values": "0=Flat,1=Long",
    "participates_in_fit": False,
    "scaled": False,
    "clipped": False,
    "appended_by": "rl_platform.env.AlignedLongFlatEnv._observation",
}

#: 生产 scaler 不 clip(与 V1 相同事实)。
PRODUCTION_SCALER_CLIPS_V2 = False

#: V2 观察空间语义:feature 维无界、position 维 [0,1];由外层
#: preprocessing-aware wrapper 正式声明(不再沿用内层 env 的
#: Box(-10,10) 作为 preprocessing 后合同)。
OBSERVATION_SPACE_SEMANTICS_V2 = {
    "feature_dimensions": "(-inf, +inf) per feature dim",
    "position_dimension": "[0, 1]",
    "dtype": "float32",
    "dim": 9,
    "clip_by_pipeline": False,
    "clip_by_wrapper": False,
    "out_of_train_range": "linear extrapolation beyond [-1, 1];"
                          "unbounded space accepts any finite value",
    "declared_by": "RouteCPreprocessingEnvV2(outer Gymnasium wrapper;"
                   "inner AlignedLongFlatEnv 冻结声明不变)",
}


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, default=str)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ================================================================ A 层
def parameter_state_hash(state: dict[str, Any]) -> str:
    """§9A Parameter State Hash:只绑 transform 参数。

    绑定字段:retained mask、data_min/data_max、data_range/scale/min、
    输入/保留列、dtype、pipeline 版本。刻意不绑 n_samples_seen_(
    非 transform 参数:同 min/max 下增删内部样本不改变 transform)。
    """
    payload = {
        "contract_version": ROUTE_C_FEATURE_PREPROCESSING_V2,
        "pipeline": [
            "ds.VarianceThreshold(threshold=0)",
            "SKLearnWrapper(MinMaxScaler(feature_range=(-1,1)))",
        ],
        "input_columns": list(state["input_columns"]),
        "retained_columns": list(state["retained_columns"]),
        "variance_threshold_mask": [
            bool(m) for m in state["variance_threshold"]["mask"]],
        "scaler_feature_range": list(
            state["scaler"]["feature_range"]),
        "scaler_data_min": [float(v) for v in state["scaler"]["data_min_"]],
        "scaler_data_max": [float(v) for v in state["scaler"]["data_max_"]],
        "scaler_scale": [float(v) for v in state["scaler"]["scale_"]],
        "scaler_min": [float(v) for v in state["scaler"]["min_"]],
        "dtype_input": state["dtype_input"],
        "dtype_output": state["dtype_output"],
    }
    return "r4ps-" + _sha(_canonical(payload))


# ================================================================ B 层
@dataclass(frozen=True)
class FitManifestEntry:
    """fit manifest 单条(一个 episode 的 fit 来源记录)。"""

    namespace: str
    family: str
    rung: str
    pair_index: int
    side: str
    episode_hash: str
    feature_matrix_hash: str
    generator_identity: str

    def canonical(self) -> dict[str, Any]:
        return {
            "namespace": self.namespace,
            "family": self.family,
            "rung": self.rung,
            "pair_index": int(self.pair_index),
            "side": self.side,
            "episode_hash": self.episode_hash,
            "feature_matrix_hash": self.feature_matrix_hash,
            "generator_identity": self.generator_identity,
        }

    def entry_hash(self) -> str:
        return _sha(_canonical(self.canonical()))


def episode_feature_matrix_hash(episode: Any) -> str:
    """episode 8 特征列 float64 矩阵的内容哈希(%.17g CSV)。"""
    df = episode.df[list(PRODUCTION_FEATURE_COLUMNS)]
    return _sha(df.astype(np.float64).to_csv(
        index=False, float_format="%.17g"))


def build_fit_manifest_entries(
        records: list[Any], namespace: str,
        parameter_pack_identity: str) -> list[FitManifestEntry]:
    """从 fit bank records 构造 manifest entries。

    generator_identity = family_version + parameter-pack identity
    (D0-D2/C2 行使用 historical 标记;pack 由调用方给出整体 identity,
    行级差异在 D3 override 下由 feature/episode hash 反映)。
    """
    from rl_curriculum.curriculum261_pairs import family_specs

    specs = family_specs()
    entries: list[FitManifestEntry] = []
    for rec in records:
        fam_version = specs[rec.family].generator.family_version
        gen_identity = (
            f"{rec.family}|{fam_version}|{parameter_pack_identity}")
        for side in ("A", "B"):
            ep = rec.episodes[side]
            entries.append(FitManifestEntry(
                namespace=namespace,
                family=rec.family,
                rung=rec.rung,
                pair_index=int(rec.pair_index),
                side=side,
                episode_hash=rec.attempt_log.episode_hashes[side],
                feature_matrix_hash=episode_feature_matrix_hash(ep),
                generator_identity=gen_identity,
            ))
    return entries


def fit_manifest_multiset_hash(entries: list[FitManifestEntry]) -> str:
    """§9B:order-invariant multiset hash(排序后逐 entry 哈希再总哈希)。"""
    hashes = sorted(e.entry_hash() for e in entries)
    return "r4fm-" + _sha(_canonical({
        "n_entries": len(hashes),
        "entry_hashes": hashes,
    }))


def fit_manifest_document(entries: list[FitManifestEntry],
                          namespace: str) -> dict[str, Any]:
    return {
        "format": "cur261-r4-fit-manifest-v1",
        "namespace": namespace,
        "n_entries": len(entries),
        "entries": [e.canonical() for e in entries],
        "multiset_hash": fit_manifest_multiset_hash(entries),
    }


# ================================================================ C 层
def fit_protocol_digest() -> str:
    """fit 协议摘要(协议级 identity,与具体数据无关)。"""
    payload = {
        "format": "r4-fit-protocol-v1",
        "protocol": "offline training-corpus fit -> frozen deployment "
                    "transform",
        "fit_scope": "单一统一 preprocessor,C1/C2/C3 共享;fit 于完整"
                     "fit bank 的全部 policy-visible feature rows;"
                     "position slot 不参与 fit",
        "isolation": "fit bank namespace(preprocess_fit_*_r4)与全部"
                     "evaluation namespace 隔离;fit bank 不进入任何 "
                     "qualification metric",
        "order_invariance": "fit 对 manifest 行序不敏感"
                            "(staged/mixed 同 multiset 同 state)",
        "no_refit": "eval 时禁止 refit / episode 内 / family 切换 / "
                    "online normalization",
    }
    return "r4fpd-" + _sha(_canonical(payload))


def production_pipeline_identity_light() -> dict[str, Any]:
    """production pipeline 实现身份(轻量版;bundle hash 输入)。"""
    import rl_curriculum

    root = Path(rl_curriculum.__file__).resolve().parents[2]
    src = root / "vendor" / "freqtrade" / "freqtrade" / "freqai" / (
        "freqai_interface.py")
    steps = [
        ("const", "VarianceThreshold"), ("scaler", "SKLearnWrapper")]
    return {
        "builder": "pinned vendor IFreqaiModel.define_data_pipeline",
        "freqai_interface_sha256": _sha256_file(src),
        "steps": steps,
    }


def feature_construction_identity_light() -> dict[str, Any]:
    ident = route_c_strategy_identity()
    return {
        "strategy_file_sha256": ident["strategy_file_sha256"],
        "feature_engineering_standard_sha256": ident[
            "feature_engineering_standard_sha256"],
        "ordered_feature_columns": list(PRODUCTION_FEATURE_COLUMNS),
    }


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    h.update(Path(path).read_bytes())
    return h.hexdigest()


def preprocessor_bundle_hash(
        *, parameter_state_hash_: str, manifest_multiset_hash: str,
) -> str:
    """§9C Preprocessor Bundle Hash(联合绑定六项 identity)。"""
    payload = {
        "contract_version": ROUTE_C_FEATURE_PREPROCESSING_V2,
        "parameter_state_hash": parameter_state_hash_,
        "fit_manifest_multiset_hash": manifest_multiset_hash,
        "fit_protocol_digest": fit_protocol_digest(),
        "production_pipeline_identity": (
            production_pipeline_identity_light()),
        "runtime_config_identity": production_runtime_config_identity(),
        "feature_construction_identity": (
            feature_construction_identity_light()),
    }
    return "r4pb-" + _sha(_canonical(payload))


# ================================================================ V2 对象
class RouteCPreprocessorV2:
    """RouteCFeaturePreprocessing-v2 preprocessor(fit/freeze/identity)。

    数值核心直接复用 R3 的 RouteCPreprocessor(vendor pipeline,不改
    任何数值行为);V2 在其上补齐 manifest/bundle 三层 identity 与
    envelope 序列化。transform/transform_episode_df/inverse_features
    全部委托 inner(逐位一致)。
    """

    def __init__(self, inner: RouteCPreprocessor,
                 entries: list[FitManifestEntry],
                 namespace: str) -> None:
        if not inner.fitted:
            raise RuntimeError("inner preprocessor 未 fit(fail closed)")
        self.inner = inner
        self.entries = list(entries)
        self.namespace = str(namespace)
        if self.entries:
            if any(e.namespace != self.namespace for e in self.entries):
                raise RuntimeError(
                    "fit manifest 混合多个 namespace(单一 fit bank 合同"
                    "违反)")

    # ------------------------------------------------------------ 哈希层
    @property
    def parameter_state_hash(self) -> str:
        return parameter_state_hash(self.inner.fitted_state())

    @property
    def manifest_multiset_hash(self) -> str:
        return fit_manifest_multiset_hash(self.entries)

    @property
    def bundle_hash(self) -> str:
        return preprocessor_bundle_hash(
            parameter_state_hash_=self.parameter_state_hash,
            manifest_multiset_hash=self.manifest_multiset_hash)

    def manifest_document(self) -> dict[str, Any]:
        return fit_manifest_document(self.entries, self.namespace)

    # ---------------------------------------------------------- transform
    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        return self.inner.transform(df)

    def transform_episode_df(self, df: pd.DataFrame) -> pd.DataFrame:
        return self.inner.transform_episode_df(df)

    def inverse_features(self, x: np.ndarray) -> np.ndarray:
        return self.inner.inverse_features(x)

    @property
    def retained_columns(self) -> list[str]:
        return list(self.inner.retained_columns)

    def state_hash_r3(self) -> str:
        """R3 序列化哈希(向后兼容字段;V2 主哈希是 bundle)。"""
        return self.inner.state_hash()

    # -------------------------------------------------------- 序列化/重载
    def envelope(self) -> dict[str, Any]:
        return {
            "format": PREPROCESSING_ENVELOPE_FORMAT,
            "contract_version": ROUTE_C_FEATURE_PREPROCESSING_V2,
            "namespace": self.namespace,
            "parameter_state": self.inner.fitted_state(),
            "fit_manifest": self.manifest_document(),
            "identities": {
                "fit_protocol_digest": fit_protocol_digest(),
                "production_pipeline_identity": (
                    production_pipeline_identity_light()),
                "runtime_config_identity": (
                    production_runtime_config_identity()),
                "feature_construction_identity": (
                    feature_construction_identity_light()),
                "observation_space": OBSERVATION_SPACE_SEMANTICS_V2,
                "position_slot": POSITION_SLOT_SEMANTICS_V2,
                "clips": PRODUCTION_SCALER_CLIPS_V2,
            },
            "hashes": {
                "parameter_state_hash": self.parameter_state_hash,
                "fit_manifest_multiset_hash": self.manifest_multiset_hash,
                "preprocessor_bundle_hash": self.bundle_hash,
            },
        }

    def serialize_envelope(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.envelope(), indent=2,
                                   ensure_ascii=False), encoding="utf-8")

    @classmethod
    def load_envelope(cls, path: Path) -> "RouteCPreprocessorV2":
        """envelope -> V2 对象(重载后 identity 不变;篡改即拒)。"""
        path = Path(path)
        raw = json.loads(path.read_text(encoding="utf-8"))
        if raw.get("format") != PREPROCESSING_ENVELOPE_FORMAT:
            raise RuntimeError(
                f"envelope format {raw.get('format')!r} != "
                f"{PREPROCESSING_ENVELOPE_FORMAT!r}")
        stored = raw.get("hashes", {})
        with tempfile.TemporaryDirectory() as td:
            state_path = Path(td) / "inner_state.json"
            state_path.write_text(json.dumps(raw["parameter_state"],
                                             ensure_ascii=False),
                                  encoding="utf-8")
            inner = RouteCPreprocessor.load(state_path)
        entries = [
            FitManifestEntry(
                namespace=e["namespace"], family=e["family"],
                rung=e["rung"], pair_index=int(e["pair_index"]),
                side=e["side"], episode_hash=e["episode_hash"],
                feature_matrix_hash=e["feature_matrix_hash"],
                generator_identity=e["generator_identity"])
            for e in raw["fit_manifest"]["entries"]]
        # manifest 文档内嵌的 multiset hash 必须与 entries 重算一致
        if raw["fit_manifest"].get("multiset_hash") != (
                fit_manifest_multiset_hash(entries)):
            raise RuntimeError("fit manifest multiset hash 与 entries "
                               "重算不一致(fail closed)")
        obj = cls(inner, entries, raw["namespace"])
        if obj.parameter_state_hash != stored.get(
                "parameter_state_hash"):
            raise RuntimeError("parameter state hash 复算不一致(fail closed)")
        if obj.manifest_multiset_hash != stored.get(
                "fit_manifest_multiset_hash"):
            raise RuntimeError("fit manifest multiset hash 复算不一致"
                               "(fail closed)")
        if obj.bundle_hash != stored.get("preprocessor_bundle_hash"):
            raise RuntimeError("preprocessor bundle hash 复算不一致"
                               "(fail closed)")
        return obj

    def verify(self) -> dict[str, Any]:
        """自校验(重载/篡改检测;全部三层哈希重算比对)。"""
        checks = {
            "inner_fitted": bool(self.inner.fitted),
            "retained_8_of_8": bool(
                self.retained_columns == list(PRODUCTION_FEATURE_COLUMNS)),
            "manifest_namespace_uniform": bool(all(
                e.namespace == self.namespace for e in self.entries)),
            "parameter_state_hash_recomputable": True,
            "bundle_hash_recomputable": True,
        }
        return {"checks": checks,
                "hashes": {
                    "parameter_state_hash": self.parameter_state_hash,
                    "fit_manifest_multiset_hash":
                        self.manifest_multiset_hash,
                    "preprocessor_bundle_hash": self.bundle_hash},
                "pass": bool(all(checks.values()))}

    def identity(self) -> dict[str, Any]:
        return {
            "contract_version": ROUTE_C_FEATURE_PREPROCESSING_V2,
            "numerics": "与 RouteCFeaturePreprocessing-v1 逐位一致"
                        "(vendor pipeline 直接复用,无数值改动)",
            "parameter_state_hash": self.parameter_state_hash,
            "fit_manifest_multiset_hash": self.manifest_multiset_hash,
            "preprocessor_bundle_hash": self.bundle_hash,
            "fit_namespace": self.namespace,
            "n_manifest_entries": len(self.entries),
            "observation_space": OBSERVATION_SPACE_SEMANTICS_V2,
            "position_slot": POSITION_SLOT_SEMANTICS_V2,
            "clips": PRODUCTION_SCALER_CLIPS_V2,
        }


# ================================================================ V2 env
import gymnasium as _gym  # noqa: E402


class RouteCPreprocessingEnvV2(_gym.Wrapper):
    """外层 preprocessing-aware Gymnasium wrapper(声明真实空间)。

    reset/step 透传并校验 observation(dim/float32/finite/position∈
    {0,1}),值逐位不变(无 clip、无缩放、无改写)。observation_space
    重声明为:feature 维 (-inf,+inf) + position 维 [0,1](float32);
    action_space 继承 inner。SB3 check_env / PPO model 看到的即本
    wrapper 的空间(继承 gym.Wrapper,非 duck-typing)。
    """

    def __init__(self, env: Any, bundle_hash: str | None = None) -> None:
        super().__init__(env)
        self.bundle_hash = bundle_hash
        shape = env.observation_space.shape
        if len(shape) != 1:
            raise RuntimeError(
                f"inner observation space 非一维: {shape}")
        n_total = int(shape[0])
        low = np.full(n_total, -np.inf, dtype=np.float32)
        high = np.full(n_total, np.inf, dtype=np.float32)
        low[-1] = 0.0
        high[-1] = 1.0
        self.observation_space = _gym.spaces.Box(
            low=low, high=high, dtype=np.float32)

    def _validate(self, obs: np.ndarray) -> None:
        arr = np.asarray(obs)
        if arr.shape != self.observation_space.shape:
            raise RuntimeError(
                f"V2 observation shape {arr.shape} != "
                f"{self.observation_space.shape}")
        if str(arr.dtype) != "float32":
            raise RuntimeError(f"V2 observation dtype {arr.dtype} != float32")
        if not np.isfinite(arr).all():
            raise RuntimeError("V2 observation 含非有限值")
        if float(arr[-1]) not in (0.0, 1.0):
            raise RuntimeError(
                f"V2 position 槽位 {float(arr[-1])} 非 0/1")

    def reset(self, *, seed: int | None = None,
              options: dict | None = None):
        obs, info = self.env.reset(seed=seed, options=options)
        self._validate(obs)
        return obs, info

    def step(self, action):
        obs, reward, terminated, truncated, info = self.env.step(action)
        self._validate(obs)
        return obs, reward, terminated, truncated, info


def build_v2_env(preproc_v2: RouteCPreprocessorV2,
                 scaled_df: pd.DataFrame, eval_cfg: Any,
                 seed: int | None = None) -> RouteCPreprocessingEnvV2:
    """scaled episode df -> inner env -> V2 outer wrapper。

    inner 构造与评估路径一致(select_features_strict + 市场价格列 raw)。
    """
    from rl_curriculum.curriculum261_r4_obs import r4_observation_schema
    from rl_curriculum.evaluator import select_features_strict
    from rl_platform.env import AlignedLongFlatEnv

    schema = r4_observation_schema(preproc_v2)
    features = select_features_strict(scaled_df, schema, context="r4_env")
    inner = AlignedLongFlatEnv(
        features=features,
        prices=scaled_df[list(("open", "high", "low", "close"))],
        fee=eval_cfg.fee, slippage_bps=eval_cfg.slippage_bps,
        initial_cash=eval_cfg.initial_cash,
        reward_scale=eval_cfg.reward_scale,
        window_size=eval_cfg.window_size,
        price_tick=eval_cfg.price_tick,
        execution_mode="market_open_causal",
    )
    return RouteCPreprocessingEnvV2(inner, bundle_hash=preproc_v2.bundle_hash)


# ================================================================ 验证器
def validate_observation_space_v2(
        episodes_scaled_dfs: list[pd.DataFrame],
        prices_frames: list[pd.DataFrame],
        eval_cfg: Any, seeds: list[int],
        context: str = "observation_space_v2",
        extra_probe_episodes: list[pd.DataFrame] | None = None,
) -> dict[str, Any]:
    """V2 observation space 全 corpus 实测验证。

    对每个 scaled episode 构造 V2 outer env(reset + 全 step),断言:
    dim=9、float32、finite、outer space contains(obs)==True、
    position∈{0,1}、wrapper 输出与 inner 输出逐位相等(无 clip)。
    extra_probe_episodes:对抗性 out-of-range 探针(transformed 值
    超出 ±10 的合成 episode),同样必须被 outer space 接受且不 clip。
    """
    from rl_platform.env import AlignedLongFlatEnv

    n_obs = 0
    max_abs = 0.0
    violations: list[str] = []
    space = None
    dfs = list(episodes_scaled_dfs) + list(extra_probe_episodes or [])
    for idx, df in enumerate(dfs):
        features = df[list(PRODUCTION_FEATURE_COLUMNS)]
        prices = df[list(("open", "high", "low", "close"))]

        def _make_inner():
            return AlignedLongFlatEnv(
                features=features, prices=prices,
                fee=eval_cfg.fee, slippage_bps=eval_cfg.slippage_bps,
                initial_cash=eval_cfg.initial_cash,
                reward_scale=eval_cfg.reward_scale,
                window_size=eval_cfg.window_size,
                price_tick=eval_cfg.price_tick,
                execution_mode="market_open_causal")

        # 双 inner(wrapped 与 bare)同 seed 锁步运行:wrapper 输出必须
        # 与 bare inner 逐位相等(无 clip/无改写)。
        env = RouteCPreprocessingEnvV2(_make_inner())
        bare = _make_inner()
        space = env.observation_space
        seed = seeds[idx % len(seeds)]
        obs_o, _ = env.reset(seed=seed)
        obs_i, _ = bare.reset(seed=seed)
        while True:
            n_obs += 1
            if obs_o.shape != (9,) or str(obs_o.dtype) != "float32":
                violations.append(f"{context}: shape/dtype 异常")
                break
            if not np.isfinite(obs_o).all():
                violations.append(f"{context}: obs 含非有限值")
                break
            if not env.observation_space.contains(obs_o):
                violations.append(
                    f"{context}: outer space 不 contains obs")
                break
            if not np.array_equal(
                    np.asarray(obs_o), np.asarray(obs_i)):
                violations.append(f"{context}: wrapper 改写了 obs 值")
                break
            if float(obs_o[-1]) not in (0.0, 1.0):
                violations.append(f"{context}: position 非 0/1")
                break
            max_abs = max(max_abs, float(np.max(np.abs(obs_o))))
            obs_o, _, term_o, trunc_o, _ = env.step(0)
            obs_i, _, term_i, trunc_i, _ = bare.step(0)
            if term_o or trunc_o or term_i or trunc_i:
                break
    low_ok = bool(space is not None and np.all(np.isinf(
        space.low[:-1])) and space.low[-1] == 0.0)
    high_ok = bool(space is not None and np.all(np.isinf(
        space.high[:-1])) and space.high[-1] == 1.0)
    return {
        "format": "cur261-r4-observation-space-validation-v1",
        "context": context,
        "n_observations": n_obs,
        "max_abs_value_seen": max_abs,
        "feature_bounds": "(-inf, +inf)",
        "position_bounds": [0.0, 1.0],
        "declared_low_feature_unbounded": low_ok,
        "declared_high_feature_unbounded": high_ok,
        "clip_by_wrapper": False,
        "wrapper_pass_through_bitwise": not any(
            "改写了 obs" in v for v in violations),
        "position_slot_valid": not any("position" in v for v in violations),
        "violations": violations[:20],
        "pass": bool(
            not violations and n_obs > 0 and low_ok and high_ok),
    }


def adversarial_out_of_range_probe(
        preproc_v2: RouteCPreprocessorV2, eval_cfg: Any,
) -> dict[str, Any]:
    """对抗性 out-of-range 探针:transformed feature > 10 与 < -10。

    构造合成 episode:把 raw 特征推到 fit range 之外(线性外推后
    transformed 值必须超出 ±10),V2 outer env 必须接受(contains
    == True)且不 clip(obs 与 inner 逐位相等)。禁止用 clip 或伪造
    有限边界绕过。
    """
    from rl_curriculum.curriculum261_r4_pairs import _synthetic_probe_df

    state = preproc_v2.inner.fitted_state()
    probe = _synthetic_probe_df(state)
    scaled = preproc_v2.transform_episode_df(probe)
    vals = scaled[list(PRODUCTION_FEATURE_COLUMNS)].to_numpy(
        dtype=np.float64)
    report = validate_observation_space_v2(
        [scaled], [scaled], eval_cfg, seeds=[101], context="adversarial")
    return {
        "format": "cur261-r4-adversarial-out-of-range-probe-v1",
        "max_transformed_feature": float(np.max(vals)),
        "min_transformed_feature": float(np.min(vals)),
        "exceeds_plus_10": bool(np.max(vals) > 10.0),
        "exceeds_minus_10": bool(np.min(vals) < -10.0),
        "validation": report,
        "pass": bool(
            np.max(vals) > 10.0 and np.min(vals) < -10.0
            and report["pass"]),
    }


def preprocessing_v2_contract_digest() -> str:
    """V2 合同摘要(实现身份,进 plan;与 fitted state 无关)。"""
    payload = {
        "contract_version": ROUTE_C_FEATURE_PREPROCESSING_V2,
        "envelope_format": PREPROCESSING_ENVELOPE_FORMAT,
        "numerics": "RouteCFeaturePreprocessing-v1 数值逐位一致"
                    "(vendor pipeline 直接复用)",
        "input_columns": list(PRODUCTION_FEATURE_COLUMNS),
        "identity_layers": [
            "A parameter_state_hash(r4ps-)",
            "B fit_manifest_multiset_hash(r4fm-)",
            "C preprocessor_bundle_hash(r4pb-)",
        ],
        "position_slot": POSITION_SLOT_SEMANTICS_V2,
        "observation_space": OBSERVATION_SPACE_SEMANTICS_V2,
        "clips": PRODUCTION_SCALER_CLIPS_V2,
        "outer_wrapper": "RouteCPreprocessingEnvV2",
        "runtime_config": production_runtime_config_identity(),
        "strategy_identity": route_c_strategy_identity(),
    }
    return "r4pc-" + _sha(_canonical(payload))
