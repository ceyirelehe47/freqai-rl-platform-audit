# -*- coding: utf-8 -*-
"""QProd 资格原件 → 交付适配器(到已结项 QualifiedInput 消费合同)。

唯一的交付适配器:输入是 Level A producer 真实输出的
qualification plan/result/raw evidence/exposure 终态/parameter pack/
V2 bundle+fit manifest 与代码来源;输出复用已建立的消费合同
(ppo262e 六件套)。

导出器**验证原件而非重写 PASS**:
- 重新运行公共判定核心 judge_qualification_gates 于 producer raw
  证据,要求实算 verdict/gates 与 producer result 一致——只写 PASS
  字符串、缺原件、错 result/exposure/plan/来源、旧 R2 冒充、部分
  输出一律不产可用成功包(写 export_rejected.json,零六件套);
- result/exposure/pack/envelope 以验证后的原件值逐字段适配(保持
  原始引用与语义;不静默改成另一种成功结果);
- fit 来源走 preprocessing v2 通用表示(fit_records + 显式
  source_kind),真实资格来源不改称手工夹具;v1 工程输入不变,
  已闭合校验不放宽;
- 工程 scope 导出必须存在全部工程标记;formal scope 本轮无真实
  正式资格链,一律拒绝(正式输入仍受真实资格和独立训练授权控制)。

授权锚**不在本模块产生**(导出器不是自签许可器):engineering
授权由隔离 test authority 依据 export_receipt 的三摘要在外部签发;
formal 授权属未来正式 admission 链(注册表保持为空)。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rl_curriculum.ppo262_qualified_input import (
    AUTHORIZATION_FORMAT, PARAMETER_PACK_FORMAT,
    PREPROCESSOR_ENVELOPE_FILENAME, QUALIFICATION_EXPOSURE_FORMAT,
    QUALIFICATION_PLAN_FORMAT, QUALIFICATION_RESULT_FORMAT,
    authorization_binding_digest, parameter_pack_digest,
    qualification_plan_digest,
)

QPROD_EXPORT_FORMAT = "ppo262-qprod-export-v1"
QPROD_EXPORT_REJECTED_FORMAT = "ppo262-qprod-export-rejected-v1"
QPROD_EXPORT_RECEIPT_NAME = "qprod_export_receipt.json"

#: producer 原件(artifacts root 内)。
PRODUCER_RESULT = "qprod_qualification_result.json"
PRODUCER_RAW = "qprod_qualification_raw.json"
PRODUCER_EXPOSURE = "qprod_qualification_exposure.json"
PRODUCER_PACK = "parameter_pack.json"
PRODUCER_ENVELOPE = "preprocessor_envelope.json"


class QProdExportError(RuntimeError):
    """导出拒绝(fail closed;携带结构化问题清单)。"""

    def __init__(self, report: dict[str, Any]):
        super().__init__(
            "qprod export rejected: " + "; ".join(
                report.get("problems", []))[:500])
        self.report = report


def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _canonical(obj: object) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def _producer_code_identity() -> dict[str, str]:
    """producer 侧代码身份(Level A 判定/控制模块)。"""
    import rl_curriculum

    root = Path(rl_curriculum.__file__).parent
    modules = ("curriculum261_qprod_levela.py",
               "curriculum261_qprod_context.py",
               "curriculum261_qprod_plan.py")
    return {
        "module": "curriculum261_qprod_levela.py",
        "module_sha256": hashlib.sha256(
            (root / "curriculum261_qprod_levela.py").read_bytes()
        ).hexdigest(),
        "family": "qprod_level_a_chain",
        "companions": {
            m: hashlib.sha256((root / m).read_bytes()).hexdigest()
            for m in modules},
    }


def _consumer_code_identity() -> dict[str, Any]:
    """Cq:producer 记录的共同执行语义 + 生产者身份(与 Ct 对拍)。"""
    from rl_curriculum.curriculum261_pairs import family_specs
    from rl_curriculum.curriculum261_production_obs import (
        production_observation_identity,
    )
    from rl_curriculum.curriculum261_r4_preprocessing import (
        preprocessing_v2_contract_digest,
    )
    from rl_curriculum.ppo262_input_lock import (
        PPO262_EXPECTED_VENDOR_SHA, vendor_status,
    )
    return {
        "producer": _producer_code_identity(),
        "cq_ct_semantics": "Cq(本计划记录)与 Ct(消费现场)允许不同"
                           " commit;以下共同执行语义字段必须逐字一致",
        "production_observation_identity": {
            k: v for k, v in production_observation_identity().items()
            if k in ("schema_hash", "feature_columns", "observation_dim",
                     "window_size", "strategy_file_sha256",
                     "feature_engineering_standard_sha256",
                     "env_core_version", "observation_spec_version")},
        "family_versions": {
            fam: spec.generator.family_version
            for fam, spec in family_specs().items()},
        "preprocessing_v2_contract_digest": (
            preprocessing_v2_contract_digest()),
        "vendor_sha": vendor_status()["sha"],
        "expected_vendor_sha": PPO262_EXPECTED_VENDOR_SHA,
    }


def export_qualification_delivery(
        producer_art_dir: Path | str,
        producer_state_root: Path | str,
        out_dir: Path | str, *,
        expected_scope: str = "engineering",
        profile: str = "ppo262_qprod_engineering_v1",
) -> dict[str, Any]:
    """验证 producer 原件并产出消费六件套(失败零成功包)。"""
    art = Path(producer_art_dir)
    state_root = Path(producer_state_root)
    out_dir = Path(out_dir)
    problems: list[str] = []
    checks: dict[str, bool] = {}

    def _reject() -> QProdExportError:
        report = {
            "format": QPROD_EXPORT_REJECTED_FORMAT,
            "producer_art_dir": str(art),
            "producer_state_root": str(state_root),
            "checks": checks, "problems": problems,
            "rejected": True,
            "utc": datetime.now(timezone.utc).isoformat(
                timespec="seconds"),
        }
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "export_rejected.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False),
            encoding="utf-8")
        return QProdExportError(report)

    if expected_scope != "engineering":
        problems.append(
            f"导出 scope {expected_scope!r} 拒绝:本轮无真实正式资格链"
            f"(formal 输入仍受真实资格与独立训练授权控制;"
            f"工程件改名不能取得正式权限)")
        raise _reject()

    # ---- 原件存在性 ----
    originals = {
        "result": art / PRODUCER_RESULT,
        "raw": art / PRODUCER_RAW,
        "exposure": art / PRODUCER_EXPOSURE,
        "pack": art / PRODUCER_PACK,
        "envelope": art / PRODUCER_ENVELOPE,
        "plan": state_root / "qprod_qualification_plan.json",
        "plan_digest": state_root / "qprod_qualification_plan_digest.txt",
    }
    missing = [k for k, p in originals.items() if not p.is_file()]
    checks["all_producer_originals_present"] = not missing
    if missing:
        problems.append(f"producer 原件缺失: {missing}(部分输出不产"
                        f"可用成功包)")
        raise _reject()

    result = json.loads(originals["result"].read_text(encoding="utf-8"))
    raw = json.loads(originals["raw"].read_text(encoding="utf-8"))
    exposure = json.loads(
        originals["exposure"].read_text(encoding="utf-8"))
    pack = json.loads(originals["pack"].read_text(encoding="utf-8"))
    plan = json.loads(originals["plan"].read_text(encoding="utf-8"))

    # ---- 资格计划 digest 复算 ----
    digest = qualification_plan_digest_of_producer(plan)
    locked = originals["plan_digest"].read_text(
        encoding="utf-8").strip()
    checks["producer_plan_digest_recomputed"] = digest == locked
    if not checks["producer_plan_digest_recomputed"]:
        problems.append("producer 资格计划 digest 复算不一致(冻结后"
                        "不得修改)")

    # ---- 公共判定核心复算(验证原件而非重写 PASS) ----
    from rl_curriculum.curriculum261_qprod_levela import (
        judge_qualification_gates,
    )
    rejudged = judge_qualification_gates(art, plan)
    checks["rejudged_verdict_matches_result"] = (
        rejudged["verdict"] == result.get("verdict"))
    checks["rejudged_gates_match_result"] = (
        {k: v["pass"] for k, v in rejudged["gates"].items()}
        == (result.get("gates") or {}))
    checks["result_binds_producer_plan"] = (
        result.get("qualification_plan_digest") == digest)
    checks["result_format"] = result.get("format") == (
        "cur261-qprod-levela-qualification-result-v1")
    checks["result_engineering_marked"] = bool(
        result.get("engineering_only") is True
        and result.get("scope") == "engineering"
        and result.get("formal_pass") is False)
    checks["verdict_is_pass"] = result.get("verdict") == "PASS"
    for key, msg in (
            ("rejudged_verdict_matches_result",
             f"公共判定核心实算 verdict {rejudged['verdict']!r} != "
             f"producer result {result.get('verdict')!r}(只写 PASS "
             f"字符串/改写结论拒绝)"),
            ("rejudged_gates_match_result",
             "公共判定核心实算 gates 与 result 不一致"),
            ("result_binds_producer_plan",
             "result 未绑定 producer 资格计划 digest"),
            ("result_format", "producer result format 不识别"),
            ("result_engineering_marked",
             "producer result 缺工程标记(formal_pass 必须为 false)"),
            ("verdict_is_pass",
             f"producer verdict={result.get('verdict')!r}(失败/未完成"
             f"资格不导出可用成功包;可另行走诊断导出)")):
        if not checks.get(key):
            problems.append(msg)

    # ---- exposure 终态 ----
    checks["exposure_completed_one_shot"] = bool(
        exposure.get("status") == "completed"
        and exposure.get("one_shot") is True)
    checks["exposure_binds_plan"] = (
        exposure.get("plan_digest") == digest)
    checks["exposure_iteration_consistent"] = (
        exposure.get("iteration_id") == plan.get("iteration_id"))
    if not checks["exposure_completed_one_shot"]:
        problems.append("exposure 非一次性 completed 终态")
    if not checks["exposure_binds_plan"]:
        problems.append("exposure 未绑定同一资格计划")
    if not checks["exposure_iteration_consistent"]:
        problems.append("exposure 与计划迭代不一致")

    # ---- Q1 修复:真实终态(journal)/raw 字节绑定/校准前置 ----
    # (1) producer 会话 journal 必须恰有一条绑定本计划的
    #     run_terminal_recorded,status=completed 且 verdict 与
    #     result 一致——真实终态不可伪造为"只改 result"。
    journal_path = state_root / "qprod_run_journal.jsonl"
    terminal_events = []
    if journal_path.is_file():
        for line in journal_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                problems.append("producer journal 存在不可解析行"
                                "(fail closed)")
                continue
            if rec.get("event") == "run_terminal_recorded":
                terminal_events.append(rec)
    checks["producer_terminal_recorded"] = bool(
        len(terminal_events) == 1
        and terminal_events[0].get("plan_digest") == digest
        and terminal_events[0].get("status") == "completed"
        and terminal_events[0].get("verdict")
        == result.get("verdict"))
    if not checks["producer_terminal_recorded"]:
        problems.append(
            f"producer 真实终态不可核(journal terminal 事件数="
            f"{len(terminal_events)};须恰 1 条且绑定本计划/"
            "completed/verdict 一致)")
    # (2) result 绑定 raw 证据字节摘要:raw 数据改坏而外层自洽
    #     仍拒。
    raw_sha = _sha(originals["raw"])
    checks["result_binds_raw_bytes"] = (
        result.get("raw_evidence_sha256") == raw_sha)
    if not checks["result_binds_raw_bytes"]:
        problems.append(
            f"result.raw_evidence_sha256 "
            f"{result.get('raw_evidence_sha256')!r} != raw 文件实测 "
            f"{raw_sha}(raw 证据与 result 声明不一致,改坏即拒)")
    # (3) 校准前置:资格计划绑定的 calibration_artifacts digest 与
    #     盘上校准原件逐项一致——校准前置缺失/漂移不得导出。
    cal_map = plan.get("calibration_artifacts") or {}
    cal_problems = []
    for name, want in cal_map.items():
        f = art / name
        if not f.is_file():
            cal_problems.append(f"校准前置缺失 {name}")
            continue
        if _sha(f) != want:
            cal_problems.append(f"校准前置 digest 不符 {name}")
    checks["calibration_prerequisites_intact"] = not cal_problems
    if cal_problems:
        problems.append(f"校准前置核验失败: {cal_problems}")

    # ---- pack 完整性与绑定 ----
    fams = pack.get("families") or {}
    checks["pack_families_complete"] = (
        set(fams) == {"c1_opportunity", "c2_context", "c3_cost"}
        and all(
            set(fams[f].get("rung_params", {})) == {"D0", "D1", "D2",
                                                    "D3"}
            and isinstance(fams[f].get("reference_thresholds"), dict)
            for f in fams))
    pack_d = parameter_pack_digest(pack)
    checks["pack_binds_plan"] = (
        plan.get("parameter_pack", {}).get("digest") == pack_d)
    checks["result_pack_digest_consistent"] = (
        result.get("parameter_pack_digest") == pack_d)
    if not checks["pack_families_complete"]:
        problems.append("pack 未覆盖三族 x D0-D3 + thresholds")
    if not checks["pack_binds_plan"]:
        problems.append("pack digest 与 producer 计划绑定不一致")

    # ---- V2 envelope 与 fit 来源逐项对应 ----
    try:
        from rl_curriculum.curriculum261_r4_preprocessing import (
            RouteCPreprocessorV2,
        )
        preproc = RouteCPreprocessorV2.load_envelope(
            originals["envelope"])
        bundle_hash = preproc.bundle_hash
        checks["envelope_loads"] = True
    except RuntimeError as exc:
        checks["envelope_loads"] = False
        problems.append(f"V2 envelope 拒绝: {exc}")
        raise _reject()
    checks["bundle_binds_plan"] = (
        plan.get("preprocessor_bundle_hash") == bundle_hash)
    if not checks["bundle_binds_plan"]:
        problems.append("bundle hash 与 producer 计划绑定不一致")
    preprocessing = plan.get("preprocessing") or {}
    checks["preprocessing_v2_shape"] = (
        preprocessing.get("version") == 2
        and preprocessing.get("source_kind") == "qualification_chain")
    if not checks["preprocessing_v2_shape"]:
        problems.append(
            "producer 计划 preprocessing 非 v2 qualification_chain "
            "表示(真实资格来源不改称手工夹具)")
    from collections import Counter

    def _key(rec):
        return (rec.get("pair_index"), rec.get("episode_hash"),
                rec.get("generator_identity"))

    declared_ms = Counter(_key(r) for r in
                          preprocessing.get("fit_records") or [])
    actual_ms = Counter(
        (e.pair_index, e.episode_hash, e.generator_identity)
        for e in preproc.entries)
    checks["fit_records_match_envelope"] = declared_ms == actual_ms
    if not checks["fit_records_match_envelope"]:
        problems.append("计划 fit_records 与 envelope 实际 fit manifest"
                        " 不逐项对应")
    checks["fit_namespace_match"] = (
        preprocessing.get("fit_namespace") == preproc.namespace)
    if not checks["fit_namespace_match"]:
        problems.append("计划 fit_namespace 与 envelope 实际 namespace"
                        " 不一致")

    if problems or not all(checks.values()):
        raise _reject()

    # ---- 产出消费六件套(适配保持原始引用与语义) ----
    out_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    consumer_plan = {
        "format": QUALIFICATION_PLAN_FORMAT,
        "iteration": plan["iteration_id"],
        "source_iteration": result["source_iteration"],
        "scope": "engineering",
        "engineering_only": True,
        "producer_chain": "qprod_level_a(engineering rehearsal)",
        "producer_qualification_plan_digest": digest,
        "producer_run_plan_digest": plan.get("prior_plan_digest"),
        "created_utc": now,
        "robustness_gate": {
            "pass": bool(raw["gates"]["robustness_gate_pass"]["pass"]),
            "note": "自 producer raw 证据逐字段适配(判定核心复算一致)",
        },
        "parameter_pack": {
            "digest": pack_d,
            "format": pack.get("format"),
            "source": "qprod producer parameter_pack.json(逐字节复制)",
        },
        "preprocessor_bundle_hash": bundle_hash,
        "preprocessing": {
            "contract_version": "RouteCFeaturePreprocessing-v2",
            "version": 2,
            "fit_namespace": preprocessing["fit_namespace"],
            "fit_records": preprocessing["fit_records"],
            "source_kind": "qualification_chain",
            "fit_sources": "qprod producer V2 bundle fit manifest"
                           "(工程排练;原件夹具输入,来源逐项保留)",
            "consumer_refit_forbidden": True,
        },
        "families": {
            fam: {
                "family_version": fp["family_version"],
                "rung_params_source": "parameter_pack",
            }
            for fam, fp in pack["families"].items()},
        "code_identity": _consumer_code_identity(),
        "notes": "QProd 导出适配器产出:原件经公共判定核心复算验证;"
                 "ENGINEERING_ONLY,不构成正式资格",
    }
    c_digest = qualification_plan_digest(consumer_plan)
    (out_dir / "qualification_plan.json").write_text(
        json.dumps(consumer_plan, indent=2, ensure_ascii=False,
                   sort_keys=True), encoding="utf-8")
    (out_dir / "qualification_plan_digest.txt").write_text(
        c_digest + "\n", encoding="utf-8")
    (out_dir / "qualification_result.json").write_text(json.dumps({
        "format": QUALIFICATION_RESULT_FORMAT,
        "iteration": consumer_plan["iteration"],
        "source_iteration": consumer_plan["source_iteration"],
        "plan_digest": c_digest,
        "verdict": result["verdict"],
        "engineering_only": True,
        "verdict_semantics": (
            "工程 scope 资格判定(公共判定核心于 producer raw 证据"
            "复算一致后逐字段适配);不是正式课程资格判定"),
        "producer_verdict": result["verdict"],
        "rejudged_verdict": rejudged["verdict"],
        "created_utc": now,
    }, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    (out_dir / "qualification_exposure.json").write_text(json.dumps({
        "format": QUALIFICATION_EXPOSURE_FORMAT,
        "iteration": consumer_plan["iteration"],
        "plan_digest": c_digest,
        "status": "completed",
        "one_shot": True,
        "contract": "自 producer 一次性 exposure 终态适配;"
                    "不可重放",
        "engineering_only": True,
        "producer_exposure_sha256": _sha(originals["exposure"]),
        "written_utc": now,
    }, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    (out_dir / "parameter_pack.json").write_text(json.dumps(
        pack, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8")
    envelope_bytes = originals["envelope"].read_bytes()
    (out_dir / PREPROCESSOR_ENVELOPE_FILENAME).write_bytes(
        envelope_bytes)
    (out_dir / "SYNTHETIC_ONLY.md").write_text(
        "# ENGINEERING_ONLY(QProd 导出)\n\n"
        "本目录由 QProd 导出适配器自 Level A 工程排练 producer 原件"
        "适配产出;scope=engineering,不构成正式资格,不得移动/改名/"
        "重哈希后冒充正式资格或正式训练授权。\n",
        encoding="utf-8")

    receipt = {
        "format": QPROD_EXPORT_FORMAT,
        "exported_utc": now,
        "producer_art_dir": str(art),
        "producer_state_root": str(state_root),
        "qualification_dir": str(out_dir),
        "bindings": {
            "qualification_plan_digest": c_digest,
            "parameter_pack_digest": pack_d,
            "preprocessor_bundle_hash": bundle_hash,
        },
        "producer_bindings": {
            "qualification_plan_digest": digest,
            "parameter_pack_digest": pack_d,
            "preprocessor_bundle_hash": bundle_hash,
        },
        "checks": checks,
        "engineering_only": True,
        "note": "授权锚由隔离 test authority 依据本 receipt 的 bindings"
                " 在导出器之外签发(导出器非自签许可器)",
    }
    (out_dir / QPROD_EXPORT_RECEIPT_NAME).write_text(
        json.dumps(receipt, indent=2, ensure_ascii=False),
        encoding="utf-8")
    return receipt


def qualification_plan_digest_of_producer(
        plan: dict[str, Any]) -> str:
    """producer 资格计划 digest(qapl- 前缀;复用生产侧实现)。"""
    from rl_curriculum.curriculum261_qprod_plan import (
        qualification_plan_digest,
    )
    return qualification_plan_digest(plan)


def build_engineering_authorization(
        receipt: dict[str, Any], *, profile: str,
        authority_note: str) -> dict[str, Any]:
    """由隔离 test authority 调用:依据 export receipt 构造工程授权锚。

    本函数只提供结构(权威签发动作发生在被验包之外——runner/test
    authority 脚本持有并落盘;绑定三摘要 + profile + scope)。
    """
    bindings = dict(receipt["bindings"])
    return {
        "format": AUTHORIZATION_FORMAT,
        "profile": profile,
        "scope": "engineering",
        "bindings": bindings,
        "binding_digest": authorization_binding_digest({
            **bindings, "profile": profile, "scope": "engineering"}),
        "authorized_consumption": (
            "工程 profile 的消费准备/reset/step/无梯度前向;"
            "不解锁任何正式 probe/core/dev-eval/final"),
        "issued_by": authority_note,
        "engineering_only": True,
        "created_utc": datetime.now(timezone.utc).isoformat(
            timespec="seconds"),
    }


__all__ = [
    "export_qualification_delivery", "QProdExportError",
    "build_engineering_authorization", "QPROD_EXPORT_FORMAT",
    "QPROD_EXPORT_RECEIPT_NAME",
]
