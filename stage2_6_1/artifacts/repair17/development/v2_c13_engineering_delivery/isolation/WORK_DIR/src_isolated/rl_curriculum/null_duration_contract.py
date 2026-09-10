"""全局 Strict Null Duration Contract(阶段 2.6.0f 工作包 C)。

2.6.0e 遗留缺陷:qualification spec 和 pack validity 从**第一个**
null_control Episode(sealed_exam / mock_sealed_exam,break 语义)或
**最后一个** null_control Episode(formal_exam,循环覆盖语义)推导
episode_bars,且多处 `.get("episode_bars", 96)` 静默回退默认值——同一
个 sealed exam 中不同 strict Null family / 不同 pair / 不同 Episode
可以使用不同 resolved duration 而不被发现。

v1 语义(null-duration-contract-v1):

- 从考试包中收集**所有** required strict Null family 的全部
  null_control Episode,对每条独立执行 param_resolution.resolve_duration
  (原始 episode_bars 与 duration_hours 双通道,fail closed),派生唯一
  的规范化时长合同;
- 合同比较的是 resolved duration(timeframe / bar duration seconds /
  resolved bars / resolved duration seconds),不是原始参数文本——
  `episode_bars=96` 与 `duration_hours=24`(15m)解析为完全相同的合同,
  允许;原始 duration 与 bars 自相矛盾仍由参数解析器 fail closed;
- 同一个 sealed exam 中所有 required strict Null family 必须使用完全
  相同的 timeframe 和 resolved duration:同一 pair 内 / 同一 family 的
  所有 pair / 不同 strict Null family 之间不一致均 -> EXAM_INVALID
  (不是候选 FAIL 或疑似作弊);
- 不存在"取第一个 / 取最后一个 / 缺失回退 96"语义:必须从全部
  required Null Episode 派生唯一合同,没有唯一合同即失败,没有合法
  duration 即失败,不得使用默认值;
- Episode 顺序无关:收集全部 Episode 后比较 resolved 值,重排不改变
  推导结果。

合同由 sealed-exam-commitment-v6 显式绑定(ndc- payload 与 hash);
qualification spec(nqs-)/family qualification reports/power 重跑/
pack validity report(npv-)全部通过同一 resolved bars 构建并对账。
公开 duration 与 timeframe 不属于隐藏 seed,可以公开。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

NULL_DURATION_CONTRACT_FORMAT = "null-duration-contract-v1"


class NullDurationContractError(RuntimeError):
    """全局 Null duration 合同派生/校验失败(fail closed -> EXAM_INVALID)。"""


def _canonical_json_hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"),
                   ensure_ascii=False).encode("utf-8")).hexdigest()


def collect_required_null_episode_specs(
    pack: Any, *, required_families: list[str] | tuple[str, ...],
) -> list[Any]:
    """收集所有 required strict Null family 的全部 null_control EpisodeSpec。

    返回顺序无关(spec 列表仅用于逐条解析;推导结果与 Episode 顺序
    无关——比较的是 resolved 值集合)。
    """
    required = set(required_families)
    specs = [spec for spec in (getattr(pack, "episodes", None) or [])
             if spec.split == "null_control" and spec.family in required]
    missing = sorted(required - {spec.family for spec in specs})
    if missing:
        raise NullDurationContractError(
            f"考试包缺少 required strict Null family 的 null_control "
            f"Episode: {missing}(无法派生全局 duration contract;"
            f"EXAM_INVALID)")
    return specs


def _contract_key(resolved: dict[str, Any]) -> tuple[Any, ...]:
    """resolved 合同比较键(只比较 resolved 值,不比较原始参数文本)。"""
    return (
        resolved["timeframe"],
        int(resolved["resolved_bars"]),
    )


def derive_global_null_duration_contract(
    pack: Any, *, required_families: list[str] | tuple[str, ...],
) -> dict[str, Any]:
    """从全部 required strict Null Episode 派生唯一规范化时长合同。

    任一 Episode 缺 duration 字段且无法解析 / 解析失败 / resolved 值
    不一致 -> NullDurationContractError(执行器映射为 EXAM_INVALID,
    不判候选 FAIL 或作弊)。
    """
    from rl_curriculum.param_resolution import (
        ParamResolutionError,
        resolve_duration,
        resolved_parameter_semantics_hash,
    )
    from rl_curriculum.timebase import timeframe_to_seconds

    specs = collect_required_null_episode_specs(
        pack, required_families=required_families)
    resolved_all: list[dict[str, Any]] = []
    per_family: dict[str, int] = {}
    for spec in specs:
        try:
            resolved = resolve_duration(
                dict(spec.params or {}), spec.timeframe)
        except ParamResolutionError as exc:
            raise NullDurationContractError(
                f"Null Episode(family={spec.family}, seed 匿名)时长无法"
                f"解析: {exc}(缺 duration 字段或原始声明自相矛盾;"
                f"EXAM_INVALID;不得使用默认值)") from exc
        resolved_all.append(resolved)
        per_family[spec.family] = per_family.get(spec.family, 0) + 1
    keys = {_contract_key(r) for r in resolved_all}
    if len(keys) != 1:
        detail = sorted(
            ({"timeframe": k[0], "resolved_bars": k[1]} for k in keys),
            key=lambda d: (d["timeframe"], d["resolved_bars"]))
        raise NullDurationContractError(
            f"required strict Null family 的 resolved duration 不唯一"
            f"({len(keys)} 个不同合同: {detail}):同一个 sealed exam 中"
            f"所有 required strict Null family(同一 pair 内/同一 family "
            f"的所有 pair/不同 family 之间)必须使用完全相同的 timeframe "
            f"与 resolved duration(EXAM_INVALID;不是候选 FAIL 或疑似"
            f"作弊)")
    timeframe, bars = next(iter(keys))
    bar_seconds = int(timeframe_to_seconds(timeframe))
    total_seconds = int(bars) * bar_seconds
    return {
        "format": NULL_DURATION_CONTRACT_FORMAT,
        "timeframe": timeframe,
        "bar_duration_seconds": bar_seconds,
        "resolved_bars": int(bars),
        "resolved_duration_seconds": total_seconds,
        "resolved_duration_hours": total_seconds / 3600.0,
        "resolution_rules_version": resolved_parameter_semantics_hash(),
        "n_null_episodes": len(resolved_all),
        "episodes_per_family": dict(sorted(per_family.items())),
    }


def null_duration_contract_hash(contract: dict[str, Any]) -> str:
    """duration contract 哈希(ndc-;进入 sealed commitment v6)。"""
    received = (contract.get("format") if isinstance(contract, dict)
                else type(contract))
    if not isinstance(contract, dict) or contract.get(
            "format") != NULL_DURATION_CONTRACT_FORMAT:
        raise NullDurationContractError(
            f"duration contract 格式必须是 {NULL_DURATION_CONTRACT_FORMAT!r}"
            f"(收到 {received!r})")
    return "ndc-" + _canonical_json_hash(contract)
def verify_duration_contract_consistency(
    contract: dict[str, Any],
    *,
    expected: dict[str, Any],
) -> None:
    """合同一致性对账:resolved 值必须逐项相等(用于跨报告对账)。"""
    keys = ("timeframe", "bar_duration_seconds", "resolved_bars",
            "resolved_duration_seconds")
    for k in keys:
        if contract.get(k) != expected.get(k):
            raise NullDurationContractError(
                f"duration contract 不一致({k}): {contract.get(k)!r} vs "
                f"{expected.get(k)!r}(pack 合同与 family/power/pack "
                f"validity 报告的时长必须完全一致;EXAM_INVALID)")
