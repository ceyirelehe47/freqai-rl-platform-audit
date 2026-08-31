"""阶段 2.6.2:Stage 2.6.2 PPO seed namespace 与确定性派生。

本模块为 2.6.2 建立独立的 seed 派生流(iteration = s262_r0):

- payload 前缀为 "stage2_6_2"(2.6.1 为 "stage2_6_1"),namespace
  字符串亦全部带 _262 后缀——两条派生流天然不相交,由
  seed_namespace_integrity artifact 显式枚举验证;
- 不复用 rl_curriculum.curriculum261_api.derive261_seed:其合法
  namespace 列表属于 2.6.1 冻结合同,2.6.2 无权扩充;
- 派生签名与 2.6.1 同构(namespace, family, rung, pair_index,
  attempt),attempt 语义(first_pass / max_attempts=5)沿用 2.6.1
  的 generate_pair_with_attempts 结构;
- pair A/B 继续共享同一 seed(pair_variant 不进入派生)。

namespace 语义(训练 / 开发评估 / final 评估互不重合;final eval
在 plan 锁定前对任何代码路径不可访问——lock marker 机制):

- ppo_config_dev_262       PPO config development 语料(C1/C2/C3 D1)
- ppo_probe_train_262_r{f} 三族 per-family probe 训练 bank
- ppo_probe_eval_262       probe 评估 bank(三族共用)
- ppo_core_train_262_rep{k} core 训练 bank(三 replicate 互斥)
- ppo_dev_eval_262         development evaluation bank(可重复使用)
- ppo_final_eval_262       sealed final evaluation bank(lock 前封闭)
- ppo_smoke_262            PPO smoke(不参与任何指标)

隔离合同(由 verify_namespace_isolation 显式验证):

train(config_dev/probe/core) ∩ dev_eval = ∅
train ∩ final_eval = ∅
dev_eval ∩ final_eval = ∅
qualification_r2 ∩ 全部 262 namespace = ∅(episode seed identity 层面)
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from rl_curriculum.curriculum261_api import (
    CURRICULUM261_FAMILIES,
    CURRICULUM261_RUNGS,
    CURRICULUM261_SEED_NAMESPACES as _NAMESPACES_261,
)

# ---------------------------------------------------------------- 身份合同
PPO262_STAGE_ID = "stage2_6_2"
PPO262_ITERATION_ID = "s262_r0"

#: core 训练 replicate 编号(1..3)与预注册 model seeds(§15)
PPO262_MODEL_SEEDS = (26201, 26202, 26203)
PPO262_REPLICATES = (1, 2, 3)

#: 三族 probe 的独立训练 namespace(probe 各自专用,互不重合)
PPO262_PROBE_NAMESPACES = {
    "c1_opportunity": "ppo_probe_train_262_c1",
    "c2_context": "ppo_probe_train_262_c2",
    "c3_cost": "ppo_probe_train_262_c3",
}

#: 全部 2.6.2 namespace(显式枚举;replicate 子 namespace 按规则展开)
PPO262_BASE_NAMESPACES = (
    "ppo_config_dev_262",
    "ppo_probe_eval_262",
    "ppo_dev_eval_262",
    "ppo_final_eval_262",
    "ppo_smoke_262",
) + tuple(sorted(PPO262_PROBE_NAMESPACES.values()))


def core_train_namespace(replicate: int) -> str:
    """replicate k(1..3)的 core 训练 namespace。"""
    k = int(replicate)
    if k not in PPO262_REPLICATES:
        raise ValueError(f"replicate 必须是 {PPO262_REPLICATES}, got {k}")
    return f"ppo_core_train_262_rep{k}"


def all_262_namespaces() -> list[str]:
    """全部 2.6.2 namespace 字符串(含 replicate 展开)。"""
    out = list(PPO262_BASE_NAMESPACES)
    out.extend(core_train_namespace(k) for k in PPO262_REPLICATES)
    return sorted(out)


# ---------------------------------------------------------------- final 锁
#: final evaluation 的 lock marker:final plan 锁定文件存在才允许
#: 派生 ppo_final_eval_262 seed(plan 锁定前 corpus 对任何代码路径封闭)
PPO262_FINAL_LOCK_ENV = "PPO262_FINAL_LOCK_DIR"
_ARTIFACTS_262 = Path(__file__).resolve().parents[2] / "artifacts" / (
    "route_c_stage2_6_2")
_FINAL_PLAN_FILENAME = "final_evaluation_plan.json"
_FINAL_EXPOSURE_FILENAME = "final_evaluation_exposure.json"


def ppo262_artifacts_dir() -> Path:
    """2.6.2 artifacts 输出目录(可用 PPO262_ARTIFACTS_DIR 覆盖)。"""
    env_val = os.environ.get("PPO262_ARTIFACTS_DIR")
    if env_val:
        return Path(env_val)
    return _ARTIFACTS_262


def final_eval_lock_marker() -> Path:
    env_val = os.environ.get(PPO262_FINAL_LOCK_ENV)
    base = Path(env_val) if env_val else ppo262_artifacts_dir()
    return base / _FINAL_PLAN_FILENAME


def final_eval_unlocked() -> bool:
    return final_eval_lock_marker().is_file()


def final_eval_exposure_marker() -> Path:
    env_val = os.environ.get(PPO262_FINAL_LOCK_ENV)
    base = Path(env_val) if env_val else ppo262_artifacts_dir()
    return base / _FINAL_EXPOSURE_FILENAME


def write_final_eval_exposure(
        plan_digest: str, status: str = "running") -> None:
    """写入 exposure marker:一旦写入,s262_r0 的 final corpus 永久消耗。

    状态只允许单次推进 running -> completed(同 digest);任何已完成
    后的再次写入、跨 digest 写入、重开 running 都被拒绝。
    """
    from datetime import datetime, timezone

    path = final_eval_exposure_marker()
    if path.is_file():
        prev = json.loads(path.read_text(encoding="utf-8"))
        if (prev.get("plan_digest") == plan_digest
                and prev.get("status") == "running"
                and status == "completed"):
            pass  # 唯一允许的单次状态推进
        else:
            raise RuntimeError(
                f"final evaluation exposure marker 已存在({path},"
                f"status={prev.get('status')},digest="
                f"{prev.get('plan_digest')}):s262_r0 final corpus 已"
                f"消耗,禁止第二次执行;继续必须 s262_r1 + 全新 seed space")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "iteration": PPO262_ITERATION_ID,
        "plan_digest": plan_digest,
        "status": status,
        "written_utc": datetime.now(timezone.utc).isoformat(
            timespec="seconds"),
        "contract": "Stage 2.6.2 final evaluation 一旦开始执行即视为语料"
                    "暴露;无论 PASS/FAIL/crash/checker bug,同一 corpus "
                    "不得再次执行(下一次必须 s262_r1 + 全新 final seeds)。",
    }
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def final_eval_exposed() -> bool:
    return final_eval_exposure_marker().is_file()


# ---------------------------------------------------------------- seed 派生
def derive262_seed(
    namespace: str, family: str, rung: str, pair_index: int, attempt: int,
) -> int:
    """2.6.2 确定性 seed 派生(单一来源)。

    - namespace 必须在 2.6.2 namespace 集合内(含 replicate 展开);
    - ppo_final_eval_262 在 final plan 锁定前对任何代码路径封闭;
    - payload = ["stage2_6_2", namespace, family, rung, pair, attempt],
      sha256 前 8 字节(与 2.6.1 同构但前缀不同,派生流不相交);
    - 不含 side:pair A/B 共享同一随机流(2.6.1 pair nuisance 合同)。
    """
    if final_eval_locked_ns(namespace) and not final_eval_unlocked():
        raise RuntimeError(
            "ppo_final_eval_262 seed 在 final evaluation plan 锁定前"
            "不可访问(final corpus lock 前对任何代码路径封闭;"
            "开发/诊断一律使用 ppo_config_dev_262 / ppo_dev_eval_262)")
    return _derive262_seed_raw(namespace, family, rung, pair_index, attempt)


def final_eval_locked_ns(namespace: str) -> bool:
    return namespace == "ppo_final_eval_262"


def _derive262_seed_raw(
    namespace: str, family: str, rung: str, pair_index: int, attempt: int,
) -> int:
    """seed 派生纯哈希核心(无 final lock 守卫)。

    仅用于 namespace integrity 的碰撞枚举——只计算 seed 整数值,
    不生成任何 episode(final corpus 的暴露以生成为准)。
    """
    if namespace not in all_262_namespaces():
        raise ValueError(
            f"seed namespace {namespace!r} 不在 2.6.2 namespace 集合"
            f"({len(all_262_namespaces())} 个;2.6.1 namespace 一律拒绝)")
    payload = json.dumps(
        [PPO262_STAGE_ID, namespace, family, rung,
         int(pair_index), int(attempt)],
        sort_keys=True, separators=(",", ":"),
    )
    return int.from_bytes(
        hashlib.sha256(payload.encode("utf-8")).digest()[:8], "big"
    )


# ---------------------------------------------------------------- 隔离验证
def _namespace_seed_set(
    namespace: str, *, pair_range: range, attempts: int,
    derive_fn,
) -> set[int]:
    """枚举一个 namespace 在给定 pair 范围/attempt 数下的全部 seed。"""
    out: set[int] = set()
    for family in CURRICULUM261_FAMILIES:
        for rung in CURRICULUM261_RUNGS:
            for pair_index in pair_range:
                for attempt in range(attempts):
                    out.add(
                        derive_fn(namespace, family, rung, pair_index, attempt)
                    )
    return out


def verify_namespace_isolation(
    *, pair_range_262: range, pair_range_261: range, attempts: int = 5,
) -> dict:
    """2.6.2 namespace 隔离合同验证(episode seed identity 层面)。

    验证(全量枚举,比较的是派生 seed 整数而非 namespace 字符串):
    - 全部 262 namespace 两两不相交;
    - 与 2.6.1 全部 11 个 namespace(calibration/qualification/training
      等)不相交——qualification_r2 显式包含在内;
    - core 三 replicate 训练 namespace 两两不相交。
    """
    ns_262 = all_262_namespaces()
    sets_262: dict[str, set[int]] = {
        ns: _namespace_seed_set(
            ns, pair_range=pair_range_262, attempts=attempts,
            derive_fn=_derive262_seed_raw)
        for ns in ns_262
    }
    problems: list[str] = []
    ordered = sorted(sets_262)
    for i, a in enumerate(ordered):
        for b in ordered[i + 1:]:
            inter = sets_262[a] & sets_262[b]
            if inter:
                problems.append(f"{a} ∩ {b} = {len(inter)} 个 seed 重合")
    sets_261: dict[str, set[int]] = {
        ns: _namespace_seed_set(
            ns, pair_range=pair_range_261, attempts=attempts,
            derive_fn=_ns261_raw)
        for ns in _NAMESPACES_261
    }
    cross: dict[str, int] = {}
    for ns in ordered:
        for ns_old, s_old in sets_261.items():
            inter = sets_262[ns] & s_old
            if inter:
                problems.append(
                    f"262:{ns} ∩ 261:{ns_old} = {len(inter)} 个 seed 重合")
                cross[f"{ns}|{ns_old}"] = len(inter)
    return {
        "format": "ppo262-seed-namespace-integrity-v1",
        "stage": PPO262_STAGE_ID,
        "iteration": PPO262_ITERATION_ID,
        "namespaces_262": ordered,
        "namespaces_261_checked": list(_NAMESPACES_261),
        "pair_range_262": [pair_range_262.start, pair_range_262.stop],
        "pair_range_261": [pair_range_261.start, pair_range_261.stop],
        "attempts_enumerated": attempts,
        "seeds_per_namespace_262": {k: len(v) for k, v in sets_262.items()},
        "cross_261_overlaps": cross,
        "problems": problems,
        "pass": not problems,
    }


def _ns261_raw(
    namespace: str, family: str, rung: str, pair_index: int, attempt: int,
) -> int:
    """2.6.1 seed 派生的复算核心(仅用于隔离枚举,不生成 episode)。"""
    payload = json.dumps(
        ["stage2_6_1", namespace, family, rung,
         int(pair_index), int(attempt)],
        sort_keys=True, separators=(",", ":"),
    )
    return int.from_bytes(
        hashlib.sha256(payload.encode("utf-8")).digest()[:8], "big"
    )
