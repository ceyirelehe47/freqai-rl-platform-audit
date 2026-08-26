"""阶段 2.6.0a 工作包 E/F/G/H/O + 2.6.0b 工作包 C/G/E + 2.6.0c
工作包 A/B/C:密封(hidden)考试执行器 v4。

流程(mock 演示与正式同构):
 1. 加载 sealed commitment v3 与考试包;
 2. 退休检查(已退休包拒绝);
 3. 物化 Episode(spec 自带 timeframe;resolved duration 实际物化);
 4. 逐项验证密封承诺 v3(pack/charter/schema/spec versions/逐族生成器
    实现指纹/evaluator/counterfactual/verdict(含 nuisance 等价、复制
    门槛与 seed 聚合规则)/EvalConfig/sandbox profile/候选运行时
    manifest(B:实际执行的 rl_candidate_runtime 逐文件哈希)/严格
    Null 资格真实报告(D)/受信 issuer 自洽(A)/resolved parameter
    semantics);
 5. checkpoint 正式资格:受信 training attestation 验证(签名+逐项
    绑定+runner hash+smoke 策略;sidecar 自声明 boolean 无效);
    issuer 信任根唯一来自 commitment canonical payload(A);
 6. attempt registry 幂等检查;
 7. 候选在系统级沙箱内执行(unshare namespaces + Landlock + rlimits
    + 协议限制;沙箱在 checkpoint 加载之前进入;staging 运行时在
    启动前与承诺逐字节比对——B2 TOCTOU 防护);
 8. 全套反事实考试(多 Episode/多切割点/多变换 seed;每一种作弊
    原因按冻结判定器门槛 max(min_distinct_cheat_seeds,
    min_failing_cheat_episodes) 动态取样不同 seed,pack seed 不足 ->
    EXAM_INVALID(C1);逐原因按 seed 聚合复制证据(C3))+
    多族严格 Null + classify_cheating(四门证据);
 9. 冻结判定器输出 PASS / FAIL / SUSPECTED_CHEATING / EXAM_INVALID;
10. 默认输出最小化(minimal_hidden_output);
11. --detailed:详细结果写出的同时该考试包立即退休。

任何校验失败 -> EXAM_INVALID(fail closed,不产出部分成绩)。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rl_curriculum.attempt_registry import AttemptRegistry
from rl_curriculum.charter import validate_charter
from rl_curriculum.counterfactual import (
    NuisanceEquivalenceSpec,
    build_replication_evidence,
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
EXAM_CLI_VERSION = "hidden-exam-cli-v5"
#: 工作包 E:反作弊复制证据的多切割点(common_prefix 逐 seed 3 cut)
COMMON_PREFIX_CUT_RATIOS = (0.25, 0.5, 0.75)


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
    *,
    nuisance_spec: NuisanceEquivalenceSpec | None = None,
    verdict_spec: CourseVerdictSpec | None = None,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """全套 G4 反事实考试(2.6.0b:真实多 seed 复制证据;2.6.0c 工作包
    C1/C3:动态门槛取样 + 按 seed 聚合)。

    返回 (records, replication_evidence):
    - records: 逐考试 PairResult.to_record();
    - replication_evidence: 每种作弊原因的实际多 Episode/seed 聚合
      (build_replication_evidence,bootstrap 抽样单位是 seed),供
      classify_cheating 四门证据使用;不用考试包总 Episode 数冒充
      重复次数。

    工作包 C1:每一种作弊原因必须按冻结判定器门槛动态计算所需样本:
    required_seed_count = max(min_distinct_cheat_seeds,
    min_failing_cheat_episodes)。考试包对应 split 的不同 seed 不足
    -> SealedExamError(EXAM_INVALID):不降低门槛,也不把整个考试包
    Episode 数填进复制统计。
    """
    from rl_curriculum.generators import FORMAL_NULL_FAMILIES

    nuisance_spec = nuisance_spec or NuisanceEquivalenceSpec()
    min_seeds = (verdict_spec.min_distinct_cheat_seeds
                 if verdict_spec else 3)
    min_failing = (verdict_spec.min_failing_cheat_episodes
                   if verdict_spec else 3)
    min_effective = (verdict_spec.min_effective_net_return
                     if verdict_spec else 0.0)
    seed_aggregation = (verdict_spec.seed_aggregation
                        if verdict_spec else "per-seed-mean-v1")

    def pick(split: str) -> list[Any]:
        eps = [e for e in episodes if e.spec.split == split]
        return eps or [e for e in episodes if e.spec.split == "train"]

    seed_eps = pick("dev_seed_holdout")
    ext_eps = pick("param_extrapolation")
    # 工作包 C1:按冻结门槛动态计算所需不同 seed 数;不足 -> EXAM_INVALID
    required_seed_count = max(min_seeds, min_failing)
    by_seed: dict[int, Any] = {}
    for ep in seed_eps:
        by_seed.setdefault(int(ep.spec.seed), ep)
    if len(by_seed) < required_seed_count:
        raise SealedExamError(
            f"考试包 dev_seed_holdout(或回退 train)split 仅有 "
            f"{len(by_seed)} 个不同 seed({sorted(by_seed)}),低于冻结"
            f"反作弊复制门槛 max(min_distinct_cheat_seeds={min_seeds},"
            f"min_failing_cheat_episodes={min_failing})="
            f"{required_seed_count}:EXAM_INVALID(不得降低门槛,也不得"
            f"把考试包总 Episode 数当作复制样本)")
    replication_eps = [by_seed[s]
                       for s in sorted(by_seed)[:required_seed_count]]
    base_ep = seed_eps[0]
    gen_a = registry.get("probe_segmented_drift")
    if gen_a is None:
        raise SealedExamError(
            "注册表缺少 probe_segmented_drift(反事实考试依赖)")

    null_by_family: dict[str, list[Any]] = {
        fam: [e for e in episodes if e.spec.family == fam]
        for fam in FORMAL_NULL_FAMILIES
    }
    missing = {k: len(v) for k, v in null_by_family.items() if not v}
    if missing:
        raise SealedExamError(
            f"考试包缺少必需严格 Null 家族 Episode: {missing}")

    results = []
    # 1. 共同前缀:多 Episode × 多切割点(E2)
    cp_records = [
        test_common_prefix_future_suffix(
            gen_a, policy, ep, cfg, schema, cut_ratio=cr)
        for ep in replication_eps
        for cr in COMMON_PREFIX_CUT_RATIOS
    ]
    results.extend(cp_records)
    # 2/3. 价格尺度与初始价:多 Episode(工作包 C1:全部所需 seed,
    #     不再截取前 2 个——旧 [:2] 使该原因永远达不到 3-seed 门槛)
    ps_records = [test_price_scale_invariance(policy, ep, cfg, schema)
                  for ep in replication_eps]
    ip_records = [test_initial_price_invariance(gen_a, policy, ep, cfg, schema)
                  for ep in replication_eps]
    results.extend(ps_records)
    results.extend(ip_records)
    # 4/5. Episode 长度/时间平移:多 Episode(同上,全量所需 seed)
    el_records = [test_episode_length_invariance(gen_a, policy, ep, cfg, schema)
                  for ep in replication_eps]
    ts_records = [test_time_shift_invariance(policy, ep, cfg, schema)
                  for ep in replication_eps]
    results.extend(el_records)
    results.extend(ts_records)
    # 6. regime 顺序随机化:多 Episode(同上)
    ro_records = [test_regime_order_randomization(gen_a, policy, ep, cfg, schema)
                  for ep in replication_eps]
    results.extend(ro_records)
    # 7/8. nuisance 双边等价(D)
    results.append(test_nuisance_slot_injection(
        policy, ext_eps, cfg, schema, spec=nuisance_spec))
    results.append(test_nuisance_slot_shuffle(
        policy, ext_eps, cfg, schema, spec=nuisance_spec))
    # 9-12
    results.append(test_signal_ablation(
        policy, ext_eps, cfg, schema, signal_group="trend"))
    results.append(test_trend_direction_mirror(policy, ext_eps, cfg, schema))
    results.append(test_cost_monotonicity(policy, base_ep, cfg, schema))
    results.append(test_null_control(policy, null_by_family, cfg, schema))

    records = [r.to_record() for r in results]

    # 逐作弊原因聚合复制证据(E1)
    base_net_by_episode = {}
    for ep in replication_eps:
        from rl_curriculum.evaluator import run_policy_episode

        base_net_by_episode[ep.spec.seed] = run_policy_episode(
            policy, ep, cfg, schema).net_return

    def evidence_for(names: list[str]) -> dict[str, Any]:
        recs = [r for r in records if r["test"] in names]
        return build_replication_evidence(
            recs, base_net_by_episode=base_net_by_episode,
            min_effective_net_return=min_effective,
            min_distinct_seeds=min_seeds,
            min_failing_episodes=min_failing,
            seed_aggregation=seed_aggregation)

    replication_evidence = {
        "future_leakage": evidence_for(["common_prefix_future_suffix"]),
        "absolute_price": evidence_for(
            ["price_scale_invariance", "initial_price_invariance"]),
        "episode_position": evidence_for(
            ["episode_length_invariance", "time_shift_invariance"]),
        "periodic_pattern": evidence_for(["regime_order_randomization"]),
    }
    return records, replication_evidence


def _load_sandboxed_candidate(
    checkpoint_path: str, commitment: SealedExamCommitment,
    sandbox_profile,
):
    """工作包 C + B:候选只在系统级沙箱内加载执行(无进程内选项)。

    阶段 2.6.0c 工作包 B:把承诺绑定的候选运行时 manifest 传给
    启动器——staging 复制完成后、unshare/bootstrap 启动前对 staging
    实际执行副本逐字节比对(TOCTOU 防护)。
    """
    from rl_curriculum.sandbox import (
        CandidateSandboxError,
        SandboxedCandidate,
    )

    try:
        return SandboxedCandidate(
            checkpoint_path,
            expected_charter_hash=commitment.charter_hash,
            expected_observation_schema_hash=(
                commitment.observation_schema_hash),
            profile=sandbox_profile,
            expected_runtime_manifest=(
                commitment.candidate_runtime_manifest),
        )
    except CandidateSandboxError:
        raise SealedExamError(
            "候选沙箱启动失败(已脱敏):正式候选必须在系统级沙箱内"
            "执行;沙箱不可用、staging 运行时与承诺不一致或候选协议"
            "违规 -> EXAM_INVALID") from None


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
    sandbox_profile: Any = None,
    context_issuer_payload: dict[str, Any] | None = None,
    detailed_path: str | None = None,
) -> tuple[dict[str, Any], int]:
    """执行一次密封考试(v4:沙箱强制 + attestation 强制 + 信任根
    只来自承诺);返回 (输出 JSON, 退出码)。

    工作包 C1:没有 use_subprocess 参数——正式候选永远在系统级沙箱内
    执行;进程内执行只允许 public dev test(输出 formal_conclusion=
    false)或单元测试专用入口。

    阶段 2.6.0c 工作包 A:没有 trusted_issuer 参数——issuer 信任根
    唯一从 sealed commitment 的 canonical issuer payload 构造(先做
    自洽校验)。context_issuer_payload 只是可选的展示副本:提供时
    必须与承诺逐字段 canonical equality,任何不同 -> EXAM_INVALID;
    它永远不能覆盖/改写承诺信任根。
    """
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
        # 沙箱可用性硬前置(C1:任何请求正式考试但未启用沙箱 ->
        # EXAM_INVALID,绝不降级为普通子进程)
        from rl_curriculum.sandbox import (
            SandboxUnavailableError,
            default_sandbox_profile,
        )

        if sandbox_profile is None:
            sandbox_profile = default_sandbox_profile()
        # 1-2. 加载承诺/包,退休检查
        commitment = SealedExamCommitment.load(sealed_manifest_path)
        pack = ExamPack.load(pack_path)
        retire_registry = RetirementRegistry(retire_registry_path)
        assert_pack_usable(pack, retire_registry)

        # 3. 物化(spec 自带 timeframe;resolved duration 实际物化)
        episodes = materialize_pack(
            pack, registry, retire_registry=retire_registry)

        # 4. 密封承诺 v4 逐项验证(含沙箱 profile/Null 资格/issuer/
        #    spec/power/pack 构建算法)
        sealed_checks = verify_sealed_commitment(
            commitment, pack=pack, charter=validate_charter(charter),
            schema=schema, registry=registry, eval_config=eval_config,
            verdict_spec=verdict_spec, sandbox_profile=sandbox_profile,
        )

        # 4b. 实际 Null pack 的 pack-level validity(阶段 2.6.0d B2):
        #     执行器对物化 pack 现算报告并与承诺 hash 逐字段对账;
        #     偶然抽出明显正漂移的 pack -> EXAM_INVALID(候选未进入
        #     评估,不得判 FAIL 或作弊)。
        null_eps: dict[str, list] = {}
        null_episode_bars = 96
        for ep in episodes:
            if ep.spec.split == "null_control":
                null_eps.setdefault(ep.spec.family, []).append(ep)
                null_episode_bars = int(
                    (ep.spec.params or {}).get("episode_bars", 96))
        if null_eps:
            from rl_curriculum.null_pack_validation import (
                build_spec_for_pack,
                pack_validity_report_hash,
                validate_null_pack,
            )

            pv_spec = build_spec_for_pack(
                eval_config, timeframe=pack.timeframe,
                episode_bars=null_episode_bars)
            pv_report = validate_null_pack(
                null_eps, cfg=eval_config, schema=schema, spec=pv_spec,
                pack_hash=pack.pack_hash())
            pv_hash = pack_validity_report_hash(pv_report)
            if pv_hash != commitment.pack_validity.get("report_hash"):
                raise SealedExamError(
                    f"实际 pack 的 pack-level validity 报告哈希与承诺"
                    f"不一致(EXAM_INVALID):现算 {pv_hash} vs 承诺 "
                    f"{commitment.pack_validity.get('report_hash')}"
                    f"(pack 与承诺时使用的 pack 不同或统计被替换)")
            if pv_report["verdict"] != "PACK_VALID":
                raise SealedExamError(
                    "实际 pack 未通过 pack-level validity(EXAM_INVALID,"
                    "候选未进入评估,不判 FAIL/作弊): "
                    + "; ".join(pv_report["reasons"][:3]))
        else:
            raise SealedExamError(
                "考试包不含 null_control Episode(EXAM_INVALID):严格 "
                "Null pack 是正式考试的组成部分")

        # 5. checkpoint 正式资格(受信 attestation 驱动)
        from rl_curriculum.attestation import (
            AttestationError,
            TrustedIssuerConfig,
            _sha256_file,
            formal_eligibility_from_attestation,
            load_attestation,
            verify_attestation,
        )
        from rl_curriculum.checkpoints import (
            load_checkpoint_manifest,
        )

        manifest = load_checkpoint_manifest(checkpoint_path)
        ckpt_sha = checkpoint_sha()
        # 工作包 A(2.6.0c):信任根唯一来自承诺 canonical issuer
        # payload——自洽校验(重算公钥指纹/协议/runner hash/smoke)
        # 失败即 EXAM_INVALID;不存在任何参数覆盖通道
        if not commitment.trusted_issuer:
            raise SealedExamError(
                "承诺缺少 trusted_issuer 配置(EXAM_INVALID):无法验证"
                "训练来源")
        try:
            trusted_issuer = TrustedIssuerConfig.from_payload(
                commitment.trusted_issuer)
        except AttestationError as exc:
            raise SealedExamError(
                f"承诺 issuer 配置自洽校验失败(EXAM_INVALID): {exc}"
            ) from exc
        # 工作包 A:context issuer 只是展示副本——与承诺逐字段
        # canonical equality,任何字段不同都 EXAM_INVALID(不比较
        # "参数非空优先",不存在 fallback 语义)
        if context_issuer_payload is not None:
            if context_issuer_payload != commitment.trusted_issuer:
                raise SealedExamError(
                    "context 携带的 issuer 副本与承诺不一致"
                    "(EXAM_INVALID):正式信任根唯一来自 sealed "
                    "commitment;context issuer 不得覆盖或改写任何字段"
                    "(context issuer override 攻击被拒绝)")
        attestation_report: dict[str, Any] | None = None
        training_manifest_sha = str(manifest.get("training_manifest_sha256")
                                    or "")
        try:
            doc = load_attestation(str(Path(checkpoint_path).with_name(
                Path(checkpoint_path).name + ".rl_attestation.json")))
            attestation_report = verify_attestation(
                doc, trusted=trusted_issuer,
                checkpoint_path=checkpoint_path,
                sidecar_sha256=_sha256_file(str(Path(checkpoint_path).with_name(
                    Path(checkpoint_path).name + ".rl_manifest.json"))),
                training_manifest_sha256=training_manifest_sha,
                charter_hash=commitment.charter_hash,
                observation_schema_hash=commitment.observation_schema_hash)
        except AttestationError as exc:
            raise SealedExamError(
                f"training attestation 验证失败(EXAM_INVALID): {exc}"
            ) from exc
        verify_checkpoint_requirements(
            commitment, manifest, checkpoint_sha256=ckpt_sha,
            attestation_report=attestation_report)
        eligibility = formal_eligibility_from_attestation(
            checkpoint_path=checkpoint_path, sidecar_manifest=manifest,
            trusted=trusted_issuer,
            training_manifest_sha256=training_manifest_sha,
            charter_hash=commitment.charter_hash,
            observation_schema_hash=commitment.observation_schema_hash)
        if not eligibility["formal_eligible"]:
            raise SealedExamError(
                "checkpoint 不满足正式资格:必须持有受信签发方签名的 "
                "training attestation(sidecar 自声明无效;"
                f"原因: {eligibility.get('reason', '未提供 attestation')})")

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
                "exam_cli_version": EXAM_CLI_VERSION,
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

        # 7. 候选:系统级沙箱内执行(工作包 C;checkpoint 加载发生在
        #    沙箱内——加载前进入隔离)
        candidate = _load_sandboxed_candidate(
            checkpoint_path, commitment, sandbox_profile)

        # 8. 评估 + 反事实(多 seed 复制证据)+ 作弊分类
        from rl_curriculum.policies import AlwaysFlatPolicy, RuleTrendPolicy

        report = evaluate_policy(
            candidate, episodes, eval_config, schema,
            baseline_policies={
                "always_flat": AlwaysFlatPolicy(),
                "rule_trend": RuleTrendPolicy(),
            },
        )
        cf_records, replication_evidence = run_counterfactual_suite(
            candidate, episodes, eval_config, schema, registry,
            nuisance_spec=verdict_spec.nuisance_equivalence,
            verdict_spec=verdict_spec)
        cheating = classify_cheating(
            [_CfRecordAdapter(r) for r in cf_records],
            base_median_net_return=float(report["overall"]["median"]),
            base_seed_pass_ratio=float(
                report["seed_pass_ratio_vs_always_flat"]),
            replication_evidence=replication_evidence,
            min_effective_net_return=(
                verdict_spec.min_effective_net_return),
            min_seed_pass_ratio=(
                verdict_spec.min_seed_pass_ratio_for_cheat),
            min_distinct_seeds=verdict_spec.min_distinct_cheat_seeds,
            min_failing_episodes=verdict_spec.min_failing_cheat_episodes,
        )

        # 9. 冻结判定器(含 replication_evidence;缺崩溃证据 -> INVALID)
        verdict = verdict_spec.evaluate({
            "integrity_ok": True, "integrity_errors": [],
            "report": report, "counterfactual_results": cf_records,
            "cheating": cheating,
            "replication_evidence": replication_evidence,
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
            "exam_cli_version": EXAM_CLI_VERSION,
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
                "counterfactuals": cf_records,
                "replication_evidence": replication_evidence,
                "cheating": cheating,
                "sealed_verification": sealed_checks,
                "attestation": {
                    "payload_hash": attestation_report.get("payload_hash"),
                    "issuer_fingerprint": trusted_issuer.key_fingerprint,
                },
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
        "exam_cli_version": EXAM_CLI_VERSION,
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
