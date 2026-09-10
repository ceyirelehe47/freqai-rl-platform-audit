"""正式执行器的完整 power report 重跑验证(阶段 2.6.0e 工作包 C)。

2.6.0d 缺陷:执行器只检查 code_hash 相等 + public_summary.targets_met
== true——public summary 是可篡改的摘要,不是信任源;完整报告的 npa-
哈希从未被重算对账(与 pack validity 的 4b 现算对账形成对照)。

v2 语义:正式执行器在加载候选 checkpoint 前:

1. 读取 commitment 绑定的 family qualification report payload(完整
   报告本就嵌入承诺,经验 cluster 分布在其中);
2. 重建 Null Qualification Spec(margin/场景清单/MC 配置);
3. 用当前 power-analysis 代码确定性重新运行完整 power analysis;
4. 重算完整 report hash(npa-)并与承诺比对;
5. 从完整报告重新派生 targets_met(public summary 不再是信任源,
   摘要字段必须与重派生值逐项一致,否则 EXAM_INVALID);
6. 核验 required scenario manifest(清单哈希 + 完整覆盖 + 无跳过);
7. 核验所有 family / block / scenario 的硬目标(Wilson 保守界);
8. 核验 MC 配置与比例置信方法;
9. 核验 power code hash 与当前实现一致(代码变化 -> 旧报告失效)。

加速缓存(可信缓存):键覆盖 qualification spec hash / family report
哈希 / power code hash / generator implementation hashes / EvalConfig /
timeframe / Episode duration / MC 配置 / 场景清单哈希;命中后仍验证
缓存内容 hash(报告自哈希 == 存储哈希),不符即重建——缓存只是加速,
不是信任来源。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

POWER_REVERIFY_FORMAT = "null-power-reverification-v1"


def _cache_root() -> Path:
    src_dir = Path(__file__).resolve().parent            # src/rl_curriculum
    return src_dir.parents[1] / ".cache" / "null_power_reverify_v2"


def _content_hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"),
                   ensure_ascii=False).encode("utf-8")).hexdigest()


def reverify_committed_power_analysis(
    *,
    commitment: Any,
    eval_config: Any,
    timeframe: str,
    episode_bars: int,
    required_families: list[str],
) -> dict[str, Any]:
    """确定性重跑完整 power analysis 并与承诺逐项对账。

    返回 {checks, problems, pass, report_hash, targets_met};
    problems 非空 -> 执行器 EXAM_INVALID(public summary 不是信任源)。
    """
    from rl_curriculum.null_power_analysis import (
        POWER_ANALYSIS_FORMAT,
        REQUIRED_BLOCKS,
        power_analysis_code_hash,
        power_analysis_report_hash,
        run_power_analysis,
    )
    from rl_curriculum.null_qualification_spec import (
        POWER_MC_CONFIG,
        build_spec_payload,
        null_qualification_spec_hash,
        scenario_manifest_hash,
        verify_spec_payload,
    )

    checks: dict[str, bool] = {}
    problems: list[str] = []

    power_bound = dict(commitment.null_power_analysis or {})

    # 1. 逐族读取承诺绑定的完整报告 payload(经验 cluster 分布来源)
    bindings = commitment.null_qualification_bindings or {}
    pseudo_reports: dict[str, dict[str, Any]] = {}
    family_report_hashes: dict[str, str] = {}
    from rl_curriculum.null_qualification import qualification_report_hash

    for fam in required_families:
        bound = bindings.get(fam) or {}
        payload = bound.get("report_payload")
        if not isinstance(payload, dict):
            problems.append(
                f"承诺未绑定 Null 族 {fam!r} 的完整资格报告 payload"
                f"(无法重跑 power analysis;public summary 不是信任源)")
            continue
        family_report_hashes[fam] = str(bound.get("report_hash") or "")
        pseudo_reports[fam] = {
            block: {"cluster_values": list(
                (payload.get(block) or {}).get("cluster_values") or [])}
            for block in REQUIRED_BLOCKS}
    if problems:
        return {"checks": checks, "problems": problems, "pass": False,
                "report_hash": None, "targets_met": False}

    # 2. 重建 spec(margin / 场景清单 / MC 配置)并自洽校验
    spec = build_spec_payload(
        eval_config, timeframe=timeframe, episode_bars=episode_bars)
    spec_problems = verify_spec_payload(spec)
    if spec_problems:
        problems.append(
            f"qualification spec 自洽失败(power 重跑前置): "
            f"{spec_problems[:3]}")
    if null_qualification_spec_hash(spec) != (
            commitment.null_qualification_spec_hash):
        # 12 节也会对账;此处 fail closed 双保险
        problems.append("spec 哈希与承诺不一致(power 重跑无法进行)")

    # 3. 可信缓存(键覆盖全部必需材料;命中后验证内容哈希)
    cache_key_material = {
        "format": POWER_REVERIFY_FORMAT,
        "spec_hash": null_qualification_spec_hash(spec),
        "family_report_hashes": family_report_hashes,
        "power_code_hash": power_analysis_code_hash(),
        "generator_bindings": {
            fam: (commitment.generator_bindings.get(fam) or {}).get(
                "implementation_hash")
            for fam in required_families},
        "eval_config": eval_config.manifest(),
        "timeframe": timeframe,
        "episode_duration_hours": spec["episode_duration_hours"],
        "power_mc_config": dict(POWER_MC_CONFIG),
        "scenario_manifest_hash": scenario_manifest_hash(),
    }
    cache_key = _content_hash(cache_key_material)
    cache_path = _cache_root() / f"{cache_key}.json"
    report: dict[str, Any] | None = None
    if cache_path.is_file():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if (isinstance(cached, dict)
                    and cached.get("key") == cache_key
                    and isinstance(cached.get("report"), dict)
                    and power_analysis_report_hash(
                        cached["report"]) == cached.get("report_hash")):
                report = cached["report"]
                checks["power_reverify_cache_valid"] = True
        except (OSError, json.JSONDecodeError, ValueError, TypeError):
            report = None
    if report is None:
        checks["power_reverify_cache_valid"] = False
        try:
            report = run_power_analysis(
                pseudo_reports, margin=spec["margin"])
        except Exception as exc:  # noqa: BLE001 - 重跑失败 = 材料不一致,fail closed
            problems.append(
                f"完整 power analysis 重跑失败(承诺材料不一致/目标不可达,"
                f"不得降级): {exc}")
            return {
                "format": POWER_REVERIFY_FORMAT,
                "checks": checks,
                "problems": problems,
                "pass": False,
                "report_hash": None,
                "targets_met": False,
            }

    # 4. 重算完整报告哈希并与承诺比对
    recomputed_hash = power_analysis_report_hash(report)
    checks["power_report_hash"] = (
        recomputed_hash == power_bound.get("report_hash"))
    if not checks["power_report_hash"]:
        problems.append(
            f"完整 power report 重算哈希 {recomputed_hash} != 承诺 "
            f"{power_bound.get('report_hash')!r}(报告被篡改/材料不一致/"
            f"power 代码变化后未重跑——public summary 不是信任源)")

    # 5. 从完整报告重新派生 targets_met(并与承诺摘要逐项比对)
    targets = report.get("targets") or {}
    derived_met = targets.get("targets_met") is True
    checks["power_targets_met_derived"] = derived_met
    if not derived_met:
        problems.append(
            "完整 power report 重跑后 targets_met 不为真(硬目标覆盖全部"
            " family x block x required scenario;功效不足的 Null 资格"
            "不得进入正式考试)")
    summary = dict(power_bound.get("public_summary") or {})
    derived_summary = {
        "margin": report.get("margin"),
        "min_qualification_clusters": report.get(
            "min_qualification_clusters"),
        "targets_met": derived_met,
        "required_scenario_count": report.get("required_scenario_count"),
        "max_false_invalid_at_zero": targets.get(
            "max_false_invalid_at_zero"),
        "max_false_qualified_at_2x_margin": targets.get(
            "max_false_qualified_at_2x_margin"),
        "min_rejection_power_at_1x_margin": targets.get(
            "min_rejection_power_at_1x_margin"),
    }
    checks["power_public_summary_consistent"] = (
        summary == derived_summary)
    if not checks["power_public_summary_consistent"]:
        problems.append(
            f"承诺 public_summary 与完整报告重派生值不一致(摘要不是"
            f"信任源;必须与重跑结果逐项一致): 承诺 {summary!r} vs "
            f"重派生 {derived_summary!r}")

    # 6. required scenario manifest / 覆盖 / 无跳过
    checks["power_scenario_manifest"] = (
        report.get("scenario_manifest_hash") == scenario_manifest_hash()
        and report.get("scenario_manifest_hash")
        == power_bound.get("scenario_spec_hash"))
    if not checks["power_scenario_manifest"]:
        problems.append(
            "power 场景清单哈希不一致(报告场景清单/承诺 scenario_spec_"
            "hash/预注册清单三者必须一致)")
    checks["power_required_scenarios_complete"] = (
        report.get("required_scenarios_complete") is True
        and report.get("skipped_required_scenarios") == [])
    if not checks["power_required_scenarios_complete"]:
        problems.append(
            "required scenario 覆盖不完整或存在跳过(零方差场景必须走"
            "解析确定性分支,不得 skipped)")

    # 7. family / block 全覆盖(硬目标细节由 targets_met 承载;此处
    #    核验结构覆盖:每 family x required block 的三个门场景都在)
    expected_keys = {
        f"{fam}::{block}"
        for fam in required_families for block in REQUIRED_BLOCKS}
    detail_keys = set((targets.get("by_family_block") or {}))
    checks["power_family_block_coverage"] = detail_keys == expected_keys
    if not checks["power_family_block_coverage"]:
        problems.append(
            f"power 硬目标未覆盖全部 family x block:缺失 "
            f"{sorted(expected_keys - detail_keys)},多余 "
            f"{sorted(detail_keys - expected_keys)}")

    # 8. MC 配置与比例置信方法
    checks["power_mc_config"] = (
        report.get("mc_iters") == POWER_MC_CONFIG["mc_iters"]
        and report.get("mc_seed") == POWER_MC_CONFIG["mc_seed"]
        and report.get("confidence_method")
        == POWER_MC_CONFIG["confidence_method"]
        and targets.get("confidence_method")
        == POWER_MC_CONFIG["confidence_method"])
    if not checks["power_mc_config"]:
        problems.append(
            "power MC 配置(MC 次数/种子/比例置信方法)与预注册值不一致")
    checks["power_cluster_count"] = (
        report.get("min_qualification_clusters")
        == spec.get("min_qualification_clusters"))
    if not checks["power_cluster_count"]:
        problems.append(
            "power 报告选定的 cluster 数与 qualification spec 冻结值"
            "不一致(选定值必须进入 spec hash)")

    # 9. power 代码哈希与当前实现一致
    checks["power_code_hash"] = (
        power_bound.get("code_hash") == power_analysis_code_hash())
    if not checks["power_code_hash"]:
        problems.append(
            f"功效分析代码哈希不匹配:承诺 "
            f"{power_bound.get('code_hash')!r} vs 当前 "
            f"{power_analysis_code_hash()}(power 代码变化后旧报告未重跑)")

    # 报告格式必须是 v2(v1 未中心化/只覆盖 Always Long/点估计)
    checks["power_report_format"] = report.get("format") == (
        POWER_ANALYSIS_FORMAT)
    if not checks["power_report_format"]:
        problems.append(
            f"重跑报告格式 {report.get('format')!r} != "
            f"{POWER_ANALYSIS_FORMAT!r}(null-power-analysis-v1 已弃用)")

    out = {
        "format": POWER_REVERIFY_FORMAT,
        "checks": checks,
        "problems": problems,
        "pass": not problems,
        "report_hash": recomputed_hash,
        "targets_met": derived_met,
    }
    # 写缓存(仅在重跑路径;内容哈希在读取时复验)
    if not checks.get("power_reverify_cache_valid"):
        try:
            _cache_root().mkdir(parents=True, exist_ok=True)
            cache_path.write_text(
                json.dumps({"key": cache_key, "report_hash": recomputed_hash,
                            "report": report}, sort_keys=True,
                           ensure_ascii=False, indent=1),
                encoding="utf-8")
        except OSError:
            pass  # 缓存不可写不影响验证(只是慢)
    return out
