"""阶段 2.6.0a 工作包 E/F/G/H/O:密封(hidden)考试执行器。

流程(mock 演示与正式同构):
 1. 加载 sealed commitment 与考试包;
 2. 退休检查(已退休包拒绝);
 3. 物化 Episode(spec 自带 timeframe,无默认值);
 4. 逐项验证密封承诺(pack/charter/schema/spec versions/generator
    代码哈希/evaluator/counterfactual/verdict/EvalConfig);
 5. checkpoint 正式资格(formal_eligible / charter / observation 绑定 /
    SHA-256,与承诺要求比对);
 6. attempt registry 幂等检查(同 checkpoint+pack 重跑返回同一结果);
 7. 候选模型在受限接口中运行(默认子进程,只收 observation);
    反事实套件与主评估使用同一受限候选接口(子进程在整个考试期间
    保持存活,结束后统一关闭);
 8. 全套反事实考试 + 多族 Null + classify_cheating(四门证据);
 9. 冻结判定器输出 PASS / FAIL / SUSPECTED_CHEATING / EXAM_INVALID 与
    G0-G4;
10. 默认输出最小化(minimal_hidden_output);
11. --detailed:详细结果写出的同时该考试包立即退休,再次评估被拒绝。

任何校验失败 -> EXAM_INVALID(fail closed,不产出部分成绩)。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rl_curriculum.attempt_registry import AttemptRegistry
from rl_curriculum.charter import validate_charter
from rl_curriculum.counterfactual import (
    classify_cheating,
    test_common_prefix_future_suffix,
    test_cost_monotonicity,
    test_episode_length_invariance,
    test_initial_price_invariance,
    test_nuisance_slot_injection,
    test_nuisance_slot_shuffle,
    test_null_control,
    test_price_scale_invariance,
    test_regime_order_randomization,
    test_signal_ablation,
    test_time_shift_invariance,
    test_trend_direction_mirror,
)
from rl_curriculum.evaluator import (
    EvalConfig,
    evaluator_code_hash,
    evaluate_policy,
)
from rl_curriculum.exam_pack import (
    ExamPack,
    RetirementRegistry,
    assert_pack_usable,
    materialize_pack,
    minimal_hidden_output,
)
from rl_curriculum.generators import DEFAULT_GENERATOR_REGISTRY
from rl_curriculum.observation_schema import ObservationSchema
from rl_curriculum.sealed_exam import (
    SealedExamCommitment,
    SealedExamError,
    verify_checkpoint_requirements,
    verify_sealed_commitment,
)
from rl_curriculum.verdict_spec import CourseVerdictSpec
from rl_platform.fingerprint import dependency_versions
from rl_platform.versions import spec_versions

EXAM_INVALID_EXIT_CODE = 5


def _redact_sealed_checks(sealed_checks: dict[str, Any]) -> dict[str, Any]:
    """输出级脱敏:checks 键中的 generator 族名替换为匿名序号(H)。"""
    checks = dict(sealed_checks.get("checks") or {})
    redacted: dict[str, bool] = {}
    fam_index: dict[str, int] = {}
    for key, value in checks.items():
        if "::" in key:
            head, _, tail = key.partition("::")
            idx = fam_index.setdefault(tail, len(fam_index))
            redacted[f"{head}::family_{idx}"] = bool(value)
        else:
            redacted[key] = bool(value)
    out = dict(sealed_checks)
    out["checks"] = redacted
    out.pop("pack_families", None)
    out["n_pack_families"] = len(checks)
    out["pack_families_redacted"] = True
    return out


class _CfRecordAdapter:
    """classify_cheating 需要的 PairResult 最小视图(record dict 适配)。"""

    def __init__(self, record: dict[str, Any]):
        self.name = record["test"]
        self.pass_ = bool(record["pass"])
        self.extra = record.get("extra") or {}
        self.base = record.get("base") or {}
        self.variant = record.get("variant") or {}


def run_counterfactual_suite(
    policy: Any, episodes: list[Any], cfg: EvalConfig,
    schema: ObservationSchema, registry: dict[str, Any],
) -> list[dict[str, Any]]:
    """全套 G4 反事实考试(代表 Episode 按 split 选择;fail closed)。"""
    def pick(split: str) -> list[Any]:
        eps = [e for e in episodes if e.spec.split == split]
        return eps or [e for e in episodes if e.spec.split == "train"]

    seed_eps = pick("dev_seed_holdout")
    ext_eps = pick("param_extrapolation")
    base_ep = seed_eps[0]
    gen_a = registry.get("probe_segmented_drift")
    if gen_a is None:
        raise SealedExamError(
            "注册表缺少 probe_segmented_drift(反事实考试依赖)")
    from rl_curriculum.generators import FORMAL_NULL_FAMILIES

    null_by_family: dict[str, list[Any]] = {
        fam: [e for e in episodes if e.spec.family == fam]
        for fam in FORMAL_NULL_FAMILIES
    }
    missing = {k: len(v) for k, v in null_by_family.items() if not v}
    if missing:
        raise SealedExamError(
            f"考试包缺少必需 Null 家族 Episode: {missing}")

    results = [
        test_common_prefix_future_suffix(gen_a, policy, base_ep, cfg, schema),
        test_price_scale_invariance(policy, base_ep, cfg, schema),
        test_initial_price_invariance(gen_a, policy, base_ep, cfg, schema),
        test_episode_length_invariance(gen_a, policy, base_ep, cfg, schema),
        test_time_shift_invariance(policy, base_ep, cfg, schema),
        test_regime_order_randomization(gen_a, policy, base_ep, cfg, schema),
        test_nuisance_slot_injection(policy, ext_eps, cfg, schema),
        test_nuisance_slot_shuffle(policy, ext_eps, cfg, schema),
        test_signal_ablation(policy, ext_eps, cfg, schema,
                             signal_group="trend"),
        test_trend_direction_mirror(policy, ext_eps, cfg, schema),
        test_cost_monotonicity(policy, base_ep, cfg, schema),
        test_null_control(policy, null_by_family, cfg, schema),
    ]
    return [r.to_record() for r in results]


def _load_candidate(
    checkpoint_path: str, commitment: SealedExamCommitment,
    schema: ObservationSchema, *, use_subprocess: bool,
    python_executable: str | None,
):
    if use_subprocess:
        from rl_curriculum.candidate_worker import SubprocessCandidate

        kwargs = {}
        if python_executable:
            kwargs["python"] = python_executable
        return SubprocessCandidate(
            checkpoint_path,
            expected_charter_hash=commitment.charter_hash,
            expected_observation_schema_hash=(
                commitment.observation_schema_hash),
            **kwargs,
        )
    from rl_curriculum.policies import SB3CheckpointPolicy

    return SB3CheckpointPolicy(
        checkpoint_path,
        expected_charter_hash=commitment.charter_hash,
        expected_observation_schema_hash=(
            commitment.observation_schema_hash),
        schema=schema,
    )


def run_sealed_exam(
    *,
    sealed_manifest_path: str,
    pack_path: str,
    checkpoint_path: str,
    out_path: str,
    retire_registry_path: str,
    attempt_registry_path: str,
    charter: dict[str, Any],
    schema: ObservationSchema,
    verdict_spec: CourseVerdictSpec,
    eval_config: EvalConfig,
    registry: dict[str, Any] | None = None,
    use_subprocess: bool = True,
    detailed_path: str | None = None,
    python_executable: str | None = None,
) -> tuple[dict[str, Any], int]:
    """执行一次密封考试;返回 (输出 JSON, 退出码)。"""
    import pandas as pd

    registry = registry or DEFAULT_GENERATOR_REGISTRY
    started = pd.Timestamp.now(tz="UTC").isoformat()
    sealed_checks: dict[str, Any] = {}
    commitment: SealedExamCommitment | None = None
    pack: ExamPack | None = None
    candidate = None

    def checkpoint_sha() -> str:
        from rl_curriculum.checkpoints import sha256_file

        return sha256_file(checkpoint_path)

    try:
        # 1-2. 加载承诺/包,退休检查
        commitment = SealedExamCommitment.load(sealed_manifest_path)
        pack = ExamPack.load(pack_path)
        retire_registry = RetirementRegistry(retire_registry_path)
        assert_pack_usable(pack, retire_registry)

        # 3. 物化(spec 自带 timeframe;无默认)
        episodes = materialize_pack(
            pack, registry, retire_registry=retire_registry)

        # 4. 密封承诺逐项验证
        sealed_checks = verify_sealed_commitment(
            commitment, pack=pack, charter=validate_charter(charter),
            schema=schema, registry=registry, eval_config=eval_config,
            verdict_spec=verdict_spec,
        )

        # 5. checkpoint 正式资格
        from rl_curriculum.checkpoints import (
            is_formal_eligible,
            load_checkpoint_manifest,
        )

        manifest = load_checkpoint_manifest(checkpoint_path)
        ckpt_sha = checkpoint_sha()
        verify_checkpoint_requirements(commitment, manifest,
                                       checkpoint_sha256=ckpt_sha)
        if not is_formal_eligible(manifest):
            raise SealedExamError(
                "checkpoint 不满足 formal_eligible(v2 绑定/章程/版本),"
                "正式隐藏考试拒绝执行")

        # 6. attempt registry(幂等 + 上限)
        attempt_policy = commitment.attempt_policy or {}
        attempt_registry = AttemptRegistry(
            attempt_registry_path,
            max_attempts_per_checkpoint_pack=(
                attempt_policy.get("max_attempts_per_checkpoint_pack")),
        )
        pack_hash = pack.pack_hash()
        previous = attempt_registry.previous_completed(pack_hash, ckpt_sha)
        # 幂等重试只适用于"同结果最小输出"的重复提交;--detailed 是
        # 终结性披露动作:必须完整重评 + 立即退休包,不走缓存捷径
        if (previous is not None
                and detailed_path is None
                and attempt_policy.get("idempotent_retry", True)):
            verdict = json.loads(previous["extra"].get("verdict_json", "{}"))
            if not verdict:
                raise SealedExamError("幂等重试缺少既往判定记录(EXAM_INVALID)")
            out = {
                "exam_cli_version": "hidden-exam-cli-v2",
                "mode": "sealed",
                "sealed_verification": _redact_sealed_checks(sealed_checks),
                "attempt": {
                    "attempt_id": previous["attempt_id"],
                    "idempotent_retry_of": previous["attempt_id"],
                    "recorded_utc": previous["recorded_utc"],
                },
                "result": minimal_hidden_output(
                    attempt_id=previous["attempt_id"],
                    checkpoint_hash=ckpt_sha, pack_hash=pack_hash,
                    verdict=verdict, integrity_ok=True,
                    redaction_note="幂等重试:返回既往同一结果,"
                                   "不产生新的可探测信息"),
                "dependencies": dependency_versions(),
                "started_utc": started,
                "finished_utc": pd.Timestamp.now(tz="UTC").isoformat(),
                "exit_code": 0,
            }
            Path(out_path).parent.mkdir(parents=True, exist_ok=True)
            Path(out_path).write_text(
                json.dumps(out, indent=2, ensure_ascii=False),
                encoding="utf-8")
            return out, 0

        # 7. 候选(默认子进程,只收 observation;整场考试存活)
        candidate = _load_candidate(
            checkpoint_path, commitment, schema,
            use_subprocess=use_subprocess, python_executable=python_executable)

        # 8. 评估 + 反事实 + 作弊分类(同一受限候选接口)
        from rl_curriculum.policies import AlwaysFlatPolicy, RuleTrendPolicy

        report = evaluate_policy(
            candidate, episodes, eval_config, schema,
            baseline_policies={
                "always_flat": AlwaysFlatPolicy(),
                "rule_trend": RuleTrendPolicy(),
            },
        )
        cf_records = run_counterfactual_suite(
            candidate, episodes, eval_config, schema, registry)
        cheating = classify_cheating(
            [_CfRecordAdapter(r) for r in cf_records],
            base_median_net_return=float(report["overall"]["median"]),
            base_seed_pass_ratio=float(
                report["seed_pass_ratio_vs_always_flat"]),
            n_episodes_tested=int(report["n_episodes"]),
            min_effective_net_return=(
                verdict_spec.min_effective_net_return),
            min_seed_pass_ratio=(
                verdict_spec.min_seed_pass_ratio_for_cheat),
            min_replication=verdict_spec.min_replication_episodes,
        )

        # 9. 冻结判定器
        verdict = verdict_spec.evaluate({
            "integrity_ok": True, "integrity_errors": [],
            "report": report, "counterfactual_results": cf_records,
            "cheating": cheating,
        })
        status = verdict["status"]
        exit_code = 0

        # 10. attempt 记录 + 最小化输出
        attempt = attempt_registry.record_attempt(
            pack_hash=pack_hash, checkpoint_hash=ckpt_sha, status=status,
            completed=True,
            extra={"verdict_json": json.dumps(
                {"status": verdict["status"], "grade": verdict["grade"],
                 "hard_gates": verdict["hard_gates"],
                 "score_band": verdict["score_band"],
                 "recommendation": verdict["recommendation"]})},
        )
        out = {
            "exam_cli_version": "hidden-exam-cli-v2",
            "mode": "sealed",
            "sealed_verification": _redact_sealed_checks(sealed_checks),
            "attempt": {"attempt_id": attempt["attempt_id"]},
            "result": minimal_hidden_output(
                attempt_id=attempt["attempt_id"],
                checkpoint_hash=ckpt_sha, pack_hash=pack_hash,
                verdict=verdict, integrity_ok=True),
            "dependencies": dependency_versions(),
            "spec_versions": spec_versions(),
            "evaluator_code_hash": evaluator_code_hash(),
            "started_utc": started,
            "finished_utc": pd.Timestamp.now(tz="UTC").isoformat(),
            "exit_code": exit_code,
        }

        # 11. 详细输出 -> 立即退休
        if detailed_path and status != "EXAM_INVALID":
            retire_registry.retire(
                pack_hash,
                reason=f"详细结果已公开(--detailed -> {detailed_path})")
            detailed = {
                "verdict": verdict, "report": report,
                "counterfactuals": cf_records, "cheating": cheating,
                "sealed_verification": sealed_checks,
                "attempt": attempt,
            }
            Path(detailed_path).parent.mkdir(parents=True, exist_ok=True)
            Path(detailed_path).write_text(
                json.dumps(detailed, indent=2, ensure_ascii=False),
                encoding="utf-8")
            attempt_registry.record_attempt(
                pack_hash=pack_hash, checkpoint_hash=ckpt_sha,
                status=status, completed=True, detailed_disclosed=True,
                pack_retired_after=True,
                extra={"detailed_path": str(detailed_path)})
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_text(
            json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
        return out, exit_code

    except Exception as exc:  # noqa: BLE001 - fail closed:任何校验/评估异常
        return _emit_exam_invalid(
            out_path=out_path, started=started,
            commitment=commitment, pack=pack,
            sealed_checks=sealed_checks,
            integrity_error=exc,
            checkpoint_path=checkpoint_path,
            attempt_registry_path=attempt_registry_path,
        )
    finally:
        if candidate is not None:
            try:
                candidate.close()
            except Exception:  # noqa: BLE001 - 清理阶段不抛
                pass


def _emit_exam_invalid(
    *, out_path: str, started: str,
    commitment: SealedExamCommitment | None,
    pack: ExamPack | None,
    sealed_checks: dict[str, Any],
    integrity_error: Exception,
    checkpoint_path: str,
    attempt_registry_path: str,
) -> tuple[dict[str, Any], int]:
    """EXAM_INVALID 输出(错误细节脱敏;不产出部分成绩)。"""
    import pandas as pd

    ckpt_sha = ""
    try:
        from rl_curriculum.checkpoints import sha256_file

        ckpt_sha = sha256_file(checkpoint_path)
    except Exception:  # noqa: BLE001
        ckpt_sha = ""
    pack_hash = ""
    if pack is not None:
        try:
            pack_hash = pack.pack_hash()
        except Exception:  # noqa: BLE001
            pack_hash = ""
    attempt_out: dict[str, Any] = {}
    if attempt_registry_path and pack_hash and ckpt_sha:
        try:
            ar = AttemptRegistry(attempt_registry_path)
            attempt_out = ar.record_attempt(
                pack_hash=pack_hash, checkpoint_hash=ckpt_sha,
                status="EXAM_INVALID", completed=True,
                extra={"integrity_failure_type": type(integrity_error).__name__})
        except Exception:  # noqa: BLE001
            attempt_out = {}
    verdict = {
        "status": "EXAM_INVALID", "grade": None, "hard_gates": {},
        "score_band": None, "recommendation": "do_not_proceed",
    }
    out = {
        "exam_cli_version": "hidden-exam-cli-v2",
        "mode": "sealed",
        "status": "EXAM_INVALID",
        "sealed_verification": _redact_sealed_checks({
            "commitment_hash": (
                commitment.commitment_hash() if commitment else None),
            "checks": sealed_checks.get("checks", {}),
            "problems_redacted": True,
        }),
        "attempt": attempt_out,
        "result": minimal_hidden_output(
            attempt_id=attempt_out.get("attempt_id"),
            checkpoint_hash=ckpt_sha, pack_hash=pack_hash,
            verdict=verdict, integrity_ok=False,
            redaction_note="EXAM_INVALID:失败原因已脱敏(不泄露隐藏考试"
                           "细节);详细信息仅独立审计方可查询"),
        "dependencies": dependency_versions(),
        "spec_versions": spec_versions(),
        "started_utc": started,
        "finished_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "exit_code": EXAM_INVALID_EXIT_CODE,
    }
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    return out, EXAM_INVALID_EXIT_CODE
