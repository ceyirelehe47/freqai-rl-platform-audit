"""阶段 2.6.2 Repair R1:诊断 seed namespace(s262_diag_r1,独立派生流)。

- 与 s262_r0 的 11 个 official namespace(ppo_*_262)字符串零重合,
  与 2.6.1 全部 namespace 零重合;派生 payload 前缀仍为
  "stage2_6_2"(同族派生),但 namespace 枚举完全独立;
- 诊断 seed 一律走本模块 derive262_diag_seed,不得调用
  derive262_seed(official 白名单不接受 diag namespace——防诊断
  语料混入 official 流);
- 诊断 namespace 不含 final corpus,不触碰 ppo_final_eval_262,
  不生成 official final lock / exposure;
- 3 个 model seed 的训练/评估 bank 用全局 pair_index 区间互斥
  (bank 不重合合同,见 verify_diag_namespace_isolation 的区间记录)。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from rl_curriculum.curriculum261_api import (
    CURRICULUM261_FAMILIES,
    CURRICULUM261_RUNGS,
    CURRICULUM261_SEED_NAMESPACES as _NAMESPACES_261,
)

# ---------------------------------------------------------------- 身份
DIAG262_ITERATION_ID = "s262_diag_r1"
DIAG262_STAGE_ID = "stage2_6_2"

#: 诊断 model seeds(与 official PPO262_MODEL_SEEDS 26201-26203 不重合;
#: overfit 用 2710x,ablation 用 2720x,BC 用 2730x)
DIAG262_OVERFIT_SEEDS = (27101, 27102, 27103)
DIAG262_ABLATION_SEEDS = (27201, 27202, 27203)
DIAG262_BC_SEEDS = (27301, 27302, 27303)

#: 诊断固定 RNG(概率级 stochastic 评估 / 监督划分等)
DIAG262_PROB_RNG_SEED = 262099

#: 全部诊断 namespace(显式枚举;training/eval 互不重合,
#: 与 s262_r0 的 11 个 official namespace 及 2.6.1 全部 namespace
#: 字符串零重合)
DIAG262_NAMESPACES: tuple[str, ...] = (
    "diag262r1_feature_profile",   # 特征尺度 profile(只读统计,不训练)
    "diag262r1_supervised_train",  # 监督探针训练语料(pair 级划分)
    "diag262r1_supervised_eval",   # 监督探针 held-out(pair 级划分)
    "diag262r1_overfit_c1",        # tiny overfit Test A(C1 D0)
    "diag262r1_overfit_c2",        # tiny overfit Test B(C2 D0)
    "diag262r1_overfit_c3",        # tiny overfit Test C(C3 D0)
    "diag262r1_preprocess_train",  # preprocessing ablation 训练 bank
    "diag262r1_preprocess_eval",   # preprocessing ablation 评估 bank
    "diag262r1_bc_train",          # BC warm-start 训练语料
    "diag262r1_bc_eval",           # BC warm-start held-out
    "diag262r1_smoke",             # 诊断 harness smoke
)

#: 每 model seed 的全局 pair 偏移区间(bank 不重合合同:
#: seed i 使用 [i*32, i*32+32) 的 pair 区间;eval 语料统一 +256 偏移)
DIAG262_SEED_PAIR_STRIDE = 32
DIAG262_EVAL_PAIR_BASE = 256


def diag_seed_pair_base(seed_slot: int) -> int:
    """model seed 槽位(0/1/2)的训练 pair 基址。"""
    if seed_slot not in (0, 1, 2):
        raise ValueError("seed_slot 必须是 0/1/2")
    return seed_slot * DIAG262_SEED_PAIR_STRIDE


# ---------------------------------------------------------------- 派生
def derive262_diag_seed(
    namespace: str, family: str, rung: str, pair_index: int, attempt: int,
) -> int:
    """诊断确定性 seed 派生(单一来源;official derive262_seed 不接受)。"""
    if namespace not in DIAG262_NAMESPACES:
        raise ValueError(
            f"seed namespace {namespace!r} 不在 s262_diag_r1 诊断集合"
            f"({len(DIAG262_NAMESPACES)} 个;official 262 namespace 与"
            f" 2.6.1 namespace 一律拒绝)")
    return _derive_diag_raw(
        namespace, family, rung, pair_index, attempt)


def _derive_diag_raw(
    namespace: str, family: str, rung: str, pair_index: int, attempt: int,
) -> int:
    payload = json.dumps(
        [DIAG262_STAGE_ID, namespace, family, rung,
         int(pair_index), int(attempt)],
        sort_keys=True, separators=(",", ":"))
    return int.from_bytes(
        hashlib.sha256(payload.encode("utf-8")).digest()[:8], "big")


# ---------------------------------------------------------------- 隔离验证
def _ns_seed_set(namespace: str, *, pair_range: range, attempts: int,
                 families=CURRICULUM261_FAMILIES, rungs=CURRICULUM261_RUNGS,
                 raw_fn=_derive_diag_raw) -> set[int]:
    out: set[int] = set()
    for family in families:
        for rung in rungs:
            for pair_index in pair_range:
                for attempt in range(attempts):
                    out.add(raw_fn(namespace, family, rung, pair_index,
                                   attempt))
    return out


def verify_diag_namespace_isolation(
    *, pair_range: range, official_pair_range: range,
    pair_range_261: range, attempts: int = 5,
) -> dict:
    """诊断 namespace 隔离合同验证(seed 整数层面全量枚举)。

    - diag namespace 两两不相交;
    - diag ∩ s262_r0 official 11 namespace = 空;
    - diag ∩ 2.6.1 全部 namespace = 空;
    - 诊断 iteration 与 official iteration 字符串隔离记录。
    """
    from rl_curriculum.ppo262_namespaces import (
        _derive262_seed_raw as _official_raw,
        all_262_namespaces,
    )

    ns_diag = list(DIAG262_NAMESPACES)
    sets_diag: dict[str, set[int]] = {
        ns: _ns_seed_set(ns, pair_range=pair_range, attempts=attempts)
        for ns in ns_diag}
    problems: list[str] = []
    ordered = sorted(sets_diag)
    for i, a in enumerate(ordered):
        for b in ordered[i + 1:]:
            inter = sets_diag[a] & sets_diag[b]
            if inter:
                problems.append(f"{a} ∩ {b} = {len(inter)} seed 重合")
    # official 262(s262_r0)与 2.6.1 的 seed 合并集(逐 namespace 记录
    # 命中;合并集求交避免 O(n^2) 两两全枚举)
    merged_official: dict[int, str] = {}
    for ons in all_262_namespaces():
        for s in _ns_seed_set(ons, pair_range=official_pair_range,
                              attempts=attempts, raw_fn=_official_raw):
            merged_official.setdefault(s, ons)

    def _ns261_raw(namespace, family, rung, pair_index, attempt):
        payload = json.dumps(
            ["stage2_6_1", namespace, family, rung,
             int(pair_index), int(attempt)],
            sort_keys=True, separators=(",", ":"))
        return int.from_bytes(
            hashlib.sha256(payload.encode("utf-8")).digest()[:8], "big")

    merged_261: dict[int, str] = {}
    for ns_old in _NAMESPACES_261:
        for s in _ns_seed_set(ns_old, pair_range=pair_range_261,
                              attempts=attempts, raw_fn=_ns261_raw):
            merged_261.setdefault(s, ns_old)
    cross_official: dict[str, int] = {}
    cross_261: dict[str, int] = {}
    for ns in ordered:
        for s in sets_diag[ns]:
            hit = merged_official.get(s)
            if hit is not None:
                key = f"{ns}|{hit}"
                cross_official[key] = cross_official.get(key, 0) + 1
                problems.append(f"diag:{ns} ∩ official:{hit} seed 重合")
            hit261 = merged_261.get(s)
            if hit261 is not None:
                key = f"{ns}|{hit261}"
                cross_261[key] = cross_261.get(key, 0) + 1
                problems.append(f"diag:{ns} ∩ 261:{hit261} seed 重合")
    return {
        "format": "ppo262-diag-namespace-integrity-v1",
        "stage": DIAG262_STAGE_ID,
        "iteration": DIAG262_ITERATION_ID,
        "namespaces_diag": ordered,
        "official_iteration_preserved": "s262_r0",
        "namespaces_261_checked": list(_NAMESPACES_261),
        "pair_range_diag": [pair_range.start, pair_range.stop],
        "pair_range_official": [official_pair_range.start,
                                official_pair_range.stop],
        "pair_range_261": [pair_range_261.start, pair_range_261.stop],
        "attempts_enumerated": attempts,
        "seeds_per_namespace_diag": {k: len(v)
                                     for k, v in sets_diag.items()},
        "cross_official_overlaps": cross_official,
        "cross_261_overlaps": cross_261,
        "final_namespace_untouched": True,
        "problems": problems,
        "pass": not problems,
    }
