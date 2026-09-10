"""阶段 2.6.0a 工作包 B/K1:课程级正式 Observation Schema(冻结与哈希)。

阶段 2.6.0 的 ObservationSpec 只有一个通用版本字符串
(ObservationSpec-v1,来自冻结环境核心),没有课程级有序特征契约:
- 评估器按"所有非价格、非 date 列"选择输入,DataFrame 列序即输入序;
- 相同总维度下特征语义错位无法被发现;
- 无关特征注入只能新增列,固定维度 PPO 无法执行;
- checkpoint 不绑定有序特征名/shape/window/dtype/归一化。

本模块定义课程级 observation schema:有序 feature whitelist、每个窗口
的 feature shape、window_size、dtype、账户状态槽位与顺序、成本上下文
声明、每个特征的因果可用时点与最大历史窗口、归一化方法与 pipeline
哈希、预注册 nuisance 槽位、schema 版本与 schema hash。

schema hash 进入:
- checkpoint sidecar(v2,加载守卫逐项比对);
- sealed exam commitment(工作包 E);
- 正式考试包(工作包 M);
- 评估报告。

语义比对规则(assert_same_semantics):特征顺序、总维度、window_size、
dtype、归一化 pipeline、账户状态槽位、nuisance 槽位数量任一不同即
拒绝——即使总维度恰好相同也必须拒绝语义错位,绝不静默通过。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

import numpy as np

OBSERVATION_SCHEMA_FORMAT = "course-observation-schema-v1"

# 环境核心追加在特征窗口之后的账户状态槽位(顺序即 obs 尾部顺序;
# 与冻结的 AlignedLongFlatEnv._observation 合同一致:窗口展平 + [仓位])
DEFAULT_ACCOUNT_SLOTS: tuple[str, ...] = ("target_position",)

_DTYPE_MAP = {"float32": np.float32, "float64": np.float64}


class ObservationSchemaError(RuntimeError):
    """schema 构造/内容不合法(fail closed)。"""


class ObservationSchemaMismatchError(ObservationSchemaError):
    """两个 schema 语义不一致(顺序/维度/窗口/dtype/归一化/槽位)。"""


@dataclass(frozen=True)
class FeatureSpec:
    """单个正式 observation 特征的预注册声明(K1)。"""

    name: str
    available_at: str          # 因果可用时点,如 "close_of_bar_t"
    max_history_bars: int      # 因果滚动所需最大历史窗口(bars)
    nuisance: bool = False     # 是否为预注册 nuisance 槽位
    signal_group: str = ""     # 所属 signal group(消融考试分组)
    normalization: str = "identity"

    def canonical(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "available_at": self.available_at,
            "max_history_bars": int(self.max_history_bars),
            "nuisance": bool(self.nuisance),
            "signal_group": self.signal_group,
            "normalization": self.normalization,
        }


@dataclass(frozen=True)
class ObservationSchema:
    """课程级正式 observation schema(可规范化、可哈希、可严格比较)。"""

    schema_version: str                       # 课程级 schema 版本(非环境核心版本)
    features: tuple[FeatureSpec, ...]         # 有序 feature whitelist
    window_size: int                          # 观察特征窗口行数(含当前行)
    dtype: str = "float32"
    account_slots: tuple[str, ...] = DEFAULT_ACCOUNT_SLOTS
    includes_cost_context: bool = False       # observation 是否含费用/成本上下文
    normalization_method: str = "identity"
    normalization_pipeline_hash: str = "identity-v1"  # scaler/pipeline 身份哈希
    nuisance_fill: str = "independent_noise"  # 正常训练时 nuisance 槽位填充语义

    def __post_init__(self) -> None:
        if not self.schema_version:
            raise ObservationSchemaError("schema_version 不得为空")
        if not self.features:
            raise ObservationSchemaError("features(有序 whitelist)不得为空")
        names = [f.name for f in self.features]
        if len(set(names)) != len(names):
            raise ObservationSchemaError(f"特征名重复: {names}")
        if self.window_size < 1:
            raise ObservationSchemaError(f"window_size 必须 >= 1,收到 {self.window_size}")
        if self.dtype not in _DTYPE_MAP:
            raise ObservationSchemaError(
                f"不支持的 dtype {self.dtype!r}:仅支持 {sorted(_DTYPE_MAP)}")
        if not self.account_slots:
            raise ObservationSchemaError("account_slots 不得为空(环境合同要求仓位槽位)")
        for f in self.features:
            if f.nuisance and f.signal_group not in ("", "nuisance"):
                raise ObservationSchemaError(
                    f"nuisance 特征 {f.name!r} 不得声明非 nuisance 信号组"
                    f" {f.signal_group!r}")
            if f.normalization != self.normalization_method and f.normalization != "identity":
                raise ObservationSchemaError(
                    f"特征 {f.name!r} 归一化 {f.normalization!r} 与 schema 级 "
                    f"{self.normalization_method!r} 不一致")

    # -------------------------------------------------------------- 基本信息
    @property
    def feature_names(self) -> tuple[str, ...]:
        return tuple(f.name for f in self.features)

    @property
    def nuisance_feature_names(self) -> tuple[str, ...]:
        return tuple(f.name for f in self.features if f.nuisance)

    @property
    def nuisance_slot_count(self) -> int:
        return sum(1 for f in self.features if f.nuisance)

    @property
    def observation_dim(self) -> int:
        return len(self.features) * self.window_size + len(self.account_slots)

    def observation_shape(self) -> tuple[int, ...]:
        return (self.observation_dim,)

    def feature_index(self, name: str) -> int:
        """名称 -> observation 内索引(window_size=1 时即特征序;
        window>1 时取最新窗口行内位置,即评估器展平序:
        [row t-w+1 的全部特征, ..., row t 的全部特征, 账户槽位])。"""
        try:
            i = self.feature_names.index(name)
        except ValueError as exc:
            raise ObservationSchemaError(
                f"特征 {name!r} 不在 schema whitelist {list(self.feature_names)} 中"
            ) from exc
        return i + (self.window_size - 1) * len(self.features)

    def account_slot_index(self, slot_name: str) -> int:
        try:
            j = self.account_slots.index(slot_name)
        except ValueError as exc:
            raise ObservationSchemaError(
                f"账户槽位 {slot_name!r} 不在 {list(self.account_slots)} 中") from exc
        return len(self.features) * self.window_size + j

    def signal_groups(self) -> dict[str, tuple[str, ...]]:
        groups: dict[str, list[str]] = {}
        for f in self.features:
            if f.signal_group and f.signal_group != "nuisance":
                groups.setdefault(f.signal_group, []).append(f.name)
        return {k: tuple(v) for k, v in sorted(groups.items())}

    # -------------------------------------------------------------- 规范化/哈希
    def canonical_payload(self) -> dict[str, Any]:
        return {
            "format": OBSERVATION_SCHEMA_FORMAT,
            "schema_version": self.schema_version,
            "features": [f.canonical() for f in self.features],
            "window_size": int(self.window_size),
            "dtype": self.dtype,
            "account_slots": list(self.account_slots),
            "includes_cost_context": bool(self.includes_cost_context),
            "normalization_method": self.normalization_method,
            "normalization_pipeline_hash": self.normalization_pipeline_hash,
            "nuisance_fill": self.nuisance_fill,
            "nuisance_slot_count": self.nuisance_slot_count,
            "observation_dim": self.observation_dim,
        }

    def canonical(self) -> str:
        return json.dumps(
            self.canonical_payload(), sort_keys=True,
            separators=(",", ":"), ensure_ascii=False,
        )

    def schema_hash(self) -> str:
        return "o-" + hashlib.sha256(self.canonical().encode("utf-8")).hexdigest()

    # -------------------------------------------------------------- 守卫
    def assert_observation_array(self, obs: np.ndarray, *, context: str = "") -> None:
        """输入 observation 数组必须与本 schema 的 shape/dtype 完全一致。"""
        arr = np.asarray(obs)
        prefix = f"[{context}] " if context else ""
        if arr.shape != self.observation_shape():
            raise ObservationSchemaMismatchError(
                f"{prefix}observation shape {arr.shape} != schema "
                f"{self.observation_shape()}({len(self.features)} 特征 x "
                f"window {self.window_size} + {len(self.account_slots)} 账户槽位;"
                f"特征序 {list(self.feature_names)})"
            )
        if arr.dtype != _DTYPE_MAP[self.dtype]:
            raise ObservationSchemaMismatchError(
                f"{prefix}observation dtype {arr.dtype} != schema {self.dtype}")

    def assert_same_semantics(self, other: "ObservationSchema", *, context: str = "") -> None:
        """语义级比对:任何一项不同即拒绝,即使总维度恰好相同。

        被拒绝的典型情形:特征顺序相同但 dtype 不同;维度相同但特征
        顺序/名称不同;window_size 不同;scaler 哈希不同;账户槽位布局
        不同;nuisance 槽位数量不同。
        """
        prefix = f"[{context}] " if context else ""
        if not isinstance(other, ObservationSchema):
            raise ObservationSchemaMismatchError(
                f"{prefix}对方不是 ObservationSchema: {type(other)!r}")
        problems: list[str] = []
        if self.feature_names != other.feature_names:
            problems.append(
                f"有序特征名不同: {list(self.feature_names)} vs "
                f"{list(other.feature_names)}(顺序即输入序,语义错位)")
        if self.observation_dim != other.observation_dim:
            problems.append(
                f"observation 总维度不同: {self.observation_dim} vs "
                f"{other.observation_dim}")
        if self.window_size != other.window_size:
            problems.append(
                f"window_size 不同: {self.window_size} vs {other.window_size}")
        if self.dtype != other.dtype:
            problems.append(f"dtype 不同: {self.dtype} vs {other.dtype}")
        if self.normalization_method != other.normalization_method:
            problems.append(
                f"归一化方法不同: {self.normalization_method} vs "
                f"{other.normalization_method}")
        if self.normalization_pipeline_hash != other.normalization_pipeline_hash:
            problems.append(
                f"归一化 pipeline 哈希不同: {self.normalization_pipeline_hash} "
                f"vs {other.normalization_pipeline_hash}(scaler 被替换)")
        if self.account_slots != other.account_slots:
            problems.append(
                f"账户状态槽位不同: {list(self.account_slots)} vs "
                f"{list(other.account_slots)}")
        if self.nuisance_slot_count != other.nuisance_slot_count:
            problems.append(
                f"nuisance 槽位数量不同: {self.nuisance_slot_count} vs "
                f"{other.nuisance_slot_count}")
        if problems:
            raise ObservationSchemaMismatchError(
                f"{prefix}observation schema 语义不匹配 -> " + "; ".join(problems))

    def assert_hash_binding(self, expected_hash: str, *, context: str = "") -> None:
        actual = self.schema_hash()
        if actual != expected_hash:
            raise ObservationSchemaMismatchError(
                f"[{context}] observation schema hash 不匹配:期望 {expected_hash},"
                f"实际 {actual}(特征/维度/窗口/dtype/归一化/槽位任一变化都会改变哈希;"
                f"总维度相同不代表语义相同)")

    def assert_sidecar_binding(self, sidecar: dict[str, Any], *, context: str = "") -> None:
        """checkpoint sidecar v2 的 observation 绑定逐项校验(工作包 F)。"""
        prefix = f"[{context}] " if context else ""
        fields = (
            "observation_schema_hash", "observation_feature_names",
            "observation_dim", "observation_window_size", "observation_dtype",
            "observation_normalization_pipeline_hash",
        )
        missing = [f for f in fields if f not in sidecar]
        if missing:
            raise ObservationSchemaMismatchError(
                f"{prefix}sidecar 缺少 observation 绑定字段: {missing}"
                f"(formal checkpoint 必须绑定 observation schema)")
        problems: list[str] = []
        if sidecar["observation_schema_hash"] != self.schema_hash():
            problems.append("schema hash 不同")
        if list(sidecar["observation_feature_names"]) != list(self.feature_names):
            problems.append(
                f"有序特征名不同: {sidecar['observation_feature_names']} vs "
                f"{list(self.feature_names)}")
        if int(sidecar["observation_dim"]) != self.observation_dim:
            problems.append(f"维度不同: {sidecar['observation_dim']} vs {self.observation_dim}")
        if int(sidecar["observation_window_size"]) != self.window_size:
            problems.append(
                f"window_size 不同: {sidecar['observation_window_size']} vs "
                f"{self.window_size}")
        if sidecar["observation_dtype"] != self.dtype:
            problems.append(f"dtype 不同: {sidecar['observation_dtype']} vs {self.dtype}")
        if sidecar["observation_normalization_pipeline_hash"] != \
                self.normalization_pipeline_hash:
            problems.append(
                f"归一化 pipeline 不同: "
                f"{sidecar['observation_normalization_pipeline_hash']} vs "
                f"{self.normalization_pipeline_hash}")
        if problems:
            raise ObservationSchemaMismatchError(
                f"{prefix}checkpoint observation 绑定不匹配 -> " + "; ".join(problems))

    def sidecar_binding(self) -> dict[str, Any]:
        """写入 checkpoint sidecar 的 observation 绑定字段。"""
        return {
            "observation_schema_hash": self.schema_hash(),
            "observation_feature_names": list(self.feature_names),
            "observation_dim": self.observation_dim,
            "observation_window_size": self.window_size,
            "observation_dtype": self.dtype,
            "observation_normalization_pipeline_hash": self.normalization_pipeline_hash,
        }

    def assert_column_whitelist(self, columns: list[str], *, context: str = "") -> None:
        """Episode 的特征列必须与 whitelist 精确一致(集合相等;
        输入顺序由 schema 决定,不由 DataFrame 列序决定)。"""
        prefix = f"[{context}] " if context else ""
        extra = sorted(set(columns) - set(self.feature_names))
        missing = sorted(set(self.feature_names) - set(columns))
        if extra or missing:
            raise ObservationSchemaError(
                f"{prefix}特征列与 schema whitelist 不一致"
                f"(额外列 fail closed: {extra};缺失列: {missing};"
                f"whitelist = {list(self.feature_names)})")


def schema_from_json(text: str) -> ObservationSchema:
    data = json.loads(text)
    if data.get("format") != OBSERVATION_SCHEMA_FORMAT:
        raise ObservationSchemaError(
            f"observation schema format {data.get('format')!r} != "
            f"{OBSERVATION_SCHEMA_FORMAT!r}")
    return ObservationSchema(
        schema_version=data["schema_version"],
        features=tuple(
            FeatureSpec(
                name=f["name"], available_at=f["available_at"],
                max_history_bars=int(f["max_history_bars"]),
                nuisance=bool(f.get("nuisance", False)),
                signal_group=f.get("signal_group", ""),
                normalization=f.get("normalization", "identity"),
            ) for f in data["features"]
        ),
        window_size=int(data["window_size"]),
        dtype=data.get("dtype", "float32"),
        account_slots=tuple(data.get("account_slots", DEFAULT_ACCOUNT_SLOTS)),
        includes_cost_context=bool(data.get("includes_cost_context", False)),
        normalization_method=data.get("normalization_method", "identity"),
        normalization_pipeline_hash=data.get("normalization_pipeline_hash", "identity-v1"),
        nuisance_fill=data.get("nuisance_fill", "independent_noise"),
    )
