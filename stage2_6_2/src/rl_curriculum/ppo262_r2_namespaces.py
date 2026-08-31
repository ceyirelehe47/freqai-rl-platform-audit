"""阶段 2.6.2 Repair R2:诊断 seed namespace(s262_diag_r2_1,独立派生流)。

iteration 历史(诚实记录):
- s262_diag_r2(锁 dp-0551c1a1):gradient-verify 的 clipping 单调性
  检查浮点容差缺陷,在任何正式 bank 生成前发现,清空重锁;
- s262_diag_r2(锁 dp-0a0c2e2c):_checkpoint_diagnostics 缺
  evaluate_family_cells 导入,首个 scratch run 的 checkpoint 评估
  即崩溃(scratch/BC 零模型证据);按任务书 §13 迭代结束;
- s262_diag_r2_1(当前):修复后的重启;全部 namespace 字符串与
  model seeds 更换(新 eval seed 空间)。

隔离合同:
- 与 s262_r0 的 11 个 official namespace(ppo_*_262)字符串零重合;
- 与 s262_diag_r1 的 11 个诊断 namespace(diag262r1_*)零重合;
- 与被废止的 s262_diag_r2 namespace(diag262r2_*)零重合;
- 与 2.6.1 全部 namespace 零重合;
- 诊断 seed 一律走本模块 derive262r2_seed(单一来源);
- 不含 final corpus,不触碰 ppo_final_eval_262 / qualification_r2;
- 3 个 model seed 槽位的训练 bank 用全局 pair_index 区间互斥
  (stride 32;eval 语料 +256 偏移)。
"""

from __future__ import annotations

import hashlib
import json

from rl_curriculum.curriculum261_api import (
    CURRICULUM261_FAMILIES,
    CURRICULUM261_RUNGS,
    CURRICULUM261_SEED_NAMESPACES as _NAMESPACES_261,
)

# ---------------------------------------------------------------- 身份
DIAG262R2_ITERATION_ID = "s262_diag_r2_1"
DIAG262R2_STAGE_ID = "stage2_6_2"
DIAG262R2_NS_PREFIX = "diag262r2_1"

#: R2_1 诊断 model seeds(预注册;2840x supervised / 2850x scratch /
#: 2860x BC;与 official 26201-3、R1 2710x/2720x/2730x、被废止的
#: R2 2810x/2820x/2830x 全部不重合)
DIAG262R2_SUPERVISED_SEEDS = (28401, 28402, 28403)
DIAG262R2_SCRATCH_SEEDS = (28501, 28502, 28503)
DIAG262R2_BC_SEEDS = (28601, 28602, 28603)

#: 诊断固定 RNG(概率级 stochastic 评估;全新值)
DIAG262R2_PROB_RNG_SEED = 262311

_FAM_SHORT = {"c1_opportunity": "c1", "c2_context": "c2", "c3_cost": "c3"}


def _ns(suffix: str) -> str:
    return f"{DIAG262R2_NS_PREFIX}_{suffix}"


#: 全部 R2_1 诊断 namespace(显式枚举;train/eval 互不重合)
DIAG262R2_NAMESPACES: tuple[str, ...] = (
    _ns("integrity"),        # 评估器 sentinel/隔离枚举(非训练语料)
    _ns("supervised_train"),
    _ns("supervised_eval"),
    _ns("scratch_c1_train"),
    _ns("scratch_c1_eval"),
    _ns("scratch_c2_train"),
    _ns("scratch_c2_eval"),
    _ns("scratch_c3_train"),
    _ns("scratch_c3_eval"),
    _ns("bc_c1_train"),
    _ns("bc_c1_eval"),
    _ns("bc_c2_train"),
    _ns("bc_c2_eval"),
    _ns("bc_c3_train"),
    _ns("bc_c3_eval"),
    _ns("smoke"),            # 诊断 harness smoke(不参与任何指标)
)
DIAG262R2_SMOKE_NS = _ns("smoke")
DIAG262R2_INTEGRITY_NS = _ns("integrity")

#: 每 model seed 槽位的训练 pair 基址(bank 不重合合同)
DIAG262R2_SEED_PAIR_STRIDE = 32
DIAG262R2_EVAL_PAIR_BASE = 256


def r2_fam_short(family: str) -> str:
    return _FAM_SHORT[family]


def supervised_train_namespace() -> str:
    return _ns("supervised_train")


def supervised_eval_namespace() -> str:
    return _ns("supervised_eval")


def scratch_train_namespace(family: str) -> str:
    return _ns(f"scratch_{_FAM_SHORT[family]}_train")


def scratch_eval_namespace(family: str) -> str:
    return _ns(f"scratch_{_FAM_SHORT[family]}_eval")


def bc_train_namespace(family: str) -> str:
    return _ns(f"bc_{_FAM_SHORT[family]}_train")


def bc_eval_namespace(family: str) -> str:
    return _ns(f"bc_{_FAM_SHORT[family]}_eval")


def diag_seed_pair_base(seed_slot: int) -> int:
    """model seed 槽位(0/1/2)的训练 pair 基址。"""
    if seed_slot not in (0, 1, 2):
        raise ValueError("seed_slot 必须是 0/1/2")
    return seed_slot * DIAG262R2_SEED_PAIR_STRIDE


# ---------------------------------------------------------------- 派生
def _derive_r2_raw(
    namespace: str, family: str, rung: str, pair_index: int, attempt: int,
) -> int:
    payload = json.dumps(
        [DIAG262R2_STAGE_ID, namespace, family, rung,
         int(pair_index), int(attempt)],
        sort_keys=True, separators=(",", ":"))
    return int.from_bytes(
        hashlib.sha256(payload.encode("utf-8")).digest()[:8], "big")


def derive262r2_seed(
    namespace: str, family: str, rung: str, pair_index: int, attempt: int,
) -> int:
    """R2_1 诊断确定性 seed 派生(单一来源;拒绝一切非 r2_1 namespace)。"""
    if namespace not in DIAG262R2_NAMESPACES:
        raise ValueError(
            f"seed namespace {namespace!r} 不在 s262_diag_r2_1 诊断集合"
            f"({len(DIAG262R2_NAMESPACES)} 个;official 262 / diag r1 / "
            f"被废止的 diag262r2_* / 2.6.1 namespace 一律拒绝)")
    return _derive_r2_raw(namespace, family, rung, pair_index, attempt)


# ---------------------------------------------------------------- 隔离验证
def _ns_seed_set(namespace: str, *, pair_range: range, attempts: int,
                  families=CURRICULUM261_FAMILIES,
                  rungs=CURRICULUM261_RUNGS, raw_fn=_derive_r2_raw) -> set[int]:
    out: set[int] = set()
    for family in families:
        for rung in rungs:
            for pair_index in pair_range:
                for attempt in range(attempts):
                    out.add(raw_fn(namespace, family, rung, pair_index,
                                   attempt))
    return out


def _ns261_raw(namespace, family, rung, pair_index, attempt):
    payload = json.dumps(
        ["stage2_6_1", namespace, family, rung,
         int(pair_index), int(attempt)],
        sort_keys=True, separators=(",", ":"))
    return int.from_bytes(
        hashlib.sha256(payload.encode("utf-8")).digest()[:8], "big")


def _r2_superseded_raw(namespace, family, rung, pair_index, attempt):
    """被废止的 s262_diag_r2 派生(与前缀 diag262r2_* 的 seed 隔离验证)。"""
    payload = json.dumps(
        ["stage2_6_2", namespace.replace("diag262r2_1", "diag262r2"),
         family, rung, int(pair_index), int(attempt)],
        sort_keys=True, separators=(",", ":"))
    return int.from_bytes(
        hashlib.sha256(payload.encode("utf-8")).digest()[:8], "big")


def verify_r2_namespace_isolation(
    *, pair_range: range, official_pair_range: range,
    r1_pair_range: range, pair_range_261: range, attempts: int = 5,
) -> dict:
    """R2_1 诊断 namespace 隔离合同验证(seed 整数层面全量枚举)。

    - r2_1 namespace 两两不相交;
    - r2_1 ∩ s262_r0 official 11 namespace = 空;
    - r2_1 ∩ s262_diag_r1 11 namespace = 空;
    - r2_1 ∩ 被废止 s262_diag_r2 16 namespace = 空(迭代重启合同);
    - r2_1 ∩ 2.6.1 全部 namespace = 空;
    - r2_1 namespace 字符串不含 ppo_final_eval_262 / qualification_r2。
    """
    from rl_curriculum.ppo262_diag_namespaces import (
        _derive_diag_raw as _r1_raw,
        DIAG262_NAMESPACES as _R1_NAMESPACES,
    )
    from rl_curriculum.ppo262_namespaces import (
        _derive262_seed_raw as _official_raw,
        all_262_namespaces,
    )

    ns_r2 = list(DIAG262R2_NAMESPACES)
    sets_r2: dict[str, set[int]] = {
        ns: _ns_seed_set(ns, pair_range=pair_range, attempts=attempts)
        for ns in ns_r2}
    problems: list[str] = []
    ordered = sorted(sets_r2)
    for i, a in enumerate(ordered):
        for b in ordered[i + 1:]:
            inter = sets_r2[a] & sets_r2[b]
            if inter:
                problems.append(f"{a} ∩ {b} = {len(inter)} seed 重合")

    merged_official: dict[int, str] = {}
    for ons in all_262_namespaces():
        for s in _ns_seed_set(ons, pair_range=official_pair_range,
                              attempts=attempts, raw_fn=_official_raw):
            merged_official.setdefault(s, ons)
    merged_r1: dict[int, str] = {}
    for r1ns in _R1_NAMESPACES:
        for s in _ns_seed_set(r1ns, pair_range=r1_pair_range,
                              attempts=attempts, raw_fn=_r1_raw):
            merged_r1.setdefault(s, r1ns)
    merged_261: dict[int, str] = {}
    for ns_old in _NAMESPACES_261:
        for s in _ns_seed_set(ns_old, pair_range=pair_range_261,
                              attempts=attempts, raw_fn=_ns261_raw):
            merged_261.setdefault(s, ns_old)
    merged_superseded: dict[int, str] = {}
    for ns in ordered:
        for s in _ns_seed_set(ns, pair_range=pair_range,
                              attempts=attempts,
                              raw_fn=_r2_superseded_raw):
            merged_superseded.setdefault(s, ns)

    cross_official: dict[str, int] = {}
    cross_r1: dict[str, int] = {}
    cross_261: dict[str, int] = {}
    cross_superseded: dict[str, int] = {}
    for ns in ordered:
        for s in sets_r2[ns]:
            hit = merged_official.get(s)
            if hit is not None:
                key = f"{ns}|{hit}"
                cross_official[key] = cross_official.get(key, 0) + 1
                problems.append(f"r2_1:{ns} ∩ official:{hit} seed 重合")
            hitr1 = merged_r1.get(s)
            if hitr1 is not None:
                key = f"{ns}|{hitr1}"
                cross_r1[key] = cross_r1.get(key, 0) + 1
                problems.append(f"r2_1:{ns} ∩ diag_r1:{hitr1} seed 重合")
            hit261 = merged_261.get(s)
            if hit261 is not None:
                key = f"{ns}|{hit261}"
                cross_261[key] = cross_261.get(key, 0) + 1
                problems.append(f"r2_1:{ns} ∩ 261:{hit261} seed 重合")
            hits = merged_superseded.get(s)
            if hits is not None:
                key = f"{ns}|{hits}"
                cross_superseded[key] = cross_superseded.get(key, 0) + 1
                problems.append(
                    f"r2_1:{ns} ∩ superseded diag_r2:{hits} seed 重合")

    forbidden_strings = ("ppo_final_eval_262", "qualification_r2")
    for ns in ordered:
        for bad in forbidden_strings:
            if bad in ns:
                problems.append(f"namespace {ns!r} 含禁止串 {bad!r}")

    return {
        "format": "ppo262-repair2-namespace-integrity-v1",
        "stage": DIAG262R2_STAGE_ID,
        "iteration": DIAG262R2_ITERATION_ID,
        "namespaces_r2": ordered,
        "official_iteration_preserved": "s262_r0",
        "r1_iteration_preserved": "s262_diag_r1(diag262r1_* 只读)",
        "superseded_iteration": (
            "s262_diag_r2(diag262r2_* 已废止;seed 空间亦隔离)"),
        "namespaces_261_checked": list(_NAMESPACES_261),
        "pair_range_r2": [pair_range.start, pair_range.stop],
        "pair_range_official": [official_pair_range.start,
                                official_pair_range.stop],
        "pair_range_r1": [r1_pair_range.start, r1_pair_range.stop],
        "pair_range_261": [pair_range_261.start, pair_range_261.stop],
        "attempts_enumerated": attempts,
        "seeds_per_namespace_r2": {k: len(v) for k, v in sets_r2.items()},
        "cross_official_overlaps": cross_official,
        "cross_r1_overlaps": cross_r1,
        "cross_261_overlaps": cross_261,
        "cross_superseded_overlaps": cross_superseded,
        "final_namespace_untouched": True,
        "problems": problems,
        "pass": not problems,
    }
