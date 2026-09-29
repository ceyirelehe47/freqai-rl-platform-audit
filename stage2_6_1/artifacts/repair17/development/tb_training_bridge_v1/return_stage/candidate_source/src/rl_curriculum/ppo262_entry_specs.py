"""阶段 2.6.2 Engineering Bridge:消费入口准备管线(B1 修复)。

ChatGPT 终审 B1:route_profile_inputs 手写字典不构成真实路由。本模块
把六类消费入口(smoke/config-dev/probe/core/dev-eval/final)的**输入
解析 + bank/评估坐标规划**提取为命令与检查共用的实现:

- prepare_X_inputs():真实命令(cmd_*)实际调用的输入准备函数——
  profile 上下文存在时参数/阈值来自已验证 QualifiedInput(pack,含
  verify_integrity),train/eval 坐标进入隔离工程 namespace
  ppo_eng_bank_262e;缺省(无上下文)保持官方 R2 参数与官方 namespace
  逐字节不变;
- EntrySpec.build_bank(generate_bank=None):真实 generator 消费边界
  (缺省 = generate262_bank 本体;检查可注入哨兵,零生成);
- EntrySpec.build_reference(...):评估 reference/baseline 消费边界
  (缺省 = build_261_policy_set 本体)。

官方命令的 gates(config/probe/core/final gate)不在本模块——它们是
入口门禁,不是输入来源;gate 通过后命令才调用 prepare_*。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from rl_curriculum.curriculum261_api import CURRICULUM261_RUNGS
from rl_curriculum.ppo262_banks import EpisodeKey, staged_order
from rl_curriculum.ppo262_config import (
    PPO262_CONFIG_DEV_EPISODES_PER_FAMILY,
    PPO262_CONFIG_DEV_EVAL_PAIRS_PER_FAMILY, PPO262_CONFIG_DEV_EVAL_PAIR_BASE,
    PPO262_CONFIG_DEV_FAMILIES, PPO262_CONFIG_DEV_RUNG,
    PPO262_CONFIG_DEV_TRAIN_PAIR_BASE, PPO262_DEV_EVAL_PAIRS_PER_RUNG,
    PPO262_FINAL_EVAL_PAIRS_PER_RUNG, PPO262_PROBE_BUDGETS,
)
from rl_curriculum.ppo262_qualified_input import (
    active_profile_input, authorization_binding_digest,  # noqa: F401
)

#: 工程 profile 上下文下的统一隔离 train/eval namespace
PROFILE_BANK_NAMESPACE = "ppo_eng_bank_262e"

_OFFICIAL_FAMILIES = ("c1_opportunity", "c2_context", "c3_cost")


def _resolve_rung_params() -> tuple[dict[str, Any], dict[str, Any], str]:
    """共享参数解析:profile 上下文(pack)或官方 R2;返回 (rung,
    thresholds, namespace)。"""
    from rl_curriculum.curriculum261_plan import load_locked_plan
    from rl_curriculum.curriculum261_api import (
        qualification_r2_lock_marker,
    )

    qi = active_profile_input()
    if qi is not None:
        qi.verify_integrity()  # B2.2:消费边界重验
        return qi.rung_params(), qi.reference_thresholds(), (
            PROFILE_BANK_NAMESPACE)
    plan, _ = load_locked_plan(qualification_r2_lock_marker().parent)
    rung = {fam: fp["rung_params"] for fam, fp in plan["families"].items()}
    thr = {fam: fp["reference_thresholds"]
           for fam, fp in plan["families"].items()}
    return rung, thr, "official"


@dataclass
class EntrySpec:
    """一个消费入口经共享解析得到的真实输入与坐标。

    build_bank/build_reference 是命令实际使用的 generator/评估消费
    边界;generate_bank/build 参数仅供哨兵注入(零生成检查),缺省
    即真实实现。
    """

    entry: str
    rung_params: dict[str, Any]
    reference_thresholds: dict[str, Any]
    namespace: str
    bank_keys: list[EpisodeKey] = field(default_factory=list)
    config: dict[str, Any] | None = None
    config_name: str | None = None
    model_seed: int | None = None
    total_steps: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------ 消费边界
    def build_bank(self, *, generate_bank: Callable | None = None,
                   progress: bool = False, keys: list | None = None):
        """真实 generator 消费边界(缺省 = generate262_bank 本体)。

        keys 覆盖:同一入口内第二 bank(如 config-dev 的 per-family
        训练 bank)仍走同一消费边界与同一 rung_params 来源。
        """
        if generate_bank is None:
            from rl_curriculum.ppo262_banks import generate262_bank
            generate_bank = generate262_bank
        return generate_bank(
            list(self.bank_keys if keys is None else keys),
            locked_plan_rung_params=self.rung_params,
            progress=progress)

    def build_reference(self, family: str, rung: str, *, build=None):
        """评估 reference/baseline 消费边界(缺省 = build_261_policy_set)。"""
        if build is None:
            from rl_curriculum.ppo262_metrics import build_261_policy_set
            build = build_261_policy_set
        return build(family, self.rung_params[family][rung],
                     self.reference_thresholds[family])

    def assert_from_profile(self, qi) -> None:
        """检查用断言:本 spec 的参数/阈值/坐标确实来自该已验证输入。"""
        if self.namespace != PROFILE_BANK_NAMESPACE:
            raise AssertionError(
                f"{self.entry}: profile 上下文下 namespace "
                f"{self.namespace!r} != {PROFILE_BANK_NAMESPACE!r}")
        if self.rung_params != qi.rung_params():
            raise AssertionError(
                f"{self.entry}: rung_params 与 pack 不一致(真实路由断裂)")
        if self.reference_thresholds != qi.reference_thresholds():
            raise AssertionError(
                f"{self.entry}: thresholds 与 pack 不一致(真实路由断裂)")


# ---------------------------------------------------------------- prepare
def prepare_smoke_inputs() -> EntrySpec:
    """smoke 入口(ppo-smoke 命令实际输入来源)。"""
    rung, thr, ns = _resolve_rung_params()
    train_ns = ns if ns != "official" else "ppo_smoke_262"
    keys = [EpisodeKey(train_ns, fam, "D1", 0, side)
            for fam in _OFFICIAL_FAMILIES for side in ("A", "B")]
    return EntrySpec(entry="smoke", rung_params=rung,
                     reference_thresholds=thr, namespace=train_ns,
                     bank_keys=keys)


def prepare_config_dev_inputs() -> EntrySpec:
    rung, thr, ns = _resolve_rung_params()
    train_ns = ns if ns != "official" else "ppo_config_dev_262"
    eval_keys: list[EpisodeKey] = []
    for fam in PPO262_CONFIG_DEV_FAMILIES:
        n_eps = PPO262_CONFIG_DEV_EVAL_PAIRS_PER_FAMILY * 2
        for j in range(n_eps // 2):
            for variant in ("A", "B"):
                eval_keys.append(EpisodeKey(
                    train_ns, fam, PPO262_CONFIG_DEV_RUNG,
                    PPO262_CONFIG_DEV_EVAL_PAIR_BASE + j, variant))
    return EntrySpec(
        entry="config_dev", rung_params=rung, reference_thresholds=thr,
        namespace=train_ns, bank_keys=eval_keys,
        extra={
            "train_pair_base": PPO262_CONFIG_DEV_TRAIN_PAIR_BASE,
            "episodes_per_family": PPO262_CONFIG_DEV_EPISODES_PER_FAMILY,
            "rung": PPO262_CONFIG_DEV_RUNG,
            "families": list(PPO262_CONFIG_DEV_FAMILIES),
        })


def config_dev_train_keys(spec: EntrySpec, family: str) -> list[EpisodeKey]:
    """config-dev 每 family 的训练 keys(与命令共享的坐标派生)。"""
    from rl_curriculum.ppo262_banks import staged_order
    n = spec.extra["episodes_per_family"]
    keys = [EpisodeKey(spec.namespace, family, spec.extra["rung"],
                       spec.extra["train_pair_base"] + j, v)
            for j in range(n // 2) for v in ("A", "B")]
    return staged_order(keys)


def prepare_probe_inputs(family: str, *, config_name: str,
                         config: dict[str, Any]) -> EntrySpec:
    from rl_curriculum.ppo262_namespaces import PPO262_PROBE_NAMESPACES
    rung, thr, ns = _resolve_rung_params()
    train_ns = ns if ns != "official" else PPO262_PROBE_NAMESPACES[family]
    layout = PPO262_PROBE_BUDGETS[family]
    keys = []
    for rung_name in CURRICULUM261_RUNGS:
        n_pairs = layout[rung_name] // 2
        for j in range(n_pairs):
            for variant in ("A", "B"):
                keys.append(EpisodeKey(
                    train_ns, family, rung_name, j, variant))
    keys = staged_order(keys)
    total_eps = sum(layout.values())
    return EntrySpec(
        entry="probe", rung_params=rung, reference_thresholds=thr,
        namespace=train_ns, bank_keys=keys, config=dict(config),
        config_name=config_name, model_seed=26201,
        total_steps=total_eps * 287,
        extra={"budget_episodes": total_eps})


def prepare_core_inputs(replicate: int, order: str) -> EntrySpec:
    from rl_curriculum.ppo262_namespaces import (
        PPO262_MODEL_SEEDS, core_train_namespace,
    )
    from rl_curriculum.ppo262_banks import (
        core_bank_keys, mixed_order, staged_order as _staged,
    )
    rung, thr, ns = _resolve_rung_params()
    if ns != "official":
        # 工程 profile 的 core 坐标:同一隔离 namespace 的追加 pair
        # 区间(pair_index 从 1000 起,与 smoke/config-dev 工程区间分离)
        keys = _eng_core_keys(ns)
        train_ns = ns
    else:
        base = core_bank_keys(replicate)
        keys = (_staged(base) if order == "staged"
                else mixed_order(base, model_seed=PPO262_MODEL_SEEDS[
                    replicate - 1]))
        train_ns = core_train_namespace(replicate)
    return EntrySpec(
        entry="core", rung_params=rung, reference_thresholds=thr,
        namespace=str(keys[0].namespace) if keys else train_ns,
        bank_keys=keys,
        model_seed=(PPO262_MODEL_SEEDS[replicate - 1]
                    if ns == "official" else None),
        total_steps=(len(keys) * 287) if keys else None,
        extra={"replicate": replicate, "order": order})


def _eng_core_keys(ns: str) -> list[EpisodeKey]:
    keys = []
    pair = 1000
    for fam in _OFFICIAL_FAMILIES:
        for rung_name in CURRICULUM261_RUNGS:
            for v in ("A", "B"):
                keys.append(EpisodeKey(ns, fam, rung_name, pair, v))
    return staged_order(keys)



def prepare_dev_eval_inputs() -> EntrySpec:
    rung, thr, ns = _resolve_rung_params()
    train_ns = ns if ns != "official" else "ppo_dev_eval_262"
    keys = []
    for fam in _OFFICIAL_FAMILIES:
        for rung_name in CURRICULUM261_RUNGS:
            for j in range(PPO262_DEV_EVAL_PAIRS_PER_RUNG):
                for variant in ("A", "B"):
                    keys.append(EpisodeKey(
                        train_ns, fam, rung_name, j, variant))
    return EntrySpec(entry="dev_eval", rung_params=rung,
                     reference_thresholds=thr, namespace=train_ns,
                     bank_keys=keys)


def prepare_final_inputs() -> EntrySpec:
    """final 入口:官方坐标属正式链(锁定 plan 派生);profile 上下文
    下坐标仍为官方 final 坐标但参数/阈值来自 pack——正式入口本身仍受
    final gate 与 formal admission 约束(工程上下文不解锁正式 final)。"""
    rung, thr, ns = _resolve_rung_params()
    train_ns = ns if ns != "official" else "ppo_final_eval_262"
    keys = []
    for fam in _OFFICIAL_FAMILIES:
        for rung_name in CURRICULUM261_RUNGS:
            for j in range(PPO262_FINAL_EVAL_PAIRS_PER_RUNG):
                for variant in ("A", "B"):
                    keys.append(EpisodeKey(
                        train_ns, fam, rung_name, j, variant))
    return EntrySpec(entry="final", rung_params=rung,
                     reference_thresholds=thr, namespace=train_ns,
                     bank_keys=keys,
                     extra={"note": "final 消费仍需 final gate + formal "
                                    "admission;工程上下文不签发正式许"})

ENTRY_PREPARERS = {
    "smoke": prepare_smoke_inputs,
    "config_dev": prepare_config_dev_inputs,
    "probe": None,   # 需要 family/config 参数,单独驱动
    "core": None,    # 需要 replicate/order,单独驱动
    "dev_eval": prepare_dev_eval_inputs,
    "final": prepare_final_inputs,
}
