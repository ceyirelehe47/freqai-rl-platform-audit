"""阶段 2.6.2:PPO episode bank 构成、生成与 staged/mixed 顺序。

- 复用 2.6.1 三族生成器(只读):C1OpportunityGenerator /
  C2ContextGatingGenerator / C3CostAwareGenerator,rung 参数一律从
  **锁定的 R2 qualification plan** 读取(不信任源码常量,防漂移);
- seed 派生走 2.6.2 自己的 derive262_seed(namespace 隔离);
- 尝试策略沿用 first_pass / max_attempts=5 / 结构性拒绝词表
  (generate_pair_with_attempts 的 2.6.1 语义,seed 入口换成 262);
- core bank 固定 640 episodes(§16 构成表),三 replicate 用全局
  pair_index 区间互斥;
- staged order = C1 D0→D1→D2→D3 → C2 ... → C3 ...;
  mixed order = 同一 multiset 的确定性 shuffle(shuffle seed 从
  replicate model seed 派生,预注册);
- manifest equality:same_multiset = true / different_order = true。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from rl_curriculum.curriculum261_api import (
    CURRICULUM261_TIMEFRAME,
    CURRICULUM261_FAMILIES,
    CURRICULUM261_RUNGS,
    AttemptRecord,
    EpisodeAttemptLog,
    PairGenerationError,
    check_attempt_log,
    episode_content_hash,
)
from rl_curriculum.curriculum261_pairs import (
    FamilySpec,
    compute_pair_integrity,
    family_specs,
    pair_structural_contract,
)
from rl_curriculum.generator_api import GeneratedEpisode, GeneratorError
from rl_curriculum.ppo262_namespaces import (
    PPO262_MODEL_SEEDS,
    PPO262_REPLICATES,
    core_train_namespace,
    derive262_seed,
)

# ---------------------------------------------------------------- bank 构成
#: core 训练 bank 固定构成(§16:640 episodes;family × rung 计数为
#: **episode 数(端级)**——pair A/B 双端各算一个 episode;
#: 640 x 287 = 183,680 env steps)
PPO262_CORE_BANK_LAYOUT: dict[str, dict[str, int]] = {
    "c1_opportunity": {"D0": 32, "D1": 48, "D2": 64, "D3": 16},
    "c2_context": {"D0": 24, "D1": 72, "D2": 96, "D3": 48},
    "c3_cost": {"D0": 24, "D1": 72, "D2": 96, "D3": 48},
}
PPO262_CORE_BANK_EPISODES = sum(
    n for per in PPO262_CORE_BANK_LAYOUT.values() for n in per.values())
#: staged 家族顺序:C1 → C2 → C3(rung 内 D0→D1→D2→D3)
PPO262_STAGED_FAMILY_ORDER = ("c1_opportunity", "c2_context", "c3_cost")
#: pair A/B 双端都进入训练 bank(pair 是统计单位;训练暴露同 multiset)
PPO262_SIDES = ("A", "B")


def core_bank_step_count(episodes: int = PPO262_CORE_BANK_EPISODES,
                         episode_bars: int = 288, window_size: int = 1) -> int:
    """core run 环境步数(每 episode 决策步 = bars - window)。"""
    return episodes * (episode_bars - window_size)


#: 每 replicate 的全局 pair_index 偏移(family/rung 内顺序编号 + 偏移,
#: 三 replicate 区间互斥:rep1 [0,640) rep2 [640,1280) rep3 [1280,1920))
def replicate_pair_offset(replicate: int) -> int:
    k = int(replicate)
    if k not in PPO262_REPLICATES:
        raise ValueError(f"replicate 必须是 {PPO262_REPLICATES}")
    return (k - 1) * PPO262_CORE_BANK_EPISODES


# ---------------------------------------------------------------- episode key
@dataclass(frozen=True)
class EpisodeKey:
    """训练/评估 bank 中一个 episode 的完整身份。

    variant ∈ {"A","B"}:pair A/B 双端(pair nuisance 合同下 A/B 共享
    随机流,只是因果映射不同;2.6.2 训练/评估都按端粒度消费)。
    """

    namespace: str
    family: str
    rung: str
    pair_index: int
    variant: str

    def canonical(self) -> str:
        return (f"{self.namespace}|{self.family}|{self.rung}|"
                f"{self.pair_index}|{self.variant}")

    def side_key(self) -> tuple[str, str, int]:
        """pair 身份(namespace 内唯一;A/B 同键)。"""
        return (self.namespace, f"{self.family}/{self.rung}",
                int(self.pair_index))


@dataclass
class LoadedEpisode:
    """已生成的 episode(内存驻留;df + hidden + 身份)。"""

    key: EpisodeKey
    episode: GeneratedEpisode
    content_hash: str

    def canonical(self) -> dict[str, Any]:
        return {
            "namespace": self.key.namespace,
            "family": self.key.family,
            "rung": self.key.rung,
            "pair_index": int(self.key.pair_index),
            "variant": self.key.variant,
            "seed": int(self.episode.spec.seed),
            "content_hash": self.content_hash,
            "family_version": self.episode.family_version,
        }


# ---------------------------------------------------------------- pair 生成
def generate262_pair(
    family: str, rung: str, pair_index: int, *, namespace: str,
    locked_rung_params: dict[str, Any],
) -> dict[str, GeneratedEpisode]:
    """2.6.2 的确定性 pair 生成(2.6.1 attempt 语义 + 262 seed 派生)。

    - rung 参数必须来自锁定 R2 plan 的 families.{family}.rung_params;
    - 结构拒绝沿用 pair_structural_contract(2.6.1 唯一合同源);
    - 与 2.6.1 generate_pair 的唯一差异:seed = derive262_seed(...)
      (2.6.1 派生函数的 namespace 列表属冻结合同,不可扩充)。
    """
    if rung not in CURRICULUM261_RUNGS:
        raise GeneratorError(f"未知 rung {rung!r}")
    params_src = dict(locked_rung_params[rung])
    params_src["cur261_rung"] = rung
    spec = family_specs()[family]
    base_params = {
        side: spec.generator.base_params(params_src, side)
        for side in PPO262_SIDES
    }
    issues_all: list[list[str]] = []
    for attempt in range(5):
        seed = derive262_seed(namespace, family, rung, pair_index, attempt)
        episodes: dict[str, GeneratedEpisode] = {}
        try:
            for side in PPO262_SIDES:
                episodes[side] = spec.generator.generate(
                    base_params[side], seed,
                    split=f"curriculum261_{namespace}",
                    timeframe=CURRICULUM261_TIMEFRAME)
            issues = list(pair_structural_contract(
                episodes["A"], episodes["B"], family))
        except GeneratorError as exc:
            issues = [f"generator_contract:{str(exc)[:200]}"]
        if not issues:
            return episodes
        issues_all.append(issues)
    raise PairGenerationError(
        f"{family}/{rung}/pair{pair_index}@{namespace}: 5 次尝试全部未"
        f"通过结构性校验: {issues_all}")


def generate262_bank(
    keys: list[EpisodeKey], *, locked_plan_rung_params: dict[str, Any],
    progress: bool = False,
) -> list[LoadedEpisode]:
    """按 key 列表生成 episode bank(pair A/B 一次生成两份)。"""
    pair_cache: dict[tuple, dict[str, GeneratedEpisode]] = {}
    out: list[LoadedEpisode] = []
    pair_keys = {}
    for k in keys:
        pair_keys.setdefault(k.side_key(), (k.family, k.rung, k.pair_index,
                                            k.namespace))
    for i, (sk, (family, rung, pair_index, namespace)) in enumerate(
            pair_keys.items()):
        pair_cache[sk] = generate262_pair(
            family, rung, pair_index, namespace=namespace,
            locked_rung_params=locked_plan_rung_params[family])
        if progress and (i + 1) % 50 == 0:
            print(f"  generated {i + 1}/{len(pair_keys)} pairs", flush=True)
    for k in keys:
        ep = pair_cache[k.side_key()][k.variant]
        out.append(LoadedEpisode(
            key=k, episode=ep, content_hash=episode_content_hash(ep)))
    return out


# ---------------------------------------------------------------- bank 规划
def core_bank_keys(replicate: int) -> list[EpisodeKey]:
    """replicate k 的 core 训练 bank keys(staged 顺序)。

    布局计数为 episode 数(端级):family × rung 条目 = pairs × 2。
    """
    ns = core_train_namespace(replicate)
    offset = replicate_pair_offset(replicate)
    keys: list[EpisodeKey] = []
    for family in PPO262_STAGED_FAMILY_ORDER:
        for rung in CURRICULUM261_RUNGS:
            n_eps = PPO262_CORE_BANK_LAYOUT[family][rung]
            if n_eps % 2 != 0:
                raise ValueError(
                    f"{family}/{rung} episode 数 {n_eps} 必须为偶数"
                    f"(pair A/B 双端)")
            for j in range(n_eps // 2):
                for side in PPO262_SIDES:
                    keys.append(EpisodeKey(
                        ns, family, rung, offset + j, side))
    assert len(keys) == PPO262_CORE_BANK_EPISODES
    return keys


def staged_order(keys: list[EpisodeKey]) -> list[EpisodeKey]:
    """staged 顺序:按 family(C1→C2→C3) → rung(D0..D3) → pair → side。

    core_bank_keys 已按该序生成;本函数显式重排以支持任意输入 multiset。
    """
    fam_rank = {f: i for i, f in enumerate(PPO262_STAGED_FAMILY_ORDER)}
    rung_rank = {r: i for i, r in enumerate(CURRICULUM261_RUNGS)}
    side_rank = {s: i for i, s in enumerate(PPO262_SIDES)}
    return sorted(keys, key=lambda k: (
        fam_rank[k.family], rung_rank[k.rung], k.pair_index,
        side_rank[k.variant]))


def mixed_order(keys: list[EpisodeKey], *, model_seed: int) -> list[EpisodeKey]:
    """mixed 顺序:同一 multiset 的确定性 shuffle(shuffle seed 派生)。

    shuffle seed 从 (stage, iteration, model_seed) 哈希派生——同
    replicate 的 staged/mixed 共享 multiset、只差顺序(§17);不同
    replicate shuffle 不同(可审计)。
    """
    payload = json.dumps(
        ["stage2_6_2", "s262_mixed_shuffle", int(model_seed)],
        sort_keys=True, separators=(",", ":"))
    shuffle_seed = int.from_bytes(
        hashlib.sha256(payload.encode("utf-8")).digest()[:8], "big")
    rng = np.random.default_rng(shuffle_seed)
    arr = list(keys)
    order = rng.permutation(len(arr))
    return [arr[i] for i in order]


def manifest_equality(staged: list[EpisodeKey],
                      mixed: list[EpisodeKey]) -> dict[str, Any]:
    """staged/mixed manifest equality artifact(§17)。"""
    c_staged = sorted(k.canonical() for k in staged)
    c_mixed = sorted(k.canonical() for k in mixed)
    same_multiset = c_staged == c_mixed
    different_order = [k.canonical() for k in staged] != [
        k.canonical() for k in mixed]
    return {
        "format": "ppo262-manifest-pairing-v1",
        "episodes": len(staged),
        "same_multiset": same_multiset,
        "different_order": different_order,
        "pass": same_multiset and different_order,
    }


# ---------------------------------------------------------------- manifest
def bank_manifest(bank: list[LoadedEpisode]) -> dict[str, Any]:
    """训练 bank manifest(顺序即训练顺序;hash 供 plan 绑定)。"""
    entries = [e.canonical() for e in bank]
    payload = json.dumps(entries, sort_keys=False, separators=(",", ":"))
    return {
        "format": "ppo262-bank-manifest-v1",
        "n_episodes": len(entries),
        "entries": entries,
        "manifest_sha256": hashlib.sha256(
            payload.encode("utf-8")).hexdigest(),
        "unique_pair_seeds": len({e.episode.spec.seed for e in bank}),
    }
